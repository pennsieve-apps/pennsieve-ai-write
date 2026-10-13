"""Turn the audited Markdown into a bioRxiv preprint: LaTeX source and a PDF.

bioRxiv does not typeset what it is sent. Whatever PDF goes up is exactly what
readers see, and LaTeX has to be compiled before submission, so this produces
both: `paper.tex` beside `biorxiv-preprint.cls`, and `preprint.pdf` built from
them with `latexmk -pdf`, the same toolchain the lab's other manuscripts use.

Pandoc converts the Markdown body to a LaTeX fragment; the title, the abstract
and the front matter are set by the class. Citations are already inline text
and the References section is already a list, so there is no `.bib` and no
bibtex pass to go wrong.

A `Makefile` goes in beside them, so the folder rebuilds with `make` on any
machine with a TeX installation, and so the draft can be edited by hand after
the run.

Nothing here raises. Every failure comes back as a string, which the pipeline
records in `review.json`, because a missing LaTeX installation should not cost
anyone a manuscript that is otherwise finished.

Settings:
  VP_WRITE_TEX_CLASS    path to a different .cls to use instead of ours
  VP_WRITE_TEX_COLUMNS  "1" (default) or "2"
  VP_WRITE_TEX_PDF=0    write the .tex but do not compile it
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
DEFAULT_CLASS = TEMPLATES / "biorxiv-preprint.cls"
# bioRxiv asks every submission to declare one of these.
CATEGORIES = ("New Results", "Confirmatory Results", "Contradictory Results")

MAKEFILE = """# Rebuild the preprint PDF. Needs pdflatex and latexmk.
PDF := preprint.pdf

.PHONY: pdf clean
pdf:
\tlatexmk -pdf -interaction=nonstopmode -halt-on-error -jobname=preprint paper.tex

clean:
\tlatexmk -C -jobname=preprint paper.tex
"""


def latex_escape(text: str) -> str:
    """Escape a plain string, for the title and other front-matter fields."""
    replacements = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
                    "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
                    "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
    return "".join(replacements.get(ch, ch) for ch in text)


def split_markdown(markdown: str) -> tuple[str, str, str]:
    """(title, abstract, the rest of the body) from the manuscript Markdown.

    The paper writer is asked for a `# Title` and an `## Abstract`, but a
    manuscript missing either still has to export, so both fall back to empty
    and the body keeps whatever was there.
    """
    title = ""
    title_match = re.search(r"^\#\s+(.+?)\s*$", markdown, re.MULTILINE)
    if title_match:
        title = title_match.group(1).strip()
        markdown = markdown[:title_match.start()] + markdown[title_match.end():]
    abstract = ""
    abstract_match = re.search(
        r"^\#{2,3}\s*Abstract\s*$\n(.*?)(?=^\#{1,3}\s|\Z)", markdown,
        re.MULTILINE | re.DOTALL | re.IGNORECASE)
    if abstract_match:
        abstract = abstract_match.group(1).strip()
        markdown = markdown[:abstract_match.start()] + markdown[abstract_match.end():]
    return title, abstract, markdown.strip()


def pandoc_fragment(markdown: str, cwd: Path, pandoc: str, *, shift: int = 0) -> str:
    r"""Markdown to a LaTeX fragment, with no preamble of its own.

    `shift` moves the heading levels. The manuscript's `#` title is pulled out
    into the front matter, so its `##` sections have to come back up a level to
    become `\section` rather than `\subsection`.
    """
    command = [pandoc, "--from=markdown-raw_tex-raw_html", "--to=latex", "--wrap=preserve"]
    if shift:
        command.append(f"--shift-heading-level-by={shift}")
    result = subprocess.run(command, input=markdown, cwd=cwd, check=True,
                            capture_output=True, text=True, timeout=120)
    return result.stdout


def build_tex(title: str, abstract: str, body: str, *, authors: str, affiliation: str,
              corresponding: str, data_doi: str, category: str, columns: str,
              class_name: str) -> str:
    options = "twocolumn" if columns == "2" else ""
    running = title if len(title) <= 70 else title[:67].rstrip() + "..."
    lines = [
        f"\\documentclass[{options}]{{{class_name}}}" if options
        else f"\\documentclass{{{class_name}}}",
        "",
        f"\\title{{{latex_escape(title)}}}",
        f"\\author{{{latex_escape(authors)}}}",
        f"\\affiliation{{1}}{{{latex_escape(affiliation)}}}",
    ]
    if corresponding:
        lines.append(f"\\corresponding{{{latex_escape(corresponding)}}}")
    if data_doi:
        lines.append(f"\\datadoi{{{latex_escape(data_doi)}}}")
    lines += [
        f"\\category{{{latex_escape(category)}}}",
        f"\\runningtitle{{{latex_escape(running)}}}",
        "",
        "\\begin{document}",
        f"\\makefrontmatter{{{abstract}}}",
        "",
        body,
        "",
        "\\end{document}",
        "",
    ]
    return "\n".join(lines)


def export_tex(markdown_path: Path, *, authors: str = "Pennsieve AI Co-Scientist",
               affiliation: str = "University of Pennsylvania, Philadelphia, PA, USA",
               corresponding: str = "", data_doi: str = "",
               category: str = "New Results") -> str | None:
    """Write paper.tex and, unless turned off, compile preprint.pdf.

    Returns None when everything worked, or a sentence saying what did not.
    """
    paper_dir = markdown_path.parent
    pandoc = shutil.which("pandoc")
    if not pandoc:
        return "pandoc is not installed, so paper.tex was not written"
    if category not in CATEGORIES:
        category = "New Results"

    class_path = Path(os.environ.get("VP_WRITE_TEX_CLASS") or DEFAULT_CLASS)
    if not class_path.is_file():
        return f"no document class at {class_path}, so paper.tex was not written"
    try:
        shutil.copy2(class_path, paper_dir / class_path.name)
    except OSError as exc:
        return f"the document class could not be copied next to the paper: {exc}"

    title, abstract, body = split_markdown(markdown_path.read_text())
    try:
        body_tex = pandoc_fragment(body, paper_dir, pandoc, shift=-1)
        abstract_tex = pandoc_fragment(abstract, paper_dir, pandoc).strip() if abstract else ""
    except (OSError, subprocess.SubprocessError) as exc:
        return f"pandoc could not convert the manuscript: {type(exc).__name__}"

    (paper_dir / "paper.tex").write_text(build_tex(
        title, abstract_tex, body_tex, authors=authors, affiliation=affiliation,
        corresponding=corresponding, data_doi=data_doi, category=category,
        columns=os.environ.get("VP_WRITE_TEX_COLUMNS", "1"), class_name=class_path.stem))
    (paper_dir / "Makefile").write_text(MAKEFILE)

    if os.environ.get("VP_WRITE_TEX_PDF", "1") == "0":
        return None
    return compile_pdf(paper_dir)


def compile_pdf(paper_dir: Path) -> str | None:
    """Build preprint.pdf from paper.tex, or say why it could not be built."""
    latexmk = shutil.which("latexmk")
    if not latexmk:
        return ("latexmk is not installed, so paper.tex was written but not compiled; "
                "run `make` in the paper folder on a machine with LaTeX")
    try:
        subprocess.run(
            [latexmk, "-pdf", "-interaction=nonstopmode", "-halt-on-error",
             "-file-line-error", "-jobname=preprint", "paper.tex"],
            cwd=paper_dir, check=True, capture_output=True, text=True, timeout=600)
    except subprocess.CalledProcessError as exc:
        return f"LaTeX could not build the PDF: {first_latex_error(exc.stdout or '')}"
    except (OSError, subprocess.SubprocessError) as exc:
        return f"LaTeX could not build the PDF: {type(exc).__name__}"
    if not (paper_dir / "preprint.pdf").is_file():
        return "latexmk reported success but wrote no preprint.pdf"
    return None


def first_latex_error(log: str) -> str:
    """The first real error line, so review.json says something usable."""
    for line in log.splitlines():
        if line.startswith("!") or re.match(r"^\S+\.(tex|cls):\d+:", line):
            return line.strip()[:300]
    return "see the LaTeX log in the paper folder"
