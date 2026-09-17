"""Shared test setup: unit tests never contact the governor."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def offline_governor(monkeypatch):
    monkeypatch.setenv("PENNSIEVE_LLM_MOCK", "1")
