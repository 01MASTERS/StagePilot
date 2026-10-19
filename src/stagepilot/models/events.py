"""App event data models and timestamp parsing."""

import re
from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field, field_validator

from stagepilot.config import parse_iso_timestamp, to_iso_timestamp

DEEPLINK_DIALECT_PATTERN = re.compile(r"ott://c/[^/]+/([^/]+)/title/")


class AppEvent(BaseModel):
    """Normalized app event adhering to the events.jsonl schema."""
    event_id: str
    user_id: str
    event: str
    received_at: datetime
    occurred_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    deliver_at: Optional[datetime] = None
    session_id: Optional[str] = None
    app_dialect: Optional[str] = None
    app_language: Optional[str] = None
    platform: Optional[str] = None
    app_version: Optional[str] = None
    properties: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("received_at", "occurred_at", "sent_at", "deliver_at", mode="before")
    @classmethod
    def parse_datetime(cls, v: Any) -> Optional[datetime]:
        if isinstance(v, str):
            return parse_iso_timestamp(v)
        return v

    @property
    def clock_skew_seconds(self) -> float:
        """Seconds difference between server received_at and phone occurred_at."""
        if self.occurred_at:
            return abs((self.received_at - self.occurred_at).total_seconds())
        return 0.0

    @property
    def buffer_delay_seconds(self) -> float:
        """Buffer latency on device before sending: sent_at - occurred_at."""
        if self.sent_at and self.occurred_at:
            return max(0.0, (self.sent_at - self.occurred_at).total_seconds())
        return 0.0

    @property
    def is_stale_buffer(self) -> bool:
        """True if the event was buffered offline on the device for > 600s (10 min)."""
        return self.buffer_delay_seconds > 600.0

    @property
    def campaign_dialect(self) -> Optional[str]:
        """Dialect extracted from promotional campaign deeplink if present."""
        deeplink = self.properties.get("deeplink")
        if deeplink and isinstance(deeplink, str):
            match = DEEPLINK_DIALECT_PATTERN.search(deeplink)
            if match:
                return match.group(1)
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize back to standard dictionary with ISO-8601 UTC strings."""
        data = self.model_dump()
        data["received_at"] = to_iso_timestamp(self.received_at)
        data["occurred_at"] = to_iso_timestamp(self.occurred_at)
        data["sent_at"] = to_iso_timestamp(self.sent_at)
        if self.deliver_at:
            data["deliver_at"] = to_iso_timestamp(self.deliver_at)
        else:
            data.pop("deliver_at", None)
        return data
