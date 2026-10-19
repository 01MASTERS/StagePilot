"""Viewer profile model with validation and synthetic hydration."""

from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, field_validator

from stagepilot.config import parse_iso_timestamp, to_iso_timestamp


class ViewerProfile(BaseModel):
    """Viewer profile record corresponding to profiles_snapshot.csv."""
    user_id: str
    signup_at: Optional[datetime] = None
    subscription_status: str = "never"  # never, trial_active, active, lapsed
    plan_started_at: Optional[datetime] = None
    plan_ends_at: Optional[datetime] = None
    preferred_dialect: Optional[str] = None
    preferred_language: Optional[str] = None
    notifications_opt_in: bool = False
    whatsapp_opt_in: bool = False
    platform: Optional[str] = None
    updated_at: Optional[datetime] = None
    snapshot_at: Optional[datetime] = None
    is_synthetic: bool = False

    @field_validator(
        "signup_at", "plan_started_at", "plan_ends_at", "updated_at", "snapshot_at",
        mode="before"
    )
    @classmethod
    def parse_datetime(cls, v: Any) -> Optional[datetime]:
        if isinstance(v, str):
            return parse_iso_timestamp(v)
        return v

    @field_validator("notifications_opt_in", "whatsapp_opt_in", mode="before")
    @classmethod
    def parse_boolean(cls, v: Any) -> bool:
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "yes", "t")
        return bool(v)

    @classmethod
    def create_synthetic(
        cls,
        user_id: str,
        signup_at: Optional[datetime] = None,
        dialect: Optional[str] = None,
        language: Optional[str] = None,
        platform: Optional[str] = None,
        updated_at: Optional[datetime] = None
    ) -> "ViewerProfile":
        """Synthesize a profile for a brand-new viewer absent from the warehouse snapshot."""
        return cls(
            user_id=user_id,
            signup_at=signup_at,
            subscription_status="never",
            preferred_dialect=dialect,
            preferred_language=language,
            notifications_opt_in=False,
            whatsapp_opt_in=False,
            platform=platform,
            updated_at=updated_at or signup_at,
            is_synthetic=True,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with ISO-8601 UTC timestamp strings."""
        data = self.model_dump()
        for f in ("signup_at", "plan_started_at", "plan_ends_at", "updated_at", "snapshot_at"):
            if data.get(f):
                data[f] = to_iso_timestamp(data[f])
        return data
