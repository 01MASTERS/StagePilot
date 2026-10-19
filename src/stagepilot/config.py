"""Configuration and path definitions for StagePilot."""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Union

UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class TimeConfig:
    """Time-related configurations and constants."""
    utc_tz: timezone = UTC
    ist_tz: timezone = IST
    quiet_hours_start_ist: int = 22  # 22:00 IST
    quiet_hours_end_ist: int = 8    # 08:00 IST
    page_ttl_minutes: int = 120
    offline_buffer_threshold_seconds: int = 600  # 10 minutes


@dataclass
class BudgetConfig:
    """Resource and latency budgets."""
    max_model_calls_per_decision: int = 8
    max_tool_calls_per_decision: int = 20
    max_decision_latency_ms: int = 60000     # 60s
    fatal_decision_latency_ms: int = 300000  # 5 min


@dataclass
class PathConfig:
    """Path management for pack data and artifacts."""
    pack_dir: Path = field(default_factory=lambda: Path("docs/one_user_one_agent_pack"))
    output_dir: Path = field(default_factory=lambda: Path("sample_run"))

    @property
    def events_path(self) -> Path:
        return self.pack_dir / "data" / "events.jsonl"

    @property
    def profiles_path(self) -> Path:
        return self.pack_dir / "data" / "profiles_snapshot.csv"

    @property
    def catalogue_path(self) -> Path:
        return self.pack_dir / "data" / "catalogue.csv"

    @property
    def episodes_path(self) -> Path:
        return self.pack_dir / "data" / "episodes.csv"

    @property
    def goals_config_path(self) -> Path:
        return self.pack_dir / "config" / "goals.json"

    @property
    def interventions_config_path(self) -> Path:
        return self.pack_dir / "config" / "interventions.json"

    @property
    def pricing_config_path(self) -> Path:
        return self.pack_dir / "config" / "pricing.json"

    @property
    def messaging_policy_path(self) -> Path:
        return self.pack_dir / "config" / "messaging_policy.md"

    @property
    def pilot_assignment_path(self) -> Path:
        return self.pack_dir / "pilot" / "pilot_assignment.csv"

    @property
    def pilot_outcomes_path(self) -> Path:
        return self.pack_dir / "pilot" / "pilot_outcomes.csv"

    @property
    def pilot_summary_path(self) -> Path:
        return self.pack_dir / "pilot" / "pilot_summary_report.md"

    @property
    def replay_triggers_path(self) -> Path:
        return self.pack_dir / "replay" / "triggers.jsonl"

    @property
    def replay_live_events_path(self) -> Path:
        return self.pack_dir / "replay" / "live_events.jsonl"

    @property
    def replay_control_events_path(self) -> Path:
        return self.pack_dir / "replay" / "control_events.jsonl"

    @property
    def replay_model_faults_path(self) -> Path:
        return self.pack_dir / "replay" / "model_faults.jsonl"

    @property
    def replay_arms_path(self) -> Path:
        return self.pack_dir / "replay" / "arms.csv"

    @property
    def simulator_script_path(self) -> Path:
        return self.pack_dir / "simulator" / "simulate_outcomes.py"


@dataclass
class AppConfig:
    """Master application configuration."""
    project_name: str = "StagePilot"
    version: str = "1.0.0"
    paths: PathConfig = field(default_factory=PathConfig)
    time: TimeConfig = field(default_factory=TimeConfig)
    budgets: BudgetConfig = field(default_factory=BudgetConfig)
    default_provider: str = "mock"
    gemini_model: str = "gemini-1.5-flash"
    ollama_model: str = "llama3"
    ollama_base_url: str = "http://localhost:11434"


def parse_iso_timestamp(ts_str: Optional[str]) -> Optional[datetime]:
    """Parse ISO-8601 UTC timestamp string into a timezone-aware datetime."""
    if not ts_str:
        return None
    # Handle both trailing 'Z' and offset format
    clean_ts = ts_str.replace("Z", "+00:00")
    dt = datetime.fromisoformat(clean_ts)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_iso_timestamp(dt: Optional[datetime]) -> Optional[str]:
    """Convert datetime to ISO-8601 UTC string with Z suffix."""
    if dt is None:
        return None
    utc_dt = dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
