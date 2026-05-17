"""Markdown → PDF rendering via WeasyPrint.

Best-effort: if the WeasyPrint deps aren't installed (local dev without
[pdf] extras) or the system libraries are missing, returns an error
string instead of raising. Callers log the error and continue — PDF
generation should never break a workflow run that has already produced
the canonical paper.md.

Vendored from `virtual-postdoc/agents/writer.py` (the deterministic-render
half; the report-rendering half is not used here).
"""
from __future__ import annotations

from pathlib import Path

_PDF_CSS = """
@page { margin: 0.75in; size: letter; }
body { font-family: -apple-system, "Helvetica Neue", "Segoe UI", sans-serif;
       font-size: 10.5pt; line-height: 1.45; color: #222; }
h1 { font-size: 20pt; margin-bottom: 4pt; }
h2 { font-size: 14pt; margin-top: 22pt; border-bottom: 1px solid #ccc; padding-bottom: 3pt; }
h3 { font-size: 12pt; margin-top: 16pt; color: #1a3d6b; }
h4 { font-size: 11pt; margin-top: 12pt; color: #444; }
p { margin: 6pt 0; }
ul, ol { margin: 4pt 0 8pt 0; padding-left: 22pt; }
li { margin: 2pt 0; }
code { background: #f4f4f4; padding: 1pt 4pt; border-radius: 3pt;
       font-family: "SF Mono", Menlo, monospace; font-size: 9pt; }
em { color: #555; }
table { border-collapse: collapse; margin: 6pt 0; }
th, td { padding: 3pt 8pt; border: 1px solid #ddd; font-size: 9.5pt; text-align: left; }
th { background: #f0f0f0; }
blockquote { border-left: 3px solid #ccc; padding-left: 10pt; color: #555; margin: 6pt 0; }
/* Cap embedded figures so tall plots don't overflow a page. */
img { display: block; max-width: 100%; max-height: 7.5in;
      margin: 8pt auto; object-fit: contain; }
/* Paper Auditor highlight classes — applied by audit_render to mark
   suspect spans in the audited PDF. */
mark.audit-partial      { background: #fff3cd; padding: 1pt 2pt; border-radius: 2pt; }
mark.audit-unsupported  { background: #f8d7da; padding: 1pt 2pt; border-radius: 2pt; color: #721c24; font-weight: 500; }
mark.audit-unverifiable { background: #ffe5b4; padding: 1pt 2pt; border-radius: 2pt; }
.audit-banner { background: #f0f0f0; border-left: 4px solid #888; padding: 8pt 12pt; margin: 0 0 16pt 0; font-size: 9.5pt; }
"""


def render_pdf(md_path: Path, pdf_path: Path) -> str | None:
    """Render a markdown file to PDF. Returns None on success, or an
    error message string on failure (importable deps missing, system
    libraries missing, etc.). Callers should log + continue, not raise.

    Relative image paths in the markdown (e.g. `figures/cell12_out0.png`
    written by paper_writer) resolve against the markdown file's
    directory, which is `base_url` to WeasyPrint.
    """
    try:
        import markdown as _md
        from weasyprint import CSS, HTML
    except ImportError as e:
        return (
            f"PDF deps not installed ({e}). The runtime image must include "
            f"weasyprint + markdown; locally run `pip install -e \".[pdf]\"`."
        )
    except OSError as e:
        return (
            f"PDF system libs missing ({e}). On Debian/Ubuntu: "
            f"apt-get install libpango-1.0-0 libpangoft2-1.0-0 libcairo2 "
            f"libfontconfig1 shared-mime-info."
        )

    html_body = _md.markdown(
        md_path.read_text(),
        extensions=["extra", "sane_lists", "smarty", "tables"],
    )
    html = (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        "<title>Manuscript</title></head>"
        f"<body>{html_body}</body></html>"
    )
    HTML(string=html, base_url=str(md_path.parent)).write_pdf(
        pdf_path, stylesheets=[CSS(string=_PDF_CSS)]
    )
    return None
