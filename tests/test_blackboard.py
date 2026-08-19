from __future__ import annotations

from write.blackboard import Blackboard


def test_blackboard_preserves_upstream_diagnostics(tmp_path):
    path = tmp_path / "blackboard.json"
    original = Blackboard(
        research_question="question",
        subsystem="pennsieve:530",
        degraded=[{"stage": "topic_extractor", "error": "bedrock_error"}],
        model_assignments={
            "opus": {"model_id": "us.anthropic.claude-sonnet-4-6"},
        },
    )
    original.save(path)
    loaded = Blackboard.load(path)
    assert loaded.degraded == original.degraded
    assert loaded.model_assignments == original.model_assignments
