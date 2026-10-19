"""Operational surprise handling for control events during replay."""

from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from stagepilot.config import parse_iso_timestamp
from stagepilot.ingest.catalogue import CatalogueStore
from stagepilot.planner.goals import GoalPlanner
from stagepilot.state.models import ActiveGoal


class ControlEventManager:
    """Manages dynamic operational surprises injected during replay."""

    def __init__(self, catalogue_store: CatalogueStore, goal_planner: GoalPlanner) -> None:
        self.catalogue = catalogue_store
        self.goal_planner = goal_planner
        self.withdrawn_titles: Dict[str, datetime] = {}
        self.outage_windows: List[Tuple[str, datetime, datetime]] = []  # (dep_name, start, end)
        self.degraded_windows: List[Tuple[str, datetime, datetime]] = []

    def handle(self, event_data: Dict[str, Any], open_goals: Optional[List[ActiveGoal]] = None) -> Dict[str, Any]:
        """Process a control event and apply operational side effects."""
        event_type = event_data.get("type")
        at = parse_iso_timestamp(event_data.get("at")) or datetime.min

        if event_type == "title_withdrawn":
            title_id = event_data.get("title_id", "")
            self.catalogue.withdraw_title(title_id, at)
            self.withdrawn_titles[title_id] = at
            return {
                "handled": True,
                "type": event_type,
                "title_id": title_id,
                "withdrawn_at": at.isoformat(),
            }

        elif event_type == "goal_rule_corrected":
            goals_to_patch = open_goals or []
            patched_count = self.goal_planner.apply_rule_correction(event_data, goals_to_patch)
            return {
                "handled": True,
                "type": event_type,
                "goal_id": event_data.get("goal_id"),
                "patched_open_goals": patched_count,
            }

        elif event_type == "dependency_unavailable":
            dep = event_data.get("dependency", "model_provider")
            until = parse_iso_timestamp(event_data.get("until")) or at
            self.outage_windows.append((dep, at, until))
            return {
                "handled": True,
                "type": event_type,
                "dependency": dep,
                "start": at.isoformat(),
                "until": until.isoformat(),
            }

        elif event_type == "dependency_degraded":
            dep = event_data.get("dependency", "user_data_store")
            until = parse_iso_timestamp(event_data.get("until")) or at
            self.degraded_windows.append((dep, at, until))
            return {
                "handled": True,
                "type": event_type,
                "dependency": dep,
                "start": at.isoformat(),
                "until": until.isoformat(),
            }

        return {"handled": False, "reason": f"unknown_control_event_type: {event_type}"}

    def is_dependency_unavailable(self, dependency: str, at: datetime) -> bool:
        """Return True if the named dependency is undergoing an outage at timestamp."""
        for dep, start, end in self.outage_windows:
            if dep == dependency and start <= at < end:
                return True
        return False

    def is_dependency_degraded(self, dependency: str, at: datetime) -> bool:
        """Return True if the named dependency is degraded at timestamp."""
        for dep, start, end in self.degraded_windows:
            if dep == dependency and start <= at < end:
                return True
        return False
