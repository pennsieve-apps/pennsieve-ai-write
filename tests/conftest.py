from __future__ import annotations

import sys
import types
import pytest


@pytest.fixture(autouse=True)
def explicit_test_transport(monkeypatch):
    monkeypatch.setenv("PENNSIEVE_LLM_MOCK", "1")


try:
    import pennsieve_llm  # noqa: F401
except ModuleNotFoundError:
    stub = types.ModuleType("pennsieve_llm")
    stub.Governor = object
    sys.modules["pennsieve_llm"] = stub
