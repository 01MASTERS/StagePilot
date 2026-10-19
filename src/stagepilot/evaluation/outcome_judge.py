"""Closed-loop attributable goal outcome judging engine."""

import csv
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from stagepilot.config import IST, UTC, parse_iso_timestamp, to_iso_timestamp
from stagepilot.ingest.arms import ArmStore
from stagepilot.ingest.catalogue import CatalogueStore
from stagepilot.models.events import AppEvent
from stagepilot.state.models import ActiveGoal, ViewerState

logger = logging.getLogger(__name__)


@dataclass
class ViewerOutcome:
    """Attributed lifecycle outcome for an individual viewer."""
    user_id: str
    arm: str  # 'agent' | 'holdout' | 'unknown'
    served: bool  # True if viewer received at least one published action
    goal_id: str
    goal_name: str
    goal_started_at: Optional[str]
    goal_deadline: Optional[str]
    succeeded: bool
    resolved_at: Optional[str]
    qualifying_event_ids: List[str] = field(default_factory=list)
    attribution_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class OutcomeJudge:
    """Evaluates viewer active goals against simulated outcome events strictly within attribution windows."""

    def __init__(
        self,
        catalogue_store: CatalogueStore,
        arm_store: Optional[ArmStore] = None,
    ) -> None:
        self.catalogue = catalogue_store
        self.arm_store = arm_store or ArmStore()

    def judge_all(
        self,
        viewer_state_dir: Path,
        outcome_events_path: Path,
        actions_path: Optional[Path] = None,
        output_dir: Optional[Path] = None,
    ) -> List[ViewerOutcome]:
        """Judge all viewers in viewer_state_dir against outcome_events_path."""
        viewer_state_dir = Path(viewer_state_dir)
        outcome_events_path = Path(outcome_events_path)

        # 1. Identify served viewers from actions.jsonl
        served_users: Set[str] = set()
        if actions_path and Path(actions_path).exists():
            with open(actions_path, "r", encoding="utf-8") as f:
                for line in f:
                    line_str = line.strip()
                    if line_str:
                        act = json.loads(line_str)
                        uid = act.get("user_id")
                        if uid:
                            served_users.add(uid)

        # 2. Ingest and index outcome events by user_id
        events_by_user: Dict[str, List[AppEvent]] = {}
        if outcome_events_path.exists():
            with open(outcome_events_path, "r", encoding="utf-8") as f:
                for line in f:
                    line_str = line.strip()
                    if line_str:
                        raw = json.loads(line_str)
                        ev = AppEvent(**raw)
                        if ev.user_id not in events_by_user:
                            events_by_user[ev.user_id] = []
                        events_by_user[ev.user_id].append(ev)

        # Sort each user's events chronologically
        for uid in events_by_user:
            events_by_user[uid].sort(key=lambda e: e.received_at)

        # 3. Load viewer states and evaluate goals
        outcomes: List[ViewerOutcome] = []
        state_files = list(viewer_state_dir.glob("*.json"))

        for state_file in sorted(state_files):
            with open(state_file, "r", encoding="utf-8") as f:
                state_data = json.load(f)
            state = ViewerState(**state_data)

            arm = "unknown"
            arm_obj = self.arm_store.get(state.user_id)
            if arm_obj:
                arm = "agent" if arm_obj.is_agent_arm else "holdout"

            served = state.user_id in served_users
            user_events = events_by_user.get(state.user_id, [])

            outcome = self.evaluate_viewer_goal(
                state=state,
                events=user_events,
                arm=arm,
                served=served,
            )
            outcomes.append(outcome)

            # Persist updated state with concluded goal
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(state.to_dict(), f, indent=2, ensure_ascii=False)

        # 4. Export outcomes.jsonl and outcomes.csv
        if output_dir:
            out_path = Path(output_dir)
            out_path.mkdir(parents=True, exist_ok=True)
            self._export_outcomes(outcomes, out_path)

        return outcomes

    def evaluate_viewer_goal(
        self,
        state: ViewerState,
        events: List[AppEvent],
        arm: str,
        served: bool,
    ) -> ViewerOutcome:
        """Evaluate a single viewer's active goal against their event stream."""
        goal = state.active_goal

        if not goal:
            # Check if there is an existing completed goal
            if state.completed_goals:
                last_goal = state.completed_goals[-1]
                return ViewerOutcome(
                    user_id=state.user_id,
                    arm=arm,
                    served=served,
                    goal_id=last_goal.goal_id,
                    goal_name=last_goal.name,
                    goal_started_at=to_iso_timestamp(last_goal.started_at),
                    goal_deadline=to_iso_timestamp(last_goal.deadline),
                    succeeded=last_goal.status == "SUCCEEDED",
                    resolved_at=to_iso_timestamp(last_goal.resolved_at),
                    qualifying_event_ids=last_goal.qualifying_event_ids,
                    attribution_reason=f"Goal previously concluded as {last_goal.status}",
                )
            return ViewerOutcome(
                user_id=state.user_id,
                arm=arm,
                served=served,
                goal_id="none",
                goal_name="none",
                goal_started_at=None,
                goal_deadline=None,
                succeeded=False,
                resolved_at=None,
                attribution_reason="No goal committed for this viewer",
            )

        start_time = goal.started_at
        deadline = goal.deadline
        gid = goal.goal_id
        success_event = goal.success_event

        succeeded = False
        resolved_at: Optional[datetime] = None
        qualifying_ids: List[str] = []
        reason = ""

        # Special tracking for habit goal G09
        g09_distinct_days: Set[date] = set()

        for ev in events:
            # Enforce strict attribution window [start_time, deadline]
            if ev.received_at < start_time:
                continue
            if ev.received_at > deadline:
                # Beyond window cutoff: event is non-attributable
                continue

            ev_name = ev.event
            props = ev.properties or {}

            if gid == "G01":
                # first_play_24h: play_started on any title
                if ev_name == "play_started":
                    succeeded = True
                    resolved_at = ev.received_at
                    qualifying_ids.append(ev.event_id)
                    reason = f"First play started at {to_iso_timestamp(ev.received_at)} within 24h"
                    break

            elif gid == "G02":
                # first_full_episode_3d: episode_completed for any episode
                if ev_name == "episode_completed":
                    succeeded = True
                    resolved_at = ev.received_at
                    qualifying_ids.append(ev.event_id)
                    reason = f"First episode completed at {to_iso_timestamp(ev.received_at)} within 72h"
                    break

            elif gid == "G03":
                # second_day_return_2d: play_started on a later IST calendar day (rule corrected from app_open)
                if ev_name == success_event:
                    start_ist = start_time.astimezone(IST).date()
                    ev_ist = ev.received_at.astimezone(IST).date()
                    if ev_ist > start_ist:
                        succeeded = True
                        resolved_at = ev.received_at
                        qualifying_ids.append(ev.event_id)
                        reason = f"Return {success_event} on later IST day ({ev_ist}) within 48h"
                        break

            elif gid in ("G04", "G05"):
                # trial_to_paid_7d & first_paid_7d: purchase_completed where is_trial == false
                if ev_name == "purchase_completed":
                    is_trial = props.get("is_trial", False)
                    if isinstance(is_trial, str):
                        is_trial = is_trial.lower() == "true"
                    if not is_trial:
                        succeeded = True
                        resolved_at = ev.received_at
                        qualifying_ids.append(ev.event_id)
                        reason = f"Paid purchase completed at {to_iso_timestamp(ev.received_at)} within 7d"
                        break

            elif gid == "G06":
                # reactivate_lapsed_14d: purchase_completed for any paid plan
                if ev_name == "purchase_completed":
                    succeeded = True
                    resolved_at = ev.received_at
                    qualifying_ids.append(ev.event_id)
                    reason = f"Reactivation purchase completed at {to_iso_timestamp(ev.received_at)} within 14d"
                    break

            elif gid == "G07":
                # resume_series_3d: play_started on same content_slug
                if ev_name == "play_started":
                    tid = props.get("title_id")
                    title_obj = self.catalogue.get_title(tid) if tid else None
                    if title_obj and goal.target_content_slug:
                        if title_obj.content_slug == goal.target_content_slug:
                            succeeded = True
                            resolved_at = ev.received_at
                            qualifying_ids.append(ev.event_id)
                            reason = f"Resumed target series {goal.target_content_slug} at {to_iso_timestamp(ev.received_at)}"
                            break

            elif gid == "G08":
                # try_new_release_7d: play_started on title released within 30 days prior to start
                if ev_name == "play_started":
                    tid = props.get("title_id")
                    title_obj = self.catalogue.get_title(tid) if tid else None
                    if title_obj and title_obj.release_date:
                        rel_dt: Optional[datetime] = None
                        if isinstance(title_obj.release_date, str):
                            rel_dt = parse_iso_timestamp(title_obj.release_date)
                            if rel_dt is None:
                                try:
                                    rel_dt = datetime.strptime(title_obj.release_date[:10], "%Y-%m-%d").replace(tzinfo=UTC)
                                except Exception:
                                    pass
                        elif isinstance(title_obj.release_date, datetime):
                            rel_dt = title_obj.release_date

                        if rel_dt:
                            cutoff_30d = start_time - timedelta(days=30)
                            if cutoff_30d <= rel_dt <= start_time:
                                succeeded = True
                                resolved_at = ev.received_at
                                qualifying_ids.append(ev.event_id)
                                reason = f"Played new release {tid} at {to_iso_timestamp(ev.received_at)}"
                                break

            elif gid == "G09":
                # weekly_habit_14d: play_started on 3 distinct IST days
                if ev_name == "play_started":
                    ist_d = ev.received_at.astimezone(IST).date()
                    g09_distinct_days.add(ist_d)
                    qualifying_ids.append(ev.event_id)
                    if len(g09_distinct_days) >= 3:
                        succeeded = True
                        resolved_at = ev.received_at
                        reason = f"Habit achieved on 3 distinct IST days ({len(g09_distinct_days)}) within 14d"
                        break

        # Conclude and mutate viewer state
        if succeeded:
            goal.status = "SUCCEEDED"
            goal.resolved_at = resolved_at
            goal.qualifying_event_ids = qualifying_ids
        else:
            goal.status = "FAILED"
            goal.resolved_at = deadline
            reason = f"No qualifying event observed before deadline {to_iso_timestamp(deadline)}"

        # Archive active goal
        state.completed_goals.append(goal)
        state.active_goal = None
        state.updated_at = resolved_at or deadline

        return ViewerOutcome(
            user_id=state.user_id,
            arm=arm,
            served=served,
            goal_id=gid,
            goal_name=goal.name,
            goal_started_at=to_iso_timestamp(start_time),
            goal_deadline=to_iso_timestamp(deadline),
            succeeded=succeeded,
            resolved_at=to_iso_timestamp(resolved_at or deadline),
            qualifying_event_ids=qualifying_ids,
            attribution_reason=reason,
        )

    def _export_outcomes(self, outcomes: List[ViewerOutcome], output_dir: Path) -> None:
        """Write outcomes.jsonl and outcomes.csv."""
        jsonl_path = output_dir / "outcomes.jsonl"
        csv_path = output_dir / "outcomes.csv"

        with open(jsonl_path, "w", encoding="utf-8") as f:
            for out in outcomes:
                f.write(json.dumps(out.to_dict(), ensure_ascii=False) + "\n")

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "user_id",
                "arm",
                "served",
                "goal_id",
                "goal_name",
                "goal_started_at",
                "goal_deadline",
                "succeeded",
                "resolved_at",
                "attribution_reason",
            ])
            for out in outcomes:
                writer.writerow([
                    out.user_id,
                    out.arm,
                    out.served,
                    out.goal_id,
                    out.goal_name,
                    out.goal_started_at,
                    out.goal_deadline,
                    out.succeeded,
                    out.resolved_at,
                    out.attribution_reason,
                ])
