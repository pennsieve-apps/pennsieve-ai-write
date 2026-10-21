from __future__ import annotations

import pytest

from pennsieve_ai_utils import pricing
from write.pipeline import _cost_from_usage


def test_cost_uses_concrete_routed_model_family():
    usage = [{
        "event": "request_complete",
        "logical_model": "opus",
        "model_id": "us.anthropic.claude-sonnet-4-6",
        "input_tokens": 1_000_000,
        "output_tokens": 1_000_000,
    }]
    # A `us.` profile pays the regional premium over the global list price.
    assert _cost_from_usage(usage) == pytest.approx(18.0 * pricing.REGIONAL_PREMIUM)


def test_cost_accepts_legacy_usage_events():
    usage = [{
        "model": "sonnet",
        "input_tokens": 1_000_000,
        "output_tokens": 0,
    }]
    # A bare family name names no inference profile. Every stage here calls a
    # regional one, so that is the assumption, and it does not undercount.
    assert _cost_from_usage(usage) == pytest.approx(3.0 * pricing.REGIONAL_PREMIUM)


def _blackboard_with(outcome, reason="18 patients is too few"):
    from pennsieve_ai_utils.blackboard import Blackboard, CriticReview, Hypothesis
    h = Hypothesis("H5", "claim", "why", [], "pred", "experiment")
    h.iteration = 1
    h.analysis_workdir = "hypotheses/H5"
    h.analysis_summary = "The analysis ran and produced numbers."
    h.methods_critique = {"outcome": outcome, "not_testable_reason": reason}
    return Blackboard("q", "pennsieve:530", iterations_completed=1, hypotheses=[h],
                      critic_reviews=[CriticReview("H5", 4, 4, 4, 4, [], "accept", 1)])


@pytest.mark.parametrize("outcome, phrase", [
    ("not_testable", "is not testable with this deposit"),
    ("unresolved", "did not pass its methods review after every round"),
])
def test_an_analysis_that_did_not_pass_is_refused_with_its_own_reason(outcome, phrase):
    """A hypothesis Analyze gave up on still carries a workdir and a summary, so
    the refusal has to say what actually happened, not the generic line."""
    from write.pipeline import select_hypothesis
    with pytest.raises(ValueError, match="18 patients is too few") as caught:
        select_hypothesis(_blackboard_with(outcome), "auto")
    assert phrase in str(caught.value)


def test_an_empty_manuscript_is_refused_rather_than_written(tmp_path, monkeypatch):
    """An empty paper.md used to be written and audited as if it were a paper."""
    from write.agents import paper_writer
    from pennsieve_ai_utils.blackboard import Blackboard, Hypothesis
    monkeypatch.setattr(paper_writer, "call_json", lambda client, **kw: {"paper_md": "   \n"})
    monkeypatch.setattr(paper_writer.notebook_extract, "extract", lambda *a, **k: [])
    monkeypatch.setattr(paper_writer.notebook_extract, "summarize_for_prompt", lambda c: "")
    h = Hypothesis("H5", "claim", "why", [], "pred", "experiment")
    with pytest.raises(RuntimeError, match="no manuscript text"):
        paper_writer.write_paper(Blackboard("q", "s"), client=None, hypothesis=h,
                                 executed_nb_path=tmp_path / "nb.ipynb", paper_dir=tmp_path)
    assert not (tmp_path / "paper.md").exists()


def test_a_run_report_is_written_even_when_there_is_no_manuscript(tmp_path, monkeypatch):
    """The runs worth reading are the ones that produced no paper."""
    from pennsieve_ai_utils.blackboard import Blackboard
    from write import main as write_main

    import pennsieve_ai_utils.run_report_summary as summary_module

    run_dir = tmp_path / "run"
    (run_dir / "write").mkdir(parents=True)
    # No model call in a unit test; the figures are what matter here.
    monkeypatch.setattr(summary_module, "summarize", lambda facts, client, **kw: "")

    bb = Blackboard("q", "pennsieve:530")
    write_main.build_run_report(bb, client=None, output_dir=run_dir / "write")
    assert (run_dir / "report.html").is_file(), "the report lands at the run root"
    assert "run report" in (run_dir / "report.html").read_text().lower()


def test_a_report_failure_does_not_change_the_outcome(tmp_path, monkeypatch):
    from pennsieve_ai_utils.blackboard import Blackboard
    from write import main as write_main
    import pennsieve_ai_utils.run_report as report_module

    def explode(_):
        raise RuntimeError("unreadable run folder")

    monkeypatch.setattr(report_module, "collect", explode)
    bb = Blackboard("q", "s")
    write_main.build_run_report(bb, client=None, output_dir=tmp_path / "write")
    assert any(entry["action"] == "report_failed" for entry in bb.notebook)
