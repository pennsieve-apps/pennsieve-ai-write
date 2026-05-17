"""Render an audited paper as a PDF with claim-level highlights.

Takes the original paper.md plus the audit JSON (from paper_auditor)
and produces a paper_audited.pdf where suspect spans are wrapped in
colored marks: yellow (`partial`), red (`unsupported`), orange
(`unverifiable`). Supported claims are unmarked.

Best-effort substring matching: if the auditor's `text` field doesn't
appear verbatim in the markdown, the highlight is skipped — but the
claim remains in the audit JSON for human review. Each substring is
highlighted on its first occurrence only.

Vendored from `virtual-postdoc/tools/audit_render.py`.
"""
from __future__ import annotations

from pathlib import Path

from write.tools.pdf_render import render_pdf

VERDICT_CLASS = {
    "partial": "audit-partial",
    "unsupported": "audit-unsupported",
    "unverifiable": "audit-unverifiable",
}


def _wrap_first(md: str, substring: str, css_class: str) -> tuple[str, bool]:
    """Wrap the FIRST occurrence of `substring` in `md` with a `<mark class=...>`."""
    if not substring or substring not in md:
        return md, False
    idx = md.index(substring)
    wrapped = f'<mark class="{css_class}">{substring}</mark>'
    return md[:idx] + wrapped + md[idx + len(substring):], True


def _verdict_counts(claims: list[dict]) -> dict[str, int]:
    counts = {"supported": 0, "partial": 0, "unsupported": 0, "unverifiable": 0}
    for c in claims:
        v = c.get("verdict", "")
        if v in counts:
            counts[v] += 1
    return counts


def _fallback_summary(audit: dict) -> str:
    """When the auditor's `summary` is missing or truncated, derive a short
    summary from the structured claims."""
    claims = audit.get("claims") or []
    by_verdict: dict[str, list[dict]] = {}
    for c in claims:
        by_verdict.setdefault(c.get("verdict", ""), []).append(c)

    exemplars: list[str] = []
    for v in ("unsupported", "partial", "unverifiable"):
        for c in (by_verdict.get(v) or [])[:2]:
            text = (c.get("text") or "").strip()
            if text:
                snippet = text[:100] + ("..." if len(text) > 100 else "")
                exemplars.append(f"[{v}] '{snippet}'")
            if len(exemplars) >= 2:
                break
        if len(exemplars) >= 2:
            break

    if not exemplars:
        return "All claims supported by source artifacts; no concerns flagged."
    return "Examples of flagged spans: " + " · ".join(exemplars)


def _audit_banner(audit: dict, n_wrapped: int, n_total: int) -> str:
    counts = _verdict_counts(audit.get("claims") or [])
    summary = (audit.get("summary", "") or "").strip()
    # Auditor sometimes hits max_tokens mid-summary; fall back to a
    # generated one when the result is suspiciously short or ends
    # mid-sentence.
    if len(summary) < 80 or not summary.rstrip().endswith((".", "!", "?")):
        summary = _fallback_summary(audit)
    return (
        '<div class="audit-banner">'
        f"<strong>Paper Audit Summary</strong> — checked {sum(counts.values())} claims "
        f"(<span style='color:#155724'>{counts['supported']} supported</span>, "
        f"<span style='color:#856404'>{counts['partial']} partial</span>, "
        f"<span style='color:#721c24'>{counts['unsupported']} unsupported</span>, "
        f"<span style='color:#995c00'>{counts['unverifiable']} unverifiable</span>); "
        f"highlighted {n_wrapped}/{n_total} non-supported spans inline.<br>"
        f"<em>{summary}</em>"
        "</div>\n\n"
    )


def render_audited_paper(md_path: Path, audit: dict, out_pdf: Path) -> str | None:
    """Build paper_audited.pdf from paper.md + audit JSON. Returns None on
    success or an error message string on PDF render failure."""
    md_text = md_path.read_text()
    claims = audit.get("claims") or []
    non_supported = [c for c in claims if c.get("verdict") in VERDICT_CLASS]

    n_wrapped = 0
    # Sort by length descending so we wrap "p = 0.001" before "0.001".
    non_supported.sort(key=lambda c: -len(c.get("text", "") or ""))
    for c in non_supported:
        text = (c.get("text") or "").strip()
        css = VERDICT_CLASS[c["verdict"]]
        md_text, ok = _wrap_first(md_text, text, css)
        if ok:
            n_wrapped += 1

    md_text = _audit_banner(audit, n_wrapped, len(non_supported)) + md_text

    # Write the audited markdown next to the output PDF so figure paths
    # still resolve relative to the paper directory.
    audited_md = out_pdf.with_suffix(".md")
    audited_md.write_text(md_text)
    return render_pdf(audited_md, out_pdf)
