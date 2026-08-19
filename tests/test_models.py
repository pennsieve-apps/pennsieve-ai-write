from __future__ import annotations

from write import models

ALLOW_LIST = [
    "us.anthropic.claude-sonnet-4-6",
    "us.anthropic.claude-3-5-haiku-20241022-v1:0",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
]


class Denied(Exception):
    def __init__(self, body):
        self.body = body
        super().__init__(repr(body))


def test_reported_allow_list_routes_write_roles_to_sonnet_46():
    resolver = models.ModelResolver(ALLOW_LIST)
    assert resolver.resolve("opus") == "us.anthropic.claude-sonnet-4-6"
    assert resolver.resolve("sonnet") == "us.anthropic.claude-sonnet-4-6"


def test_allow_list_is_parsed_from_governor_error():
    error = Denied({"error": "model_not_allowed", "allowedModels": ALLOW_LIST})
    assert models.is_model_not_allowed(error)
    assert models.parse_allowed_models(error) == ALLOW_LIST


def test_learning_invalidates_optimistic_assignment():
    resolver = models.ModelResolver()
    assert resolver.resolve("opus") == "us.anthropic.claude-opus-4-7"
    resolver.learn(ALLOW_LIST)
    assert resolver.resolve("opus") == "us.anthropic.claude-sonnet-4-6"
