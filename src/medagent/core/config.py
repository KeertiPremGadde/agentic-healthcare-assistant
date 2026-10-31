"""Typed application settings, loaded from environment variables / .env."""

import json
from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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

    database_url: str = "postgresql+psycopg://medagent:medagent@localhost:5432/medagent"

    # Doctors' working hours are defined in this IANA timezone; all stored times are UTC.
    clinic_timezone: str = "Europe/Berlin"
    slot_minutes: int = Field(default=30, ge=5, le=240)

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
