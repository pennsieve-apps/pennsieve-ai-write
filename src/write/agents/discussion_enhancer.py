"""Discussion Enhancer — STORM-style multi-perspective Discussion writer.

Two-stage process inspired by Shao et al. (2024; doi:10.18653/v1/2024.naacl-long.347):

  1. **Survey** (synthesis role) — generate 2 perspective-grounded questions
     per fixed persona (Skeptical Reviewer, Methodologist, Domain Expert,
     Reproducibility Analyst), and draft a one-paragraph answer per question
     against the paper's source artifacts (notebook cells, methods-critic
     concerns, critic attacks, authoritative bibliography, RAG chunks).

  2. **Synthesize** (reasoning role) — fold the eight Q&A pairs into a single
     coherent Discussion section of 4-6 paragraphs, with explicit cell
     references and DOI citations.

Slots in `run_write` **between** the Paper Writer and the audit loop, so
the audit grades the enhanced Discussion. Disabled with VP_WRITE_ENHANCE_DISCUSSION=0.
Total cost ~$0.40 per paper.

The agent does NOT splice into paper.md — the caller does that via the
`splice_discussion` helper. This keeps the agent pure (returns the new
Discussion markdown + the per-perspective Q&A as inspectable artifacts)
and the splicing logic in one place.

Vendored from virtual-postdoc/agents/discussion_enhancer.py. Single-
hypothesis only (the cross-hypothesis "synthesis paper" variant is not
part of v0).
"""
from __future__ import annotations

import re
from pathlib import Path

from write.agents._common import call_json, load_prompt, strip_attack_tag
from write.agents.paper_auditor import (
    _format_bibliography_for_audit,
    _format_dataset_context,
    _format_hypothesis_context,
)
from pennsieve_ai_utils.blackboard import Blackboard, Hypothesis
from pennsieve_ai_utils.llm import LLMClient
from write.tools import notebook_extract

AGENT = "discussion_enhancer"
SURVEY_MODEL = "sonnet"
SYNTHESIZE_MODEL = "opus"


def _format_methods_concerns(methods_review: dict) -> str:
    """Render Methods Critic concerns for inclusion in the perspectives prompt."""
    if not methods_review:
        return "(no methods review available)"
    lines = [
        f"**Methods Critic verdict:** {methods_review.get('verdict','?')}",
        f"**Reasoning:** {methods_review.get('reasoning','') or ''}",
    ]
    concerns = methods_review.get("concerns") or methods_review.get("issues") or []
    if concerns:
        lines.append("**Concerns:**")
        for c in concerns:
            if isinstance(c, dict):
                lines.append(
                    f"- [{c.get('severity','?')}] [{c.get('category','?')}] "
                    f"{(c.get('concern') or c.get('description') or c.get('text') or '').strip()}"
                )
                if c.get("suggested_fix"):
                    lines.append(f"  fix: {c['suggested_fix']}")
            else:
                lines.append(f"- {c}")
    return "\n".join(lines)


def _format_critic_concerns(bb: Blackboard, h: Hypothesis) -> str:
    """Render the Critic's prior attacks on this hypothesis."""
    latest = max(
        (r for r in bb.critic_reviews if r.hypothesis_id == h.id),
        key=lambda r: r.iteration, default=None,
    )
    if latest is None or not latest.attacks:
        return "(no prior critic attacks recorded)"
    parts = [f"### Critic concerns on {h.id}"]
    for a in latest.attacks:
        parts.append(f"- {strip_attack_tag(a)}")
    return "\n".join(parts)


def _format_perspective_qa(qa: dict) -> str:
    """Render the survey-stage output for the synthesizer's prompt."""
    perspectives = qa.get("perspectives") or []
    if not perspectives:
        return "(survey produced no perspective Q&A)"
    lines = []
    for p in perspectives:
        lines.append(f"### {p.get('name','?')}")
        for q in (p.get("questions") or []):
            lines.append(f"**Q:** {q.get('question','')}")
            lines.append(f"**A:** {q.get('answer','')}")
            lines.append("")
    return "\n".join(lines)


def enhance(
    bb: Blackboard,
    client: LLMClient,
    *,
    hypothesis: Hypothesis,
    executed_nb_path: Path,
    paper_md_path: Path,
) -> dict:
    """Run the two-stage Discussion enhancer for one hypothesis.

    Returns `{discussion_md, perspectives_qa, error?}` — caller handles splicing.
    The methods-critic review (if any) is read from `hypothesis.methods_critique`
    so callers don't need to plumb it separately.
    """
    paper_md = paper_md_path.read_text()
    methods_review = hypothesis.methods_critique or {}

    figures_dir = paper_md_path.parent / "figures"
    cells = notebook_extract.extract(executed_nb_path, figures_dir)
    nb_summary = notebook_extract.summarize_for_prompt(cells, max_total_chars=60000)

    common_context = "\n\n".join([
        "## Hypothesis context",
        _format_hypothesis_context(hypothesis),
        "",
        "## Authoritative bibliography (cite ONLY from this list)",
        _format_bibliography_for_audit(bb),
        "",
        "## Dataset metadata",
        _format_dataset_context(bb),
        "",
        "## Methods Critic — residual concerns to engage with",
        _format_methods_concerns(methods_review),
        "",
        "## Prior Critic attacks (hypothesis-stage reviewer concerns)",
        _format_critic_concerns(bb, hypothesis),
        "",
        "## Source notebook (cell sources + outputs)",
        nb_summary,
        "",
        "## CURRENT DRAFT PAPER (the existing Discussion is the target you'll replace)",
        "```",
        paper_md,
        "```",
    ])

    # ---- Stage 1: Survey ----
    try:
        survey = call_json(
            client,
            agent=AGENT + "_survey",
            system=load_prompt("discussion_perspectives"),
            user=common_context,
            run_id=bb.run_id,
            model=SURVEY_MODEL,
            max_tokens=8192,
        )
    except Exception as e:
        bb.log(AGENT, "survey_error", repr(e))
        return {"discussion_md": "", "perspectives_qa": {}, "error": repr(e)}

    perspectives_qa = {"perspectives": survey.get("perspectives") or []}
    n_perspectives = len(perspectives_qa["perspectives"])
    n_questions = sum(len(p.get("questions") or [])
                      for p in perspectives_qa["perspectives"])
    bb.log(AGENT, "survey",
           f"{n_perspectives} perspectives, {n_questions} questions answered")

    # ---- Stage 2: Synthesize ----
    synth_user = "\n\n".join([
        common_context,
        "## Perspective Q&A from the survey stage (use these to write the Discussion)",
        _format_perspective_qa(perspectives_qa),
    ])
    try:
        synth = call_json(
            client,
            agent=AGENT + "_synthesize",
            system=load_prompt("discussion_synthesizer"),
            user=synth_user,
            run_id=bb.run_id,
            model=SYNTHESIZE_MODEL,
            max_tokens=8192,
        )
    except Exception as e:
        bb.log(AGENT, "synthesize_error", repr(e))
        return {"discussion_md": "",
                "perspectives_qa": perspectives_qa,
                "error": repr(e)}

    discussion_md = (synth.get("discussion_md") or "").strip()
    bb.log(AGENT, "synthesize", f"discussion_md={len(discussion_md)} chars")
    return {
        "discussion_md": discussion_md,
        "perspectives_qa": perspectives_qa,
    }


def splice_discussion(paper_md: str, new_discussion_md: str) -> str:
    """Replace the existing Discussion section in `paper_md` with
    `new_discussion_md`. The Discussion is identified by an `^## Discussion`
    or `^### Discussion` header. Replacement runs from that header to the
    next header at the same depth (or end of file). Returns the spliced
    markdown.

    If no Discussion header is found, inserts before Conclusion / References
    if present, else appends to the end.
    """
    if not new_discussion_md.strip():
        return paper_md

    # Match `## Discussion`, `### Discussion`, `## 6. Discussion`, etc.
    header_pat = re.compile(
        r"^(#{2,3})\s*(?:\d+\.?\s*)?Discussion\b.*?$",
        re.MULTILINE | re.IGNORECASE,
    )
    m = header_pat.search(paper_md)
    if m is None:
        # No Discussion section; insert before References / Conclusion if present,
        # else append.
        for after_marker in ("\n## Conclusion", "\n## References",
                             "\n### References", "\n## 7. Conclusion"):
            i = paper_md.find(after_marker)
            if i != -1:
                return paper_md[:i] + "\n\n" + new_discussion_md.rstrip() + "\n\n" + paper_md[i:]
        return paper_md.rstrip() + "\n\n" + new_discussion_md.rstrip() + "\n"

    depth = len(m.group(1))
    start = m.start()
    # Find the next header at same depth or shallower
    next_header_pat = re.compile(
        rf"^#{{2,{depth}}}\s+\S",
        re.MULTILINE,
    )
    rest = paper_md[m.end():]
    nm = next_header_pat.search(rest)
    end = m.end() + (nm.start() if nm is not None else len(rest))

    # Ensure the new discussion has a leading header that matches the depth
    new_md = new_discussion_md.lstrip()
    if not new_md.startswith("#"):
        new_md = ("#" * depth) + " Discussion\n\n" + new_md
    elif not new_md.startswith("#" * depth + " "):
        new_md = re.sub(r"^#+\s+", ("#" * depth) + " ", new_md, count=1)
    new_md = new_md.rstrip() + "\n\n"

    return paper_md[:start] + new_md + paper_md[end:]
