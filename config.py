import os
from dotenv import load_dotenv

load_dotenv()

basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    """Base configuration, loaded from environment variables."""

    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{os.path.join(basedir, 'dev.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # AI provider selection: "anthropic" or "openai"
    AI_PROVIDER = os.environ.get("AI_PROVIDER", "anthropic")
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

    ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")

    # External search-data provider (DataForSEO)
    DATAFORSEO_LOGIN = os.environ.get("DATAFORSEO_LOGIN")
    DATAFORSEO_PASSWORD = os.environ.get("DATAFORSEO_PASSWORD")
    # If no DataForSEO credentials are supplied, the pipeline falls back to a
    # clearly-labelled simulated data source so the API remains runnable out
    # of the box. See app/services/external_data.py.
    USE_MOCK_EXTERNAL_DATA = os.environ.get("USE_MOCK_EXTERNAL_DATA", "true").lower() == "true"

    # Pipeline behaviour
    MAX_QUERIES_PER_RUN = int(os.environ.get("MAX_QUERIES_PER_RUN", 20))
    MIN_QUERIES_PER_RUN = int(os.environ.get("MIN_QUERIES_PER_RUN", 10))
    RATE_LIMIT_PIPELINE = os.environ.get("RATE_LIMIT_PIPELINE", "5 per minute")


class DevelopmentConfig(Config):
    DEBUG = True


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    USE_MOCK_EXTERNAL_DATA = True


class ProductionConfig(Config):
    DEBUG = False


config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
