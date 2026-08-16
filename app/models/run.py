from app.extensions import db
from app.models.base import UUIDMixin, utcnow


class PipelineRun(UUIDMixin, db.Model):
    __tablename__ = "pipeline_runs"

    profile_uuid = db.Column(
        db.String(36), db.ForeignKey("business_profiles.uuid"), nullable=False, index=True
    )
    status = db.Column(db.String(32), nullable=False, default="pending")
    queries_discovered = db.Column(db.Integer, default=0)
    queries_scored = db.Column(db.Integer, default=0)
    recommendations_generated = db.Column(db.Integer, default=0)
    tokens_used = db.Column(db.Integer, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    agent_status = db.Column(db.JSON, nullable=True, default=dict)

    started_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    def to_dict(self) -> dict:
        return {
            "run_uuid": self.uuid,
            "profile_uuid": self.profile_uuid,
            "status": self.status,
            "queries_discovered": self.queries_discovered,
            "queries_scored": self.queries_scored,
            "recommendations_generated": self.recommendations_generated,
            "tokens_used": self.tokens_used,
            "error_message": self.error_message,
            "agent_status": self.agent_status or {},
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
