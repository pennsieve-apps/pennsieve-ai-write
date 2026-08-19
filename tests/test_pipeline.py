from __future__ import annotations

from write.pipeline import _cost_from_usage


def test_cost_uses_concrete_routed_model_family():
    usage = [{
        "event": "request_complete",
        "logical_model": "opus",
        "model_id": "us.anthropic.claude-sonnet-4-6",
        "input_tokens": 1_000_000,
        "output_tokens": 1_000_000,
    }]
    assert _cost_from_usage(usage) == 18.0


def test_cost_accepts_legacy_usage_events():
    usage = [{
        "model": "sonnet",
        "input_tokens": 1_000_000,
        "output_tokens": 0,
    }]
    assert _cost_from_usage(usage) == 3.0
