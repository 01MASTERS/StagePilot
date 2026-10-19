"""Catalogue title and episode models with prompt injection sanitization."""

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field, field_validator

from stagepilot.config import parse_iso_timestamp, to_iso_timestamp

# Regex patterns for detecting and isolating prompt injections in title descriptions
INJECTION_PATTERN = re.compile(
    r"(SYSTEM\s+NOTE.*|AI\s+AGENT.*|ignore\s+(your\s+)?(previous\s+)?rules.*)",
    re.IGNORECASE | re.DOTALL
)


def sanitize_description(desc: str) -> Tuple[str, Optional[str]]:
    """Sanitize description text, stripping and quarantining any prompt injection attempts.
    
    Returns:
        (sanitized_description, quarantined_instruction)
    """
    if not desc:
        return "", None
    
    match = INJECTION_PATTERN.search(desc)
    if match:
        clean_text = desc[:match.start()].strip()
        quarantined = desc[match.start():].strip()
        return clean_text, quarantined
    return desc.strip(), None


class CatalogueTitle(BaseModel):
    """Represents a media title in the catalogue."""
    title_id: str
    content_slug: str
    title: str
    dialect: str
    language: str
    content_type: str  # film, show, micro_drama
    genres: List[str] = Field(default_factory=list)
    release_date: Optional[str] = None
    available_from: datetime
    available_until: Optional[datetime] = None
    is_premium: bool = False
    description: str = ""
    is_sanitized: bool = False
    quarantined_instruction: Optional[str] = None

    @field_validator("available_from", "available_until", mode="before")
    @classmethod
    def parse_datetime(cls, v: Any) -> Optional[datetime]:
        if isinstance(v, str):
            return parse_iso_timestamp(v)
        return v

    @field_validator("is_premium", mode="before")
    @classmethod
    def parse_bool(cls, v: Any) -> bool:
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "yes")
        return bool(v)

    @field_validator("genres", mode="before")
    @classmethod
    def parse_genres(cls, v: Any) -> List[str]:
        if isinstance(v, str):
            return [g.strip() for g in v.split("|") if g.strip()]
        return v or []

    @classmethod
    def create_from_raw(cls, raw: Dict[str, str]) -> "CatalogueTitle":
        """Factory method that sanitizes descriptions upon creation."""
        clean_desc, quarantined = sanitize_description(raw.get("description", ""))
        return cls(
            title_id=raw["title_id"],
            content_slug=raw["content_slug"],
            title=raw["title"],
            dialect=raw["dialect"],
            language=raw["language"],
            content_type=raw["content_type"],
            genres=raw.get("genres", ""),
            release_date=raw.get("release_date"),
            available_from=raw["available_from"],
            available_until=raw.get("available_until") or None,
            is_premium=raw.get("is_premium", "false"),
            description=clean_desc,
            is_sanitized=quarantined is not None,
            quarantined_instruction=quarantined,
        )

    def is_available_at(self, dt: datetime) -> bool:
        """Check if title is available at given UTC timestamp."""
        if dt < self.available_from:
            return False
        if self.available_until and dt >= self.available_until:
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        data = self.model_dump()
        data["available_from"] = to_iso_timestamp(self.available_from)
        data["available_until"] = to_iso_timestamp(self.available_until)
        return data


class Episode(BaseModel):
    """Represents an episode for a show or micro-drama."""
    episode_id: str
    content_slug: str
    season: int
    episode: int
    minutes: float = 0.0

    @field_validator("season", "episode", mode="before")
    @classmethod
    def parse_int(cls, v: Any) -> int:
        return int(v)

    @field_validator("minutes", mode="before")
    @classmethod
    def parse_float(cls, v: Any) -> float:
        return float(v) if v else 0.0
