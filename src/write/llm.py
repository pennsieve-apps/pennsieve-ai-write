"""Governor-backed LLM client with allow-list-aware model routing."""
from __future__ import annotations

import os
import re
import time
from datetime import datetime

import anthropic
from pennsieve_llm import Governor

from write.models import (
    ModelResolver,
    discover_allowed_models,
    family_key,
    is_access_denied,
    is_model_not_allowed,
    parse_allowed_models,
    render_manifest,
)

_NO_PREFILL = ("opus-4-6", "opus-4-7", "opus-4-8", "opus-5", "sonnet-4-6", "sonnet-5")
_NO_SAMPLING = ("opus-4-7", "opus-4-8", "opus-5", "sonnet-5")
_DATE_SUFFIX = re.compile(r"-\d{8}(?:-v\d+:\d+)?$")
SDK_MAX_RETRIES = int(os.environ.get("VP_LLM_MAX_RETRIES", "1"))
MAX_ATTEMPTS = 3
PREFLIGHT_ROLES = ("opus", "sonnet")


def supports_prefill(model_id: str) -> bool:
    family = _DATE_SUFFIX.sub("", model_id.strip())
    return not any(tag in family for tag in _NO_PREFILL)


def supports_sampling(model_id: str) -> bool:
    family = _DATE_SUFFIX.sub("", model_id.strip())
    return not any(tag in family for tag in _NO_SAMPLING)


class LLMClient:
    """Resolve logical model roles and send direct Messages API calls."""

    def __init__(self) -> None:
        self._gov = Governor()
        self._resolver = ModelResolver()
        self.usage_log: list[dict] = []

    def preflight(self) -> dict:
        """Discover allowed models and verify assignments are invokable."""
        allowed = discover_allowed_models(self._probe)
        if allowed:
            self._resolver.learn(allowed)
        self._assign_roles()
        self._verify_usable()
        self._assign_roles()
        print(render_manifest(self._resolver), flush=True)
        return self._resolver.assignments()

    def _assign_roles(self) -> None:
        for logical_name in PREFLIGHT_ROLES:
            self._resolver.resolve(logical_name)

    def _verify_usable(self, max_swaps: int = 6) -> None:
        swaps = 0
        verified: set[str] = set()
        for logical_name in PREFLIGHT_ROLES:
            while True:
                model_id = self.resolve_model(logical_name)
                key = family_key(model_id)
                if key in verified:
                    break
                try:
                    self._probe(model_id)
                except anthropic.PermissionDeniedError as exc:
                    if swaps >= max_swaps:
                        raise
                    if is_access_denied(exc):
                        swaps += 1
                        print(
                            f"  [llm] ! {model_id} is permitted but not invokable "
                            f"(IAM); dropping it for {logical_name!r}.", flush=True,
                        )
                        self._resolver.mark_unusable(model_id)
                        continue
                    if is_model_not_allowed(exc):
                        learned = parse_allowed_models(exc)
                        if learned:
                            swaps += 1
                            self._resolver.learn(learned)
                            continue
                    raise
                except Exception as exc:
                    print(
                        f"  [llm] preflight could not verify {model_id} "
                        f"({type(exc).__name__}); continuing.", flush=True,
                    )
                verified.add(key)
                break

    def _probe(self, model_id: str) -> None:
        self._gov.client().messages.create(
            model=model_id, max_tokens=1,
            messages=[{"role": "user", "content": "."}],
        )

    def resolve_model(self, logical_name: str) -> str:
        return self._resolver.resolve(logical_name)

    def supports_prefill(self, logical_name: str) -> bool:
        return supports_prefill(self.resolve_model(logical_name))

    def model_assignments(self) -> dict:
        return self._resolver.assignments()

    def _send(self, kwargs: dict):
        client = self._gov.client()
        if hasattr(client, "with_options"):
            client = client.with_options(max_retries=SDK_MAX_RETRIES)
        stream = getattr(client.messages, "stream", None)
        if stream is None:
            return client.messages.create(**kwargs)
        with stream(**kwargs) as response_stream:
            return response_stream.get_final_message()

    def messages_create(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict],
        max_tokens: int = 16384,
        prefill: str | None = None,
        run_id: str | None = None,
        agent: str | None = None,
        temperature: float = 0.0,
    ):
        bedrock_model = self.resolve_model(model)
        prompt_chars = sum(_chars(m.get("content", "")) for m in messages) + len(system or "")

        for attempt in range(1, MAX_ATTEMPTS + 1):
            prefill_used = prefill if prefill is not None and supports_prefill(bedrock_model) else None
            send_messages = list(messages)
            if prefill_used is not None:
                send_messages.append({"role": "assistant", "content": prefill_used})
            prefill_note = f" prefill={prefill_used!r}" if prefill_used else ""
            print(
                f"  [llm] → {agent}  logical={model}  model={bedrock_model}  "
                f"attempt={attempt}/{MAX_ATTEMPTS}  prompt~{prompt_chars:,} chars{prefill_note}",
                flush=True,
            )

            kwargs = {
                "model": bedrock_model,
                "system": system,
                "messages": send_messages,
                "max_tokens": max_tokens,
            }
            if supports_sampling(bedrock_model):
                kwargs["temperature"] = temperature

            t0 = time.monotonic()
            try:
                resp = self._send(kwargs)
                break
            except anthropic.PermissionDeniedError as exc:
                elapsed = time.monotonic() - t0
                not_allowed = is_model_not_allowed(exc)
                access_denied = is_access_denied(exc)
                allowed = parse_allowed_models(exc) if not_allowed else None
                self.usage_log.append({
                    "ts": datetime.now().isoformat(timespec="seconds"),
                    "run_id": run_id,
                    "agent": agent,
                    "event": "request_error",
                    "attempt": attempt,
                    "logical_model": model,
                    "model_id": bedrock_model,
                    "error_type": "model_not_allowed" if not_allowed else (
                        "access_denied" if access_denied else type(exc).__name__
                    ),
                    "allowed_models": allowed or [],
                    "elapsed_s": round(elapsed, 2),
                })
                if attempt == MAX_ATTEMPTS:
                    raise
                if not_allowed:
                    if not allowed:
                        raise
                    print(
                        f"  [llm] ! {bedrock_model} rejected; governor allows "
                        f"{', '.join(allowed)}. Re-resolving {model!r}.", flush=True,
                    )
                    self._resolver.learn(allowed)
                elif access_denied:
                    print(
                        f"  [llm] ! {bedrock_model} is allowed but not invokable (IAM); "
                        f"re-resolving {model!r}.", flush=True,
                    )
                    self._resolver.mark_unusable(bedrock_model)
                else:
                    raise
                bedrock_model = self.resolve_model(model)
        else:  # pragma: no cover
            raise RuntimeError("LLM retry loop exhausted")

        elapsed = time.monotonic() - t0
        in_tok = resp.usage.input_tokens
        out_tok = resp.usage.output_tokens
        if in_tok == 0 and not getattr(self, "_warned_zero_usage", False):
            print("  [llm] WARNING: governor reported zero input tokens; cost estimates are incomplete. "
                  "Check governor usage telemetry.", flush=True)
            self._warned_zero_usage = True
        stop = resp.stop_reason or ""
        stop_note = f" stop={stop}" if stop and stop != "end_turn" else ""
        print(
            f"  [llm] ← {agent}  in={in_tok:,} tok  out={out_tok:,} tok  "
            f"({elapsed:.1f}s){stop_note}", flush=True,
        )

        self.usage_log.append({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "run_id": run_id,
            "agent": agent,
            "event": "request_complete",
            "logical_model": model,
            "model_id": bedrock_model,
            "input_tokens": in_tok,
            "input_usage_suspect": in_tok == 0,
            "output_tokens": out_tok,
            "elapsed_s": round(elapsed, 2),
            "stop_reason": stop,
        })
        return resp


def _chars(content) -> int:
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(len(b.get("text", "")) if isinstance(b, dict) else 0 for b in content)
    return 0
