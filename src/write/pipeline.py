"""Orchestrates the write-stage pipeline for one hypothesis:

    writer  →  auditor  →  (revisor, if unsupported claims found)

Reads the executed notebook the analyze stage produced; writes paper.md,
audit.json, and updated blackboard metadata to OUTPUT_DIR/papers/<HX>/.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from write.agents import paper_auditor, paper_revisor, paper_writer
from write.blackboard import Blackboard, Hypothesis
from write.llm import LLMClient
from write.tools import notebook_extract


def select_hypothesis(bb: Blackboard, hypothesis_id: str) -> Hypothesis:
    """Pick the hypothesis to write a manuscript for. Fails with a clear error
    if the requested ID isn't on the blackboard or has no analysis output."""
    matches = [h for h in bb.hypotheses if h.id == hypothesis_id]
    if not matches:
        available = ", ".join(sorted(h.id for h in bb.hypotheses)) or "(none)"
        raise ValueError(
            f"Hypothesis {hypothesis_id!r} not found on blackboard. "
            f"Available: {available}. Set VP_WRITE_HYPOTHESIS_ID to one of them."
        )
    h = matches[-1]  # latest iteration wins if there are revisions
    if not (h.analysis_summary or h.analysis_workdir):
        raise ValueError(
            f"Hypothesis {h.id} has no analyze-stage output (analysis_summary "
            f"and analysis_workdir are both empty). The analyze stage must run "
            f"successfully before the write stage can produce a manuscript."
        )
    return h


def locate_notebook(input_dir: Path, h: Hypothesis) -> Path:
    """Find the executed notebook the analyze stage produced for this hypothesis.

    Analyze's blackboard records `analysis_workdir` as a path relative to the
    compute-node workdir root (one level up from analyze's OUTPUT_DIR). Within
    the write stage's INPUT_DIR (= analyze's OUTPUT_DIR), the workdir appears
    at `hypotheses/<HX>/` because analyze's agentic_analyst pins
    `cwd = workdir / "hypotheses" / hypothesis.id`.
    """
    # Primary location: workdir layout the agent uses.
    primary = input_dir / "hypotheses" / h.id
    if primary.exists():
        nb = notebook_extract.find_notebook(primary, h.id)
        if nb is not None:
            return nb

    # Secondary: try the path stored on the hypothesis. analysis_workdir is
    # written as a workdir-relative path by analyze, so we strip a leading
    # path prefix and look under INPUT_DIR.
    if h.analysis_workdir:
        rel = h.analysis_workdir.lstrip("/")
        # If the recorded path includes its OUTPUT_DIR root (e.g.
        # "workdir-hash/hypotheses/H1"), take just the trailing hypothesis dir.
        parts = Path(rel).parts
        if "hypotheses" in parts:
            i = parts.index("hypotheses")
            tail = Path(*parts[i:])
            candidate = input_dir / tail
            if candidate.exists():
                nb = notebook_extract.find_notebook(candidate, h.id)
                if nb is not None:
                    return nb

    raise FileNotFoundError(
        f"Could not locate an executed notebook for hypothesis {h.id} under "
        f"{input_dir}. Looked in: hypotheses/{h.id}/, and "
        f"{h.analysis_workdir or '(no recorded path)'}. "
        f"Confirm the analyze stage actually produced a notebook."
    )


def run_write(
    bb: Blackboard,
    client: LLMClient,
    *,
    hypothesis_id: str,
    input_dir: Path,
    output_dir: Path,
    revise: bool = True,
) -> None:
    """End-to-end write pipeline for the selected hypothesis."""
    h = select_hypothesis(bb, hypothesis_id)
    nb_path = locate_notebook(input_dir, h)

    print(f"\n--- write pipeline: {h.id} ---")
    print(f"  notebook: {nb_path}")

    paper_dir = output_dir / "papers" / h.id
    paper_dir.mkdir(parents=True, exist_ok=True)
    figures_dir = paper_dir / "figures"

    h.manuscript_started_at = datetime.utcnow().isoformat(timespec="seconds")

    # 1. Write
    print("\n--- paper_writer ---")
    md_path, _ = paper_writer.write_paper(
        bb, client,
        hypothesis=h,
        executed_nb_path=nb_path,
        paper_dir=paper_dir,
    )

    # 2. Audit
    print("\n--- paper_auditor ---")
    audit_result = paper_auditor.audit(
        bb, client,
        hypothesis=h,
        paper_md_path=md_path,
        executed_nb_path=nb_path,
        figures_dir=figures_dir,
    )
    (paper_dir / "audit.json").write_text(json.dumps(audit_result, indent=2))

    claims = audit_result.get("claims") or []
    counts = {
        "supported":   sum(1 for c in claims if c.get("verdict") == "supported"),
        "partial":     sum(1 for c in claims if c.get("verdict") == "partial"),
        "unsupported": sum(1 for c in claims if c.get("verdict") == "unsupported"),
        "unverifiable": sum(1 for c in claims if c.get("verdict") == "unverifiable"),
    }
    print(f"  audit: {len(claims)} claims "
          f"({counts['supported']} sup / {counts['partial']} par / "
          f"{counts['unsupported']} uns / {counts['unverifiable']} unv)")

    iterations = 1

    # 3. Revise (optional)
    if revise and counts["unsupported"] > 0:
        print(f"\n--- paper_revisor ({counts['unsupported']} unsupported claims) ---")
        unsupported = [c for c in claims if c.get("verdict") == "unsupported"]
        note_lines = [
            "The auditor flagged the following unsupported claims. Revise these "
            "specifically; do not rewrite unrelated content.",
            "",
        ]
        for c in unsupported:
            note_lines.append(f"- **[{c.get('category','?')}]** {(c.get('text') or '')[:200]!r}")
            rationale = (c.get("rationale") or "").strip()
            if rationale:
                note_lines.append(f"  REASON: {rationale[:400]}")
        note = "\n".join(note_lines)

        result = paper_revisor.revise(
            bb, client,
            hypothesis=h,
            executed_nb_path=nb_path,
            paper_md_path=md_path,
            user_note=note,
        )
        new_md = result.get("paper_md", "")
        if new_md.strip():
            # Back up the pre-revision version for inspection
            ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
            (paper_dir / f"paper.preRevision.{ts}.md").write_text(md_path.read_text())
            md_path.write_text(new_md)
            iterations = 2
            bb.log("paper_revisor", "applied", (result.get("revision_summary") or "")[:400])
        else:
            bb.log("paper_revisor", "skipped", "revisor returned empty paper_md")
    elif revise:
        print(f"\n--- paper_revisor skipped (0 unsupported claims) ---")
    else:
        print(f"\n--- paper_revisor skipped (VP_WRITE_REVISE=0) ---")

    # 4. Record manuscript metadata on the hypothesis
    h.manuscript_path = str(md_path.relative_to(output_dir))
    h.manuscript_cost_usd = _cost_from_usage(client.usage_log)
    h.manuscript_iterations = iterations
    h.audit_summary = audit_result.get("summary", "")
    h.audit_counts = counts
    h.manuscript_finished_at = datetime.utcnow().isoformat(timespec="seconds")

    bb.log("write", "done",
           f"{h.id}: manuscript={h.manuscript_path} iterations={iterations} "
           f"cost=${h.manuscript_cost_usd:.4f}")


def _cost_from_usage(usage_log: list[dict]) -> float:
    """Sum estimated USD across the write-stage's LLM calls.

    The Bedrock SDK doesn't return per-call cost directly — we estimate from
    token counts using the published list prices. These are coarse (margins
    rounded to the cent) and don't apply any provisioned-throughput or
    enterprise discount, but they're useful for relative-cost tracking and
    budget-aware UX. The governor's audit table is the source of truth for
    actual billed amounts.
    """
    # USD per million tokens (input, output) by logical model name.
    rates = {
        "opus":   (15.0, 75.0),
        "sonnet": ( 3.0, 15.0),
        "haiku":  ( 0.80, 4.0),
    }
    total = 0.0
    for entry in usage_log:
        model = entry.get("model", "")
        in_rate, out_rate = rates.get(model, (0.0, 0.0))
        total += entry.get("input_tokens", 0)  * in_rate  / 1_000_000
        total += entry.get("output_tokens", 0) * out_rate / 1_000_000
    return round(total, 6)
