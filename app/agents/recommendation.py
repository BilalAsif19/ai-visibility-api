from __future__ import annotations

import logging
from typing import Any

from app.agents.base import BaseAgent

logger = logging.getLogger(__name__)

VALID_CONTENT_TYPES = {"blog_post", "landing_page", "faq", "comparison_page", "case_study", "product_page"}
VALID_PRIORITIES = {"high", "medium", "low"}

SYSTEM_PROMPT = """You are the Content Recommendation Agent inside an AI Visibility \
Intelligence platform. You are given a list of high-opportunity questions where the \
target business currently does NOT appear in AI-generated answers. Your job is to \
recommend specific, actionable content the business should create to close that gap.

RULES:
- Produce between 3 and 5 recommendations total (not per query — across the whole batch).
- Prioritise covering the highest opportunity_score queries first; you do not need one \
recommendation per query if a single piece of content can address multiple related queries \
(pick the single query_uuid it most directly targets).
- Each recommendation must be genuinely specific to the query and business given — no generic \
"write a blog post about your industry" advice.
- "title" should be a specific, publishable content title, not a description of the task.
- "rationale" must explain, in 1-3 sentences, why this content closes the specific gap for \
that query (reference the query and why the domain currently doesn't appear).
- "target_keywords" should be 3-6 concrete keyword/topic phrases the content should cover.
- "content_type" must be one of: blog_post, landing_page, faq, comparison_page, case_study, product_page.
- "priority" must be one of: high, medium, low — base it primarily on the query's opportunity_score \
(higher score -> higher priority) and secondarily on commercial intent.

OUTPUT FORMAT:
Return ONLY a JSON object (no markdown fences, no commentary):
{
  "recommendations": [
    {
      "query_uuid": "<the query_uuid this targets, copied exactly from the input>",
      "content_type": "blog_post|landing_page|faq|comparison_page|case_study|product_page",
      "title": "...",
      "rationale": "...",
      "target_keywords": ["...", "..."],
      "priority": "high|medium|low"
    }
  ]
}
"""

USER_PROMPT_TEMPLATE = """Business:
- Name: {name}
- Domain: {domain}
- Industry: {industry}
- Competitors: {competitors}

Top opportunity gap queries (domain NOT currently visible), sorted by opportunity_score descending:
{query_block}

Generate 3-5 content recommendations as JSON, matching the schema in the system prompt. \
Every "query_uuid" you output MUST be copied exactly from the list above."""


class ContentRecommendationAgent(BaseAgent):
    agent_name = "agent_3_content_recommendation"
    max_tokens = 2000

    def run(self, profile: dict, gap_queries: list[dict]) -> dict:
        """gap_queries: list of dicts with at least query_uuid, query_text,
        opportunity_score, intent — already filtered to domain_visible=False
        and sorted by opportunity_score descending by the caller.

        Returns {"recommendations": [...], "error": str|None}.
        """
        if not gap_queries:
            return {"recommendations": [], "error": None}

        valid_uuids = {q["query_uuid"] for q in gap_queries}
        query_block = "\n".join(
            f'- query_uuid: "{q["query_uuid"]}" | opportunity_score: {q["opportunity_score"]} | '
            f'intent: {q.get("intent", "informational")} | question: "{q["query_text"]}"'
            for q in gap_queries[:15]  # cap prompt size
        )
        user_prompt = USER_PROMPT_TEMPLATE.format(
            name=profile["name"],
            domain=profile["domain"],
            industry=profile["industry"],
            competitors=", ".join(profile.get("competitors") or []) or "none listed",
            query_block=query_block,
        )

        data, error = self._run(SYSTEM_PROMPT, user_prompt)
        if error or not data:
            return {"recommendations": self._fallback(gap_queries), "error": error}

        recs = self._validate(data, valid_uuids)
        if not recs:
            return {"recommendations": self._fallback(gap_queries), "error": "empty_or_invalid_output"}

        return {"recommendations": recs, "error": None}

    @staticmethod
    def _validate(data: Any, valid_uuids: set) -> list[dict]:
        if not isinstance(data, dict) or not isinstance(data.get("recommendations"), list):
            return []

        cleaned = []
        for item in data["recommendations"]:
            if not isinstance(item, dict):
                continue
            query_uuid = item.get("query_uuid")
            if query_uuid not in valid_uuids:
                continue
            content_type = str(item.get("content_type", "")).strip().lower()
            if content_type not in VALID_CONTENT_TYPES:
                content_type = "blog_post"
            title = str(item.get("title", "")).strip()
            rationale = str(item.get("rationale", "")).strip()
            if not title or not rationale:
                continue
            keywords = item.get("target_keywords")
            if not isinstance(keywords, list):
                keywords = []
            keywords = [str(k).strip() for k in keywords if str(k).strip()][:6]
            priority = str(item.get("priority", "")).strip().lower()
            if priority not in VALID_PRIORITIES:
                priority = "medium"

            cleaned.append({
                "query_uuid": query_uuid,
                "content_type": content_type,
                "title": title,
                "rationale": rationale,
                "target_keywords": keywords,
                "priority": priority,
            })
            if len(cleaned) >= 5:
                break
        return cleaned

    @staticmethod
    def _fallback(gap_queries: list[dict]) -> list[dict]:
        """Template fallback if the LLM call fails, covering the top-scoring
        gap queries so the pipeline still returns something actionable."""
        recs = []
        for q in gap_queries[:5]:
            recs.append({
                "query_uuid": q["query_uuid"],
                "content_type": "blog_post",
                "title": f'Answering: "{q["query_text"]}"',
                "rationale": (
                    "This query currently has no visibility for the domain; a dedicated "
                    "piece of content directly answering it is the most direct way to close the gap."
                ),
                "target_keywords": [q["query_text"]],
                "priority": "high" if q.get("opportunity_score", 0) >= 0.6 else "medium",
            })
        return recs
