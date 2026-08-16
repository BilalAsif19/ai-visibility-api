from __future__ import annotations

import logging
from typing import Any

from app.agents.base import BaseAgent

logger = logging.getLogger(__name__)

VALID_INTENTS = {"comparison", "best_of", "informational", "transactional"}

SYSTEM_PROMPT = """You are the Query Discovery Agent inside an AI Visibility \
Intelligence platform. Your sole job is to generate realistic, natural-language \
questions that real users type into AI assistants (ChatGPT, Claude, Perplexity) \
when they are researching products or services in a specific competitive space.

RULES:
- Generate between 10 and 20 questions.
- Questions must be phrased exactly as a user would type them into an AI \
assistant chat box (conversational, not SEO keyword fragments). \
Good: "What is the best AI tool for writing SEO content briefs?" \
Bad: "best ai tool seo content briefs" (this is a keyword, not a question).
- Cover a mix of intents:
  - "comparison": explicitly compares two or more named products/brands \
(e.g. "X vs Y — which is better for ...?")
  - "best_of": asks for the best/top option in a category \
(e.g. "What is the best tool for ...?")
  - "informational": asks how to do something or how something works, \
without naming a specific brand
  - "transactional": signals buying intent (pricing, "should I buy", \
"is X worth it")
- Every question must be plausible for someone evaluating the given industry, \
using the target business's domain, description, and competitor list as context.
- Do not invent products or industries outside what is given.
- Do not repeat near-duplicate questions.

OUTPUT FORMAT:
Return ONLY a JSON object (no markdown fences, no commentary) with this exact shape:
{
  "queries": [
    {"query_text": "...", "intent": "comparison|best_of|informational|transactional"}
  ]
}
Every "intent" value MUST be one of exactly: comparison, best_of, informational, transactional.
"""

USER_PROMPT_TEMPLATE = """Business profile:
- Name: {name}
- Domain: {domain}
- Industry: {industry}
- Description: {description}
- Competitors: {competitors}

Generate 10-20 realistic questions a potential customer would ask an AI \
assistant while researching products/services in this space. Return JSON only, \
matching the schema described in the system prompt."""


class QueryDiscoveryAgent(BaseAgent):
    agent_name = "agent_1_query_discovery"
    max_tokens = 2500

    def run(self, profile: dict, max_queries: int = 20, min_queries: int = 10) -> dict:
        """Returns {"queries": [{"query_text", "intent"}, ...], "error": str|None}"""
        user_prompt = USER_PROMPT_TEMPLATE.format(
            name=profile["name"],
            domain=profile["domain"],
            industry=profile["industry"],
            description=profile.get("description") or "N/A",
            competitors=", ".join(profile.get("competitors") or []) or "none listed",
        )

        data, error = self._run(SYSTEM_PROMPT, user_prompt)
        if error or not data:
            return {"queries": self._fallback(profile, min_queries), "error": error}

        queries = self._validate(data, max_queries)
        if not queries:
            return {"queries": self._fallback(profile, min_queries), "error": "empty_or_invalid_output"}

        return {"queries": queries, "error": None}

    @staticmethod
    def _validate(data: Any, max_queries: int) -> list[dict]:
        if not isinstance(data, dict) or not isinstance(data.get("queries"), list):
            return []

        seen = set()
        cleaned = []
        for item in data["queries"]:
            if not isinstance(item, dict):
                continue
            text = str(item.get("query_text", "")).strip()
            intent = str(item.get("intent", "informational")).strip().lower()
            if not text or text.lower() in seen:
                continue
            if intent not in VALID_INTENTS:
                intent = "informational"
            seen.add(text.lower())
            cleaned.append({"query_text": text, "intent": intent})
            if len(cleaned) >= max_queries:
                break
        return cleaned

    @staticmethod
    def _fallback(profile: dict, min_queries: int) -> list[dict]:
        """Deterministic template-based fallback used only if the LLM call
        fails entirely, so the pipeline can still complete end-to-end."""
        industry = profile.get("industry", "this industry")
        name = profile.get("name", "this business")
        competitors = profile.get("competitors") or []
        templates = [
            (f"What is the best {industry} tool?", "best_of"),
            (f"How do I choose a {industry} solution?", "informational"),
            (f"Is {name} worth it for {industry}?", "transactional"),
            (f"What are the top {industry} platforms in 2026?", "best_of"),
        ]
        for competitor in competitors[:6]:
            templates.append((f"{name} vs {competitor} — which is better?", "comparison"))
            templates.append((f"How does {competitor} compare to alternatives?", "comparison"))
        return [
            {"query_text": text, "intent": intent}
            for text, intent in templates[: max(min_queries, len(templates))]
        ]
