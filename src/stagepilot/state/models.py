"""Viewer state, fact provenance, goal tracking, and decision models."""

from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, Field, field_validator

from stagepilot.config import parse_iso_timestamp, to_iso_timestamp, IST, UTC
from stagepilot.models.profiles import ViewerProfile


class ViewerFact(BaseModel):
    """An individual fact known about a viewer with source provenance."""
    fact_key: str
    value: Any
    source: str  # 'profile', 'events', 'app_setting', 'campaign_deeplink', 'inferred'
    observed_at: datetime

    @field_validator("observed_at", mode="before")
    @classmethod
    def parse_dt(cls, v: Any) -> datetime:
        if isinstance(v, str):
            dt = parse_iso_timestamp(v)
            if dt is None:
                raise ValueError(f"Invalid timestamp: {v}")
            return dt
        return v

    def freshness_seconds(self, at: datetime) -> float:
        """Seconds elapsed between fact observation and target timestamp."""
        return max(0.0, (at - self.observed_at).total_seconds())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fact_key": self.fact_key,
            "value": self.value,
            "source": self.source,
            "observed_at": to_iso_timestamp(self.observed_at),
        }


class ActiveGoal(BaseModel):
    """A viewer's active or concluded goal."""
    goal_id: str
    name: str
    status: str = "OPEN"  # OPEN, SUCCEEDED, FAILED, REVISED, INCONCLUSIVE
    started_at: datetime
    deadline: datetime
    rule_version: str = "2026-09-30"
    success_event: str
    success_condition: str = "any"
    target_content_slug: Optional[str] = None
    target_release_cutoff: Optional[datetime] = None
    qualifying_event_ids: List[str] = Field(default_factory=list)
    resolved_at: Optional[datetime] = None

    @field_validator("started_at", "deadline", "target_release_cutoff", "resolved_at", mode="before")
    @classmethod
    def parse_dt(cls, v: Any) -> Optional[datetime]:
        if isinstance(v, str):
            return parse_iso_timestamp(v)
        return v

    def is_expired(self, at: datetime) -> bool:
        """Check if goal deadline has passed."""
        return at >= self.deadline

    def to_dict(self) -> Dict[str, Any]:
        data = self.model_dump()
        data["started_at"] = to_iso_timestamp(self.started_at)
        data["deadline"] = to_iso_timestamp(self.deadline)
        if self.target_release_cutoff:
            data["target_release_cutoff"] = to_iso_timestamp(self.target_release_cutoff)
        if self.resolved_at:
            data["resolved_at"] = to_iso_timestamp(self.resolved_at)
        return data


class DecisionRecord(BaseModel):
    """Machine-readable decision output conforming to Section 4 of the candidate brief."""
    decision_id: str
    viewer_id: str
    trigger: Dict[str, Any]
    goal: Optional[Dict[str, Any]] = None
    action: str  # HOME_PAGE, PUSH, WHATSAPP, IN_APP_MESSAGE, NO_ACTION
    dialect: Dict[str, Any]
    content: List[str] = Field(default_factory=list)
    confidence: float
    confidence_reason: str = ""
    evidence: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    checks: Dict[str, List[str]] = Field(default_factory=lambda: {"passed": [], "failed": []})
    decided_in_ms: int = 0
    status: str = "PUBLISHED"  # PUBLISHED, NO_ACTION, REJECTED, FALLBACK
    no_action_reason: Optional[str] = None
    fallback_used: bool = False
    model_calls: int = 0
    tool_calls: int = 0
    rule_version: str = "2026-09-30"

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class ViewerState(BaseModel):
    """Aggregated, durable per-viewer state."""
    user_id: str
    profile: ViewerProfile
    facts: Dict[str, ViewerFact] = Field(default_factory=dict)
    active_goal: Optional[ActiveGoal] = None
    completed_goals: List[ActiveGoal] = Field(default_factory=list)

    # Watch history & consumption telemetry
    completed_episodes: Set[str] = Field(default_factory=set)
    slug_progress: Dict[str, str] = Field(default_factory=dict)  # slug -> latest episode_id completed
    genre_plays: Dict[str, int] = Field(default_factory=dict)
    play_sessions: Set[str] = Field(default_factory=set)
    total_plays: int = 0
    total_completes: int = 0
    last_play_at: Optional[datetime] = None
    last_play_by_slug: Dict[str, datetime] = Field(default_factory=dict)
    last_app_open_at: Optional[datetime] = None
    active_days_ist: Set[str] = Field(default_factory=set)  # 'YYYY-MM-DD' strings

    # Messaging history for frequency capping
    sent_messages: List[Dict[str, Any]] = Field(default_factory=list)

    # Idempotency ledger
    idempotency_keys: Set[str] = Field(default_factory=set)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("last_play_at", "last_app_open_at", "updated_at", mode="before")
    @classmethod
    def parse_dt(cls, v: Any) -> Optional[datetime]:
        if isinstance(v, str):
            return parse_iso_timestamp(v)
        return v

    @field_validator("last_play_by_slug", mode="before")
    @classmethod
    def parse_slug_dt(cls, v: Any) -> Dict[str, datetime]:
        if isinstance(v, dict):
            out = {}
            for k, val in v.items():
                out[k] = parse_iso_timestamp(val) if isinstance(val, str) else val
            return out
        return v or {}

    def is_processed(self, event_id: str) -> bool:
        """Idempotency check: returns True if event_id was already handled."""
        return event_id in self.idempotency_keys

    def record_processed(self, event_id: str) -> None:
        """Add event_id to idempotency ledger."""
        self.idempotency_keys.add(event_id)

    def record_fact(self, key: str, value: Any, source: str, observed_at: datetime) -> None:
        """Record or update a provenanced fact."""
        self.facts[key] = ViewerFact(
            fact_key=key,
            value=value,
            source=source,
            observed_at=observed_at
        )

    def message_count_for_day_ist(self, dt: datetime) -> int:
        """Return count of push/whatsapp messages sent on the IST calendar day of dt."""
        target_ist_day = dt.astimezone(IST).strftime("%Y-%m-%d")
        count = 0
        for m in self.sent_messages:
            if m.get("ist_day") == target_ist_day:
                count += 1
        return count

    def to_dict(self) -> Dict[str, Any]:
        """Convert state to JSON-serializable dictionary."""
        data = self.model_dump()
        data["profile"] = self.profile.to_dict()
        data["facts"] = {k: v.to_dict() for k, v in self.facts.items()}
        data["active_goal"] = self.active_goal.to_dict() if self.active_goal else None
        data["completed_goals"] = [g.to_dict() for g in self.completed_goals]
        data["completed_episodes"] = sorted(list(self.completed_episodes))
        data["play_sessions"] = sorted(list(self.play_sessions))
        data["active_days_ist"] = sorted(list(self.active_days_ist))
        data["idempotency_keys"] = sorted(list(self.idempotency_keys))
        data["last_play_at"] = to_iso_timestamp(self.last_play_at)
        data["last_app_open_at"] = to_iso_timestamp(self.last_app_open_at)
        data["updated_at"] = to_iso_timestamp(self.updated_at)
        data["last_play_by_slug"] = {
            k: to_iso_timestamp(v) for k, v in self.last_play_by_slug.items()
        }
        return data
