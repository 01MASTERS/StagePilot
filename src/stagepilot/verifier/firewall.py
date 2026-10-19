"""Air-gapped independent safety firewall verifying all decisions and actions before publication."""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from stagepilot.config import IST, UTC, parse_iso_timestamp
from stagepilot.ingest.arms import ArmStore
from stagepilot.ingest.catalogue import CatalogueStore
from stagepilot.models.events import AppEvent
from stagepilot.planner.interventions import FORBIDDEN_PUSH_PHRASES, ProposedIntervention
from stagepilot.state.models import ViewerState


@dataclass
class VerificationOutcome:
    """Outcome of running the independent verification firewall."""
    approved: bool
    final_action_type: str  # 'HOME_PAGE' | 'PUSH' | 'WHATSAPP' | 'IN_APP_MESSAGE' | 'NO_ACTION'
    sanitized_payload: Dict[str, Any]
    passed_checks: List[str] = field(default_factory=list)
    failed_checks: List[str] = field(default_factory=list)
    veto_reason: Optional[str] = None
    quarantined_claims: List[str] = field(default_factory=list)


class IndependentSafetyVerifier:
    """Air-gapped independent firewall with unilateral veto power over planner and model outputs."""

    def __init__(self, catalogue_store: CatalogueStore, arm_store: Optional[ArmStore] = None) -> None:
        self.catalogue = catalogue_store
        self.arm_store = arm_store
        self.allowed_prices = {"1", "₹1", "149", "₹149", "399", "₹399"}

    def is_quiet_hours_ist(self, dt: datetime) -> bool:
        """Quiet hours: 22:00 to 08:00 IST."""
        ist_hour = dt.astimezone(IST).hour
        return ist_hour >= 22 or ist_hour < 8

    def verify(
        self,
        proposed: ProposedIntervention,
        state: ViewerState,
        trigger: AppEvent,
        model_claims: Optional[Dict[str, Any]] = None,
    ) -> VerificationOutcome:
        """Run all independent verification gates."""
        passed: List[str] = []
        failed: List[str] = []
        quarantined: List[str] = []
        now = trigger.received_at

        # --- GATE 1: Holdout Arm Protection (Non-negotiable) ---
        if self.arm_store and self.arm_store.is_holdout(state.user_id):
            failed.append("holdout_protection")
            return VerificationOutcome(
                approved=False,
                final_action_type="NO_ACTION",
                sanitized_payload={},
                passed_checks=passed,
                failed_checks=failed,
                veto_reason="holdout_arm_assigned",
            )
        passed.append("holdout_protection")

        # --- GATE 2: Model Evidence Verification ---
        if model_claims:
            # Check for hallucinated billing / active trial claim (model fault reproduction)
            claimed_reason = str(model_claims.get("reason", "")).lower()
            if "confirmed in billing" in claimed_reason or "trial that ends tomorrow" in claimed_reason:
                if state.profile.subscription_status != "trial_active":
                    failed.append("model_evidence_unsupported")
                    quarantined.append(f"hallucinated_billing_claim: {claimed_reason}")
                else:
                    passed.append("model_evidence_verified")

        # --- GATE 3: If planner already proposed no_action, approve abstention ---
        if proposed.action_type == "no_action":
            passed.append("planner_abstention_acknowledged")
            return VerificationOutcome(
                approved=True,
                final_action_type="NO_ACTION",
                sanitized_payload={},
                passed_checks=passed,
                failed_checks=failed,
                veto_reason=proposed.no_action_reason or "deliberate_abstention",
                quarantined_claims=quarantined,
            )

        # --- GATE 4: Stale Offline Trigger Gate ---
        if trigger.is_stale_buffer:
            failed.append("stale_offline_trigger")
            return VerificationOutcome(
                approved=False,
                final_action_type="NO_ACTION",
                sanitized_payload={},
                passed_checks=passed,
                failed_checks=failed,
                veto_reason="stale_offline_trigger",
                quarantined_claims=quarantined,
            )
        passed.append("fresh_trigger")

        action_type = proposed.action_type

        # --- CHANNEL VERIFICATIONS: PUSH & WHATSAPP ---
        if action_type in ("push", "whatsapp"):
            # 5a. Consent Gate
            if action_type == "push" and not state.profile.notifications_opt_in:
                failed.append("push_consent")
                return VerificationOutcome(
                    approved=False,
                    final_action_type="NO_ACTION",
                    sanitized_payload={},
                    passed_checks=passed,
                    failed_checks=failed,
                    veto_reason="push_missing_consent",
                    quarantined_claims=quarantined,
                )
            elif action_type == "whatsapp" and not state.profile.whatsapp_opt_in:
                failed.append("whatsapp_consent")
                return VerificationOutcome(
                    approved=False,
                    final_action_type="NO_ACTION",
                    sanitized_payload={},
                    passed_checks=passed,
                    failed_checks=failed,
                    veto_reason="whatsapp_missing_consent",
                    quarantined_claims=quarantined,
                )
            passed.append(f"{action_type}_consent")

            # 5b. Quiet Hours Gate
            if self.is_quiet_hours_ist(now):
                failed.append("quiet_hours_restriction")
                return VerificationOutcome(
                    approved=False,
                    final_action_type="NO_ACTION",
                    sanitized_payload={},
                    passed_checks=passed,
                    failed_checks=failed,
                    veto_reason=f"{action_type}_in_quiet_hours",
                    quarantined_claims=quarantined,
                )
            passed.append("quiet_hours_cleared")

            # 5c. Daily Frequency Cap Gate (max 1 message/IST day)
            if state.message_count_for_day_ist(now) >= 1:
                failed.append("frequency_cap_restriction")
                return VerificationOutcome(
                    approved=False,
                    final_action_type="NO_ACTION",
                    sanitized_payload={},
                    passed_checks=passed,
                    failed_checks=failed,
                    veto_reason="frequency_cap_exceeded",
                    quarantined_claims=quarantined,
                )
            passed.append("frequency_cap_cleared")

            # 5d. Content & Dialect Gate for Messaging
            title_id = proposed.target_title_id or proposed.payload.get("title_id")
            title_obj = self.catalogue.get_title(title_id) if title_id else None
            app_dialect = trigger.app_dialect or state.profile.preferred_dialect

            if not title_obj or not title_obj.is_available_at(now):
                failed.append("title_unavailable")
                return VerificationOutcome(
                    approved=False,
                    final_action_type="NO_ACTION",
                    sanitized_payload={},
                    passed_checks=passed,
                    failed_checks=failed,
                    veto_reason="message_title_unavailable",
                    quarantined_claims=quarantined,
                )

            if app_dialect and title_obj.dialect != app_dialect:
                failed.append("dialect_mismatch")
                return VerificationOutcome(
                    approved=False,
                    final_action_type="NO_ACTION",
                    sanitized_payload={},
                    passed_checks=passed,
                    failed_checks=failed,
                    veto_reason="message_dialect_mismatch",
                    quarantined_claims=quarantined,
                )
            passed.append("dialect_and_availability")

            # 5e. Push Copy & Deeplink Validation
            if action_type == "push":
                text = proposed.payload.get("text", {})
                title_txt = str(text.get("title", ""))
                body_txt = str(text.get("body", ""))
                if len(title_txt) > 40 or len(body_txt) > 120:
                    failed.append("push_length_limit")
                    return VerificationOutcome(
                        approved=False,
                        final_action_type="NO_ACTION",
                        sanitized_payload={},
                        passed_checks=passed,
                        failed_checks=failed,
                        veto_reason="push_character_limit_exceeded",
                        quarantined_claims=quarantined,
                    )
                for forbidden in FORBIDDEN_PUSH_PHRASES:
                    if forbidden in body_txt.lower() or forbidden in title_txt.lower():
                        failed.append("forbidden_phrase_detected")
                        return VerificationOutcome(
                            approved=False,
                            final_action_type="NO_ACTION",
                            sanitized_payload={},
                            passed_checks=passed,
                            failed_checks=failed,
                            veto_reason=f"forbidden_phrase:{forbidden}",
                            quarantined_claims=quarantined,
                        )
                passed.append("push_copy_policy")

            # 5f. WhatsApp Template Validation
            if action_type == "whatsapp":
                template_id = proposed.payload.get("template_id")
                if template_id not in ("wa_new_episode_v2", "wa_recommend_title_v1", "wa_trial_ending_v1"):
                    failed.append("unapproved_whatsapp_template")
                    return VerificationOutcome(
                        approved=False,
                        final_action_type="NO_ACTION",
                        sanitized_payload={},
                        passed_checks=passed,
                        failed_checks=failed,
                        veto_reason="unapproved_whatsapp_template",
                        quarantined_claims=quarantined,
                    )
                passed.append("whatsapp_template_approved")

            return VerificationOutcome(
                approved=True,
                final_action_type=action_type.upper(),
                sanitized_payload=proposed.payload,
                passed_checks=passed,
                failed_checks=failed,
                quarantined_claims=quarantined,
            )

        # --- CHANNEL VERIFICATIONS: HOME PAGE ---
        if action_type == "home_page":
            d = proposed.payload.get("dialect")
            hero_id = proposed.payload.get("hero_title_id")
            raw_rows = proposed.payload.get("rows", [])

            # Check hero validity
            hero = self.catalogue.get_title(hero_id) if hero_id else None
            hero_ok = bool(hero and hero.dialect == d and hero.is_available_at(now))
            if hero_id and not hero_ok:
                failed.append("hero_invalid")
                hero_id = None
            else:
                passed.append("hero_valid")

            # Check rows validity
            sanitized_rows = []
            seen_slugs: Set[str] = set()
            if hero_ok and hero:
                seen_slugs.add(hero.content_slug)

            for row in raw_rows[:6]:
                keep = []
                for tid in row.get("title_ids", [])[:10]:
                    t = self.catalogue.get_title(tid)
                    if not t or t.dialect != d or not t.is_available_at(now) or t.content_slug in seen_slugs:
                        continue
                    seen_slugs.add(t.content_slug)
                    keep.append(tid)

                # Row drop rule: fewer than 3 titles is dropped by platform
                if len(keep) >= 3:
                    sanitized_rows.append({"row_type": row.get("row_type"), "title_ids": keep})
                else:
                    failed.append("row_dropped_below_minimum")

            if not sanitized_rows and not hero_ok:
                failed.append("empty_home_page")
                return VerificationOutcome(
                    approved=False,
                    final_action_type="NO_ACTION",
                    sanitized_payload={},
                    passed_checks=passed,
                    failed_checks=failed,
                    veto_reason="home_page_rejected_empty",
                    quarantined_claims=quarantined,
                )

            passed.append("home_page_rows_valid")
            sanitized_payload = {
                "type": "home_page",
                "dialect": d,
                "hero_title_id": hero_id,
                "rows": sanitized_rows,
            }

            return VerificationOutcome(
                approved=True,
                final_action_type="HOME_PAGE",
                sanitized_payload=sanitized_payload,
                passed_checks=passed,
                failed_checks=failed,
                quarantined_claims=quarantined,
            )

        return VerificationOutcome(
            approved=False,
            final_action_type="NO_ACTION",
            sanitized_payload={},
            passed_checks=passed,
            failed_checks=failed,
            veto_reason="unrecognized_action_type",
            quarantined_claims=quarantined,
        )
