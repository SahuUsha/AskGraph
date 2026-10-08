import os

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# app2 is started from SQLAI/, so a relative ".env" would miss the repo-root file.
_REPO_ROOT_ENV = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_REPO_ROOT_ENV, extra="ignore")

    # Any OpenAI-compatible chat endpoint; defaults to NVIDIA's hosted API.
    NVIDIA_API_KEY: str
    LLM_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    LLM_MODEL: str = "nvidia/nemotron-3-super-120b-a12b"

    # No default. A committed fallback URL is a committed password, and it also
    # means a missing env var silently points production at someone's dev DB.
    CACHE_DB_URL: str

    # Behind the UI's "Use sample database" button, sent as 'preset:sample'.
    SAMPLE_DB_URL: str | None = None

    # Caps a caller can't exceed; see models.PaginationRequest.
    MAX_PAGE_SIZE: int = 1000

    # Cached schemas older than this are refetched, so a migration on the
    # target DB stops poisoning every prompt forever.
    SCHEMA_CACHE_TTL_HOURS: int = 24

    # Applied to DB connects and LLM calls. Without them a hung connect
    # holds a threadpool worker until the process dies.
    DB_CONNECT_TIMEOUT: int = 10
    AI_TIMEOUT_SECONDS: int = 120

    @field_validator("CACHE_DB_URL", "NVIDIA_API_KEY")
    @classmethod
    def _require_non_empty(cls, v: str, info) -> str:
        if not v or not v.strip():
            raise ValueError(f"{info.field_name} must be set (see .env.example).")
        return v.strip()


settings = Settings()
