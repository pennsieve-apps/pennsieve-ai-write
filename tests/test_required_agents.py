from __future__ import annotations

import pytest

from write.agents import paper_auditor, paper_revisor
from pennsieve_ai_utils.blackboard import Blackboard, Hypothesis


def _hypothesis() -> Hypothesis:
    return Hypothesis(
        id="H1",
        claim="claim",
        rationale="rationale",
        supporting_evidence=[],
        predicted_observation="observation",
        suggested_experiment="experiment",
    )


@pytest.mark.parametrize(
    "module,call,expected",
    [
        (paper_auditor, "audit", "Paper audit failed"),
        (paper_revisor, "revise", "Paper revision failed"),
    ],
)
def test_required_agent_failure_propagates(monkeypatch, tmp_path, module, call, expected):
    bb = Blackboard(research_question="question", subsystem="dataset")
    paper_path = tmp_path / "paper.md"
    notebook_path = tmp_path / "analysis.ipynb"
    paper_path.write_text("# Paper")
    notebook_path.write_text("{}")
    monkeypatch.setattr(module.notebook_extract, "extract", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        module.notebook_extract, "summarize_for_prompt", lambda *args, **kwargs: "",
    )
    monkeypatch.setattr(
        module, "call_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("governor unavailable")),
    )

    kwargs = {
        "hypothesis": _hypothesis(),
        "executed_nb_path": notebook_path,
        "paper_md_path": paper_path,
    }
    if call == "audit":
        kwargs["figures_dir"] = tmp_path / "figures"
    else:
        kwargs["user_note"] = "fix unsupported claim"

    with pytest.raises(RuntimeError, match=expected):
        getattr(module, call)(bb, object(), **kwargs)

    assert bb.notebook[-1]["action"] == "error"
