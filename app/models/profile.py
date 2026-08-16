from app.extensions import db
from app.models.base import UUIDMixin, TimestampMixin


class BusinessProfile(UUIDMixin, TimestampMixin, db.Model):
    __tablename__ = "business_profiles"

    name = db.Column(db.String(255), nullable=False)
    domain = db.Column(db.String(255), nullable=False, index=True)
    industry = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    # Stored as JSON list of competitor domains, e.g. ["clearscope.io", ...]
    competitors = db.Column(db.JSON, nullable=False, default=list)
    # created -> pipeline never run, running -> a run is in progress,
    # completed -> at least one successful run, failed -> last run failed
    status = db.Column(db.String(32), nullable=False, default="created")

    runs = db.relationship(
        "PipelineRun", backref="profile", lazy="dynamic", cascade="all, delete-orphan"
    )
    queries = db.relationship(
        "DiscoveredQuery", backref="profile", lazy="dynamic", cascade="all, delete-orphan"
    )
    recommendations = db.relationship(
        "ContentRecommendation", backref="profile", lazy="dynamic", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict:
        return {
            "profile_uuid": self.uuid,
            "name": self.name,
            "domain": self.domain,
            "industry": self.industry,
            "description": self.description,
            "competitors": self.competitors or [],
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    def summary_stats(self) -> dict:
        # Deferred import avoids a circular import at module load time.
        from app.models.query import DiscoveredQuery

        query_count = self.queries.count()
        if query_count:
            avg_score = (
                db.session.query(db.func.avg(DiscoveredQuery.opportunity_score))
                .filter(DiscoveredQuery.profile_uuid == self.uuid)
                .scalar()
            )
        else:
            avg_score = None
        return {
            "total_queries_discovered": query_count,
            "avg_opportunity_score": round(avg_score, 4) if avg_score is not None else None,
            "total_pipeline_runs": self.runs.count(),
        }
