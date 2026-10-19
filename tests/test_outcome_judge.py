"""Unit and integration tests for the closed-loop goal outcome judge."""

from datetime import datetime, timedelta
from pathlib import Path
import pytest

from stagepilot.config import IST, UTC
from stagepilot.ingest.catalogue import CatalogueStore
from stagepilot.models.catalogue import CatalogueTitle
from stagepilot.models.events import AppEvent
from stagepilot.models.profiles import ViewerProfile
from stagepilot.evaluation.outcome_judge import OutcomeJudge
from stagepilot.state.models import ActiveGoal, ViewerState


class TestOutcomeJudge:
    """Verifies that goal success attribution strictly respects deadlines and goal-specific criteria."""

    @pytest.fixture
    def catalogue(self) -> CatalogueStore:
        store = CatalogueStore()
        title_g07 = CatalogueTitle(
            title_id="T-SERIES-1",
            content_slug="thriller-series",
            title="Thriller Series",
            dialect="d1",
            language="hin",
            content_type="show",
            genres=["Thriller"],
            release_date="2026-08-01",
            available_from=datetime(2026, 1, 1, tzinfo=UTC),
        )
        title_other = CatalogueTitle(
            title_id="T-OTHER-1",
            content_slug="comedy-show",
            title="Comedy Show",
            dialect="d1",
            language="hin",
            content_type="show",
            genres=["Comedy"],
            release_date="2026-08-01",
            available_from=datetime(2026, 1, 1, tzinfo=UTC),
        )
        store.titles["T-SERIES-1"] = title_g07
        store.titles["T-OTHER-1"] = title_other
        return store

    def test_outcome_judge_window_enforcement(self, catalogue: CatalogueStore):
        """Verify events occurring after the goal deadline are non-attributable and the goal fails."""
        start_t = datetime(2026, 10, 1, 10, 0, 0, tzinfo=UTC)
        deadline = start_t + timedelta(hours=24)

        goal = ActiveGoal(
            goal_id="G01",
            name="first_play_24h",
            status="OPEN",
            started_at=start_t,
            deadline=deadline,
            success_event="play_started",
        )
        state = ViewerState(
            user_id="U-WINDOW-TEST",
            profile=ViewerProfile(user_id="U-WINDOW-TEST"),
            active_goal=goal,
        )

        # Event occurs 1 minute AFTER deadline
        late_event = AppEvent(
            event_id="EV-LATE",
            user_id="U-WINDOW-TEST",
            event="play_started",
            received_at=deadline + timedelta(minutes=1),
        )

        judge = OutcomeJudge(catalogue_store=catalogue)
        outcome = judge.evaluate_viewer_goal(state, [late_event], arm="agent", served=True)

        assert outcome.succeeded is False
        assert state.completed_goals[-1].status == "FAILED"
        assert state.active_goal is None

    def test_outcome_judge_g03_corrected_rule(self, catalogue: CatalogueStore):
        """Verify G03 requires play_started on a later IST calendar day."""
        start_t = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)  # 17:30 IST on Oct 1
        deadline = start_t + timedelta(hours=48)

        goal = ActiveGoal(
            goal_id="G03",
            name="second_day_return_2d",
            status="OPEN",
            started_at=start_t,
            deadline=deadline,
            success_event="play_started",  # Mid-replay rule correction
            success_condition="on a later IST calendar day within the window",
        )
        state = ViewerState(
            user_id="U-G03-TEST",
            profile=ViewerProfile(user_id="U-G03-TEST"),
            active_goal=goal,
        )

        # Same IST calendar day event: 2026-10-01 21:00 IST -> must NOT succeed
        same_day_ev = AppEvent(
            event_id="EV-SAME-DAY",
            user_id="U-G03-TEST",
            event="play_started",
            received_at=start_t + timedelta(hours=3),
        )

        # Later IST calendar day event: 2026-10-02 10:00 IST -> MUST succeed
        next_day_ev = AppEvent(
            event_id="EV-NEXT-DAY",
            user_id="U-G03-TEST",
            event="play_started",
            received_at=start_t + timedelta(hours=17),
        )

        judge = OutcomeJudge(catalogue_store=catalogue)

        # Evaluate with same-day only
        outcome1 = judge.evaluate_viewer_goal(state, [same_day_ev], arm="agent", served=True)
        assert outcome1.succeeded is False

        # Reset active goal and evaluate with next-day event
        state.active_goal = goal
        state.completed_goals.clear()
        outcome2 = judge.evaluate_viewer_goal(state, [next_day_ev], arm="agent", served=True)
        assert outcome2.succeeded is True
        assert "EV-NEXT-DAY" in outcome2.qualifying_event_ids

    def test_outcome_judge_purchase_trial_flag(self, catalogue: CatalogueStore):
        """Verify trial purchases (is_trial = true) do not satisfy paid subscription goals G04 and G05."""
        start_t = datetime(2026, 10, 1, 10, 0, 0, tzinfo=UTC)
        deadline = start_t + timedelta(days=7)

        goal = ActiveGoal(
            goal_id="G05",
            name="first_paid_7d",
            status="OPEN",
            started_at=start_t,
            deadline=deadline,
            success_event="purchase_completed",
            success_condition="is_trial = false",
        )
        state = ViewerState(
            user_id="U-TRIAL-TEST",
            profile=ViewerProfile(user_id="U-TRIAL-TEST"),
            active_goal=goal,
        )

        # Trial purchase
        trial_ev = AppEvent(
            event_id="EV-TRIAL",
            user_id="U-TRIAL-TEST",
            event="purchase_completed",
            received_at=start_t + timedelta(hours=4),
            properties={"plan_id": "P_TRIAL", "price_inr": 1, "is_trial": True},
        )

        # Paid purchase
        paid_ev = AppEvent(
            event_id="EV-PAID",
            user_id="U-TRIAL-TEST",
            event="purchase_completed",
            received_at=start_t + timedelta(hours=20),
            properties={"plan_id": "P_MONTH", "price_inr": 149, "is_trial": False},
        )

        judge = OutcomeJudge(catalogue_store=catalogue)

        # Trial event only -> failure
        outcome1 = judge.evaluate_viewer_goal(state, [trial_ev], arm="agent", served=True)
        assert outcome1.succeeded is False

        # Reset and evaluate with trial followed by paid -> success on paid
        state.active_goal = goal
        state.completed_goals.clear()
        outcome2 = judge.evaluate_viewer_goal(state, [trial_ev, paid_ev], arm="agent", served=True)
        assert outcome2.succeeded is True
        assert outcome2.qualifying_event_ids == ["EV-PAID"]

    def test_outcome_judge_g07_slug_match(self, catalogue: CatalogueStore):
        """Verify G07 requires play_started on the matching target_content_slug."""
        start_t = datetime(2026, 10, 1, 10, 0, 0, tzinfo=UTC)
        deadline = start_t + timedelta(hours=72)

        goal = ActiveGoal(
            goal_id="G07",
            name="resume_series_3d",
            status="OPEN",
            started_at=start_t,
            deadline=deadline,
            success_event="play_started",
            target_content_slug="thriller-series",
        )
        state = ViewerState(
            user_id="U-G07-TEST",
            profile=ViewerProfile(user_id="U-G07-TEST"),
            active_goal=goal,
        )

        # Unrelated series event
        wrong_slug_ev = AppEvent(
            event_id="EV-WRONG-SLUG",
            user_id="U-G07-TEST",
            event="play_started",
            received_at=start_t + timedelta(hours=10),
            properties={"title_id": "T-OTHER-1"},
        )

        # Matching series event
        correct_slug_ev = AppEvent(
            event_id="EV-CORRECT-SLUG",
            user_id="U-G07-TEST",
            event="play_started",
            received_at=start_t + timedelta(hours=12),
            properties={"title_id": "T-SERIES-1"},
        )

        judge = OutcomeJudge(catalogue_store=catalogue)

        outcome1 = judge.evaluate_viewer_goal(state, [wrong_slug_ev], arm="agent", served=True)
        assert outcome1.succeeded is False

        state.active_goal = goal
        state.completed_goals.clear()
        outcome2 = judge.evaluate_viewer_goal(state, [correct_slug_ev], arm="agent", served=True)
        assert outcome2.succeeded is True
        assert outcome2.qualifying_event_ids == ["EV-CORRECT-SLUG"]
