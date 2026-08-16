from __future__ import annotations

import logging

from app.services.llm_client import LLMClient, LLMResponseError

logger = logging.getLogger(__name__)


class BaseAgent:
    """Shared behaviour for all pipeline agents.
    Each agent subclass defines:
      - `system_prompt`: persona + constraints + output schema
      - `build_user_prompt(...)`: fills the prompt template for one call
      - `fallback(...)`: what to return if the LLM call fails after retries,
        so a single agent failure never crashes the whole pipeline.

    Keeping this contract in the base class is what makes the three agents
    "independently testable": each can be unit tested by mocking
    `LLMClient.complete_json` and asserting on the parsed/validated output.
    """

    agent_name: str = "base_agent"
    max_tokens: int = 2000

    def __init__(self, llm_client: LLMClient | None = None):
        self.llm_client = llm_client or LLMClient()
        self.last_tokens_used: int = 0

    def _run(self, system_prompt: str, user_prompt: str):
        try:
            result = self.llm_client.complete_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=self.max_tokens,
            )
            self.last_tokens_used = result.tokens_used
            return result.data, None
        except LLMResponseError as exc:
            logger.error("%s: LLM call failed after retries: %s", self.agent_name, exc)
            self.last_tokens_used = 0
            return None, str(exc)
        except RuntimeError as exc:
            # Missing API key etc — treat as agent failure, not a crash.
            logger.error("%s: configuration error: %s", self.agent_name, exc)
            self.last_tokens_used = 0
            return None, str(exc)
