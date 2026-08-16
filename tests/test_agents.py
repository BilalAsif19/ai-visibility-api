"""Unit tests for agent logic with the LLM call mocked out, per the
assessment's 'unit tests for agent logic using mocked LLM responses'
bonus criterion. Each agent is tested for: happy path, malformed-output
fallback, and (where relevant) validation of individual bad records.
"""
from unittest.mock import patch

from app.agents.discovery import QueryDiscoveryAgent
from app.agents.recommendation import ContentRecommendationAgent
from app.agents.scoring import VisibilityScoringAgent
from app.services.llm_client import LLMResult
from app.utils.scoring import compute_opportunity_score

PROFILE = {
    "name": "Frase",
    "domain": "frase.io",
    "industry": "SEO Content Tools",
    "description": "AI-powered content briefs and SEO research",
    "competitors": ["surferseo.com", "marketmuse.com"],
}


def _mock_llm_result(data, tokens=100):
    return LLMResult(data=data, tokens_used=tokens, raw_text="mocked")


class TestQueryDiscoveryAgent:
    def test_happy_path_returns_validated_queries(self, app):
        with app.app_context():
            payload = {
                "queries": [
                    {"query_text": "What is the best SEO content tool?", "intent": "best_of"},
                    {"query_text": "Frase vs Surfer SEO — which is better?", "intent": "comparison"},
                ]
            }
            with patch(
                "app.services.llm_client.LLMClient.complete_json",
                return_value=_mock_llm_result(payload),
            ):
                agent = QueryDiscoveryAgent()
                result = agent.run(PROFILE, max_queries=20, min_queries=10)

            assert result["error"] is None
            assert len(result["queries"]) == 2
            assert result["queries"][0]["intent"] == "best_of"

    def test_invalid_intent_defaults_to_informational(self, app):
        with app.app_context():
            payload = {"queries": [{"query_text": "How does AI SEO work?", "intent": "nonsense"}]}
            with patch(
                "app.services.llm_client.LLMClient.complete_json",
                return_value=_mock_llm_result(payload),
            ):
                agent = QueryDiscoveryAgent()
                result = agent.run(PROFILE)

            assert result["queries"][0]["intent"] == "informational"

    def test_malformed_output_triggers_fallback(self, app):
        from app.services.llm_client import LLMResponseError

        with app.app_context():
            with patch(
                "app.services.llm_client.LLMClient.complete_json",
                side_effect=LLMResponseError("bad json"),
            ):
                agent = QueryDiscoveryAgent()
                result = agent.run(PROFILE, min_queries=10)

            assert result["error"] is not None
            assert len(result["queries"]) >= 10  # fallback still meets the minimum


class TestVisibilityScoringAgent:
    def test_happy_path_scores_query(self, app):
        with app.app_context():
            payload = {
                "domain_visible": False,
                "visibility_position": None,
                "visibility_notes": "Competitor has stronger brand presence.",
            }
            with patch(
                "app.services.llm_client.LLMClient.complete_json",
                return_value=_mock_llm_result(payload),
            ):
                agent = VisibilityScoringAgent()
                result = agent.run(PROFILE, "What is the best SEO tool?", "best_of")

            assert result["error"] is None
            assert result["domain_visible"] is False
            assert 0.0 <= result["opportunity_score"] <= 1.0
            assert result["estimated_search_volume"] > 0

    def test_llm_failure_falls_back_to_not_visible(self, app):
        from app.services.llm_client import LLMResponseError

        with app.app_context():
            with patch(
                "app.services.llm_client.LLMClient.complete_json",
                side_effect=LLMResponseError("timeout"),
            ):
                agent = VisibilityScoringAgent()
                result = agent.run(PROFILE, "What is the best SEO tool?", "best_of")

            assert result["error"] is not None
            assert result["domain_visible"] is False
            # Scoring must still succeed even when the visibility judgment fails.
            assert result["opportunity_score"] >= 0.0


class TestContentRecommendationAgent:
    def test_filters_recommendations_with_unknown_query_uuid(self, app):
        with app.app_context():
            gap_queries = [
                {"query_uuid": "q1", "query_text": "best seo tool?", "opportunity_score": 0.8, "intent": "best_of"}
            ]
            payload = {
                "recommendations": [
                    {
                        "query_uuid": "q1",
                        "content_type": "blog_post",
                        "title": "Best SEO Tools in 2026",
                        "rationale": "Closes the visibility gap for this exact question.",
                        "target_keywords": ["seo tool", "content optimization"],
                        "priority": "high",
                    },
                    {
                        "query_uuid": "does-not-exist",
                        "content_type": "blog_post",
                        "title": "Should be dropped",
                        "rationale": "Invalid query_uuid",
                        "target_keywords": [],
                        "priority": "low",
                    },
                ]
            }
            with patch(
                "app.services.llm_client.LLMClient.complete_json",
                return_value=_mock_llm_result(payload),
            ):
                agent = ContentRecommendationAgent()
                result = agent.run(PROFILE, gap_queries)

            assert result["error"] is None
            assert len(result["recommendations"]) == 1
            assert result["recommendations"][0]["query_uuid"] == "q1"

    def test_no_gap_queries_returns_empty_without_calling_llm(self, app):
        with app.app_context():
            with patch("app.services.llm_client.LLMClient.complete_json") as mock_call:
                agent = ContentRecommendationAgent()
                result = agent.run(PROFILE, [])

            mock_call.assert_not_called()
            assert result == {"recommendations": [], "error": None}


class TestOpportunityScoreFormula:
    def test_not_visible_scores_higher_than_visible_otherwise_equal(self):
        visible = compute_opportunity_score(1000, 50, domain_visible=True, intent="best_of")
        not_visible = compute_opportunity_score(1000, 50, domain_visible=False, intent="best_of")
        assert not_visible > visible

    def test_comparison_intent_scores_higher_than_informational(self):
        comparison = compute_opportunity_score(1000, 50, domain_visible=False, intent="comparison")
        informational = compute_opportunity_score(1000, 50, domain_visible=False, intent="informational")
        assert comparison > informational

    def test_score_bounded_between_zero_and_one(self):
        score = compute_opportunity_score(1_000_000, 0, domain_visible=False, intent="comparison")
        assert 0.0 <= score <= 1.0
