"""Shared extension instances, kept separate from app/__init__.py to avoid
circular imports between models, agents and the app factory."""
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

db = SQLAlchemy()
migrate = Migrate()

try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address

    limiter = Limiter(key_func=get_remote_address, default_limits=[])
    LIMITER_AVAILABLE = True
except ImportError:  # flask-limiter is an optional "nice to have" dependency
    limiter = None
    LIMITER_AVAILABLE = False

