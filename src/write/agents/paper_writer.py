"""Paper Writer — turns one hypothesis + its executed notebook into a paper.

One reasoning-role call per hypothesis. Reads the executed notebook produced
by the analyze stage, extracts cell sources + outputs + figures, and produces
a structured ~4–6 page paper in markdown form.

Adapted from `virtual-postdoc/agents/paper_writer.py`. Differences:
  - Imports rewritten for the `write.*` namespace.
  - Dropped `fit_review` and `methods_review` parameters: analyze doesn't
    produce a fit review, and v0 of the write stage doesn't try to run the
    methods critic from this side. `methods_critique` lives on the
    hypothesis (populated by analyze) and flows in through that path
    instead.
  - Dropped `find_hypothesis_with_executed`: the caller picks the one
    hypothesis via env var and supplies the notebook path directly.
"""
from __future__ import annotations

from pathlib import Path

from write.agents._common import call_json, format_datasets, load_prompt, strip_attack_tag
from write.blackboard import Blackboard, Hypothesis
from write.llm import LLMClient
from write.tools import doi_lookup, notebook_extract

MODEL = "opus"
AGENT = "paper_writer"


def _format_supporting_claims(bb: Blackboard, indices: list[int]) -> str:
    out: list[str] = []
    for i in indices:
        if 0 <= i < len(bb.literature_claims):
            c = bb.literature_claims[i]
            out.append(f"  [{i}] {c.text} ({c.source})")
    return "\n".join(out) if out else "  (none cited)"


def _format_field_context(bb: Blackboard) -> str:
    if bb.director_brief is None:
        return "(no director brief — limited field context)"
    b = bb.director_brief
    parts = ["### Field landscape (from Director's brief)", b.field_landscape, ""]
    if b.review_papers:
        parts.append("### Papers the system has read (use only these for citations)")
        for p in b.review_papers:
            doi = p.get("doi", "")
            title = p.get("title", "")
            year = p.get("year", "")
            role = p.get("role", "")
            parts.append(f"- {title} ({year}) doi:{doi} [{role}]")
    return "\n".join(parts)


def _collect_citable_dois(bb: Blackboard, h: Hypothesis) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []

    def _add(raw: str) -> None:
        d = (raw or "").strip().lower()
        for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
            if d.startswith(prefix):
                d = d[len(prefix):]
        if d and d not in seen:
            seen.add(d); out.append(d)

    if bb.director_brief and bb.director_brief.review_papers:
        for p in bb.director_brief.review_papers:
            _add(p.get("doi") or "")
    for i in (h.supporting_evidence or []):
        if 0 <= i < len(bb.literature_claims):
            _add(bb.literature_claims[i].source or "")
    for c in (bb.deep_evidence or []):
        _add(c.get("doi") or "")
    for c in (h.evidence_chunks or []):
        _add(c.get("doi") or "")
    for ds in (bb.dataset_summaries or []):
        _add(getattr(ds, "doi", "") or "")
    return out


def _format_authoritative_bibliography(bb: Blackboard, h: Hypothesis) -> str:
    """Render an authoritative bibliography for the Paper Writer's prompt.

    For every citable DOI, provide the EXACT author / year / title / journal
    from CrossRef/DataCite. The prompt requires the model to use these
    verbatim — no inventing author names. DOIs without metadata appear with
    `(metadata unavailable)` so the model knows to cite by DOI only.
    """
    enriched = dict(bb.papers_enriched or {})
    citable = _collect_citable_dois(bb, h)
    missing = [d for d in citable if d not in enriched]
    if missing:
        enriched.update(doi_lookup.lookup_batch(missing))
    # The auditor and revisor must see the same authoritative records as
    # the writer, including DataCite dataset DOIs discovered here.
    bb.papers_enriched = enriched

    dataset_dois = {
        (getattr(d, "doi", "") or "").strip().lower()
        for d in (bb.dataset_summaries or [])
    }
    dataset_dois.discard("")

    lines = [
        "## Authoritative bibliography  (use these EXACT author/year strings — do NOT invent or modify)",
        "",
        "Each entry is tagged `[PAPER]` (peer-reviewed publication or preprint) or "
        "`[DATASET]` (repository deposit). **`[DATASET]` entries MUST appear in the "
        "final References section even if not cited inline** — they document the "
        "data substrate. Format dataset references as: "
        "`Authors (Year). Title. *Repository*. doi:...` (use the Journal field as "
        "the repository label).",
        "",
    ]
    for doi in citable:
        is_dataset = doi.lower() in dataset_dois
        tag = "[DATASET]" if is_dataset else "[PAPER]"
        md = enriched.get(doi)
        if md:
            authors = (md.get("authors") or "").strip()
            if len(authors) > 240:
                authors = authors[:240] + "..."
            year = md.get("year") or ""
            title = (md.get("title") or "").strip()
            journal = (md.get("journal") or "").strip()
            inline = doi_lookup.author_string(doi, fallback=year or "?")
            lines.append(f"- {tag} **doi:{doi}**  →  inline form: `({inline}; doi:{doi})`")
            lines.append(f"    Authors: {authors or '(none listed)'}")
            lines.append(f"    Year: {year}")
            lines.append(f"    Title: {title[:240]}")
            lines.append(f"    {'Repository' if is_dataset else 'Journal'}: {journal}")
        else:
            lines.append(
                f"- {tag} **doi:{doi}**  →  metadata unavailable; cite as `(doi:{doi})` "
                f"only — DO NOT invent an author"
            )
    return "\n".join(lines)


def _format_rag_references(bb: Blackboard, h: Hypothesis) -> str:
    chunks_by_doi: dict[str, list[dict]] = {}
    for c in (bb.deep_evidence or []) + (h.evidence_chunks or []):
        doi = (c.get("doi") or "").strip().lower()
        if not doi:
            continue
        chunks_by_doi.setdefault(doi, []).append(c)
    if not chunks_by_doi:
        return "(no full-text RAG citations available)"
    lines: list[str] = []
    for doi in sorted(chunks_by_doi):
        chunks = chunks_by_doi[doi]
        sections = sorted({(c.get("section") or "body") for c in chunks})
        snippet = (chunks[0].get("text") or "")[:240].replace("\n", " ")
        lines.append(
            f"- doi:{doi}  (chunks from sections: {', '.join(sections)[:120]})\n"
            f"    excerpt: \"{snippet}...\""
        )
    return "\n".join(lines)


def _format_reviewer_concerns(bb: Blackboard, h: Hypothesis) -> str:
    """Critic attacks for this hypothesis at its latest iteration, reframed
    as 'concerns a careful reviewer would raise.' Drives Discussion/Limitations."""
    matching = [r for r in bb.critic_reviews if r.hypothesis_id == h.id]
    if not matching:
        return "(no prior reviewer concerns recorded)"
    latest = max(matching, key=lambda r: r.iteration)
    if not latest.attacks:
        return "(no specific concerns raised)"
    return "\n".join(f"- {strip_attack_tag(a)}" for a in latest.attacks)


def _format_methods_critique(h: Hypothesis) -> list[str]:
    """If the analyze stage's methods critic produced a verdict, surface its
    concerns to the writer so they get engaged in Discussion. Returns a list
    of markdown lines (empty list if no critique)."""
    mc = h.methods_critique or {}
    if not mc:
        return []
    verdict = (mc.get("verdict") or "").strip()
    if not verdict:
        return []
    lines = [
        "",
        "## Methodological concerns from the Methods Critic (engage with these explicitly in Discussion)",
        f"Methods Critic verdict: **{verdict}**",
        (mc.get("reasoning") or "").strip(),
        "",
    ]
    for issue in mc.get("issues") or []:
        if isinstance(issue, dict):
            lines.append(f"- {issue.get('description') or issue.get('text') or ''}")
        else:
            lines.append(f"- {issue}")
    return lines


def _build_user_message(bb: Blackboard, h: Hypothesis, nb_summary: str) -> str:
    return "\n\n".join([
        f"## Hypothesis {h.id}",
        f"**Claim:** {h.claim}",
        f"**Rationale:** {h.rationale}",
        f"**Predicted observation:** {h.predicted_observation}",
        f"**Suggested experiment:** {h.suggested_experiment}",
        "",
        "## Supporting literature claims",
        _format_supporting_claims(bb, h.supporting_evidence),
        "",
        "## Field context",
        _format_field_context(bb),
        "",
        "## Full-text RAG citations (real papers — chunks retrieved from the persistent corpus)",
        _format_rag_references(bb, h),
        "",
        _format_authoritative_bibliography(bb, h),
        "",
        "## Dataset metadata",
        format_datasets(bb),
        "",
        "## Concerns a careful reviewer would raise (engage with these in Discussion/Limitations)",
        _format_reviewer_concerns(bb, h),
        *_format_methods_critique(h),
        "",
        "## Notebook content (extracted from executed notebook)",
        nb_summary,
    ])


def write_paper(
    bb: Blackboard,
    client: LLMClient,
    *,
    hypothesis: Hypothesis,
    executed_nb_path: Path,
    paper_dir: Path,
) -> tuple[Path, str]:
    """Run the Paper Writer on one hypothesis. Returns (paper_md_path, raw_markdown)."""
    paper_dir.mkdir(parents=True, exist_ok=True)
    figures_dir = paper_dir / "figures"

    cells = notebook_extract.extract(executed_nb_path, figures_dir)
    nb_summary = notebook_extract.summarize_for_prompt(cells)

    bb.log(AGENT, "extract",
           f"{hypothesis.id}: {len(cells)} cells, "
           f"{sum(len(c.image_paths) for c in cells)} figures, "
           f"{sum(1 for c in cells if c.error)} errored cells")

    system = load_prompt("paper_writer")
    user = _build_user_message(bb, hypothesis, nb_summary)
    parsed = call_json(
        client,
        agent=AGENT,
        system=system,
        user=user,
        run_id=bb.run_id,
        model=MODEL,
        max_tokens=32768,
    )
    paper_md = parsed.get("paper_md", "")
    md_path = paper_dir / "paper.md"
    md_path.write_text(paper_md)
    bb.log(AGENT, "wrote", f"{hypothesis.id} → {md_path.name} ({len(paper_md)} chars)")
    return md_path, paper_md
