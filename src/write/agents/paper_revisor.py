"""Paper Revisor — applies targeted edits to an existing paper given a note.

Takes paper.md, the user's (or auditor's auto-generated) pushback note,
and the paper's source artifacts, and returns a revised paper.md with
targeted claims rewritten to better match what the cell outputs say.

Edits narrowly — preserves unrelated paragraphs, citations, figures, and
section headers verbatim. Vendored from `virtual-postdoc/agents/paper_revisor.py`
with imports rewired and the synthesis-paper multi-source variant dropped
(v0 is per-hypothesis only).
"""
from __future__ import annotations

from pathlib import Path

from write.agents._common import call_json, load_prompt
from write.agents.paper_auditor import (
    _format_bibliography_for_audit,
    _format_dataset_context,
    _format_hypothesis_context,
)
from pennsieve_ai_utils.blackboard import Blackboard, Hypothesis
from pennsieve_ai_utils.llm import LLMClient
from write.tools import notebook_extract

MODEL = "sonnet"
AGENT = "paper_revisor"


def revise(
    bb: Blackboard,
    client: LLMClient,
    *,
    hypothesis: Hypothesis,
    executed_nb_path: Path,
    paper_md_path: Path,
    user_note: str,
) -> dict:
    """Run the revisor on one paper. Returns {paper_md, revision_summary, [error]}."""
    if not user_note.strip():
        raise ValueError("user_note is empty; nothing to revise against")

    paper_md = paper_md_path.read_text()
    figures_dir = paper_md_path.parent / "figures"
    cells = notebook_extract.extract(executed_nb_path, figures_dir)
    nb_summary = notebook_extract.summarize_for_prompt(cells, max_total_chars=60000)

    system = load_prompt("paper_revisor")
    user = "\n\n".join([
        "## User pushback note (this is what the human reviewer wants changed)",
        user_note.strip(),
        "",
        "## Hypothesis context",
        _format_hypothesis_context(hypothesis),
        "",
        "## Authoritative bibliography (cite ONLY from this list)",
        _format_bibliography_for_audit(bb),
        "",
        "## Dataset metadata",
        _format_dataset_context(bb),
        "",
        "## Executed notebook (cell sources + outputs)",
        nb_summary,
        "",
        "## CURRENT PAPER (revise THIS document, preserve everything not targeted by the note)",
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
            max_tokens=32768,
        )
    except Exception as e:
        bb.log(AGENT, "error", f"{hypothesis.id}: {e!r}")
        raise RuntimeError(f"Paper revision failed for hypothesis {hypothesis.id}") from e
    return {
        "paper_md": parsed.get("paper_md", "") or paper_md,
        "revision_summary": parsed.get("revision_summary", "") or "",
    }
