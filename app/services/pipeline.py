from __future__ import annotations

import logging

from app.agents.discovery import QueryDiscoveryAgent
from app.agents.recommendation import ContentRecommendationAgent
from app.agents.scoring import VisibilityScoringAgent
from app.extensions import db
from app.models.profile import BusinessProfile
from app.models.query import DiscoveredQuery
from app.models.recommendation import ContentRecommendation
from app.models.run import PipelineRun
from app.models.base import utcnow

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """Runs Agent 1 -> Agent 2 (per query) -> Agent 3 in sequence for a
    profile, persisting results as it goes and tolerating partial failures.

    Failure isolation policy:
      - If Agent 1 fails outright, the run is marked "failed" (there is
        nothing downstream to do without queries).
      - If Agent 2 fails for an individual query, that query is still saved
        with a conservative default (not visible, notes explaining the
        failure) and scoring continues for the rest — a single bad LLM call
        never stops the batch.
      - If Agent 3 fails, the run is marked "partial_failure": queries were
        discovered and scored, but no recommendations were produced.
    """

    def __init__(self):
        self.discovery_agent = QueryDiscoveryAgent()
        self.scoring_agent = VisibilityScoringAgent()
        self.recommendation_agent = ContentRecommendationAgent()

    def run(self, profile: BusinessProfile, max_queries: int, min_queries: int) -> PipelineRun:
        run = PipelineRun(profile_uuid=profile.uuid, status="running", agent_status={})
        db.session.add(run)
        db.session.commit()

        total_tokens = 0
        profile_dict = profile.to_dict()

        # ---- Agent 1: Query Discovery ----
        discovery_result = self.discovery_agent.run(profile_dict, max_queries, min_queries)
        total_tokens += self.discovery_agent.last_tokens_used
        run.agent_status["agent_1"] = "ok" if discovery_result["error"] is None else "used_fallback"

        raw_queries = discovery_result["queries"]
        if not raw_queries:
            run.status = "failed"
            run.error_message = "Agent 1 (discovery) produced no queries and fallback also failed."
            run.completed_at = utcnow()
            db.session.commit()
            return run

        # ---- Persist discovered queries, then Agent 2: Visibility Scoring ----
        scored_queries: list[DiscoveredQuery] = []
        agent2_errors = 0
        for item in raw_queries:
            score_result = self.scoring_agent.run(
                profile_dict, item["query_text"], item["intent"]
            )
            total_tokens += self.scoring_agent.last_tokens_used
            if score_result.get("error"):
                agent2_errors += 1

            query = DiscoveredQuery(
                profile_uuid=profile.uuid,
                run_uuid=run.uuid,
                query_text=item["query_text"],
                intent=item["intent"],
                estimated_search_volume=score_result["estimated_search_volume"],
                competitive_difficulty=score_result["competitive_difficulty"],
                opportunity_score=score_result["opportunity_score"],
                domain_visible=score_result["domain_visible"],
                visibility_position=score_result["visibility_position"],
                visibility_notes=score_result["visibility_notes"],
            )
            db.session.add(query)
            scored_queries.append(query)

        db.session.flush()  # assign PKs without committing yet
        run.queries_discovered = len(raw_queries)
        run.queries_scored = len(scored_queries)
        run.agent_status["agent_2"] = (
            "ok" if agent2_errors == 0 else f"partial ({agent2_errors} of {len(raw_queries)} used fallback)"
        )

        # ---- Agent 3: Content Recommendations for the top opportunity gaps ----
        gap_queries = sorted(
            [q for q in scored_queries if not q.domain_visible],
            key=lambda q: q.opportunity_score,
            reverse=True,
        )
        gap_query_dicts = [
            {
                "query_uuid": q.uuid,
                "query_text": q.query_text,
                "opportunity_score": q.opportunity_score,
                "intent": q.intent,
            }
            for q in gap_queries[:10]
        ]

        rec_result = self.recommendation_agent.run(profile_dict, gap_query_dicts)
        total_tokens += self.recommendation_agent.last_tokens_used
        run.agent_status["agent_3"] = "ok" if rec_result["error"] is None else "used_fallback"

        for rec in rec_result["recommendations"]:
            db.session.add(
                ContentRecommendation(
                    profile_uuid=profile.uuid,
                    query_uuid=rec["query_uuid"],
                    run_uuid=run.uuid,
                    content_type=rec["content_type"],
                    title=rec["title"],
                    rationale=rec["rationale"],
                    target_keywords=rec["target_keywords"],
                    priority=rec["priority"],
                )
            )

        run.recommendations_generated = len(rec_result["recommendations"])
        run.tokens_used = total_tokens
        run.completed_at = utcnow()

        if discovery_result["error"] and agent2_errors == len(raw_queries):
            run.status = "failed"
            run.error_message = "All agents fell back to defaults; check LLM provider configuration."
        elif agent2_errors > 0 or rec_result["error"] or discovery_result["error"]:
            run.status = "partial_failure"
        else:
            run.status = "completed"

        profile.status = "completed" if run.status != "failed" else "failed"
        db.session.commit()
        return run
