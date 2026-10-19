"""Integration and system tests for the replay execution harness and operational resilience."""

import json
from datetime import datetime
from pathlib import Path
import pytest

from stagepilot.config import UTC, parse_iso_timestamp
from stagepilot.models.events import AppEvent
from stagepilot.models.profiles import ViewerProfile
from stagepilot.replay.control import ControlEventManager
from stagepilot.replay.harness import ReplayHarness
from stagepilot.replay.pump import ReplayEventPump, ReplayItem
from stagepilot.state.models import ActiveGoal, ViewerState


class TestReplayHarness:
    """Verifies chronological merging, operational surprises, and complete harness execution."""

    def test_chronological_stream_merger(self, tmp_path: Path):
        """Verify items pop in strict chronological order, prioritizing control > live > trigger on tie."""
        triggers_file = tmp_path / "triggers.jsonl"
        live_file = tmp_path / "live.jsonl"
        control_file = tmp_path / "control.jsonl"

        with open(triggers_file, "w", encoding="utf-8") as f:
            f.write(json.dumps({"deliver_at": "2026-10-01T10:00:00Z", "event": "app_open"}) + "\n")
            f.write(json.dumps({"deliver_at": "2026-10-01T12:00:00Z", "event": "app_open"}) + "\n")

        with open(live_file, "w", encoding="utf-8") as f:
            f.write(json.dumps({"received_at": "2026-10-01T09:00:00Z", "event": "play_started"}) + "\n")
            f.write(json.dumps({"received_at": "2026-10-01T10:00:00Z", "event": "episode_completed"}) + "\n")

        with open(control_file, "w", encoding="utf-8") as f:
            f.write(json.dumps({"at": "2026-10-01T10:00:00Z", "type": "title_withdrawn", "title_id": "T0001"}) + "\n")

        pump = ReplayEventPump(triggers_file, live_file, control_file)
        items = list(pump.stream_merged())

        assert len(items) == 5
        # Order must be: 09:00 (live), 10:00 (control), 10:00 (live), 10:00 (trigger), 12:00 (trigger)
        assert items[0].item_type == "live_event"
        assert items[0].timestamp == parse_iso_timestamp("2026-10-01T09:00:00Z")

        assert items[1].item_type == "control_event"
        assert items[1].timestamp == parse_iso_timestamp("2026-10-01T10:00:00Z")

        assert items[2].item_type == "live_event"
        assert items[2].timestamp == parse_iso_timestamp("2026-10-01T10:00:00Z")

        assert items[3].item_type == "trigger"
        assert items[3].timestamp == parse_iso_timestamp("2026-10-01T10:00:00Z")

        assert items[4].item_type == "trigger"
        assert items[4].timestamp == parse_iso_timestamp("2026-10-01T12:00:00Z")

    def test_title_withdrawn_control_event(self, pack_dir: Path):
        """Verify title_withdrawn clips availability and excludes title from subsequent recommendations."""
        harness = ReplayHarness(pack_dir=pack_dir, output_dir=pack_dir / "test_out", prepopulate_historical=False)
        harness.setup()

        before_withdrawal = datetime(2026, 10, 1, 6, 59, 0, tzinfo=UTC)
        assert harness.catalogue_store.is_available("T0001", before_withdrawal) is True

        # Handle control event at 07:00Z
        control_ev = {
            "at": "2026-10-01T07:00:00.000Z",
            "type": "title_withdrawn",
            "title_id": "T0001",
            "reason": "licence ended early",
        }
        res = harness.control_manager.handle(control_ev)
        assert res["handled"] is True

        after_withdrawal = datetime(2026, 10, 1, 7, 1, 0, tzinfo=UTC)
        assert harness.catalogue_store.is_available("T0001", after_withdrawal) is False

    def test_g03_rule_correction_control_event(self, pack_dir: Path):
        """Verify goal_rule_corrected hot-patches open goals in-memory to require play_started."""
        harness = ReplayHarness(pack_dir=pack_dir, output_dir=pack_dir / "test_out", prepopulate_historical=False)
        harness.setup()

        # Create simulated open G03 goal
        open_goal = ActiveGoal(
            goal_id="G03",
            name="return_within_7d",
            status="OPEN",
            started_at=datetime(2026, 9, 29, 10, 0, 0, tzinfo=UTC),
            deadline=datetime(2026, 10, 6, 10, 0, 0, tzinfo=UTC),
            success_event="app_open",
            success_condition="on a later IST calendar day within the window",
        )

        control_ev = {
            "at": "2026-10-01T08:30:00.000Z",
            "type": "goal_rule_corrected",
            "goal_id": "G03",
            "new_success": {"event": "play_started", "condition": "on a later IST calendar day within the window"},
        }

        res = harness.control_manager.handle(control_ev, open_goals=[open_goal])
        assert res["handled"] is True
        assert res["patched_open_goals"] == 1
        assert open_goal.success_event == "play_started"
        assert harness.goal_planner.rules["G03"]["success"]["event"] == "play_started"

    def test_model_unavailable_outage_fallback(self, pack_dir: Path):
        """Verify decisions during the 503 outage window fallback safely without crashing."""
        harness = ReplayHarness(pack_dir=pack_dir, output_dir=pack_dir / "test_out", prepopulate_historical=False)
        harness.setup()

        # Handle outage window: 10:35 to 10:42
        outage_ev = {
            "at": "2026-10-01T10:35:00.000Z",
            "type": "dependency_unavailable",
            "dependency": "model_provider",
            "until": "2026-10-01T10:42:00.000Z",
        }
        harness.control_manager.handle(outage_ev)

        # Trigger inside outage window: 10:38Z
        outage_time = datetime(2026, 10, 1, 10, 38, 0, tzinfo=UTC)
        profile = ViewerProfile(user_id="U-TEST-OUTAGE", subscription_status="active", preferred_dialect="d1")
        state = ViewerState(user_id="U-TEST-OUTAGE", profile=profile)

        trigger = AppEvent(
            event_id="EV-OUTAGE-1",
            user_id="U-TEST-OUTAGE",
            event="app_open",
            received_at=outage_time,
            deliver_at=outage_time,
            app_dialect="d1",
        )

        decision, action = harness.pipeline.process_trigger(state, trigger)
        assert decision is not None
        assert decision.fallback_used is True
        # Safety firewall passed and action was published despite 503 model outage
        assert decision.status in ("PUBLISHED", "NO_ACTION")

    def test_full_replay_smoke_run(self, pack_dir: Path, tmp_path: Path):
        """Execute replay over a limited slice of triggers and verify complete artifact generation."""
        out_dir = tmp_path / "smoke_run"
        harness = ReplayHarness(
            pack_dir=pack_dir,
            output_dir=out_dir,
            prepopulate_historical=False,
        )
        harness.setup()
        summary = harness.run(max_triggers=15)

        assert summary["triggers_processed"] == 15
        assert summary["decisions_published"] == 15
        assert (out_dir / "decisions.jsonl").exists()
        assert (out_dir / "actions.jsonl").exists()
        assert (out_dir / "latency_report.json").exists()
        assert (out_dir / "viewer_state").is_dir()

        # Validate decision lines
        with open(out_dir / "decisions.jsonl", "r", encoding="utf-8") as f:
            lines = [json.loads(line) for line in f]
            assert len(lines) == 15
            for rec in lines:
                assert "decision_id" in rec
                assert "viewer_id" in rec
                assert "action" in rec
                assert "status" in rec
                assert "decided_in_ms" in rec

        # Validate latency report
        with open(out_dir / "latency_report.json", "r", encoding="utf-8") as f:
            lat = json.load(f)
            assert lat["count"] == 15
            assert lat["sla_compliance_rate"] == 1.0
            assert lat["max_ms"] < 60000.0
