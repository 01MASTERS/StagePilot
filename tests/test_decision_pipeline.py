"""Unit tests for the end-to-end DecisionPipeline and Section 4 schema compliance."""

from datetime import datetime, timedelta, timezone
import pytest

from stagepilot.config import PathConfig
from stagepilot.ingest.arms import ArmStore
from stagepilot.ingest.catalogue import CatalogueStore
from stagepilot.models.events import AppEvent
from stagepilot.models.profiles import ViewerProfile
from stagepilot.pipeline.decision import DecisionPipeline
from stagepilot.planner.goals import GoalPlanner
from stagepilot.planner.interventions import InterventionPlanner
from stagepilot.providers.mock_provider import MockReplayModelProvider
from stagepilot.state.models import ViewerState
from stagepilot.verifier.firewall import IndependentSafetyVerifier

UTC = timezone.utc


class TestDecisionPipeline:
    """Verifies end-to-end decision creation, Section 4 output schema, and simulator compatibility."""

    @pytest.fixture
    def pipeline(self, path_config: PathConfig, catalogue_store: CatalogueStore) -> DecisionPipeline:
        goal_planner = GoalPlanner(path_config.goals_config_path, catalogue_store)
        intervention_planner = InterventionPlanner(catalogue_store)
        model_provider = MockReplayModelProvider(path_config.replay_model_faults_path)
        arm_store = ArmStore.load(path_config.replay_arms_path)
        verifier = IndependentSafetyVerifier(catalogue_store, arm_store)
        return DecisionPipeline(goal_planner, intervention_planner, model_provider, verifier)

    def test_pipeline_decision_record_schema_compliance(self, pipeline: DecisionPipeline):
        """Verify decision record matches Section 4 schema with all required fields."""
        now = datetime(2026, 10, 1, 10, 0, 0, tzinfo=UTC)
        profile = ViewerProfile(user_id="U-PIPE-01", subscription_status="trial_active", preferred_dialect="d1")
        state = ViewerState(user_id="U-PIPE-01", profile=profile)

        trigger = AppEvent(
            event_id="TRIG-PIPE-01",
            user_id="U-PIPE-01",
            event="app_open",
            received_at=now,
            app_dialect="d1",
        )

        decision, action = pipeline.process_trigger(state, trigger, decision_counter=42)

        # Assert Section 4 schema compliance
        assert decision.decision_id == "D-0042"
        assert decision.viewer_id == "U-PIPE-01"
        assert decision.trigger["event"] == "app_open"
        assert "received_at" in decision.trigger
        assert "event_age_s" in decision.trigger
        assert decision.goal is not None
        assert decision.goal["id"] == "trial_to_paid_7d"
        assert "deadline" in decision.goal
        assert decision.action == "HOME_PAGE"
        assert decision.dialect["used"] == "d1"
        assert decision.dialect["source"] == "app_setting"
        assert isinstance(decision.dialect["conflicts"], list)
        assert len(decision.content) > 0
        assert decision.confidence > 0.0
        assert len(decision.evidence) > 0
        assert len(decision.assumptions) > 0
        assert "passed" in decision.checks
        assert "failed" in decision.checks
        assert decision.decided_in_ms >= 0
        assert decision.status == "PUBLISHED"

        # Assert action payload for simulator
        assert action is not None
        assert action["action_id"] == "A-0042"
        assert action["decision_id"] == "D-0042"
        assert action["user_id"] == "U-PIPE-01"
        assert action["type"] == "home_page"
        assert "hero_title_id" in action
        assert len(action["rows"]) > 0

    def test_pipeline_dialect_conflicts_preserved(self, pipeline: DecisionPipeline):
        """Verify dialect conflicts across app_setting, profile, and campaign deeplink are preserved."""
        now = datetime(2026, 10, 1, 10, 0, 0, tzinfo=UTC)
        profile = ViewerProfile(user_id="U-PIPE-02", preferred_dialect="d1")
        state = ViewerState(user_id="U-PIPE-02", profile=profile)

        trigger = AppEvent(
            event_id="TRIG-PIPE-02",
            user_id="U-PIPE-02",
            event="app_open",
            received_at=now,
            app_dialect="d3",
            properties={"deeplink": "ott://c/festival/d5/title/T0050"},
        )

        decision, _ = pipeline.process_trigger(state, trigger)
        assert decision.dialect["used"] == "d3"
        assert decision.dialect["source"] == "app_setting"
        assert "profile:d1" in decision.dialect["conflicts"]
        assert "campaign_deeplink:d5" in decision.dialect["conflicts"]

    def test_pipeline_stale_offline_trigger_produces_no_action(self, pipeline: DecisionPipeline):
        """Verify stale offline buffer trigger produces NO_ACTION decision."""
        now = datetime(2026, 10, 1, 10, 0, 0, tzinfo=UTC)
        profile = ViewerProfile(user_id="U-PIPE-03", preferred_dialect="d1")
        state = ViewerState(user_id="U-PIPE-03", profile=profile)

        trigger = AppEvent(
            event_id="TRIG-PIPE-03",
            user_id="U-PIPE-03",
            event="app_open",
            occurred_at=now - timedelta(hours=3),
            sent_at=now,
            received_at=now,
            app_dialect="d1",
        )

        decision, action = pipeline.process_trigger(state, trigger)
        assert decision.status == "NO_ACTION"
        assert decision.no_action_reason == "stale_offline_trigger"
        assert action is None
