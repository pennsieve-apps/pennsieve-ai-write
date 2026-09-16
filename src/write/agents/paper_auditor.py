"""Paper Auditor — fact-checks a generated paper against its sources.

Reads paper.md, the executed notebook, the authoritative bibliography, and
the hypothesis context. Returns a structured list of claims with per-claim
verdicts: `supported` | `partial` | `unsupported` | `unverifiable`.

One synthesis-role call per paper. Vendored from `virtual-postdoc/agents/paper_auditor.py`
with imports rewired for the `write.*` namespace and the synthesis-paper
`audit_combined` variant dropped (v0 is per-hypothesis only).
"""
from __future__ import annotations

from pathlib import Path

from write.agents._common import call_json, load_prompt
from write.blackboard import Blackboard, Hypothesis
from write.llm import LLMClient
from write.tools import notebook_extract

MODEL = "sonnet"
AGENT = "paper_auditor"


def _format_bibliography_for_audit(bb: Blackboard) -> str:
    enriched = bb.papers_enriched or {}
    if not enriched:
        return "(no papers_enriched on blackboard — citation checks will be unverifiable)"
    lines = []
    for doi, md in enriched.items():
        authors = (md.get("authors") or "").strip()
        year = md.get("year") or ""
        title = (md.get("title") or "").strip()
        lines.append(f"- doi:{doi} | authors='{authors[:120]}' | year='{year}' | title='{title[:140]}'")
    return "\n".join(lines)


def _format_hypothesis_context(h: Hypothesis) -> str:
    return "\n".join([
        f"**Hypothesis ID:** {h.id}",
        f"**Claim:** {h.claim}",
        f"**Predicted observation:** {h.predicted_observation}",
        f"**Suggested experiment:** {h.suggested_experiment}",
    ])


def _format_dataset_context(bb: Blackboard) -> str:
    if not bb.dataset_summaries:
        return "(no dataset summaries)"
    parts = []
    for d in bb.dataset_summaries[:3]:
        block = [
            f"### {d.id}: {d.title}",
            f"  dataset DOI: {d.doi}",
            f"  repository URL: {d.url}",
            f"  bucket_uri: {d.bucket_uri}",
        ]
        if d.file_tree:
            block.append(f"  file_tree (truncated):\n{d.file_tree[:1500]}")
        if d.record_tables:
            for fn, info in list(d.record_tables.items())[:3]:
                cols = ", ".join((info.get("columns") or [])[:8])
                block.append(f"  record `{fn}`: cols=[{cols}], n_rows={info.get('n_rows', 0)}")
        if d.readme:
            block.append(f"  README excerpt: {d.readme[:600].strip()}")
        parts.append("\n".join(block))
    return "\n\n".join(parts)


def audit(
    bb: Blackboard,
    client: LLMClient,
    *,
    hypothesis: Hypothesis,
    paper_md_path: Path,
    executed_nb_path: Path,
    figures_dir: Path,
) -> dict:
    """Run the auditor on one paper. Returns {summary, claims, [error]}."""
    paper_md = paper_md_path.read_text()
    cells = notebook_extract.extract(executed_nb_path, figures_dir)
    nb_summary = notebook_extract.summarize_for_prompt(cells, max_total_chars=20000)

    system = load_prompt("paper_auditor")
    user = "\n\n".join([
        "## Hypothesis context",
        _format_hypothesis_context(hypothesis),
        "",
        "## Authoritative bibliography",
        _format_bibliography_for_audit(bb),
        "",
        "## Dataset metadata",
        _format_dataset_context(bb),
        "",
        "## Executed notebook (cell sources + outputs)",
        nb_summary,
        "",
        "## PAPER UNDER AUDIT (the document you are fact-checking)",
        "```",
        paper_md,
        "```",
    ])

    try:
        parsed = call_json(
            client,
            agent=AGENT,
            system=system,
            user=user,
            run_id=bb.run_id,
            model=MODEL,
            max_tokens=16384,
        )
    except Exception as e:
        bb.log(AGENT, "error", f"{hypothesis.id}: {e!r}")
        raise RuntimeError(f"Paper audit failed for hypothesis {hypothesis.id}") from e
    claims = parsed.get("claims")
    verdicts = {"supported", "partial", "unsupported", "unverifiable"}
    if not isinstance(claims, list) or not claims or any(
        not isinstance(c, dict) or c.get("verdict") not in verdicts
        for c in claims
    ):
        raise ValueError("Paper audit must contain nonempty claims with valid verdicts")
    return {
        "summary": parsed.get("summary", "") or "",
        "claims": claims,
    }
