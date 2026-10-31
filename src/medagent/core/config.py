"""Typed application settings, loaded from environment variables / .env."""

import json
from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PLACEHOLDER_SECRET = "change-me"  # noqa: S105  (the value we refuse outside local mode)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["local", "staging", "production"] = "local"
    log_level: str = "INFO"
    # Comma-separated in .env (API_CORS_ORIGINS=http://a,http://b); a JSON list also works.
    api_cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    llm_provider: Literal["anthropic"] = "anthropic"
    llm_model: str = "claude-haiku-5-5"  # use claude-sonnet-5-5 for the demo
    anthropic_api_key: SecretStr | None = None

    # Embeddings sit behind an interface (rag/embeddings.py); "fastembed" runs locally, no API key.
    embedding_provider: Literal["fastembed"] = "fastembed"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384  # must match the vector(N) column created by the migration

    # RAG
    kb_public_only: bool = False  # True in deployed envs: never retrieve local-only sources
    # Below this best cosine similarity => "I don't know". Calibrated for bge-small on MedlinePlus:
    # in-scope questions scored 0.74-0.87, off-topic 0.43-0.65 (re-measure if the model changes).
    rag_min_score: float = Field(default=0.70, ge=0, le=1)

    # Tools: "mcp" = nodes call the MCP server over stdio (real boundary); "local" = in-process.
    tools_transport: Literal["mcp", "local"] = "mcp"

    # Google Calendar (optional). Both set => booked appointments are added to one shared demo
    # calendar via a service account; otherwise the calendar step is skipped.
    google_service_account_file: str | None = None
    google_calendar_id: str | None = None

    # ---- API / auth (Phase 5) ----
    # Sign tokens with a long random secret (see .env.example). The default is accepted only
    # when APP_ENV=local; any other environment refuses to start with it.
    jwt_secret: SecretStr = SecretStr(PLACEHOLDER_SECRET)
    jwt_expire_minutes: int = Field(default=60, ge=1, le=24 * 60)

    # ---- Demo protection: the API is public and spends real money per chat message ----
    max_message_chars: int = Field(default=1000, ge=1, le=10_000)
    daily_message_limit: int = Field(default=50, ge=1)  # per user per UTC day
    daily_budget_usd: float = Field(default=1.00, gt=0)  # across ALL users per UTC day
    chat_rate_per_minute: int = Field(default=20, ge=1)  # per user
    login_rate_per_minute: int = Field(default=10, ge=1)  # per IP
    register_rate_per_hour: int = Field(default=5, ge=1)  # per IP
    token_replay_delay_ms: int = Field(default=15, ge=0)  # pacing of replayed `token` events

    # OpenStreetMap Overpass endpoint (public by default; set a mirror or self-hosted instance)
    overpass_url: str = "https://overpass-api.de/api/interpreter"

    database_url: str = "postgresql+psycopg://medagent:medagent@localhost:5432/medagent"

    # Doctors' working hours are defined in this IANA timezone; all stored times are UTC.
    clinic_timezone: str = "Europe/Berlin"
    slot_minutes: int = Field(default=30, ge=5, le=240)
    # Language of public-holiday names in replies ("Reformation Day" / "Reformationstag").
    holiday_language: Literal["en_US", "de"] = "en_US"

    @model_validator(mode="after")
    def _require_a_real_jwt_secret_outside_local(self) -> "Settings":
        secret = self.jwt_secret.get_secret_value()
        if self.app_env != "local" and (secret == PLACEHOLDER_SECRET or len(secret) < 32):
            raise ValueError(
                "JWT_SECRET must be a random string of at least 32 characters unless "
                'APP_ENV=local (generate one: python -c "import secrets; '
                'print(secrets.token_urlsafe(48))")'
            )
        return self

    @field_validator("api_cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: Any) -> Any:
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                return json.loads(text)
            return [part.strip() for part in text.split(",") if part.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
