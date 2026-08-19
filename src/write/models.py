"""Allow-list-aware model resolution for the Write stage."""
from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass

_FAMILY_BASE = {"haiku": 100, "sonnet": 200, "opus": 300}
_DATE_SUFFIX = re.compile(r"-\d{8}(?:-v\d+:\d+)?$")
_NUMERIC = re.compile(r"^\d{1,2}$")


def family_key(model_id: str) -> str:
    return _DATE_SUFFIX.sub("", model_id.strip())


def rank(model_id: str) -> int | None:
    tokens = family_key(model_id).lower().replace(".", "-").split("-")
    family = next((token for token in tokens if token in _FAMILY_BASE), None)
    if family is None:
        return None
    numbers = [int(token) for token in tokens if _NUMERIC.fullmatch(token)]
    major = numbers[0] if numbers else 0
    minor = numbers[1] if len(numbers) > 1 else 0
    return _FAMILY_BASE[family] + major * 10 + minor


@dataclass(frozen=True)
class Role:
    name: str
    logical_name: str
    optimistic: str
    floor: str
    ceiling: str | None = None

    @property
    def floor_rank(self) -> int:
        value = rank(self.floor)
        assert value is not None
        return value


ROLES = {
    "opus": Role(
        "reasoning", "opus", "us.anthropic.claude-opus-4-7",
        "us.anthropic.claude-sonnet-4-6",
    ),
    "sonnet": Role(
        "synthesis", "sonnet", "us.anthropic.claude-sonnet-4-6",
        "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "us.anthropic.claude-opus-4-6",
    ),
    "haiku": Role(
        "bulk", "haiku", "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "us.anthropic.claude-3-5-haiku-20241022-v1:0",
        "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    ),
}


class ModelNotAvailable(RuntimeError):
    """No permitted model meets a role's minimum capability."""


def _error_body(exc: Exception) -> dict | None:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        return body
    try:
        parsed = exc.response.json()  # type: ignore[attr-defined]
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def parse_allowed_models(exc: Exception) -> list[str] | None:
    body = _error_body(exc)
    if body and isinstance(body.get("allowedModels"), list):
        models = [str(model) for model in body["allowedModels"]]
        return models or None
    match = re.search(r"['\"]allowedModels['\"]\s*:\s*\[(.*?)\]", str(exc), re.DOTALL)
    if match:
        models = re.findall(r"['\"]([^'\"]+)['\"]", match.group(1))
        return models or None
    return None


def is_model_not_allowed(exc: Exception) -> bool:
    body = _error_body(exc)
    return bool(body and body.get("error") == "model_not_allowed") or "model_not_allowed" in str(exc)


def is_access_denied(exc: Exception) -> bool:
    body = _error_body(exc)
    return bool(body and body.get("error") == "access_denied") or "access_denied" in str(exc)


class ModelResolver:
    """Resolve logical roles onto the best currently usable model."""

    def __init__(self, allowed: list[str] | None = None) -> None:
        self._lock = threading.Lock()
        self._allowed = list(allowed) if allowed else None
        self._unusable: set[str] = set()
        self._assignments: dict[str, dict] = {}

    @property
    def allowed(self) -> list[str] | None:
        return list(self._allowed) if self._allowed is not None else None

    def learn(self, allowed: list[str]) -> None:
        with self._lock:
            self._allowed = list(allowed)
            self._assignments.clear()

    def mark_unusable(self, model_id: str) -> None:
        with self._lock:
            self._unusable.add(family_key(model_id))
            self._assignments.clear()

    @property
    def unusable(self) -> list[str]:
        with self._lock:
            return sorted(self._unusable)

    def assignments(self) -> dict[str, dict]:
        with self._lock:
            return {key: dict(value) for key, value in self._assignments.items()}

    def resolve(self, logical_name: str) -> str:
        if logical_name not in ROLES:
            raise RuntimeError(
                f"Unknown logical model {logical_name!r}; expected one of {', '.join(ROLES)}"
            )
        with self._lock:
            existing = self._assignments.get(logical_name)
            if existing:
                return existing["model_id"]
            assignment = self._select(ROLES[logical_name])
            self._assignments[logical_name] = assignment
            return assignment["model_id"]

    def _select(self, role: Role) -> dict:
        env_name = f"VP_MODEL_{role.logical_name.upper()}"
        explicit = os.environ.get(env_name, "").strip()
        preferred = explicit or role.optimistic

        if self._allowed is None:
            if family_key(preferred) in self._unusable:
                raise ModelNotAvailable(
                    f"{preferred} cannot be invoked and the governor did not report an "
                    f"allow-list to choose an alternative. Set {env_name} to a model the "
                    "governor can invoke."
                )
            return self._assignment(role, preferred, "pinned" if explicit else "optimistic")

        allowed_keys = {family_key(model) for model in self._allowed}
        if explicit:
            if family_key(explicit) not in allowed_keys:
                raise ModelNotAvailable(
                    f"{env_name} pins {explicit}, but the governor does not allow it. "
                    f"Allowed models: {', '.join(self._allowed)}"
                )
            if family_key(explicit) in self._unusable:
                raise ModelNotAvailable(
                    f"{env_name} pins {explicit}, but the governor cannot invoke it (IAM)."
                )
            return self._assignment(role, explicit, "pinned")

        candidates = sorted(
            ((model, rank(model)) for model in self._allowed
             if family_key(model) not in self._unusable),
            key=lambda item: item[1] or -1,
            reverse=True,
        )
        ceiling = rank(role.ceiling) if role.ceiling else None
        eligible = [
            (model, value) for model, value in candidates
            if value is not None and value >= role.floor_rank
            and (ceiling is None or value <= ceiling)
        ]
        if not eligible:
            raise ModelNotAvailable(
                f"No usable governor model meets the {role.name!r} floor ({role.floor}). "
                f"Allowed models: {', '.join(self._allowed) or '(none)'}. "
                f"Add a capable model to the allow-list or deliberately pin {env_name}."
            )
        return self._assignment(role, eligible[0][0], "ranked")

    @staticmethod
    def _assignment(role: Role, model_id: str, source: str) -> dict:
        return {
            "role": role.name,
            "logical_name": role.logical_name,
            "model_id": model_id,
            "rank": rank(model_id),
            "source": source,
            "at_floor": rank(model_id) == role.floor_rank,
        }


PROBE_MODEL = "__write_preflight_probe__"


def discover_allowed_models(probe) -> list[str] | None:
    try:
        probe(PROBE_MODEL)
    except Exception as exc:
        allowed = parse_allowed_models(exc)
        if allowed:
            return allowed
        print(
            f"  [llm] preflight probe returned no allow-list ({type(exc).__name__}); "
            "will learn it from the first model rejection.", flush=True,
        )
    return None


def render_manifest(resolver: ModelResolver) -> str:
    lines = ["--- LLM preflight ---"]
    allowed = resolver.allowed
    unusable = set(resolver.unusable)
    if allowed:
        lines.append(f"  allow-list ({len(allowed)} models):")
        for model_id in sorted(allowed, key=lambda item: rank(item) or -1, reverse=True):
            flag = " [not invokable — IAM]" if family_key(model_id) in unusable else ""
            lines.append(f"    {model_id}{flag}")
    else:
        lines.append("  allow-list: not reported")
    lines.append("  assignments:")
    for logical, assignment in sorted(resolver.assignments().items()):
        lines.append(
            f"    {logical:<7} ({assignment['role']}) -> {assignment['model_id']} "
            f"[{assignment['source']}]"
        )
    return "\n".join(lines)
