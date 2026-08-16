from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.agents.scoring import VisibilityScoringAgent
from app.extensions import db
from app.models.base import utcnow
from app.models.profile import BusinessProfile
from app.models.query import DiscoveredQuery
from app.models.recommendation import ContentRecommendation
from app.utils.errors import NotFoundError, ValidationError

queries_bp = Blueprint("queries", __name__, url_prefix="/api/v1")

VALID_STATUS_FILTERS = {"visible", "not_visible", "unknown"}


def _get_profile_or_404(profile_uuid: str) -> BusinessProfile:
    profile = db.session.get(BusinessProfile, profile_uuid)
    if profile is None:
        raise NotFoundError(f"Profile '{profile_uuid}' not found")
    return profile


@queries_bp.get("/profiles/<profile_uuid>/queries")
def list_queries(profile_uuid: str):
    _get_profile_or_404(profile_uuid)

    query = DiscoveredQuery.query.filter_by(profile_uuid=profile_uuid)

    min_score = request.args.get("min_score")
    if min_score is not None:
        try:
            query = query.filter(DiscoveredQuery.opportunity_score >= float(min_score))
        except ValueError:
            raise ValidationError("'min_score' must be a number")

    status_filter = request.args.get("status")
    if status_filter is not None:
        if status_filter not in VALID_STATUS_FILTERS:
            raise ValidationError(f"'status' must be one of {sorted(VALID_STATUS_FILTERS)}")
        if status_filter == "visible":
            query = query.filter(DiscoveredQuery.domain_visible.is_(True))
        elif status_filter == "not_visible":
            query = query.filter(
                DiscoveredQuery.domain_visible.is_(False),
                DiscoveredQuery.visibility_position.is_(None),
            )
        else:  # unknown — reserved for future ambiguous-signal states
            query = query.filter(
                DiscoveredQuery.domain_visible.is_(False),
                DiscoveredQuery.visibility_position.isnot(None),
            )

    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(100, max(1, int(request.args.get("per_page", 20))))
    except ValueError:
        raise ValidationError("'page' and 'per_page' must be integers")

    query = query.order_by(DiscoveredQuery.opportunity_score.desc())
    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()

    return jsonify({
        "queries": [q.to_dict() for q in items],
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total_items": total,
            "total_pages": (total + per_page - 1) // per_page if per_page else 0,
        },
    }), 200


@queries_bp.get("/profiles/<profile_uuid>/recommendations")
def list_recommendations(profile_uuid: str):
    _get_profile_or_404(profile_uuid)
    recs = (
        ContentRecommendation.query.filter_by(profile_uuid=profile_uuid)
        .order_by(ContentRecommendation.created_at.desc())
        .all()
    )
    return jsonify({"recommendations": [r.to_dict() for r in recs]}), 200


@queries_bp.post("/queries/<query_uuid>/recheck")
def recheck_query(query_uuid: str):
    query_obj = db.session.get(DiscoveredQuery, query_uuid)
    if query_obj is None:
        raise NotFoundError(f"Query '{query_uuid}' not found")

    profile = db.session.get(BusinessProfile, query_obj.profile_uuid)
    if profile is None:
        raise NotFoundError(f"Profile for query '{query_uuid}' no longer exists")

    agent = VisibilityScoringAgent()
    result = agent.run(profile.to_dict(), query_obj.query_text, query_obj.intent)

    from app.utils.scoring import compute_opportunity_score

    query_obj.estimated_search_volume = result["estimated_search_volume"]
    query_obj.competitive_difficulty = result["competitive_difficulty"]
    query_obj.domain_visible = result["domain_visible"]
    query_obj.visibility_position = result["visibility_position"]
    query_obj.visibility_notes = result["visibility_notes"]
    query_obj.opportunity_score = compute_opportunity_score(
        search_volume=result["estimated_search_volume"],
        competitive_difficulty=result["competitive_difficulty"],
        domain_visible=result["domain_visible"],
        intent=query_obj.intent,
    )
    query_obj.last_checked_at = utcnow()
    db.session.commit()

    body = query_obj.to_dict()
    body["recheck_error"] = result.get("error")
    body["data_source"] = result.get("data_source")
    return jsonify(body), 200
