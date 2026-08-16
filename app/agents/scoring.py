from __future__ import annotations

import logging
from typing import Any

from app.agents.base import BaseAgent
from app.services import external_data
from app.utils.scoring import compute_opportunity_score

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Visibility Scoring Agent inside an AI Visibility \
Intelligence platform. Given a single user question and a target business, you \
simulate how an AI assistant (like ChatGPT or Claude) would answer that question, \
and determine whether the target domain would plausibly be cited, recommended, \
or mentioned in that answer.

REASONING PROCESS (apply this before answering):
1. Consider what a well-informed AI assistant would actually say if asked this \
question today, based on the target's category, reputation signals implied by \
its description, and how it compares to the named competitors.
2. Decide whether the target domain would likely appear in that answer at all \
(domain_visible: true/false).
3. If it would appear, estimate roughly where in the answer/list it would rank \
(visibility_position: 1 = mentioned first/most prominently). If it would not \
appear, visibility_position must be null.
4. Write a one-sentence justification in visibility_notes explaining your reasoning \
(e.g. "Competitor X has stronger brand association with this exact use case").

IMPORTANT: You are NOT asked to estimate search volume or competitive difficulty \
numbers yourself — those come from a separate real search-data API. Focus only on \
the visibility judgment.

OUTPUT FORMAT:
Return ONLY a JSON object (no markdown fences, no commentary):
{
  "domain_visible": true|false,
  "visibility_position": <integer 1-10, or null if not visible>,
  "visibility_notes": "<one sentence>"
}
"""

USER_PROMPT_TEMPLATE = """Target business:
- Name: {name}
- Domain: {domain}
- Industry: {industry}
- Description: {description}
- Competitors: {competitors}

Question a user asked an AI assistant:
"{query_text}"

Would {domain} plausibly appear in the AI assistant's answer to this question? \
Return JSON only, matching the schema in the system prompt."""


class VisibilityScoringAgent(BaseAgent):
    agent_name = "agent_2_visibility_scoring"
    max_tokens = 500

    def run(self, profile: dict, query_text: str, intent: str = "informational") -> dict:
        """Scores one query. Returns a dict matching DiscoveredQuery fields
        (minus profile/run FKs), plus an "error" key (None on success).

        Failure isolation: if the LLM call fails for this single query, we
        fall back to a conservative "unknown visibility" judgment rather than
        raising, so the orchestrator can continue scoring the remaining
        queries (per the spec's "continue processing the rest" requirement).
        """
        user_prompt = USER_PROMPT_TEMPLATE.format(
            name=profile["name"],
            domain=profile["domain"],
            industry=profile["industry"],
            description=profile.get("description") or "N/A",
            competitors=", ".join(profile.get("competitors") or []) or "none listed",
            query_text=query_text,
        )

        data, error = self._run(SYSTEM_PROMPT, user_prompt)
        visibility = self._validate(data) if data else None
        if visibility is None:
            visibility = {"domain_visible": False, "visibility_position": None,
                           "visibility_notes": "Visibility judgment unavailable (LLM error); defaulted to not-visible."}

        # Real (or simulated-but-labelled) search data, independent of the LLM call.
        metrics = external_data.get_keyword_metrics(query_text)

        opportunity_score = compute_opportunity_score(
            search_volume=metrics.search_volume,
            competitive_difficulty=metrics.competition_index,
            domain_visible=visibility["domain_visible"],
            intent=intent,
        )

        return {
            "estimated_search_volume": metrics.search_volume,
            "competitive_difficulty": metrics.competition_index,
            "opportunity_score": opportunity_score,
            "domain_visible": visibility["domain_visible"],
            "visibility_position": visibility["visibility_position"],
            "visibility_notes": visibility["visibility_notes"],
            "data_source": metrics.source,
            "error": error,
        }

    @staticmethod
    def _validate(data: Any) -> dict | None:
        if not isinstance(data, dict):
            return None
        visible = data.get("domain_visible")
        if not isinstance(visible, bool):
            return None
        position = data.get("visibility_position")
        if position is not None:
            try:
                position = int(position)
                if not (1 <= position <= 10):
                    position = None
            except (TypeError, ValueError):
                position = None
        if not visible:
            position = None
        notes = str(data.get("visibility_notes", "")).strip()[:500]
        return {"domain_visible": visible, "visibility_position": position, "visibility_notes": notes}
