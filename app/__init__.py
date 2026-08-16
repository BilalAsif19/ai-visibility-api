from __future__ import annotations

import logging
import os

from flask import Flask, jsonify

from app.extensions import db, migrate, limiter, LIMITER_AVAILABLE
from app.utils.errors import APIError


def create_app(config_name: str | None = None) -> Flask:
    from config import config_by_name

    app = Flask(__name__)
    config_name = config_name or os.environ.get("FLASK_ENV", "development")
    app.config.from_object(config_by_name.get(config_name, config_by_name["development"]))

    logging.basicConfig(level=logging.INFO)

    db.init_app(app)
    migrate.init_app(app, db)

    if LIMITER_AVAILABLE:
        limiter.init_app(app)
    else:
        app.logger.info("flask-limiter not installed; pipeline endpoint will be unrated.")

    _register_blueprints(app)
    _register_error_handlers(app)
    _register_health_check(app)

    # Ensure models are imported so Alembic autogenerate can see them.
    with app.app_context():
        from app import models  # noqa: F401

    return app


def _register_blueprints(app: Flask) -> None:
    from app.api.profiles import profiles_bp
    from app.api.queries import queries_bp

    app.register_blueprint(profiles_bp)
    app.register_blueprint(queries_bp)


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(APIError)
    def handle_api_error(err: APIError):
        return jsonify(err.to_dict()), err.status_code

    @app.errorhandler(404)
    def handle_404(err):
        return jsonify({"error": {"code": "not_found", "message": "Resource not found", "details": None}}), 404

    @app.errorhandler(405)
    def handle_405(err):
        return jsonify({"error": {"code": "method_not_allowed", "message": str(err), "details": None}}), 405

    @app.errorhandler(500)
    def handle_500(err):
        app.logger.exception("Unhandled server error")
        return jsonify({"error": {"code": "internal_error", "message": "An unexpected error occurred", "details": None}}), 500


def _register_health_check(app: Flask) -> None:
    @app.get("/health")
    def health():
        return jsonify({"status": "ok"}), 200
