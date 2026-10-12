"""Entrypoint for pennsieve-ai-write.

Reads the analyze stage's blackboard from `$INPUT_DIR/blackboard.json`,
generates a manuscript for the hypothesis selected via
`$VP_WRITE_HYPOTHESIS_ID` (default `auto`, selecting the analyzed candidate),
and writes the updated blackboard plus the manuscript and review artifacts
under `papers/<HX>/` in `$OUTPUT_DIR`.

Auth model: the platform injects `LLM_GOVERNOR_FUNCTION_NAME`; the
`pennsieve-llm` SDK invokes that Lambda with the execution run ID attached.
Local runs can bypass the governor with `VP_LLM_BACKEND=bedrock` or
`anthropic` (see `pennsieve_ai_utils.backend`).

Compliance note: this processor makes outbound HTTPS to api.crossref.org
and api.datacite.org. That's incompatible with compliant-mode no-internet-
egress. We fail fast at startup if `DEPLOYMENT_MODE=compliant`.
"""
from __future__ import annotations

import os
import sys

from pennsieve_ai_utils.backend import llm_backend, missing_config
from pennsieve_ai_utils.llm import LLMClient
from pennsieve_ai_utils.models import ModelNotAvailable
from pennsieve_ai_utils.processor import (
    ProcessorEnv,
    install_sigterm_handler,
    load_upstream_blackboard,
    write_outputs,
)

from write.pipeline import run_write

STAGE = "write"


def main() -> int:
    install_sigterm_handler()
    env = ProcessorEnv.from_environ()
    deployment_mode = os.environ.get("DEPLOYMENT_MODE", "")
    hypothesis_id = os.environ.get("VP_WRITE_HYPOTHESIS_ID", "auto")
    do_revise = os.environ.get("VP_WRITE_REVISE", "1") != "0"
    env.banner(
        STAGE,
        DEPLOYMENT_MODE=deployment_mode or "<unset>",
        VP_LLM_BACKEND=llm_backend(),
        LLM_GOVERNOR_FUNCTION_NAME=os.environ.get("LLM_GOVERNOR_FUNCTION_NAME", "<unset>"),
        VP_WRITE_HYPOTHESIS_ID=hypothesis_id,
        VP_WRITE_REVISE=do_revise,
    )

    # Compliance fail-fast. This processor needs outbound HTTPS to
    # api.crossref.org / api.datacite.org for the authoritative bibliography.
    # In compliant mode there's no internet egress, so DOI enrichment would
    # silently fail and the writer would produce manuscripts with degraded
    # citations. Better to refuse to start than to silently produce broken
    # output. See README "Compliance notes".
    if deployment_mode == "compliant":
        print(
            "ERROR: pennsieve-ai-write requires outbound HTTPS to api.crossref.org "
            "and api.datacite.org for DOI metadata enrichment. This is incompatible "
            "with DEPLOYMENT_MODE=compliant (no internet egress). Refusing to start.",
            file=sys.stderr,
        )
        return 2

    # Write uses direct governor Lambda transport; unlike Analyze, it does not
    # run a Claude Agent SDK session and therefore does not require the local
    # Anthropic-compatible sidecar.
    missing = missing_config()
    if missing:
        hint = ("The write stage requires direct access to the platform-managed LLM "
                "governor. Confirm the compute node has `enable_llm_access = true`."
                if llm_backend() == "governor" else
                f"Set them for VP_LLM_BACKEND={llm_backend()}.")
        print(f"ERROR: {', '.join(missing)} not set. {hint}", file=sys.stderr)
        return 2

    bb = load_upstream_blackboard(env.input_dir / "blackboard.json", stage=STAGE,
                                  upstream="the analyze stage", run_id=env.execution_run_id)
    if bb is None:
        return 2
    output_dir = env.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    bb.log(STAGE, "start",
           f"loaded blackboard: {len(bb.dataset_summaries)} datasets, "
           f"{len(bb.hypotheses)} hypotheses, "
           f"{len(bb.literature_claims)} literature claims, "
           f"target hypothesis={hypothesis_id}")
    bb.save(output_dir / "blackboard.json")

    # Writer and discussion synthesis reason; auditor and revisor synthesize.
    client = LLMClient(stage=STAGE, roles=("reasoning", "synthesis"))
    try:
        assignments = client.preflight()
    except ModelNotAvailable as e:
        bb.log(STAGE, "fatal", f"model preflight failed: {e}")
        write_outputs(bb, output_dir, client.usage_log, stage=STAGE)
        print(f"ERROR: {e}", file=sys.stderr)
        return 5
    for role, assignment in assignments.items():
        bb.record_model_assignment(stage=STAGE, role=role, assignment=assignment)
    bb.log(STAGE, "models",
           ", ".join(f"{role}={a['model_id']}" for role, a in sorted(assignments.items())))

    try:
        run_write(
            bb, client,
            hypothesis_id=hypothesis_id,
            input_dir=env.input_dir,
            output_dir=output_dir,
            revise=do_revise,
        )
    except (FileNotFoundError, ValueError) as e:
        # Pre-LLM failures (notebook missing, hypothesis ID invalid) — write
        # what we have and exit with a clear error so the workflow surfaces it.
        bb.log(STAGE, "fatal", repr(e))
        write_outputs(bb, output_dir, client.usage_log, stage=STAGE)
        print(f"\nERROR: {e}", file=sys.stderr)
        return 2
    except (Exception, KeyboardInterrupt) as e:
        bb.log(STAGE, "fatal", repr(e))
        write_outputs(bb, output_dir, client.usage_log, stage=STAGE)
        raise

    bb.log(STAGE, "done", "")
    write_outputs(bb, output_dir, client.usage_log, stage=STAGE)
    print(f"\nWrote: {output_dir / 'blackboard.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
