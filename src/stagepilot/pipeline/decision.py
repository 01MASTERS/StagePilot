"""Unified decision pipeline executing the decide, act, and verify loop."""

import json
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from stagepilot.config import to_iso_timestamp
from stagepilot.models.events import AppEvent
from stagepilot.planner.goals import GoalPlanner
from stagepilot.planner.interventions import InterventionPlanner, ProposedIntervention
from stagepilot.providers.base import ModelProvider, ModelResponse
from stagepilot.state.models import ActiveGoal, DecisionRecord, ViewerState
from stagepilot.verifier.firewall import IndependentSafetyVerifier, VerificationOutcome


class DecisionPipeline:
    """Orchestrates viewer context, goal planning, model invocation, and independent safety verification."""

    def __init__(
        self,
        goal_planner: GoalPlanner,
        intervention_planner: InterventionPlanner,
        model_provider: ModelProvider,
        verifier: IndependentSafetyVerifier,
        control_manager: Optional[Any] = None,
    ) -> None:
        self.goal_planner = goal_planner
        self.intervention_planner = intervention_planner
        self.model_provider = model_provider
        self.verifier = verifier
        self.control_manager = control_manager

    def process_trigger(
        self,
        state: ViewerState,
        trigger: AppEvent,
        decision_counter: int = 1,
    ) -> Tuple[DecisionRecord, Optional[Dict[str, Any]]]:
        """Execute the end-to-end decision loop for a single viewer trigger event."""
        start_t = time.perf_counter()
        now = trigger.received_at
        decision_id = f"D-{decision_counter:04d}"

        # 1. Dialect Provenance & Conflict Resolution
        app_d = trigger.app_dialect
        prof_d = state.profile.preferred_dialect
        camp_d = trigger.campaign_dialect

        used_dialect = app_d or prof_d or "d1"
        source = "app_setting" if app_d else ("profile" if prof_d else "default")

        conflicts = []
        if prof_d and prof_d != used_dialect:
            conflicts.append(f"profile:{prof_d}")
        if camp_d and camp_d != used_dialect:
            conflicts.append(f"campaign_deeplink:{camp_d}")

        dialect_obj = {
            "used": used_dialect,
            "source": source,
            "conflicts": conflicts,
        }

        # 2. Goal Planning
        goal, goal_reason, goal_evidence, goal_assumptions = self.goal_planner.pick_or_maintain_goal(
            state, now
        )

        # 3. Model Invocation with Safety Bounds & Fallbacks
        model_prompt = (
            f"Viewer: {state.user_id}, Dialect: {used_dialect}, "
            f"Status: {state.profile.subscription_status}, Goal: {goal.name if goal else 'None'}"
        )
        if self.control_manager and self.control_manager.is_dependency_unavailable("model_provider", now):
            model_resp = ModelResponse(
                content="",
                model_name=getattr(self.model_provider, "model_name", "model_provider"),
                provider_name=getattr(self.model_provider, "provider_name", "mock"),
                latency_ms=10,
                error="HTTP 503 Service Unavailable: simulated outage window",
                is_fallback=True,
            )
        else:
            model_resp = self.model_provider.generate(
                prompt=model_prompt,
                trigger_event_id=trigger.event_id,
                user_id=state.user_id,
                timeout_seconds=10.0,
            )

        model_claims = {}
        if not model_resp.error and model_resp.content:
            try:
                model_claims = json.loads(model_resp.content)
            except Exception:
                # Catch malformed JSON fault gracefully
                model_resp.is_fallback = True
                model_claims = {"error": "malformed_json", "raw": model_resp.content}

        # 4. Propose Intervention
        proposed: ProposedIntervention = self.intervention_planner.plan_intervention(
            state=state,
            trigger=trigger,
            goal=goal,
        )

        # 5. Independent Air-Gapped Verification Firewall
        verification: VerificationOutcome = self.verifier.verify(
            proposed=proposed,
            state=state,
            trigger=trigger,
            model_claims=model_claims if isinstance(model_claims, dict) else None,
        )

        elapsed_ms = int((time.perf_counter() - start_t) * 1000)

        # Extract content references for decision audit log
        content_refs: List[str] = []
        if verification.sanitized_payload:
            hero_id = verification.sanitized_payload.get("hero_title_id")
            if hero_id:
                content_refs.append(f"title:{hero_id}")
            for row in verification.sanitized_payload.get("rows", []):
                for tid in row.get("title_ids", []):
                    ref = f"title:{tid}"
                    if ref not in content_refs:
                        content_refs.append(ref)
            msg_title = verification.sanitized_payload.get("title_id")
            if msg_title and f"title:{msg_title}" not in content_refs:
                content_refs.append(f"title:{msg_title}")

        decision_status = "PUBLISHED" if verification.approved and verification.final_action_type != "NO_ACTION" else "NO_ACTION"

        # 6. Assemble Section 4 Machine-Readable Decision Record
        decision = DecisionRecord(
            decision_id=decision_id,
            viewer_id=state.user_id,
            trigger={
                "event": trigger.event,
                "received_at": to_iso_timestamp(trigger.received_at),
                "event_age_s": int(trigger.buffer_delay_seconds),
            },
            goal={
                "id": goal.name if goal else "none",
                "deadline": to_iso_timestamp(goal.deadline) if goal else None,
            } if goal else None,
            action=verification.final_action_type,
            dialect=dialect_obj,
            content=content_refs[:10],
            confidence=proposed.confidence,
            confidence_reason=proposed.confidence_reason or goal_reason,
            evidence=goal_evidence + proposed.evidence,
            assumptions=goal_assumptions + proposed.assumptions,
            checks={
                "passed": verification.passed_checks,
                "failed": verification.failed_checks,
            },
            decided_in_ms=elapsed_ms,
            status=decision_status,
            no_action_reason=verification.veto_reason,
            fallback_used=model_resp.is_fallback,
            model_calls=model_resp.call_count,
            tool_calls=1,
            rule_version=goal.rule_version if goal else "2026-09-30",
        )

        # 7. Assemble Published Simulator Action Object (if approved)
        action_payload: Optional[Dict[str, Any]] = None
        if decision_status == "PUBLISHED":
            action_id = f"A-{decision_counter:04d}"
            # Published at deliver_at + measured decision time
            anchor_time = trigger.deliver_at or trigger.received_at
            published_at = anchor_time + timedelta(milliseconds=elapsed_ms)

            base_action = {
                "action_id": action_id,
                "decision_id": decision_id,
                "user_id": state.user_id,
                "trigger_event_id": trigger.event_id,
                "type": verification.sanitized_payload.get("type", verification.final_action_type.lower()),
                "published_at": to_iso_timestamp(published_at),
            }

            if base_action["type"] == "home_page":
                base_action["dialect"] = verification.sanitized_payload.get("dialect", used_dialect)
                base_action["hero_title_id"] = verification.sanitized_payload.get("hero_title_id")
                base_action["rows"] = verification.sanitized_payload.get("rows", [])
            elif base_action["type"] == "push":
                base_action["send_at"] = to_iso_timestamp(published_at)
                base_action["title_id"] = verification.sanitized_payload.get("title_id")
                base_action["text"] = verification.sanitized_payload.get("text", {})
                base_action["deeplink"] = verification.sanitized_payload.get("deeplink")
            elif base_action["type"] == "whatsapp":
                base_action["send_at"] = to_iso_timestamp(published_at)
                base_action["template_id"] = verification.sanitized_payload.get("template_id")
                base_action["variables"] = verification.sanitized_payload.get("variables", {})
                base_action["title_id"] = verification.sanitized_payload.get("title_id")

            action_payload = base_action

        return decision, action_payload
