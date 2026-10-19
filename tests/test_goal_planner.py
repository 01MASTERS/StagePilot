"""Unit tests for goal evaluation, unmeasurable goal vetoing, and mid-replay rule hot-patching."""

from datetime import datetime, timedelta, timezone
import pytest

from stagepilot.config import PathConfig, parse_iso_timestamp
from stagepilot.ingest.catalogue import CatalogueStore
from stagepilot.models.profiles import ViewerProfile
from stagepilot.planner.goals import GoalPlanner
from stagepilot.state.models import ActiveGoal, ViewerState

UTC = timezone.utc


class TestGoalPlanner:
    """Verifies evidence-based goal planning, priority ladder, and unmeasurable goal vetoing."""

    @pytest.fixture
    def planner(self, path_config: PathConfig, catalogue_store: CatalogueStore) -> GoalPlanner:
        return GoalPlanner(path_config.goals_config_path, catalogue_store)

    def test_unmeasurable_goals_are_vetoed(self, planner: GoalPlanner):
        """Verify G10 and G11 are strictly vetoed with explicit reasons."""
        now = datetime(2026, 10, 1, 10, 0, 0, tzinfo=UTC)
        profile = ViewerProfile(user_id="U-TEST-01", subscription_status="active")
        state = ViewerState(user_id="U-TEST-01", profile=profile)

        eligible, vetoed = planner.evaluate_candidates(state, now)
        vetoed_dict = dict(vetoed)

        assert "G10" in vetoed_dict
        assert "unmeasurable_success_signal: event is null" in vetoed_dict["G10"]
        assert "G11" in vetoed_dict
        assert "tv_app_open event does not exist" in vetoed_dict["G11"]

        # Neither G10 nor G11 can appear in eligible candidates
        eligible_ids = [c.goal_id for c in eligible]
        assert "G10" not in eligible_ids
        assert "G11" not in eligible_ids

    def test_trial_user_selects_g04(self, planner: GoalPlanner):
        """Verify user on trial is assigned G04 (trial_to_paid_7d) as highest priority."""
        now = datetime(2026, 10, 1, 10, 0, 0, tzinfo=UTC)
        profile = ViewerProfile(user_id="U-TRIAL-01", subscription_status="trial_active")
        state = ViewerState(user_id="U-TRIAL-01", profile=profile)

        goal, reason, evidence, assumptions = planner.pick_or_maintain_goal(state, now)
        assert goal is not None
        assert goal.goal_id == "G04"
        assert goal.name == "trial_to_paid_7d"
        assert goal.status == "OPEN"
        assert goal.deadline == now + timedelta(hours=168)
        assert "profile:subscription_status:trial_active" in evidence

    def test_lapsed_user_selects_g06(self, planner: GoalPlanner):
        """Verify lapsed subscriber is assigned G06 (reactivate_lapsed_14d)."""
        now = datetime(2026, 10, 1, 10, 0, 0, tzinfo=UTC)
        profile = ViewerProfile(user_id="U-LAPSED-01", subscription_status="lapsed")
        state = ViewerState(user_id="U-LAPSED-01", profile=profile)
        state.total_completes = 5

        goal, reason, evidence, assumptions = planner.pick_or_maintain_goal(state, now)
        assert goal is not None
        assert goal.goal_id == "G06"
        assert goal.name == "reactivate_lapsed_14d"
        assert goal.deadline == now + timedelta(hours=336)

    def test_resume_series_g07_eligibility(self, planner: GoalPlanner, catalogue_store: CatalogueStore):
        """Verify viewer with unfinished series inactive for 3+ days is eligible for G07."""
        now = datetime(2026, 10, 1, 10, 0, 0, tzinfo=UTC)
        # Find a show with > 1 episode
        sample_slug = None
        for slug, eps in catalogue_store.episodes_by_slug.items():
            if len(eps) > 2:
                sample_slug = slug
                break

        assert sample_slug is not None
        episodes = catalogue_store.get_episodes_for_slug(sample_slug)

        profile = ViewerProfile(user_id="U-SERIES-01", subscription_status="never")
        state = ViewerState(user_id="U-SERIES-01", profile=profile)
        # Mark first episode completed, but not second
        state.completed_episodes.add(episodes[0].episode_id)
        state.total_completes = 1
        # Last play on that slug was 4 days ago
        state.last_play_by_slug[sample_slug] = now - timedelta(days=4)

        eligible, _ = planner.evaluate_candidates(state, now)
        g07_candidates = [c for c in eligible if c.goal_id == "G07"]
        assert len(g07_candidates) == 1
        assert g07_candidates[0].target_content_slug == sample_slug

    def test_maintain_existing_unexpired_goal(self, planner: GoalPlanner):
        """Verify existing active goal is maintained until expiration."""
        now = datetime(2026, 10, 1, 10, 0, 0, tzinfo=UTC)
        profile = ViewerProfile(user_id="U-EXISTING-01", subscription_status="never")
        state = ViewerState(user_id="U-EXISTING-01", profile=profile)

        existing_goal = ActiveGoal(
            goal_id="G05",
            name="first_paid_7d",
            status="OPEN",
            started_at=now - timedelta(days=1),
            deadline=now + timedelta(days=6),
            success_event="purchase_completed",
        )
        state.active_goal = existing_goal

        goal, reason, _, _ = planner.pick_or_maintain_goal(state, now)
        assert goal.goal_id == "G05"
        assert "maintained_active_goal" in reason

    def test_expired_goal_transitions_to_failed(self, planner: GoalPlanner):
        """Verify expired goal is closed as FAILED and a new goal is selected."""
        now = datetime(2026, 10, 1, 10, 0, 0, tzinfo=UTC)
        profile = ViewerProfile(user_id="U-EXPIRED-01", subscription_status="never")
        state = ViewerState(user_id="U-EXPIRED-01", profile=profile)

        expired_goal = ActiveGoal(
            goal_id="G01",
            name="first_play_24h",
            status="OPEN",
            started_at=now - timedelta(days=2),
            deadline=now - timedelta(hours=1),  # Expired 1 hour ago
            success_event="play_started",
        )
        state.active_goal = expired_goal

        goal, reason, _, _ = planner.pick_or_maintain_goal(state, now)
        # Expired goal should be in completed_goals with status FAILED
        assert len(state.completed_goals) == 1
        assert state.completed_goals[0].goal_id == "G01"
        assert state.completed_goals[0].status == "FAILED"
        # New goal picked
        assert goal is not None
        assert goal.status == "OPEN"

    def test_mid_replay_g03_rule_correction(self, planner: GoalPlanner):
        """Verify control event at 08:30Z hot-patches open G03 goals from app_open to play_started."""
        now = datetime(2026, 10, 1, 8, 0, 0, tzinfo=UTC)

        open_g03 = ActiveGoal(
            goal_id="G03",
            name="second_day_return_2d",
            status="OPEN",
            started_at=now,
            deadline=now + timedelta(hours=48),
            success_event="app_open",
            success_condition="on a later IST calendar day within the window",
        )
        open_goals = [open_g03]

        control_event = {
            "at": "2026-10-01T08:30:00.000Z",
            "type": "goal_rule_corrected",
            "goal_id": "G03",
            "old_success": {"event": "app_open", "condition": "on a later IST calendar day within the window"},
            "new_success": {"event": "play_started", "condition": "on a later IST calendar day within the window"},
            "applies_to": "every G03 goal that is still open, including goals opened before this correction",
        }

        updated_count = planner.apply_rule_correction(control_event, open_goals)
        assert updated_count == 1
        assert open_g03.success_event == "play_started"
        assert open_g03.rule_version == "2026-10-01T08:30:00.000Z"
        # Planner internal rule updated
        assert planner.rules["G03"]["success"]["event"] == "play_started"
