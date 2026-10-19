"""Unit tests for SQLite state store, persistence, idempotency, and live mutations."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import pytest

from stagepilot.config import PathConfig, parse_iso_timestamp
from stagepilot.ingest.catalogue import CatalogueStore
from stagepilot.ingest.profiles import ProfileStore
from stagepilot.models.events import AppEvent
from stagepilot.models.profiles import ViewerProfile
from stagepilot.state.manager import StateManager
from stagepilot.state.models import ActiveGoal, ViewerFact, ViewerState
from stagepilot.state.store import SQLiteViewerStateStore

UTC = timezone.utc


class TestSQLiteViewerStateStore:
    """Verifies SQLite storage, idempotency, and atomic JSON export."""

    def test_save_and_retrieve_state(self, tmp_path: Path):
        """Verify state is correctly persisted to SQLite and retrieved with exact equality."""
        db_file = tmp_path / "test_viewers.db"
        store = SQLiteViewerStateStore(db_file)

        now = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
        profile = ViewerProfile(
            user_id="U-TEST-01",
            signup_at=now - timedelta(days=2),
            subscription_status="never",
            preferred_dialect="d2",
            notifications_opt_in=True,
            whatsapp_opt_in=False,
        )
        state = ViewerState(user_id="U-TEST-01", profile=profile, updated_at=now)
        state.record_fact("subscription_status", "never", "profile", now)
        state.total_plays = 3

        store.save(state)
        assert store.count() == 1
        assert store.exists("U-TEST-01") is True
        assert store.exists("U-UNKNOWN") is False

        # Retrieve and verify fields
        retrieved = store.get("U-TEST-01")
        assert retrieved is not None
        assert retrieved.user_id == "U-TEST-01"
        assert retrieved.profile.subscription_status == "never"
        assert retrieved.profile.preferred_dialect == "d2"
        assert retrieved.total_plays == 3
        assert retrieved.profile.notifications_opt_in is True
        assert "subscription_status" in retrieved.facts
        assert retrieved.facts["subscription_status"].value == "never"

        store.close()

    def test_export_all_json(self, tmp_path: Path):
        """Verify export_all_json creates inspectable per-viewer JSON files matching requirements."""
        store = SQLiteViewerStateStore(":memory:")
        now = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)

        for i in range(5):
            uid = f"U-0000{i}"
            prof = ViewerProfile(user_id=uid, subscription_status="trial_active", preferred_dialect="d1")
            st = ViewerState(user_id=uid, profile=prof, updated_at=now)
            st.record_fact("onboarding", True, "test", now)
            store.save(st)

        out_dir = tmp_path / "export_test"
        count = store.export_all_json(out_dir)
        assert count == 5

        # Check export directory
        viewer_state_dir = out_dir / "viewer_state"
        assert viewer_state_dir.exists()
        json_files = list(viewer_state_dir.glob("*.json"))
        assert len(json_files) == 5

        # Inspect one file
        sample_path = viewer_state_dir / "U-00002.json"
        with open(sample_path, encoding="utf-8") as f:
            data = json.load(f)
            assert data["user_id"] == "U-00002"
            assert data["profile"]["subscription_status"] == "trial_active"
            assert "onboarding" in data["facts"]


class TestStateManagerMutations:
    """Verifies that live events mutate viewer state correctly and idempotently."""

    @pytest.fixture
    def manager(self, catalogue_store: CatalogueStore, profile_store: ProfileStore) -> StateManager:
        store = SQLiteViewerStateStore(":memory:")
        return StateManager(store, profile_store, catalogue_store)

    def test_idempotent_event_application(self, manager: StateManager):
        """Verify the exact same event is ignored if applied multiple times."""
        now = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
        state = manager.get_or_create("U-IDEMP-01")

        event = AppEvent(
            event_id="EVT-UNIQUE-101",
            user_id="U-IDEMP-01",
            event="play_started",
            received_at=now,
            properties={"title_id": "T0001"},
        )

        state1 = manager.apply_event(state, event)
        assert state1.total_plays == 1
        assert state1.is_processed("EVT-UNIQUE-101") is True

        # Re-apply same event
        state2 = manager.apply_event(state1, event)
        assert state2.total_plays == 1  # Still 1, not 2!

    def test_purchase_event_retires_trial_and_first_paid_goals(self, manager: StateManager):
        """Verify purchase event marks open trial_to_paid goal as SUCCEEDED and updates status."""
        now = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
        state = manager.get_or_create("U-PURCH-01")
        state.profile.subscription_status = "trial_active"

        # Assign an active G04 goal
        state.active_goal = ActiveGoal(
            goal_id="G04",
            name="trial_to_paid_7d",
            status="OPEN",
            started_at=now - timedelta(days=1),
            deadline=now + timedelta(days=6),
            success_event="purchase_completed",
        )
        manager.store.save(state)

        # Purchase completed event arrives
        purchase_event = AppEvent(
            event_id="EVT-PURCHASE-999",
            user_id="U-PURCH-01",
            event="purchase_completed",
            received_at=now,
            properties={"plan_id": "P_MONTH", "price_inr": 149, "is_trial": False},
        )

        updated_state = manager.apply_event(state, purchase_event)
        assert updated_state.profile.subscription_status == "active"
        assert updated_state.active_goal is None  # Retired
        assert len(updated_state.completed_goals) == 1
        assert updated_state.completed_goals[0].goal_id == "G04"
        assert updated_state.completed_goals[0].status == "SUCCEEDED"
        assert "EVT-PURCHASE-999" in updated_state.completed_goals[0].qualifying_event_ids

    def test_opt_out_event_overrides_profile(self, manager: StateManager):
        """Verify notification_opt_out event overrides profile snapshot."""
        now = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
        state = manager.get_or_create("U-OPTOUT-01")
        state.profile.notifications_opt_in = True
        state.profile.whatsapp_opt_in = True
        manager.store.save(state)

        opt_out_evt = AppEvent(
            event_id="EVT-OPTOUT-1",
            user_id="U-OPTOUT-01",
            event="notification_opt_out",
            received_at=now,
            properties={"channel": "push"},
        )

        updated_state = manager.apply_event(state, opt_out_evt)
        assert updated_state.profile.notifications_opt_in is False
        assert updated_state.profile.whatsapp_opt_in is True

    def test_message_count_for_day_ist(self, manager: StateManager):
        """Verify message counts are isolated to specific IST calendar days."""
        state = manager.get_or_create("U-MSG-01")
        # Day 1: 2026-10-01 10:00 IST (UTC 04:30)
        dt1 = parse_iso_timestamp("2026-10-01T04:30:00.000Z")
        # Day 2: 2026-10-02 10:00 IST (UTC 04:30)
        dt2 = parse_iso_timestamp("2026-10-02T04:30:00.000Z")

        evt1 = AppEvent(
            event_id="M1",
            user_id="U-MSG-01",
            event="message_delivered",
            received_at=dt1,
            properties={"channel": "push", "action_id": "A-01"},
        )
        evt2 = AppEvent(
            event_id="M2",
            user_id="U-MSG-01",
            event="message_delivered",
            received_at=dt2,
            properties={"channel": "whatsapp", "action_id": "A-02"},
        )

        manager.apply_event(state, evt1)
        manager.apply_event(state, evt2)

        assert state.message_count_for_day_ist(dt1) == 1
        assert state.message_count_for_day_ist(dt2) == 1

    def test_dialect_conflict_recording(self, manager: StateManager):
        """Verify app setting, profile, and campaign deeplink dialects are tracked."""
        dt = parse_iso_timestamp("2026-10-01T04:30:00.000Z")
        state = manager.get_or_create("U-DIALECT-01")
        state.profile.preferred_dialect = "d1"
        state.record_fact("preferred_dialect", "d1", "profile", dt)

        trigger_with_conflict = AppEvent(
            event_id="EVT-DIALECT-TRIG",
            user_id="U-DIALECT-01",
            event="app_open",
            received_at=dt,
            app_dialect="d3",
            properties={"deeplink": "ott://c/diwali_promo/d5/title/T0100"},
        )

        updated_state = manager.apply_event(state, trigger_with_conflict)
        assert updated_state.facts["preferred_dialect"].value == "d1"
        assert updated_state.facts["app_dialect"].value == "d3"
        assert updated_state.facts["campaign_dialect"].value == "d5"
