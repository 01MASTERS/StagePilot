"""Unit tests for the air-gapped independent safety verification firewall."""

from datetime import datetime, timedelta, timezone
import pytest

from stagepilot.config import IST, UTC, parse_iso_timestamp
from stagepilot.ingest.arms import ArmStore
from stagepilot.ingest.catalogue import CatalogueStore
from stagepilot.models.arms import ViewerArm
from stagepilot.models.events import AppEvent
from stagepilot.models.profiles import ViewerProfile
from stagepilot.planner.interventions import ProposedIntervention
from stagepilot.state.models import ViewerState
from stagepilot.verifier.firewall import IndependentSafetyVerifier


class TestSafetyVerifier:
    """Verifies that the independent safety firewall catches all policy breaches and vetoes actions."""

    @pytest.fixture
    def verifier(self, catalogue_store: CatalogueStore) -> IndependentSafetyVerifier:
        return IndependentSafetyVerifier(catalogue_store)

    def test_holdout_arm_veto(self, verifier: IndependentSafetyVerifier):
        """Verify any action proposed for a holdout user is vetoed to NO_ACTION."""
        arm_store = ArmStore()
        arm_store.arms["U-HOLDOUT-99"] = ViewerArm(user_id="U-HOLDOUT-99", arm="holdout")
        verifier.arm_store = arm_store

        now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
        profile = ViewerProfile(user_id="U-HOLDOUT-99")
        state = ViewerState(user_id="U-HOLDOUT-99", profile=profile)

        trigger = AppEvent(event_id="T1", user_id="U-HOLDOUT-99", event="app_open", received_at=now)
        proposed = ProposedIntervention(action_type="home_page", payload={"type": "home_page", "dialect": "d1"})

        outcome = verifier.verify(proposed, state, trigger)
        assert outcome.approved is False
        assert outcome.final_action_type == "NO_ACTION"
        assert outcome.veto_reason == "holdout_arm_assigned"
        assert "holdout_protection" in outcome.failed_checks

    def test_quiet_hours_gate_veto(self, verifier: IndependentSafetyVerifier):
        """Verify push/WhatsApp sent during IST quiet hours (22:00-08:00) is vetoed."""
        # 23:30 IST = 18:00 UTC
        night_time_utc = datetime(2026, 10, 1, 18, 0, 0, tzinfo=UTC)
        assert verifier.is_quiet_hours_ist(night_time_utc) is True

        profile = ViewerProfile(user_id="U-NIGHT-01", notifications_opt_in=True, preferred_dialect="d1")
        state = ViewerState(user_id="U-NIGHT-01", profile=profile)

        trigger = AppEvent(event_id="T2", user_id="U-NIGHT-01", event="app_open", received_at=night_time_utc)
        proposed = ProposedIntervention(
            action_type="push",
            payload={"type": "push", "title_id": "T0001", "text": {"title": "T", "body": "B"}, "deeplink": "ott://title/T0001"},
            target_title_id="T0001",
        )

        outcome = verifier.verify(proposed, state, trigger)
        assert outcome.approved is False
        assert outcome.final_action_type == "NO_ACTION"
        assert outcome.veto_reason == "push_in_quiet_hours"
        assert "quiet_hours_restriction" in outcome.failed_checks

    def test_missing_consent_gate_veto(self, verifier: IndependentSafetyVerifier):
        """Verify push proposed without notifications_opt_in is vetoed."""
        # 12:00 IST = 06:30 UTC (waking hours)
        day_time_utc = datetime(2026, 10, 1, 6, 30, 0, tzinfo=UTC)
        profile = ViewerProfile(user_id="U-NOCONSENT-01", notifications_opt_in=False, preferred_dialect="d1")
        state = ViewerState(user_id="U-NOCONSENT-01", profile=profile)

        trigger = AppEvent(event_id="T3", user_id="U-NOCONSENT-01", event="app_open", received_at=day_time_utc)
        proposed = ProposedIntervention(
            action_type="push",
            payload={"type": "push", "title_id": "T0001", "text": {"title": "T", "body": "B"}, "deeplink": "ott://title/T0001"},
            target_title_id="T0001",
        )

        outcome = verifier.verify(proposed, state, trigger)
        assert outcome.approved is False
        assert outcome.final_action_type == "NO_ACTION"
        assert outcome.veto_reason == "push_missing_consent"
        assert "push_consent" in outcome.failed_checks

    def test_daily_frequency_cap_gate_veto(self, verifier: IndependentSafetyVerifier):
        """Verify a second message on the same IST day is vetoed."""
        day_time_utc = datetime(2026, 10, 1, 6, 30, 0, tzinfo=UTC)
        profile = ViewerProfile(user_id="U-CAP-01", notifications_opt_in=True, preferred_dialect="d1")
        state = ViewerState(user_id="U-CAP-01", profile=profile)

        # Record a prior message sent today in IST
        state.sent_messages.append({
            "channel": "push",
            "action_id": "A-PREV",
            "delivered_at": day_time_utc.isoformat(),
            "ist_day": day_time_utc.astimezone(IST).strftime("%Y-%m-%d"),
        })

        trigger = AppEvent(event_id="T4", user_id="U-CAP-01", event="app_open", received_at=day_time_utc)
        proposed = ProposedIntervention(
            action_type="push",
            payload={"type": "push", "title_id": "T0001", "text": {"title": "T", "body": "B"}, "deeplink": "ott://title/T0001"},
            target_title_id="T0001",
        )

        outcome = verifier.verify(proposed, state, trigger)
        assert outcome.approved is False
        assert outcome.final_action_type == "NO_ACTION"
        assert outcome.veto_reason == "frequency_cap_exceeded"
        assert "frequency_cap_restriction" in outcome.failed_checks

    def test_row_dropping_below_minimum_three_titles(self, verifier: IndependentSafetyVerifier):
        """Verify a row with fewer than 3 valid titles is dropped from the homepage payload."""
        now = datetime(2026, 10, 1, 6, 30, 0, tzinfo=UTC)
        profile = ViewerProfile(user_id="U-ROW-01", preferred_dialect="d1")
        state = ViewerState(user_id="U-ROW-01", profile=profile)

        trigger = AppEvent(event_id="T5", user_id="U-ROW-01", event="app_open", received_at=now, app_dialect="d1")
        proposed = ProposedIntervention(
            action_type="home_page",
            payload={
                "type": "home_page",
                "dialect": "d1",
                "hero_title_id": "T0001",
                "rows": [
                    {"row_type": "popular_in_dialect", "title_ids": ["T0003", "T0004", "T0005"]},  # Valid (3 titles)
                    {"row_type": "genre", "title_ids": ["T0006", "T0007"]},                         # Invalid (< 3 titles)
                ],
            },
        )

        outcome = verifier.verify(proposed, state, trigger)
        assert outcome.approved is True
        assert outcome.final_action_type == "HOME_PAGE"
        # The invalid row must be dropped
        assert len(outcome.sanitized_payload["rows"]) == 1
        assert outcome.sanitized_payload["rows"][0]["row_type"] == "popular_in_dialect"
        assert "row_dropped_below_minimum" in outcome.failed_checks

    def test_hallucinated_model_claim_quarantine(self, verifier: IndependentSafetyVerifier):
        """Verify hallucinated billing claim from model is caught and quarantined."""
        now = datetime(2026, 10, 1, 6, 30, 0, tzinfo=UTC)
        profile = ViewerProfile(user_id="U-HALLUC-01", subscription_status="never")
        state = ViewerState(user_id="U-HALLUC-01", profile=profile)

        trigger = AppEvent(event_id="T6", user_id="U-HALLUC-01", event="app_open", received_at=now)
        proposed = ProposedIntervention(action_type="no_action", payload={})

        # Faulty model output claiming active trial confirmed in billing
        faulty_claim = {
            "goal_id": "G04",
            "eligible": True,
            "confidence": 0.97,
            "reason": "The user is on an active trial that ends tomorrow (confirmed in billing).",
        }

        outcome = verifier.verify(proposed, state, trigger, model_claims=faulty_claim)
        assert "model_evidence_unsupported" in outcome.failed_checks
        assert len(outcome.quarantined_claims) > 0
        assert "hallucinated_billing_claim" in outcome.quarantined_claims[0]
