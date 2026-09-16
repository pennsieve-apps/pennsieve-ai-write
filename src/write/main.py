"""Entrypoint for pennsieve-ai-write.

Reads the analyze stage's blackboard from `$INPUT_DIR/blackboard.json`,
generates a manuscript for the hypothesis selected via
`$VP_WRITE_HYPOTHESIS_ID` (default `auto`, selecting the analyzed candidate),
and writes the updated blackboard plus the manuscript and review artifacts
under `papers/<HX>/` in `$OUTPUT_DIR`.

Auth model: the platform injects `LLM_GOVERNOR_FUNCTION_NAME`; the
`pennsieve-llm` SDK invokes that Lambda with the execution run ID attached.

Compliance note: this processor makes outbound HTTPS to api.crossref.org
and api.datacite.org. That's incompatible with compliant-mode no-internet-
egress. We fail fast at startup if `DEPLOYMENT_MODE=compliant`.
"""
from __future__ import annotations

import json
import os
import signal
import sys
from pathlib import Path

from write.blackboard import Blackboard
from write.llm import LLMClient
from write.pipeline import run_write


def _terminate(signum, frame):
    raise KeyboardInterrupt("termination requested")


def main() -> int:
    signal.signal(signal.SIGTERM, _terminate)
    input_dir = Path(os.environ.get("INPUT_DIR", "/mnt/efs/input"))
    output_dir = Path(os.environ.get("OUTPUT_DIR", "/mnt/efs/output"))
    execution_run_id = os.environ.get("EXECUTION_RUN_ID", "local-dev")
    workflow_instance_id = os.environ.get("WORKFLOW_INSTANCE_ID", "local-dev")
    deployment_mode = os.environ.get("DEPLOYMENT_MODE", "")
    hypothesis_id = os.environ.get("VP_WRITE_HYPOTHESIS_ID", "auto")
    do_revise = os.environ.get("VP_WRITE_REVISE", "1") != "0"

    print("=== pennsieve-ai-write ===")
    print(f"  INPUT_DIR={input_dir}")
    print(f"  OUTPUT_DIR={output_dir}")
    print(f"  EXECUTION_RUN_ID={execution_run_id}")
    print(f"  WORKFLOW_INSTANCE_ID={workflow_instance_id}")
    print(f"  DEPLOYMENT_MODE={deployment_mode or '<unset>'}")
    print(f"  LLM_GOVERNOR_FUNCTION_NAME="
          f"{os.environ.get('LLM_GOVERNOR_FUNCTION_NAME', '<unset>')}")
    print(f"  VP_WRITE_HYPOTHESIS_ID={hypothesis_id}")
    print(f"  VP_WRITE_REVISE={do_revise}")

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
    if not os.environ.get("LLM_GOVERNOR_FUNCTION_NAME"):
        print(
            "ERROR: LLM_GOVERNOR_FUNCTION_NAME is not set. The write stage "
            "requires direct access to the platform-managed LLM governor. "
            "Confirm the compute node has `enable_llm_access = true`.",
            file=sys.stderr,
        )
        return 2

    bb_path = input_dir / "blackboard.json"
    if not bb_path.exists():
        print(
            f"ERROR: no blackboard.json at {bb_path} — the analyze stage did not "
            f"produce its expected output, or the workflow wiring is wrong.",
            file=sys.stderr,
        )
        return 2

    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n--- loading blackboard from {bb_path} ---")
    bb = Blackboard.load(bb_path)
    bb.run_id = execution_run_id
    if bb.degraded:
        stages = ", ".join(sorted({d.get("stage", "?") for d in bb.degraded}))
        print(f"  WARNING: upstream blackboard is degraded — skipped/failed stages: {stages}")
        bb.log("write", "upstream_degraded", stages)
    bb.log("write", "start",
           f"loaded blackboard: {len(bb.dataset_summaries)} datasets, "
           f"{len(bb.hypotheses)} hypotheses, "
           f"{len(bb.literature_claims)} literature claims, "
           f"target hypothesis={hypothesis_id}")

    bb.save(output_dir / "blackboard.json")
    client = LLMClient()

    try:
        bb.model_assignments = client.preflight()
        bb.log(
            "write", "models",
            ", ".join(
                f"{logical}={assignment['model_id']}"
                for logical, assignment in sorted(bb.model_assignments.items())
            ),
        )
        run_write(
            bb, client,
            hypothesis_id=hypothesis_id,
            input_dir=input_dir,
            output_dir=output_dir,
            revise=do_revise,
        )
    except (FileNotFoundError, ValueError) as e:
        # Pre-LLM failures (notebook missing, hypothesis ID invalid) — write
        # what we have and exit with a clear error so the workflow surfaces it.
        bb.log("write", "fatal", repr(e))
        _write_outputs(bb, client, output_dir)
        print(f"\nERROR: {e}", file=sys.stderr)
        return 2
    except (Exception, KeyboardInterrupt) as e:
        bb.log("write", "fatal", repr(e))
        _write_outputs(bb, client, output_dir)
        raise

    bb.log("write", "done", "")
    _write_outputs(bb, client, output_dir)
    print(f"\nWrote: {output_dir / 'blackboard.json'}")
    return 0


def _write_outputs(bb: Blackboard, client: LLMClient, output_dir: Path) -> None:
    """Persist blackboard + audit logs to OUTPUT_DIR."""
    bb.save(output_dir / "blackboard.json")
    nb = "\n".join(json.dumps(e) for e in bb.notebook)
    (output_dir / "notebook.jsonl").write_text(nb + "\n" if nb else "")
    ul = "\n".join(json.dumps(e) for e in client.usage_log)
    (output_dir / "usage.jsonl").write_text(ul + "\n" if ul else "")


if __name__ == "__main__":
    raise SystemExit(main())
