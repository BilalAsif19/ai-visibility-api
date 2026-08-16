import pytest

from app import create_app
from app.extensions import db as _db


@pytest.fixture()
def app():
    application = create_app("testing")
    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def sample_profile_payload():
    return {
        "name": "Frase",
        "domain": "frase.io",
        "industry": "SEO Content Tools",
        "description": "AI-powered content briefs and SEO research",
        "competitors": ["surferseo.com", "marketmuse.com", "clearscope.io"],
    }
