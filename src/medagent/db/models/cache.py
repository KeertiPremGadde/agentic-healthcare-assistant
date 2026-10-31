from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from medagent.db.base import Base


class ExternalCache(Base):
    """Responses from external APIs (e.g. OpenStreetMap), cached to respect their usage policies."""

    __tablename__ = "external_cache"

    key: Mapped[str] = mapped_column(String(300), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
