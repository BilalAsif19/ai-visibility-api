from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from app.extensions import db, limiter, LIMITER_AVAILABLE
from app.models.profile import BusinessProfile
from app.models.query import DiscoveredQuery
from app.models.recommendation import ContentRecommendation
from app.services.pipeline import PipelineOrchestrator
from app.utils.errors import NotFoundError, ValidationError


def _noop_decorator(*_args, **_kwargs):
    def wrapper(fn):
        return fn
    return wrapper


_rate_limit = limiter.limit if LIMITER_AVAILABLE else _noop_decorator

profiles_bp = Blueprint("profiles", __name__, url_prefix="/api/v1/profiles")

REQUIRED_PROFILE_FIELDS = ["name", "domain", "industry"]


def _get_profile_or_404(profile_uuid: str) -> BusinessProfile:
    profile = db.session.get(BusinessProfile, profile_uuid)
    if profile is None:
        raise NotFoundError(f"Profile '{profile_uuid}' not found")
    return profile


@profiles_bp.post("")
def create_profile():
    payload = request.get_json(silent=True)
    if not payload:
        raise ValidationError("Request body must be valid JSON")

    missing = [f for f in REQUIRED_PROFILE_FIELDS if not payload.get(f)]
    if missing:
        raise ValidationError(f"Missing required field(s): {', '.join(missing)}", details={"missing_fields": missing})

    competitors = payload.get("competitors", [])
    if not isinstance(competitors, list) or not all(isinstance(c, str) for c in competitors):
        raise ValidationError("'competitors' must be a list of strings")

    profile = BusinessProfile(
        name=payload["name"].strip(),
        domain=payload["domain"].strip(),
        industry=payload["industry"].strip(),
        description=(payload.get("description") or "").strip() or None,
        competitors=competitors,
        status="created",
    )
    db.session.add(profile)
    db.session.commit()

    body = profile.to_dict()
    body["status"] = "created"
    return jsonify(body), 201


@profiles_bp.get("/<profile_uuid>")
def get_profile(profile_uuid: str):
    profile = _get_profile_or_404(profile_uuid)
    body = profile.to_dict()
    body["summary"] = profile.summary_stats()
    return jsonify(body), 200


@profiles_bp.post("/<profile_uuid>/run")
@_rate_limit("5 per minute")  # matches Config.RATE_LIMIT_PIPELINE default
def run_pipeline(profile_uuid: str):
    profile = _get_profile_or_404(profile_uuid)

    max_queries = current_app.config["MAX_QUERIES_PER_RUN"]
    min_queries = current_app.config["MIN_QUERIES_PER_RUN"]

    orchestrator = PipelineOrchestrator()
    run = orchestrator.run(profile, max_queries=max_queries, min_queries=min_queries)

    top_queries = (
        DiscoveredQuery.query.filter_by(run_uuid=run.uuid)
        .order_by(DiscoveredQuery.opportunity_score.desc())
        .limit(3)
        .all()
    )
    recommendations = ContentRecommendation.query.filter_by(run_uuid=run.uuid).all()

    response = run.to_dict()
    response["top_opportunity_queries"] = [q.to_dict() for q in top_queries]
    response["content_recommendations"] = [r.to_dict() for r in recommendations]

    status_code = 200 if run.status in ("completed", "partial_failure") else 502
    return jsonify(response), status_code
