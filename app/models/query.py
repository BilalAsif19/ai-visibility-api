from app.extensions import db
from app.models.base import UUIDMixin, utcnow


class DiscoveredQuery(UUIDMixin, db.Model):
    __tablename__ = "discovered_queries"

    profile_uuid = db.Column(
        db.String(36), db.ForeignKey("business_profiles.uuid"), nullable=False, index=True
    )
    run_uuid = db.Column(
        db.String(36), db.ForeignKey("pipeline_runs.uuid"), nullable=False, index=True
    )

    query_text = db.Column(db.Text, nullable=False)
    # commercial intent bucket assigned by Agent 1, e.g. "comparison",
    # "best_of", "informational", "transactional" — feeds the score formula.
    intent = db.Column(db.String(32), nullable=False, default="informational")

    estimated_search_volume = db.Column(db.Integer, nullable=False, default=0)
    competitive_difficulty = db.Column(db.Float, nullable=False, default=50.0)  # 0-100
    opportunity_score = db.Column(db.Float, nullable=False, default=0.0)  # 0-1

    domain_visible = db.Column(db.Boolean, nullable=False, default=False)
    visibility_position = db.Column(db.Integer, nullable=True)
    # Raw notes from Agent 2 on how the visibility check was simulated/derived
    visibility_notes = db.Column(db.Text, nullable=True)

    discovered_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    last_checked_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    recommendations = db.relationship(
        "ContentRecommendation", backref="target_query", lazy="dynamic"
    )

    @property
    def visibility_status(self) -> str:
        if self.visibility_position is None and not self.domain_visible:
            return "not_visible"
        if self.domain_visible:
            return "visible"
        return "unknown"

    def to_dict(self) -> dict:
        return {
            "query_uuid": self.uuid,
            "profile_uuid": self.profile_uuid,
            "run_uuid": self.run_uuid,
            "query_text": self.query_text,
            "intent": self.intent,
            "estimated_search_volume": self.estimated_search_volume,
            "competitive_difficulty": self.competitive_difficulty,
            "opportunity_score": round(self.opportunity_score, 4),
            "domain_visible": self.domain_visible,
            "visibility_position": self.visibility_position,
            "visibility_status": self.visibility_status,
            "visibility_notes": self.visibility_notes,
            "discovered_at": self.discovered_at.isoformat(),
            "last_checked_at": self.last_checked_at.isoformat(),
        }
