"""Goal eligibility evaluation, priority ranking, and mid-replay rule hot-patching."""

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from stagepilot.config import IST, UTC, parse_iso_timestamp
from stagepilot.ingest.catalogue import CatalogueStore
from stagepilot.models.events import AppEvent
from stagepilot.state.models import ActiveGoal, ViewerState


@dataclass
class GoalCandidate:
    """An eligible goal candidate with supporting evidence and parameters."""
    goal_id: str
    name: str
    priority: int
    window_hours: int
    success_event: str
    success_condition: str
    evidence: List[str]
    assumptions: List[str]
    target_content_slug: Optional[str] = None
    target_release_cutoff: Optional[datetime] = None


class GoalPlanner:
    """Evaluates viewer eligibility for candidate goals G01-G12 with strict unmeasurable goal vetoing."""

    def __init__(self, goals_config_path: Path, catalogue_store: CatalogueStore) -> None:
        self.goals_config_path = goals_config_path
        self.catalogue_store = catalogue_store
        self.rules: Dict[str, Dict[str, Any]] = {}
        self.rule_versions: Dict[str, str] = {}
        self._load_config()

    def _load_config(self) -> None:
        with open(self.goals_config_path, encoding="utf-8") as f:
            data = json.load(f)
            base_version = data.get("version", "2026-09-30")
            for g in data.get("goals", []):
                gid = g["goal_id"]
                self.rules[gid] = g
                self.rule_versions[gid] = base_version

    def apply_rule_correction(self, control_event: Dict[str, Any], open_goals: List[ActiveGoal]) -> int:
        """Hot-patch a corrected goal rule in-memory and update active open goals without full reprocessing.
        
        Example control event:
        {"at":"2026-10-01T08:30:00.000Z","type":"goal_rule_corrected","goal_id":"G03",
         "new_success":{"event":"play_started","condition":"on a later IST calendar day within the window"}}
        """
        gid = control_event.get("goal_id")
        if not gid or gid not in self.rules:
            return 0

        correction_time = control_event.get("at", "2026-10-01T08:30:00.000Z")
        new_success = control_event.get("new_success", {})
        self.rules[gid]["success"]["event"] = new_success.get("event", self.rules[gid]["success"]["event"])
        self.rules[gid]["success"]["condition"] = new_success.get("condition", self.rules[gid]["success"]["condition"])
        self.rule_versions[gid] = correction_time

        updated_count = 0
        for goal in open_goals:
            if goal.goal_id == gid and goal.status == "OPEN":
                goal.success_event = self.rules[gid]["success"]["event"]
                goal.success_condition = self.rules[gid]["success"]["condition"]
                goal.rule_version = correction_time
                updated_count += 1

        return updated_count

    def evaluate_candidates(
        self, state: ViewerState, at: datetime
    ) -> Tuple[List[GoalCandidate], List[Tuple[str, str]]]:
        """Evaluate eligibility for all candidate goals.
        
        Returns:
            (eligible_candidates_sorted_by_priority, vetoed_or_ineligible_goals_with_reasons)
        """
        eligible: List[GoalCandidate] = []
        vetoed: List[Tuple[str, str]] = []

        signup_at = state.profile.signup_at
        status = state.profile.subscription_status
        total_plays = state.total_plays
        total_completes = state.total_completes

        # G10: meaningful_engagement_7d (VETOED AS UNMEASURABLE: event is null)
        vetoed.append(("G10", "unmeasurable_success_signal: event is null"))

        # G11: tv_activation_14d (VETOED AS UNMEASURABLE: tv_app_open does not exist in telemetry)
        vetoed.append(("G11", "unmeasurable_success_signal: tv_app_open event does not exist in platform telemetry"))

        # G01: first_play_24h
        # Signed up in last 7 days and has never started a play
        if signup_at and (at - signup_at).total_seconds() <= 7 * 86400 and total_plays == 0:
            eligible.append(GoalCandidate(
                goal_id="G01",
                name="first_play_24h",
                priority=40,
                window_hours=24,
                success_event=self.rules["G01"]["success"]["event"],
                success_condition=self.rules["G01"]["success"]["condition"],
                evidence=[f"profile:signup_at:{signup_at.isoformat()}", "telemetry:total_plays:0"],
                assumptions=["viewer has intent to watch content upon onboarding"],
            ))
        else:
            vetoed.append(("G01", "ineligible: signup older than 7d or plays > 0"))

        # G02: first_full_episode_3d
        # Has never completed an episode
        if total_completes == 0:
            eligible.append(GoalCandidate(
                goal_id="G02",
                name="first_full_episode_3d",
                priority=50,
                window_hours=72,
                success_event=self.rules["G02"]["success"]["event"],
                success_condition=self.rules["G02"]["success"]["condition"],
                evidence=["telemetry:total_completes:0"],
                assumptions=["finishing a full episode correlates strongly with long-term retention"],
            ))
        else:
            vetoed.append(("G02", "ineligible: viewer has already completed an episode"))

        # G03: second_day_return_2d
        # Signed up in last 2 days
        if signup_at and (at - signup_at).total_seconds() <= 2 * 86400:
            eligible.append(GoalCandidate(
                goal_id="G03",
                name="second_day_return_2d",
                priority=45,
                window_hours=48,
                success_event=self.rules["G03"]["success"]["event"],
                success_condition=self.rules["G03"]["success"]["condition"],
                evidence=[f"profile:signup_at:{signup_at.isoformat()}"],
                assumptions=["second day return establishes habit formation"],
            ))
        else:
            vetoed.append(("G03", "ineligible: signup older than 2d"))

        # G04: trial_to_paid_7d
        # Subscription status is trial_active
        if status == "trial_active":
            eligible.append(GoalCandidate(
                goal_id="G04",
                name="trial_to_paid_7d",
                priority=10,  # Highest priority revenue goal
                window_hours=168,
                success_event=self.rules["G04"]["success"]["event"],
                success_condition=self.rules["G04"]["success"]["condition"],
                evidence=["profile:subscription_status:trial_active"],
                assumptions=["trial user needs reminder or high-value catalog hook before trial ends"],
            ))
        else:
            vetoed.append(("G04", "ineligible: subscription_status is not trial_active"))

        # G05: first_paid_7d
        # Has never had a paid plan
        if status == "never":
            eligible.append(GoalCandidate(
                goal_id="G05",
                name="first_paid_7d",
                priority=20,
                window_hours=168,
                success_event=self.rules["G05"]["success"]["event"],
                success_condition=self.rules["G05"]["success"]["condition"],
                evidence=["profile:subscription_status:never"],
                assumptions=["unpaid viewer is evaluating catalog breadth before purchasing"],
            ))
        else:
            vetoed.append(("G05", "ineligible: subscription_status is not never"))

        # G06: reactivate_lapsed_14d
        # Subscription lapsed
        if status == "lapsed":
            eligible.append(GoalCandidate(
                goal_id="G06",
                name="reactivate_lapsed_14d",
                priority=25,
                window_hours=336,
                success_event=self.rules["G06"]["success"]["event"],
                success_condition=self.rules["G06"]["success"]["condition"],
                evidence=["profile:subscription_status:lapsed"],
                assumptions=["lapsed subscriber can be reactivated with fresh dialect releases"],
            ))
        else:
            vetoed.append(("G06", "ineligible: subscription_status is not lapsed"))

        # G07: resume_series_3d
        # Started a show or micro-drama, has unwatched episodes left, and has not played it for 3+ days
        eligible_series = None
        for slug, last_play in state.last_play_by_slug.items():
            episodes = self.catalogue_store.get_episodes_for_slug(slug)
            if len(episodes) > 1:  # Is a multi-episode show or micro-drama
                completed_for_slug = sum(1 for ep in episodes if ep.episode_id in state.completed_episodes)
                if completed_for_slug < len(episodes):  # Unwatched episodes left
                    days_since_play = (at - last_play).total_seconds() / 86400.0
                    if days_since_play >= 3.0:
                        eligible_series = slug
                        break

        if eligible_series:
            eligible.append(GoalCandidate(
                goal_id="G07",
                name="resume_series_3d",
                priority=30,
                window_hours=72,
                success_event=self.rules["G07"]["success"]["event"],
                success_condition=self.rules["G07"]["success"]["condition"],
                evidence=[f"telemetry:unfinished_series:{eligible_series}", "telemetry:inactive_days>=3"],
                assumptions=["viewer enjoyed early episodes but lost momentum; reminder triggers resume"],
                target_content_slug=eligible_series,
            ))
        else:
            vetoed.append(("G07", "ineligible: no unfinished show with >= 3 days since last play"))

        # G08: try_new_release_7d
        # Active subscriber plays a recent release (released in 30 days before goal start)
        if status == "active":
            cutoff = at - timedelta(days=30)
            eligible.append(GoalCandidate(
                goal_id="G08",
                name="try_new_release_7d",
                priority=60,
                window_hours=168,
                success_event=self.rules["G08"]["success"]["event"],
                success_condition=self.rules["G08"]["success"]["condition"],
                evidence=["profile:subscription_status:active"],
                assumptions=["active subscribers value continuous fresh release discovery"],
                target_release_cutoff=cutoff,
            ))
        else:
            vetoed.append(("G08", "ineligible: subscription_status is not active"))

        # G09: weekly_habit_14d
        # Active subscriber with plays on at most 1 day in the last 14 days
        if status == "active":
            # Check plays in last 14 days
            recent_play_days = set()
            cutoff_14d = (at - timedelta(days=14)).astimezone(IST).strftime("%Y-%m-%d")
            for day in state.active_days_ist:
                if day >= cutoff_14d:
                    recent_play_days.add(day)

            if len(recent_play_days) <= 1:
                eligible.append(GoalCandidate(
                    goal_id="G09",
                    name="weekly_habit_14d",
                    priority=55,
                    window_hours=336,
                    success_event=self.rules["G09"]["success"]["event"],
                    success_condition=self.rules["G09"]["success"]["condition"],
                    evidence=["profile:subscription_status:active", f"telemetry:active_days_14d:{len(recent_play_days)}"],
                    assumptions=["low-frequency active subscribers risk churning without regular habit formation"],
                ))
            else:
                vetoed.append(("G09", f"ineligible: played on {len(recent_play_days)} days in last 14d (> 1)"))
        else:
            vetoed.append(("G09", "ineligible: subscription_status is not active"))

        # G12: return_after_absence_7d
        # No app_open in the 14 days before trigger
        if state.last_app_open_at:
            days_absent = (at - state.last_app_open_at).total_seconds() / 86400.0
            if days_absent >= 14.0:
                eligible.append(GoalCandidate(
                    goal_id="G12",
                    name="return_after_absence_7d",
                    priority=35,
                    window_hours=168,
                    success_event=self.rules["G12"]["success"]["event"],
                    success_condition=self.rules["G12"]["success"]["condition"],
                    evidence=[f"telemetry:absence_days:{days_absent:.1f}>=14"],
                    assumptions=["returning viewer after long absence needs immediate engagement hook"],
                ))
            else:
                vetoed.append(("G12", f"ineligible: absent only {days_absent:.1f} days (< 14)"))
        else:
            vetoed.append(("G12", "ineligible: no recorded prior app open"))

        # Sort eligible goals by priority (lower number = higher priority)
        eligible.sort(key=lambda c: c.priority)
        return eligible, vetoed

    def pick_or_maintain_goal(
        self, state: ViewerState, at: datetime
    ) -> Tuple[Optional[ActiveGoal], str, List[str], List[str]]:
        """Pick an eligible goal or maintain the current active goal if unexpired.
        
        Returns:
            (active_goal, decision_reason, evidence_list, assumptions_list)
        """
        # If user already has an active, non-expired goal, maintain it
        if state.active_goal and state.active_goal.status == "OPEN":
            if not state.active_goal.is_expired(at):
                return (
                    state.active_goal,
                    f"maintained_active_goal:{state.active_goal.goal_id}",
                    [f"active_goal:{state.active_goal.goal_id}", f"deadline:{state.active_goal.deadline.isoformat()}"],
                    ["viewer is currently pursuing active plan"],
                )
            else:
                # Goal expired without success -> record as FAILED
                state.active_goal.status = "FAILED"
                state.active_goal.resolved_at = at
                state.completed_goals.append(state.active_goal)
                state.active_goal = None

        # Evaluate candidate goals
        eligible, vetoed = self.evaluate_candidates(state, at)
        if not eligible:
            return None, "no_eligible_goals_found", [f"vetoed_goals_count:{len(vetoed)}"], ["insufficient evidence to commit to measurable goal"]

        # Pick top priority candidate
        top = eligible[0]
        rule_ver = self.rule_versions.get(top.goal_id, "2026-09-30")
        deadline = at + timedelta(hours=top.window_hours)

        goal = ActiveGoal(
            goal_id=top.goal_id,
            name=top.name,
            status="OPEN",
            started_at=at,
            deadline=deadline,
            rule_version=rule_ver,
            success_event=top.success_event,
            success_condition=top.success_condition,
            target_content_slug=top.target_content_slug,
            target_release_cutoff=top.target_release_cutoff,
        )
        state.active_goal = goal
        return (
            goal,
            f"selected_top_priority_goal:{top.goal_id}",
            top.evidence,
            top.assumptions,
        )
