"""Application settings, read from environment variables (see .env.example)."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql+psycopg://soivi:soivi@localhost:5432/soivi"

    # Snapshot storage (MinIO / S3)
    s3_endpoint: str = "localhost:9000"
    s3_access_key: str = "soivi"
    s3_secret_key: str = "change-me-minio"
    s3_bucket: str = "snapshots"
    s3_secure: bool = False

    # Crawling
    crawler_user_agent: str = "SoiviBot/0.1 (+mailto:contact@example.com)"
    crawler_min_delay_seconds: float = Field(default=5.0, ge=5.0)

    # Extraction
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5-5"  # empty in .env also means this
    # Card extraction (pipeline/cards): accuracy over speed, so above the model default.
    card_extraction_effort: str = Field(default="high", pattern="^(low|medium|high|xhigh|max)$")

    # Review app (HTTP basic auth). The app refuses to start without a password.
    review_username: str = "reviewer"
    review_password: str = ""

    # Scheduling and alerts
    timezone: str = "Asia/Ho_Chi_Minh"
    daily_summary_hour: int = Field(default=19, ge=0, le=23)
    telegram_bot_token: str = ""  # empty: messages are printed, not sent
    telegram_chat_id: str = ""
    pipeline_lock_file: str = "/tmp/soivi-pipeline.lock"

    # Public API (api/)
    api_cache_seconds: int = Field(default=60, ge=0)  # 0 turns the response cache off
    report_rate_limit_per_hour: int = Field(default=5, ge=1)  # per client IP
    report_max_screenshot_bytes: int = Field(default=5_000_000, ge=1)
    captcha_provider: str = Field(default="", pattern="^(|turnstile|hcaptcha)$")
    captcha_secret: str = ""
    # Behind a reverse proxy, read the client IP from X-Forwarded-For (else the socket).
    trust_proxy_headers: bool = False

    # Public site (web/): the review app calls this after approvals so pages rebuild.
    site_revalidate_url: str = ""  # e.g. http://web:3000/api/revalidate
    site_revalidate_secret: str = ""

    # Runtime
    environment: str = "development"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
