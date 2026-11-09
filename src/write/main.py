"""Entrypoint for pennsieve-ai-write.

Reads the analyze stage's blackboard from `$INPUT_DIR/blackboard.json`,
generates one manuscript per hypothesis that passed analysis (or the one
named by `$VP_WRITE_HYPOTHESIS_ID`; default `auto`), and writes the updated blackboard plus the manuscript and review artifacts
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
from pathlib import Path

from pennsieve_ai_utils.backend import llm_backend, missing_config
from pennsieve_ai_utils.llm import LLMClient
from pennsieve_ai_utils.models import ModelNotAvailable
from pennsieve_ai_utils.processor import (
    ProcessorEnv,
    install_sigterm_handler,
    load_upstream_blackboard,
    write_outputs,
)

from write.pipeline import UnsupportedClaims, run_write, select_hypotheses

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
        targets = select_hypotheses(bb, hypothesis_id)
    except (FileNotFoundError, ValueError) as e:
        bb.log(STAGE, "fatal", repr(e))
        write_outputs(bb, output_dir, client.usage_log, stage=STAGE)
        build_run_report(bb, client, output_dir, outcome="failed")
        print(f"\nERROR: {e}", file=sys.stderr)
        return 2
    bb.log(STAGE, "targets", f"one manuscript each for {', '.join(targets)}")

    # One manuscript per hypothesis that passed analysis. A manuscript the
    # audit blocks, or one that cannot be written, is recorded and the next
    # one still gets written; the stage passes if any is ready for review.
    outcomes: dict[str, str] = {}
    for target in targets:
        try:
            run_write(
                bb, client,
                hypothesis_id=target,
                input_dir=env.input_dir,
                output_dir=output_dir,
                revise=do_revise,
            )
            outcomes[target] = "ready_for_review"
        except UnsupportedClaims as e:
            # An honest result, not a crash: the draft, every audit round and a
            # review.json marked "blocked" are on disk for a human to read.
            bb.log(STAGE, "unsupported_claims", str(e))
            print(f"\n{e}", flush=True)
            outcomes[target] = "blocked"
        except (FileNotFoundError, ValueError) as e:
            # Problems with what this stage was given (a missing notebook, an
            # invalid hypothesis ID, an analysis that did not pass).
            bb.log(STAGE, "fatal", f"{target}: {e!r}")
            print(f"\nERROR: {target}: {e}", file=sys.stderr)
            outcomes[target] = "failed"
        except (Exception, KeyboardInterrupt) as e:
            bb.log(STAGE, "fatal", repr(e))
            write_outputs(bb, output_dir, client.usage_log, stage=STAGE)
            raise
    bb.log(STAGE, "outcomes", ", ".join(f"{k}={v}" for k, v in outcomes.items()))

    if "ready_for_review" not in outcomes.values():
        outcome = "blocked" if "blocked" in outcomes.values() else "failed"
        write_outputs(bb, output_dir, client.usage_log, stage=STAGE)
        build_run_report(bb, client, output_dir, outcome=outcome)
        return 8 if outcome == "blocked" else 2

    bb.log(STAGE, "done", "")
    write_outputs(bb, output_dir, client.usage_log, stage=STAGE)
    build_run_report(bb, client, output_dir)
    print(f"\nWrote: {output_dir / 'blackboard.json'}")
    return 0


def build_run_report(bb, client, output_dir: Path, outcome: str = "passed") -> None:
    """Write `report.html` for the whole run, at the root of the run folder.

    This happens on every way out of the stage, including the ones where no
    manuscript was written, because a run that produced no paper is exactly
    the run whose record someone needs to read. The report is built from the
    run folder, so it covers Scout, Hypothesize and Analyze as well.

    Nothing here is allowed to change the stage's outcome: a report that
    cannot be built is reported and the exit code stands.
    """
    from pennsieve_ai_utils import run_report, run_report_summary
    from pennsieve_ai_utils.run_report_html import render_html

    run_dir = output_dir.parent
    try:
        # The supervisor records this stage only after it exits, so tell the
        # report how it went; otherwise it reads as a run still in progress.
        facts = run_report.collect(run_dir, running_stage=STAGE, running_status=outcome)
    except Exception as exc:  # noqa: BLE001 - the report never decides the exit code
        bb.log(STAGE, "report_failed", f"could not read the run folder: {exc!r}")
        return
    summary = run_report_summary.summarize(facts, client, run_id=bb.run_id)
    if not summary:
        bb.log(STAGE, "report_summary_skipped",
               "the written summary could not be produced; the figures below are unaffected")
    for destination in (run_dir / "report.html", output_dir / "report.html"):
        try:
            destination.write_text(render_html(facts, summary))
            bb.log(STAGE, "report", f"wrote {destination}")
            print(f"Run report: {destination}", flush=True)
            return
        except OSError:
            continue  # the run root can be read-only; the stage folder is not
    bb.log(STAGE, "report_failed", "the report could not be written anywhere")


if __name__ == "__main__":
    raise SystemExit(main())
