"""Integration tests for the REST endpoints. The pipeline-triggering test
mocks the LLM layer so it runs fast and deterministically without real API
keys, exercising the full orchestrator -> DB -> response path."""
from unittest.mock import patch

from app.services.llm_client import LLMResult


def _mock_result(data):
    return LLMResult(data=data, tokens_used=50, raw_text="mocked")


def test_create_profile_success(client, sample_profile_payload):
    response = client.post("/api/v1/profiles", json=sample_profile_payload)
    assert response.status_code == 201
    body = response.get_json()
    assert body["domain"] == "frase.io"
    assert body["status"] == "created"
    assert "profile_uuid" in body


def test_create_profile_missing_fields_returns_400(client):
    response = client.post("/api/v1/profiles", json={"name": "Frase"})
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"]["code"] == "validation_error"


def test_get_profile_not_found_returns_404(client):
    response = client.get("/api/v1/profiles/does-not-exist")
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "not_found"


def test_full_pipeline_run_end_to_end(client, sample_profile_payload):
    create_resp = client.post("/api/v1/profiles", json=sample_profile_payload)
    profile_uuid = create_resp.get_json()["profile_uuid"]

    discovery_payload = {
        "queries": [
            {"query_text": "What is the best AI content brief tool?", "intent": "best_of"},
            {"query_text": "Frase vs Surfer SEO — which is better?", "intent": "comparison"},
        ]
    }
    scoring_payload = {
        "domain_visible": False,
        "visibility_position": None,
        "visibility_notes": "Not currently mentioned in AI answers for this query.",
    }
    rec_payload = {
        "recommendations": [
            {
                "query_uuid": "PLACEHOLDER",
                "content_type": "comparison_page",
                "title": "Frase vs Surfer SEO: Full Comparison",
                "rationale": "Directly answers the comparison query where Frase is not visible.",
                "target_keywords": ["frase vs surfer seo", "content brief tool comparison"],
                "priority": "high",
            }
        ]
    }

    def fake_complete_json(self, system_prompt, user_prompt, max_tokens=2000, retries=1):
        if "Query Discovery" in system_prompt:
            return _mock_result(discovery_payload)
        if "Visibility Scoring" in system_prompt:
            return _mock_result(scoring_payload)
        if "Content Recommendation" in system_prompt:
            # Recommendation agent validates query_uuid against real generated
            # UUIDs, so just approve whatever the caller listed first.
            import re

            match = re.search(r'query_uuid: "([a-f0-9\-]+)"', user_prompt)
            if match:
                rec_payload["recommendations"][0]["query_uuid"] = match.group(1)
            return _mock_result(rec_payload)
        raise AssertionError("Unexpected system prompt in test")

    with patch("app.services.llm_client.LLMClient.complete_json", fake_complete_json, create=True):
        run_resp = client.post(f"/api/v1/profiles/{profile_uuid}/run")

    assert run_resp.status_code == 200
    run_body = run_resp.get_json()
    assert run_body["status"] == "completed"
    assert run_body["queries_discovered"] == 2
    assert run_body["queries_scored"] == 2
    assert len(run_body["top_opportunity_queries"]) <= 3

    queries_resp = client.get(f"/api/v1/profiles/{profile_uuid}/queries")
    assert queries_resp.status_code == 200
    assert queries_resp.get_json()["pagination"]["total_items"] == 2

    recs_resp = client.get(f"/api/v1/profiles/{profile_uuid}/recommendations")
    assert recs_resp.status_code == 200
    assert len(recs_resp.get_json()["recommendations"]) >= 1


def test_query_filters_validate_status_param(client, sample_profile_payload):
    create_resp = client.post("/api/v1/profiles", json=sample_profile_payload)
    profile_uuid = create_resp.get_json()["profile_uuid"]

    response = client.get(f"/api/v1/profiles/{profile_uuid}/queries?status=invalid")
    assert response.status_code == 400
