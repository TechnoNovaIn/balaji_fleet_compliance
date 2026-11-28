import os
from pathlib import Path
from dotenv import load_dotenv

# Base directory
BASE_DIR = Path(__file__).resolve().parent

# Load environment variables from .env file if present
load_dotenv(BASE_DIR / ".env")


def build_database_uri() -> str:
    """Build the database URI from environment variables with PostgreSQL priority

    and local SQLite fallback for development.
    """
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        # SQLAlchemy 2.0+ requires postgresql:// instead of legacy postgres://
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
        return database_url

    # Check for individual PostgreSQL variables
    pg_user = os.environ.get("POSTGRES_USER")
    pg_pass = os.environ.get("POSTGRES_PASSWORD")
    pg_host = os.environ.get("POSTGRES_HOST")
    pg_port = os.environ.get("POSTGRES_PORT", "5432")
    pg_db = os.environ.get("POSTGRES_DB")

    if pg_user and pg_pass and pg_host and pg_db:
        return f"postgresql://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_db}"

    # Safe local fallback for development
    instance_dir = BASE_DIR / "instance"
    instance_dir.mkdir(exist_ok=True)
    return f"sqlite:///{instance_dir / 'fleet_compliance.db'}"


DEFAULT_DEV_SECRET_KEY = "dev-secret-key-balaji-fleet-2026"


class Config:
    """Base application configuration."""

    SECRET_KEY = os.environ.get("SECRET_KEY") or DEFAULT_DEV_SECRET_KEY
    SQLALCHEMY_DATABASE_URI = build_database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
    }

    # Uploads
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH") or 16 * 1024 * 1024)  # 16 MB max
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER") or str(BASE_DIR / "instance" / "uploads")

    # Security & Session Cookies
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = os.environ.get("SESSION_COOKIE_SAMESITE") or "Lax"
    SESSION_COOKIE_SECURE = (os.environ.get("SESSION_COOKIE_SECURE") or "False").lower() in ("true", "1", "t")
    PERMANENT_SESSION_LIFETIME = 86400  # 24 hours in seconds
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None

    # Challan Data Provider Selection
    CHALLAN_DATA_PROVIDER = (os.environ.get("CHALLAN_DATA_PROVIDER") or "manual").strip().lower()
    SUREPASS_CHALLAN_API_URL = os.environ.get("SUREPASS_CHALLAN_API_URL") or ""
    SUREPASS_RC_API_URL = os.environ.get("SUREPASS_RC_API_URL") or ""

    # Masters India Vehicle e-Challan API
    MASTERS_INDIA_API_URL = (
        os.environ.get("MASTERS_INDIA_API_URL")
        or "https://api-platform.mastersindia.co/api/v2/sbt/ECHALLAN/"
    )
    MASTERS_INDIA_AUTH_URL = (
        os.environ.get("MASTERS_INDIA_AUTH_URL")
        or "https://api-platform.mastersindia.co/api/v2/token-auth/"
    )
    MASTERS_INDIA_PRODUCT_ID = os.environ.get("MASTERS_INDIA_PRODUCT_ID") or ""
    MASTERS_INDIA_MODE = os.environ.get("MASTERS_INDIA_MODE") or ""
    MASTERS_INDIA_SUB_ID = os.environ.get("MASTERS_INDIA_SUB_ID") or ""
    MASTERS_INDIA_API_TOKEN = os.environ.get("MASTERS_INDIA_API_TOKEN") or None
    MASTERS_INDIA_USERNAME = os.environ.get("MASTERS_INDIA_USERNAME") or None
    MASTERS_INDIA_PASSWORD = os.environ.get("MASTERS_INDIA_PASSWORD") or None


class DevelopmentConfig(Config):
    """Development environment configuration."""

    DEBUG = True
    TESTING = False


class ProductionConfig(Config):
    """Production environment configuration."""

    DEBUG = False
    TESTING = False
    SECRET_KEY = os.environ.get("SECRET_KEY") or None
    SESSION_COOKIE_SECURE = (os.environ.get("SESSION_COOKIE_SECURE") or "True").lower() in ("true", "1", "t")

    @classmethod
    def validate(cls) -> None:
        """Fail fast on startup if production SECRET_KEY is missing or insecure."""
        if not cls.SECRET_KEY or cls.SECRET_KEY == DEFAULT_DEV_SECRET_KEY:
            raise RuntimeError(
                "SECRET_KEY environment variable must be set to a strong non-default value in production."
            )


class TestingConfig(Config):
    """Testing environment configuration."""

    TESTING = True
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    UPLOAD_FOLDER = str(BASE_DIR / "tests" / "test_uploads")


config_by_name = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}
