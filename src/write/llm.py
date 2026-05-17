"""Pennsieve LLM Governor client — thin facade over the `pennsieve-llm` SDK.

Identical in shape to the analyze stage's llm.py — both processors invoke
the per-compute-node governor with the same logical-model-name → Bedrock-
inference-profile mapping. Kept as a separate copy here (not a shared
library) so each pennsieve-ai-* repo is a self-contained processor a
third party could fork without pulling in our internal monorepo.
"""
from __future__ import annotations

import os
import time
from datetime import datetime

from pennsieve_llm import Governor


# Logical model name → Bedrock inference-profile ID. See analyze/llm.py.
# us.* keeps inference in US regions (HIPAA-friendly default).
MODEL_IDS: dict[str, str] = {
    "opus":   os.environ.get("VP_MODEL_OPUS",   "us.anthropic.claude-opus-4-7"),
    "sonnet": os.environ.get("VP_MODEL_SONNET", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"),
    "haiku":  os.environ.get("VP_MODEL_HAIKU",  "us.anthropic.claude-haiku-4-5-20251001-v1:0"),
}


class LLMClient:
    """Thin facade around the `anthropic.Anthropic` client returned by the
    pennsieve-llm Governor. Agents call `messages_create(model="opus", ...)`
    and get back the SDK's `Message` object directly.
    """

    def __init__(self) -> None:
        self._gov = Governor()
        self.usage_log: list[dict] = []

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
        bedrock_model = MODEL_IDS.get(model)
        if not bedrock_model:
            raise RuntimeError(
                f"No model ID configured for logical name {model!r}. "
                f"Set VP_MODEL_{model.upper()} or use 'opus'/'sonnet'/'haiku'."
            )

        send_messages = list(messages)
        if prefill is not None:
            send_messages = send_messages + [{"role": "assistant", "content": prefill}]

        prompt_chars = sum(_chars(m.get("content", "")) for m in send_messages) + len(system or "")
        prefill_note = f" prefill={prefill!r}" if prefill else ""
        print(
            f"  [llm] → {agent}  model={model}  prompt~{prompt_chars:,} chars{prefill_note}",
            flush=True,
        )

        t0 = time.monotonic()
        resp = self._gov.client().messages.create(
            model=bedrock_model,
            system=system,
            messages=send_messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        elapsed = time.monotonic() - t0

        in_tok = resp.usage.input_tokens
        out_tok = resp.usage.output_tokens
        stop = resp.stop_reason or ""
        stop_note = f" stop={stop}" if stop and stop != "end_turn" else ""
        print(
            f"  [llm] ← {agent}  in={in_tok:,} tok  out={out_tok:,} tok  ({elapsed:.1f}s){stop_note}",
            flush=True,
        )

        self.usage_log.append({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "run_id": run_id,
            "agent": agent,
            "model": model,
            "model_id": bedrock_model,
            "input_tokens": in_tok,
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
