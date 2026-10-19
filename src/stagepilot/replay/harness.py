"""Replay execution harness orchestrating chronological simulation, resilience, and output generation."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from stagepilot.config import IST, UTC
from stagepilot.ingest.arms import ArmStore
from stagepilot.ingest.catalogue import CatalogueStore
from stagepilot.ingest.events import EventStreamReader
from stagepilot.ingest.profiles import ProfileStore
from stagepilot.models.events import AppEvent
from stagepilot.pipeline.decision import DecisionPipeline
from stagepilot.planner.goals import GoalPlanner
from stagepilot.planner.interventions import InterventionPlanner
from stagepilot.providers.base import ModelProvider
from stagepilot.providers.mock_provider import MockReplayModelProvider
from stagepilot.replay.control import ControlEventManager
from stagepilot.replay.metrics import LatencyTracker
from stagepilot.replay.pump import ReplayEventPump, ReplayItem
from stagepilot.state.manager import StateManager
from stagepilot.state.models import ViewerState
from stagepilot.state.store import SQLiteViewerStateStore
from stagepilot.verifier.firewall import IndependentSafetyVerifier

logger = logging.getLogger(__name__)


class ReplayHarness:
    """Master orchestrator for executing the single-day or multi-day chronological replay."""

    def __init__(
        self,
        pack_dir: Path,
        output_dir: Path,
        model_provider: Optional[ModelProvider] = None,
        db_path: Union[str, Path] = ":memory:",
        prepopulate_historical: bool = True,
    ) -> None:
        self.pack_dir = Path(pack_dir)
        self.output_dir = Path(output_dir)
        self.db_path = db_path
        self.prepopulate_historical = prepopulate_historical

        self.custom_model_provider = model_provider
        self.state_cache: Dict[str, ViewerState] = {}

        # Component placeholders
        self.arm_store: Optional[ArmStore] = None
        self.catalogue_store: Optional[CatalogueStore] = None
        self.profile_store: Optional[ProfileStore] = None
        self.goal_planner: Optional[GoalPlanner] = None
        self.intervention_planner: Optional[InterventionPlanner] = None
        self.verifier: Optional[IndependentSafetyVerifier] = None
        self.control_manager: Optional[ControlEventManager] = None
        self.model_provider: Optional[ModelProvider] = None
        self.pipeline: Optional[DecisionPipeline] = None
        self.store: Optional[SQLiteViewerStateStore] = None
        self.state_manager: Optional[StateManager] = None
        self.latency_tracker: Optional[LatencyTracker] = None

    def setup(self) -> None:
        """Initialize all stores, planners, verifiers, and pipeline components."""
        # 1. Assignment Arms
        arms_path = self.pack_dir / "replay" / "arms.csv"
        if not arms_path.exists():
            arms_path = self.pack_dir / "data" / "arms.csv"
        self.arm_store = ArmStore.load(arms_path) if arms_path.exists() else ArmStore()

        # 2. Catalogue & Episodes
        catalogue_path = self.pack_dir / "data" / "catalogue.csv"
        episodes_path = self.pack_dir / "data" / "episodes.csv"
        self.catalogue_store = CatalogueStore.load(catalogue_path, episodes_path)

        # 3. Viewer Profiles
        profiles_path = self.pack_dir / "data" / "profiles_snapshot.csv"
        self.profile_store = ProfileStore.load(profiles_path)

        # 4. Goal Planner
        goals_config_path = self.pack_dir / "config" / "goals.json"
        self.goal_planner = GoalPlanner(goals_config_path, self.catalogue_store)

        # 5. Safety Verifier & Intervention Planner
        self.verifier = IndependentSafetyVerifier(self.catalogue_store, self.arm_store)
        self.intervention_planner = InterventionPlanner(self.catalogue_store)

        # 6. Operational Surprise Control Manager
        self.control_manager = ControlEventManager(self.catalogue_store, self.goal_planner)

        # 7. Model Provider
        if self.custom_model_provider:
            self.model_provider = self.custom_model_provider
        else:
            faults_path = self.pack_dir / "replay" / "model_faults.jsonl"
            self.model_provider = MockReplayModelProvider(
                model_faults_path=faults_path if faults_path.exists() else None
            )

        # 8. Unified Decision Pipeline
        self.pipeline = DecisionPipeline(
            goal_planner=self.goal_planner,
            intervention_planner=self.intervention_planner,
            model_provider=self.model_provider,
            verifier=self.verifier,
            control_manager=self.control_manager,
        )

        # 9. Durable State Store & Manager
        self.store = SQLiteViewerStateStore(self.db_path)
        self.state_manager = StateManager(self.store, self.profile_store, self.catalogue_store)

        # 10. Latency Telemetry Engine
        self.latency_tracker = LatencyTracker(sla_threshold_ms=60000.0)

    def _get_viewer_state(self, user_id: str, event: Optional[AppEvent] = None) -> ViewerState:
        """Fetch viewer state from memory cache or initialize on demand."""
        if user_id in self.state_cache:
            return self.state_cache[user_id]
        assert self.state_manager is not None
        state = self.state_manager.get_or_create(user_id, event, save_to_store=False)
        self.state_cache[user_id] = state
        return state

    def prepopulate_history(self, events_path: Optional[Path] = None) -> int:
        """Pre-hydrate viewer histories from historical events stream."""
        if not self.prepopulate_historical:
            return 0

        target_path = events_path or (self.pack_dir / "data" / "events.jsonl")
        if not target_path.exists():
            return 0

        reader = EventStreamReader(filter_duplicates=True)
        count = 0
        assert self.state_manager is not None

        for event, is_dup in reader.stream(target_path):
            state = self._get_viewer_state(event.user_id, event)
            self.state_manager.apply_event(state, event, save_to_store=False)
            count += 1

        # Bulk save initial viewer states
        assert self.store is not None
        for state in self.state_cache.values():
            self.store.save(state)

        return count

    def run(self, max_triggers: Optional[int] = None) -> Dict[str, Any]:
        """Execute the full chronological replay day stream."""
        if self.pipeline is None:
            self.setup()

        if self.prepopulate_historical and len(self.state_cache) == 0:
            self.prepopulate_history()

        self.output_dir.mkdir(parents=True, exist_ok=True)
        decisions_path = self.output_dir / "decisions.jsonl"
        actions_path = self.output_dir / "actions.jsonl"
        latency_path = self.output_dir / "latency_report.json"

        triggers_path = self.pack_dir / "replay" / "triggers.jsonl"
        live_events_path = self.pack_dir / "replay" / "live_events.jsonl"
        control_events_path = self.pack_dir / "replay" / "control_events.jsonl"

        pump = ReplayEventPump(
            triggers_path=triggers_path,
            live_events_path=live_events_path if live_events_path.exists() else None,
            control_events_path=control_events_path if control_events_path.exists() else None,
        )

        total_triggers = 0
        total_live_events = 0
        total_control_events = 0
        total_decisions = 0
        published_actions = 0
        vetoed_decisions = 0

        with open(decisions_path, "w", encoding="utf-8") as dec_f, open(
            actions_path, "w", encoding="utf-8"
        ) as act_f:
            for item in pump.stream_merged():
                if item.item_type == "control_event":
                    # Collect currently open goals to allow mid-replay corrections
                    open_goals = [
                        s.active_goal
                        for s in self.state_cache.values()
                        if s.active_goal and s.active_goal.status == "OPEN"
                    ]
                    assert self.control_manager is not None
                    self.control_manager.handle(item.data, open_goals=open_goals)
                    total_control_events += 1

                elif item.item_type == "live_event":
                    live_event = AppEvent(**item.data)
                    state = self._get_viewer_state(live_event.user_id, live_event)
                    assert self.state_manager is not None
                    self.state_manager.apply_event(state, live_event, save_to_store=False)
                    total_live_events += 1

                elif item.item_type == "trigger":
                    trigger_event = AppEvent(**item.data)
                    state = self._get_viewer_state(trigger_event.user_id, trigger_event)

                    total_decisions += 1
                    total_triggers += 1

                    assert self.pipeline is not None
                    decision, action_payload = self.pipeline.process_trigger(
                        state=state,
                        trigger=trigger_event,
                        decision_counter=total_decisions,
                    )

                    assert self.latency_tracker is not None
                    self.latency_tracker.record(decision.decided_in_ms)

                    # Stream decision record
                    dec_f.write(json.dumps(decision.to_dict(), ensure_ascii=False) + "\n")

                    if action_payload:
                        published_actions += 1
                        act_f.write(json.dumps(action_payload, ensure_ascii=False) + "\n")

                        # Track messaging for real-time frequency capping
                        if action_payload.get("type") in ("push", "whatsapp"):
                            now = trigger_event.received_at
                            ist_day = now.astimezone(IST).strftime("%Y-%m-%d")
                            state.sent_messages.append({
                                "channel": action_payload["type"],
                                "action_id": action_payload["action_id"],
                                "delivered_at": action_payload["published_at"],
                                "ist_day": ist_day,
                            })
                    else:
                        vetoed_decisions += 1

                    if max_triggers and total_triggers >= max_triggers:
                        break

        # Flush all modified viewer states to SQLite store
        assert self.store is not None
        for state in self.state_cache.values():
            self.store.save(state)

        # Export per-viewer JSON states
        exported_count = self.store.export_all_json(self.output_dir)

        # Save latency statistics
        assert self.latency_tracker is not None
        self.latency_tracker.save_json(latency_path)

        summary = {
            "total_items_processed": total_triggers + total_live_events + total_control_events,
            "triggers_processed": total_triggers,
            "live_events_processed": total_live_events,
            "control_events_processed": total_control_events,
            "decisions_published": total_decisions,
            "actions_published": published_actions,
            "vetoed_decisions": vetoed_decisions,
            "viewer_states_exported": exported_count,
            "latency": self.latency_tracker.get_summary(),
        }

        return summary
