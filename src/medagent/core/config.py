"""Typed application settings, loaded from environment variables / .env."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["local", "staging", "production"] = "local"
    log_level: str = "INFO"
    api_cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    llm_provider: Literal["openai", "anthropic"] = "openai"
    llm_model: str = ""
    embedding_model: str = "text-embedding-3-small"

    database_url: str = "postgresql+psycopg://medagent:medagent@localhost:5432/medagent"


@lru_cache
def get_settings() -> Settings:
    return Settings()
