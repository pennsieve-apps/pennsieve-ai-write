"""The preprint export: splitting the manuscript, and failing without crashing.

The compile itself needs a TeX installation, so the tests that need one skip
where it is missing rather than failing the suite on a developer's laptop.
"""
from __future__ import annotations

import shutil

import pytest

from write.tools import tex_export

PAPER = """# A title that spans the page and keeps going for a while

## Abstract

One paragraph of abstract, with a deposit cited as doi:10.26275/pgzg-jlcs.

## Introduction

Body text with a *word* in italics.

## References

1. Someone et al. (2018). A paper. doi:10.1/x
"""


def test_the_title_and_abstract_come_out_of_the_body():
    title, abstract, body = tex_export.split_markdown(PAPER)
    assert title == "A title that spans the page and keeps going for a while"
    assert abstract.startswith("One paragraph of abstract")
    assert "# A title" not in body and "## Abstract" not in body
    assert "## Introduction" in body, "the rest of the paper is untouched"


def test_a_manuscript_with_no_abstract_still_splits():
    title, abstract, body = tex_export.split_markdown("# Just a title\n\nSome text.\n")
    assert title == "Just a title" and abstract == "" and body == "Some text."


def test_a_manuscript_with_no_headings_keeps_its_text():
    title, abstract, body = tex_export.split_markdown("Just some prose.\n")
    assert (title, abstract) == ("", "")
    assert body == "Just some prose."


def test_front_matter_characters_are_escaped():
    assert tex_export.latex_escape("50% of H&E_stained") == r"50\% of H\&E\_stained"


def test_the_document_names_the_class_and_the_front_matter():
    tex = tex_export.build_tex(
        "T", "the abstract", "the body", authors="A", affiliation="Penn",
        corresponding="a@b.c", data_doi="10.1/x", category="Confirmatory Results",
        columns="1", class_name="biorxiv-preprint")
    assert "\\documentclass{biorxiv-preprint}" in tex
    assert "\\makefrontmatter{the abstract}" in tex
    assert "\\category{Confirmatory Results}" in tex
    assert "\\datadoi{10.1/x}" in tex
    assert tex.rstrip().endswith("\\end{document}")


def test_two_columns_is_a_class_option():
    tex = tex_export.build_tex("T", "a", "b", authors="A", affiliation="P", corresponding="",
                               data_doi="", category="New Results", columns="2",
                               class_name="biorxiv-preprint")
    assert "\\documentclass[twocolumn]{biorxiv-preprint}" in tex


def test_a_category_outside_biorxivs_three_falls_back(tmp_path, monkeypatch):
    """bioRxiv accepts exactly three, so an invented one must not reach the file."""
    monkeypatch.setenv("VP_WRITE_TEX_PDF", "0")
    if not shutil.which("pandoc"):
        pytest.skip("pandoc is not installed")
    paper = tmp_path / "paper.md"
    paper.write_text(PAPER)
    assert tex_export.export_tex(paper, category="Amazing Results") is None
    assert "\\category{New Results}" in (tmp_path / "paper.tex").read_text()


def test_a_missing_class_is_reported_not_raised(tmp_path, monkeypatch):
    monkeypatch.setenv("VP_WRITE_TEX_CLASS", str(tmp_path / "nothing-here.cls"))
    paper = tmp_path / "paper.md"
    paper.write_text(PAPER)
    problem = tex_export.export_tex(paper)
    assert problem and "document class" in problem
    assert not (tmp_path / "paper.tex").exists()


@pytest.mark.skipif(not shutil.which("pandoc"), reason="pandoc is not installed")
def test_the_export_writes_the_class_and_a_makefile_beside_the_paper(tmp_path, monkeypatch):
    monkeypatch.setenv("VP_WRITE_TEX_PDF", "0")
    paper = tmp_path / "paper.md"
    paper.write_text(PAPER)
    assert tex_export.export_tex(paper, data_doi="10.26275/pgzg-jlcs") is None
    assert (tmp_path / "biorxiv-preprint.cls").is_file(), "the class travels with the paper"
    assert "latexmk" in (tmp_path / "Makefile").read_text()
    tex = (tmp_path / "paper.tex").read_text()
    assert "\\section{Introduction}" in tex, "the title's removal lifts the headings a level"
    assert "\\datadoi{10.26275/pgzg-jlcs}" in tex


@pytest.mark.skipif(not (shutil.which("pandoc") and shutil.which("latexmk")),
                    reason="pandoc and latexmk are both needed to build a PDF")
def test_the_pdf_is_built_from_the_generated_source(tmp_path):
    paper = tmp_path / "paper.md"
    paper.write_text(PAPER)
    assert tex_export.export_tex(paper) is None
    assert (tmp_path / "preprint.pdf").stat().st_size > 1000


@pytest.mark.skipif(shutil.which("latexmk") is not None, reason="latexmk is installed here")
def test_a_missing_latexmk_keeps_the_tex_and_says_so(tmp_path, monkeypatch):
    if not shutil.which("pandoc"):
        pytest.skip("pandoc is not installed")
    paper = tmp_path / "paper.md"
    paper.write_text(PAPER)
    problem = tex_export.export_tex(paper)
    assert problem and "latexmk" in problem
    assert (tmp_path / "paper.tex").is_file(), "the source survives a missing compiler"


@pytest.mark.skipif(not (shutil.which("pandoc") and shutil.which("latexmk")),
                    reason="pandoc and latexmk are both needed to build a PDF")
def test_the_title_does_not_collapse_into_the_author_line(tmp_path):
    """The title is set at 20pt with its own leading.

    Wrapping it in setspace's `spacing` environment silently dropped it back to
    body size and let the author line ride up into it, because that
    environment ends the paragraph before the new size takes hold.
    """
    paper = tmp_path / "paper.md"
    paper.write_text(PAPER)
    assert tex_export.export_tex(paper) is None
    tex = (tmp_path / "paper.tex").read_text()
    assert "\\begin{spacing}" not in (tmp_path / "biorxiv-preprint.cls").read_text()
    assert "\\makefrontmatter" in tex


@pytest.mark.skipif(not shutil.which("pandoc"), reason="pandoc is not installed")
def test_the_class_carries_the_cc0_attribution(tmp_path, monkeypatch):
    """CC0 requires nothing, but the record of where this came from should stay."""
    monkeypatch.setenv("VP_WRITE_TEX_PDF", "0")
    paper = tmp_path / "paper.md"
    paper.write_text(PAPER)
    tex_export.export_tex(paper)
    header = (tmp_path / "biorxiv-preprint.cls").read_text()[:2000]
    assert "CC0" in header and "cleveref" in header
