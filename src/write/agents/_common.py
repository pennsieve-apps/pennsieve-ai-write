"""Agent helpers shared across the Co-Scientist stages live in
`pennsieve_ai_utils.agents`. This module binds `load_prompt` to this
stage's prompts directory and re-exports the rest so agent code keeps a
single import."""
from __future__ import annotations

from pathlib import Path

from pennsieve_ai_utils import agents as _shared
from pennsieve_ai_utils.agents import (  # noqa: F401 - re-exported for agent modules
    attack_kind,
    call_json,
    extract_json,
    first_text,
    format_datasets,
    strip_attack_tag,
)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def load_prompt(name: str) -> str:
    return _shared.load_prompt(PROMPTS_DIR, name)


__all__ = [
    "PROMPTS_DIR",
    "attack_kind",
    "call_json",
    "extract_json",
    "first_text",
    "format_datasets",
    "load_prompt",
    "strip_attack_tag",
]
