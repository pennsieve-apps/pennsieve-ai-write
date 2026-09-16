import json
from types import SimpleNamespace

import pytest

from write import pipeline
from write.blackboard import Blackboard, Hypothesis, CriticReview
from write.tools import tex_export


@pytest.mark.parametrize("passes", [True, False])
def test_audit_pairs_every_version_and_blocks_unsupported_draft(monkeypatch, tmp_path, passes):
    h = Hypothesis("H2", "claim", "rationale", [], "prediction", "experiment", analysis_summary="done", analysis_workdir="hypotheses/H2", methods_critique={"verdict": "sound", "issues": []})
    bb = Blackboard("q", "dataset", hypotheses=[h], critic_reviews=[CriticReview("H2", 4, 4, 4, 4, [], "accept")])
    input_dir = tmp_path / "input"
    nb = input_dir / "hypotheses/H2/analysis.ipynb"
    nb.parent.mkdir(parents=True)
    nb.write_text(json.dumps({"cells": [{"cell_type": "code", "source": "print(1)", "execution_count": 1, "outputs": []}]}))
    output_dir = tmp_path / "output"
    monkeypatch.setenv("VP_WRITE_ENHANCE_DISCUSSION", "0")
    monkeypatch.setenv("VP_WRITE_MAX_AUDIT_ITERS", "2")
    monkeypatch.setattr(pipeline, "_render_pdf_log", lambda *a: None)
    monkeypatch.setattr(pipeline, "_render_audited_pdf_log", lambda *a: None)
    monkeypatch.setattr(tex_export, "export_tex", lambda p: None)
    def writer(bb, client, **kwargs):
        path = kwargs["paper_dir"] / "paper.md"
        path.write_text("Original manuscript")
        return path, path.read_text()
    monkeypatch.setattr(pipeline.paper_writer, "write_paper", writer)
    texts = []
    def audit(bb, client, **kwargs):
        texts.append(kwargs["paper_md_path"].read_text())
        return {"claims": [{"text": "claim", "verdict": "supported" if passes and len(texts) == 2 else "unsupported"}]}
    monkeypatch.setattr(pipeline.paper_auditor, "audit", audit)
    monkeypatch.setattr(pipeline.paper_revisor, "revise", lambda *a, **k: {"paper_md": "Revised manuscript"})
    kwargs = dict(hypothesis_id="auto", input_dir=input_dir, output_dir=output_dir)
    if passes:
        pipeline.run_write(bb, SimpleNamespace(usage_log=[]), **kwargs)
    else:
        with pytest.raises(RuntimeError, match="unsupported manuscript claims"):
            pipeline.run_write(bb, SimpleNamespace(usage_log=[]), **kwargs)
    paper = output_dir / "papers/H2"
    assert (paper / "paper.iter1.md").read_text() == texts[0]
    assert (paper / "paper.iter2.md").read_text() == texts[1]
    assert (paper / "paper.md").read_text() == texts[-1]
    assert json.loads((paper / "review.json").read_text())["status"] == ("ready_for_review" if passes else "blocked")
