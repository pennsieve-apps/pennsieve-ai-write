"""Orchestrates the write-stage pipeline for one hypothesis:

    writer  →  auditor  →  (revisor, if unsupported claims found)

Reads the executed notebook the analyze stage produced; writes paper.md,
audit.json, and updated blackboard metadata to OUTPUT_DIR/papers/<HX>/.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from write.agents import (
    discussion_enhancer,
    paper_auditor,
    paper_revisor,
    paper_writer,
)
from pennsieve_ai_utils import pricing
from pennsieve_ai_utils.blackboard import Blackboard, Hypothesis
from pennsieve_ai_utils.llm import LLMClient
from write.tools import audit_render, notebook_extract, pdf_render


class UnsupportedClaims(RuntimeError):
    """The audit loop ended with claims the auditor could not support.

    The draft, every audit round and a `review.json` with status "blocked" are
    already written. This used to be a bare `RuntimeError` that escaped as an
    uncaught traceback, which made the expected first-run outcome look like a
    crash in the code.
    """

    def __init__(self, hypothesis_id: str, unsupported: int, paper_dir: str) -> None:
        self.hypothesis_id = hypothesis_id
        self.unsupported = unsupported
        self.paper_dir = paper_dir
        super().__init__(f"{hypothesis_id}: {unsupported} manuscript claim(s) remain unsupported "
                         f"after the audit; the draft and audits are in {paper_dir}")


# Outcomes Analyze records when a hypothesis did not pass, and how to say so.
ANALYSIS_FAILED = {
    "not_testable": "is not testable with this deposit",
    "unresolved": "did not pass its methods review after every round",
    "refused": "was refused by every analyst model",
}


def select_hypothesis(bb: Blackboard, hypothesis_id: str) -> Hypothesis:
    """Pick the hypothesis to write a manuscript for. Fails with a clear error
    if the requested ID isn't on the blackboard or has no analysis output."""
    if hypothesis_id == "auto":
        final = bb.iterations_completed or max((h.iteration for h in bb.hypotheses), default=0)
        candidates = [h for h in bb.hypotheses_at(final) if h.analysis_workdir and h.analysis_summary]
        if not candidates:
            raise ValueError("No analyzed hypothesis is available for writing")
        # Analyze moves on to the next-ranked hypothesis when one fails, so the
        # board can hold a failed analysis next to the one that passed. Prefer
        # the one that passed; with none, the refusal below says why.
        passed = [h for h in candidates
                  if (h.methods_critique or {}).get("outcome") not in ANALYSIS_FAILED]
        hypothesis_id = (passed or candidates)[0].id
    if not re.fullmatch(r"[A-Za-z0-9_-]+", hypothesis_id):
        raise ValueError("Hypothesis ID must be a safe directory name")
    matches = [h for h in bb.hypotheses if h.id == hypothesis_id]
    if not matches:
        available = ", ".join(sorted(h.id for h in bb.hypotheses)) or "(none)"
        # Say WHY the board is empty when upstream told us — "Available:
        # (none)" alone sends whoever reads the log on a four-repo trace.
        upstream = ""
        if not bb.hypotheses:
            stages = sorted({d.get("stage", "?") for d in (bb.degraded or [])})
            cause = (f"upstream stages failed or were skipped: {', '.join(stages)}"
                     if stages else
                     "hypothesize produced none — check its log for skip reasons "
                     "(usually 0 literature claims from scout)")
            upstream = f" The blackboard has no hypotheses at all: {cause}."
        raise ValueError(
            f"Hypothesis {hypothesis_id!r} not found on blackboard. "
            f"Available: {available}.{upstream} "
            f"Set VP_WRITE_HYPOTHESIS_ID to one of them."
        )
    h = max(matches, key=lambda h: h.iteration)
    if not (h.analysis_summary or h.analysis_workdir):
        raise ValueError(
            f"Hypothesis {h.id} has no analyze-stage output (analysis_summary "
            f"and analysis_workdir are both empty). The analyze stage must run "
            f"successfully before the write stage can produce a manuscript."
        )
    reviews = [r for r in bb.reviews_at(h.iteration) if r.hypothesis_id == h.id]
    if not reviews or reviews[-1].verdict != "accept":
        raise ValueError(f"Hypothesis {h.id} was not accepted by the hypothesis critic")
    critique = h.methods_critique or {}
    outcome = critique.get("outcome")
    if outcome in ANALYSIS_FAILED:
        # Analyze recorded why it stopped. Say that, instead of the generic
        # line, so nobody re-reads the analyze log to find out what happened.
        reason = critique.get("not_testable_reason") or "(no reason recorded)"
        headline = ANALYSIS_FAILED[outcome]
        raise ValueError(f"Hypothesis {h.id} {headline}, so there is nothing to write up: {reason}")
    if critique.get("verdict") != "sound" or any(
        i.get("severity") == "high" for i in critique.get("issues", [])
    ):
        raise ValueError(f"Hypothesis {h.id} has not passed methods review")
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
    notebook_extract.validate_execution(nb_path)
    max_iters = int(os.environ.get("VP_WRITE_MAX_AUDIT_ITERS", "3"))
    if max_iters < 1:
        raise ValueError("VP_WRITE_MAX_AUDIT_ITERS must be at least 1")

    print(f"\n--- write pipeline: {h.id} ---")
    print(f"  notebook: {nb_path}")

    paper_dir = output_dir / "papers" / h.id
    paper_dir.mkdir(parents=True, exist_ok=True)
    figures_dir = paper_dir / "figures"

    h.manuscript_started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # 1. Write
    print("\n--- paper_writer ---")
    md_path, _ = paper_writer.write_paper(
        bb, client,
        hypothesis=h,
        executed_nb_path=nb_path,
        paper_dir=paper_dir,
    )
    _render_pdf_log(bb, md_path, paper_dir / "paper.pdf")

    # 2. (Optional) STORM-style Discussion enhancement. Runs BEFORE the audit
    # loop so the auditor grades the enhanced Discussion text — if the
    # synthesizer hallucinates a citation, the auditor catches it and the
    # revisor fixes it. Disabled by VP_WRITE_ENHANCE_DISCUSSION=0. Adds
    # one synthesis-role survey pass + one reasoning-role synthesis pass.
    enhance_discussion = os.environ.get("VP_WRITE_ENHANCE_DISCUSSION", "1") != "0"
    if enhance_discussion:
        print("\n--- discussion_enhancer (STORM-style) ---")
        de_result = discussion_enhancer.enhance(
            bb, client,
            hypothesis=h,
            executed_nb_path=nb_path,
            paper_md_path=md_path,
        )
        new_discussion = de_result.get("discussion_md", "").strip()
        # Persist the per-perspective Q&A artifact for downstream inspection.
        (paper_dir / "discussion_perspectives.json").write_text(
            json.dumps(de_result.get("perspectives_qa", {}), indent=2))
        if new_discussion:
            spliced = discussion_enhancer.splice_discussion(
                md_path.read_text(), new_discussion)
            (paper_dir / "paper.preDiscussionEnhance.md").write_text(md_path.read_text())
            md_path.write_text(spliced)
            bb.log("discussion_enhancer", "spliced",
                   f"replaced Discussion with {len(new_discussion)} chars")
            _render_pdf_log(bb, md_path, paper_dir / "paper.pdf")
        else:
            err = de_result.get("error") or "synthesizer returned empty discussion_md"
            bb.log("discussion_enhancer", "skipped", err[:300])
            print(f"  [discussion_enhancer] skipped: {err[:200]}")
    else:
        print("\n--- discussion_enhancer skipped (VP_WRITE_ENHANCE_DISCUSSION=0) ---")

    # 3. Audit ⇄ Revise loop. Up to VP_WRITE_MAX_AUDIT_ITERS rounds (default 3).
    # Each round runs the auditor against the current paper.md; if unsupported
    # claims remain, run the revisor with an auto-generated note targeting
    # only those claims and re-loop. Exit when:
    #   - audit reports 0 unsupported, or
    #   - max iters reached, or
    #   - VP_WRITE_REVISE=0 (audit-only mode), or
    #   - the revisor returns empty paper_md (defensive — caller bailed).
    #
    # Each iteration's audit is persisted to audit.iter{N}.json; audit.json
    # always tracks the latest. Each pre-revise markdown snapshot is written
    # to paper.iter{N}.md so a reviewer can match audit.iter{N}.json against
    # the exact text the auditor reviewed. Exiting the loop with unsupported
    # claims retains these artifacts and fails the stage below.
    audit_result: dict = {}
    counts: dict = {
        "supported": 0, "partial": 0, "unsupported": 0, "unverifiable": 0,
    }

    for iter_n in range(1, max_iters + 1):
        print(f"\n--- paper_auditor (iter {iter_n}/{max_iters}) ---")
        (paper_dir / f"paper.iter{iter_n}.md").write_text(md_path.read_text())
        audit_result = paper_auditor.audit(
            bb, client,
            hypothesis=h,
            paper_md_path=md_path,
            executed_nb_path=nb_path,
            figures_dir=figures_dir,
        )
        (paper_dir / f"audit.iter{iter_n}.json").write_text(
            json.dumps(audit_result, indent=2))
        (paper_dir / "audit.json").write_text(
            json.dumps(audit_result, indent=2))

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
        bb.log("paper_auditor", "iter",
               f"iter{iter_n}: sup={counts['supported']} par={counts['partial']} "
               f"uns={counts['unsupported']} unv={counts['unverifiable']}")

        if counts["unsupported"] == 0:
            print(f"  → 0 unsupported claims; exiting audit loop")
            break
        if not revise:
            print(f"  → VP_WRITE_REVISE=0; staying audit-only")
            break
        if iter_n >= max_iters:
            print(f"  → max iters reached ({max_iters}); retaining draft for review")
            break

        # Revise: build a targeted note from the unsupported claims.
        print(f"\n--- paper_revisor (iter {iter_n}, {counts['unsupported']} unsupported) ---")
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
        if not new_md.strip():
            bb.log("paper_revisor", "skipped",
                   f"iter{iter_n}: revisor returned empty paper_md — bailing out of loop")
            break

        # Snapshot the pre-revise markdown so audit.iter{N}.json can be
        # matched against the exact text it audited.
        (paper_dir / f"paper.iter{iter_n}.md").write_text(md_path.read_text())
        md_path.write_text(new_md)
        bb.log("paper_revisor", "applied",
               f"iter{iter_n}: {(result.get('revision_summary') or '')[:400]}")
        _render_pdf_log(bb, md_path, paper_dir / "paper.pdf")

    iterations = iter_n  # last iteration we actually ran (last audit, possibly revise)

    # Audited PDF: render against the FINAL markdown using the FINAL audit.
    # Both are paired — audit_result is the audit of md_path's current content
    # at loop exit. Highlights show what's still concerning in the final
    # paper, not what was originally flagged before revision.
    _render_audited_pdf_log(bb, md_path, audit_result,
                            paper_dir / "paper_audited.pdf")

    # 4. Record manuscript metadata on the hypothesis
    h.manuscript_path = str(md_path.relative_to(output_dir))
    h.manuscript_cost_usd = _cost_from_usage(client.usage_log)
    h.manuscript_iterations = iterations
    h.audit_summary = audit_result.get("summary", "")
    h.audit_counts = counts
    h.manuscript_finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    from write.tools.tex_export import export_tex
    export_error = export_tex(md_path, data_doi=_seed_doi(bb), category=_category(h))
    bb.log("tex_export", "warn" if export_error else "wrote", export_error or "paper.tex")
    review = {
        "hypothesis_id": h.id,
        "status": "blocked" if counts["unsupported"] else "ready_for_review",
        "audit_counts": counts,
        "human_review_required": True,
        "tex_export_error": export_error,
    }
    (paper_dir / "review.json").write_text(json.dumps(review, indent=2))
    bb.log("write", "done",
           f"{h.id}: manuscript={h.manuscript_path} iterations={iterations} "
           f"cost=${h.manuscript_cost_usd:.4f}")
    if counts["unsupported"]:
        # The draft, the audits and a review.json saying "blocked" are all on
        # disk. A manuscript the auditor could not fully support is a result to
        # report, not a crash: the stage does not pass, and the supervisor's
        # gate already refuses a review.json that is not ready_for_review.
        raise UnsupportedClaims(h.id, counts["unsupported"], str(paper_dir))


def _render_pdf_log(bb: Blackboard, md_path: Path, pdf_path: Path) -> None:
    """Render md_path → pdf_path; log success / failure on the blackboard.
    PDF generation is best-effort — a render failure must not break a run
    that has already produced the canonical paper.md.
    """
    err = pdf_render.render_pdf(md_path, pdf_path)
    if err:
        bb.log("pdf_render", "warn",
               f"{pdf_path.name}: {err[:400]}")
        print(f"  [pdf] warn: {err[:200]}")
    else:
        bb.log("pdf_render", "wrote", str(pdf_path.name))
        print(f"  [pdf] {pdf_path.name}")


def _render_audited_pdf_log(bb: Blackboard, md_path: Path,
                            audit_result: dict, pdf_path: Path) -> None:
    """Render the audited PDF (paper.md + audit highlights). Best-effort,
    same contract as _render_pdf_log."""
    err = audit_render.render_audited_paper(md_path, audit_result, pdf_path)
    if err:
        bb.log("pdf_render", "warn",
               f"{pdf_path.name}: {err[:400]}")
        print(f"  [pdf] warn: {err[:200]}")
    else:
        bb.log("pdf_render", "wrote", str(pdf_path.name))
        print(f"  [pdf] {pdf_path.name}")


def _seed_doi(bb: Blackboard) -> str:
    """The DOI of the deposit the analysis ran on, for the preprint's front matter."""
    for dataset in bb.dataset_summaries:
        if dataset.id == bb.subsystem and getattr(dataset, "doi", ""):
            return str(dataset.doi).removeprefix("https://doi.org/")
    return ""


def _category(h: Hypothesis) -> str:
    """Which of bioRxiv's three article categories this manuscript is.

    bioRxiv asks every submission to declare one. A Co-Scientist paper
    reanalyzes a deposit that already has a published study behind it, so it is
    almost never "New Results": it either agrees with that study or it does
    not. The analyst's own summary is the only record of which, so a claim that
    the data did not support the prediction marks it as contradictory, and
    anything else as confirmatory.
    """
    summary = (h.analysis_summary or "").lower()
    contradicts = ("not supported", "contradict", "did not hold", "does not hold",
                   "no significant", "failed to replicate", "opposite direction")
    if any(phrase in summary for phrase in contradicts):
        return "Contradictory Results"
    return "Confirmatory Results"


def _cost_from_usage(usage_log: list[dict]) -> float:
    """Sum estimated USD across the write-stage's model calls.

    Bedrock does not return a per-call cost, so this prices the token counts
    with the shared table in `pennsieve_ai_utils.pricing`. That table is dated,
    covers each model by name, charges the regional inference profiles the
    premium they actually cost, and counts cache tokens.

    This used to hold its own table of $15 and $75 per million for "opus" and
    $3 and $15 for "sonnet", which are an older generation's prices: Opus 4.7
    on Bedrock is $5.50 and $27.50, so the figure was about 2.7 times too high.
    It also ignored cache tokens, which are most of what a cached prompt costs.

    Under the governor its ledger remains the billing source of truth. Running
    on Bedrock directly, this is the only cost figure the run produces.
    """
    return round(pricing.summarize_usage(usage_log)["cost_usd"], 6)
