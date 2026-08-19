from __future__ import annotations

import pytest

from write import llm


@pytest.mark.parametrize(
    "model_id,prefill,sampling",
    [
        ("us.anthropic.claude-sonnet-4-5-20250929-v1:0", True, True),
        ("us.anthropic.claude-sonnet-4-6", False, True),
        ("us.anthropic.claude-opus-4-7", False, False),
    ],
)
def test_request_capabilities(model_id, prefill, sampling):
    assert llm.supports_prefill(model_id) is prefill
    assert llm.supports_sampling(model_id) is sampling


def test_sdk_retry_budget_is_bounded():
    assert llm.SDK_MAX_RETRIES <= 1


MESSAGE = type("Message", (), {
    "content": [type("Block", (), {"type": "text", "text": "{}"})()],
    "usage": type("Usage", (), {"input_tokens": 10, "output_tokens": 2})(),
    "stop_reason": "end_turn",
})()


class FakePermissionDenied(Exception):
    def __init__(self, body):
        self.body = body
        super().__init__(repr(body))


class StreamContext:
    def __init__(self, result):
        self.result = result

    def __enter__(self):
        if isinstance(self.result, Exception):
            raise self.result
        return self

    def __exit__(self, *args):
        return False

    def get_final_message(self):
        return self.result


class Messages:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        return StreamContext(self.results.pop(0))


class RawClient:
    def __init__(self, messages):
        self.messages = messages
        self.options = None

    def with_options(self, **kwargs):
        self.options = kwargs
        return self


def test_permission_failure_is_traced_rerouted_and_retried(monkeypatch):
    allow_list = [
        "us.anthropic.claude-sonnet-4-6",
        "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    ]
    denied = FakePermissionDenied({
        "error": "model_not_allowed", "allowedModels": allow_list,
    })
    messages = Messages([denied, MESSAGE])
    raw = RawClient(messages)
    client = llm.LLMClient()
    client._gov = type("Governor", (), {"client": lambda self: raw})()
    monkeypatch.setattr(llm.anthropic, "PermissionDeniedError", FakePermissionDenied)

    response = client.messages_create(
        model="opus",
        system="system",
        messages=[{"role": "user", "content": "large manuscript prompt"}],
        agent="paper_writer",
        run_id="run-1",
    )

    assert response is MESSAGE
    assert [call["model"] for call in messages.calls] == [
        "us.anthropic.claude-opus-4-7",
        "us.anthropic.claude-sonnet-4-6",
    ]
    assert [event["event"] for event in client.usage_log] == [
        "request_error", "request_complete",
    ]
    assert raw.options == {"max_retries": llm.SDK_MAX_RETRIES}


class PreflightMessages:
    def __init__(self, allow_list):
        self.allow_list = allow_list
        self.calls = []

    def create(self, **kwargs):
        model_id = kwargs["model"]
        self.calls.append(model_id)
        if model_id == "__write_preflight_probe__":
            raise FakePermissionDenied({
                "error": "model_not_allowed", "allowedModels": self.allow_list,
            })
        return MESSAGE


def test_preflight_verifies_model_shared_by_both_roles(monkeypatch):
    allow_list = [
        "us.anthropic.claude-sonnet-4-6",
        "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    ]
    messages = PreflightMessages(allow_list)
    raw = RawClient(messages)
    client = llm.LLMClient()
    client._gov = type("Governor", (), {"client": lambda self: raw})()
    monkeypatch.setattr(llm.anthropic, "PermissionDeniedError", FakePermissionDenied)

    assignments = client.preflight()

    assert assignments["opus"]["model_id"] == "us.anthropic.claude-sonnet-4-6"
    assert assignments["sonnet"]["model_id"] == "us.anthropic.claude-sonnet-4-6"
    assert messages.calls == [
        "__write_preflight_probe__",
        "us.anthropic.claude-sonnet-4-6",
    ]
