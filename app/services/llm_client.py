"""Thin wrapper around the Anthropic / OpenAI SDKs that:

1. Centralises provider selection so agents don't care which LLM backs them.
2. Enforces "JSON-only" output and parses it defensively (LLMs occasionally
   wrap JSON in prose or markdown fences despite instructions).
3. Tracks token usage so the pipeline can report it back to the caller.
4. Retries once on a malformed response before giving up, so a single bad
   generation doesn't take down the whole pipeline run.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from flask import current_app

logger = logging.getLogger(__name__)


class LLMResponseError(Exception):
    """Raised when the LLM output cannot be parsed as valid JSON after retries."""


@dataclass
class LLMResult:
    data: Any
    tokens_used: int
    raw_text: str


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    # Handles ```json ... ``` or ``` ... ``` wrapping, which models add even
    # when told not to.
    fence_match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()
    return text


def _extract_first_json_block(text: str) -> str:
    """Best-effort extraction of the first {...} or [...] block in text, used
    as a fallback when the model adds commentary around the JSON."""
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(text)):
            if text[i] == opener:
                depth += 1
            elif text[i] == closer:
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    return text


def _parse_json_strict(text: str) -> Any:
    cleaned = _strip_code_fences(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        extracted = _extract_first_json_block(cleaned)
        return json.loads(extracted)  # let this raise if it still fails


class LLMClient:
    """Provider-agnostic chat-completion client returning parsed JSON."""

    def __init__(self, provider: str | None = None):
        self.provider = (provider or current_app.config["AI_PROVIDER"]).lower()

    def _call_anthropic(self, system_prompt: str, user_prompt: str, max_tokens: int) -> LLMResult:
        import anthropic

        api_key = current_app.config["ANTHROPIC_API_KEY"]
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")

        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=current_app.config["ANTHROPIC_MODEL"],
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        tokens = (response.usage.input_tokens or 0) + (response.usage.output_tokens or 0)
        return LLMResult(data=None, tokens_used=tokens, raw_text=text)

    def _call_openai(self, system_prompt: str, user_prompt: str, max_tokens: int) -> LLMResult:
        from openai import OpenAI

        api_key = current_app.config["OPENAI_API_KEY"]
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")

        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=current_app.config["OPENAI_MODEL"],
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        text = response.choices[0].message.content or ""
        tokens = response.usage.total_tokens if response.usage else 0
        return LLMResult(data=None, tokens_used=tokens, raw_text=text)

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 2000,
        retries: int = 1,
    ) -> LLMResult:
        """Call the configured provider and return parsed JSON. Retries once,
        re-prompting the model to fix its own invalid JSON, before raising
        LLMResponseError so the caller (an agent) can apply its own fallback.
        """
        last_error: Exception | None = None
        current_user_prompt = user_prompt

        for attempt in range(retries + 1):
            try:
                if self.provider == "anthropic":
                    result = self._call_anthropic(system_prompt, current_user_prompt, max_tokens)
                elif self.provider == "openai":
                    result = self._call_openai(system_prompt, current_user_prompt, max_tokens)
                else:
                    raise ValueError(f"Unknown AI_PROVIDER: {self.provider}")

                parsed = _parse_json_strict(result.raw_text)
                result.data = parsed
                return result
            except json.JSONDecodeError as exc:
                last_error = exc
                logger.warning("LLM returned invalid JSON on attempt %s: %s", attempt + 1, exc)
                current_user_prompt = (
                    user_prompt
                    + "\n\nYour previous response could not be parsed as valid JSON. "
                    "Return ONLY valid JSON, with no markdown fences and no commentary."
                )
            except Exception as exc:  # provider/network errors — don't retry these
                last_error = exc
                break

        raise LLMResponseError(str(last_error))
