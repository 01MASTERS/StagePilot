"""State manager handling hydration, event application, and lifecycle transitions."""

from datetime import datetime
from typing import Dict, Iterator, Optional, Set
from stagepilot.config import IST, UTC
from stagepilot.ingest.catalogue import CatalogueStore
from stagepilot.ingest.profiles import ProfileStore
from stagepilot.models.events import AppEvent
from stagepilot.models.profiles import ViewerProfile
from stagepilot.state.models import ViewerFact, ViewerState
from stagepilot.state.store import SQLiteViewerStateStore


class StateManager:
    """Manages creation, hydration, and event-driven mutations of viewer state."""

    def __init__(
        self,
        store: SQLiteViewerStateStore,
        profile_store: ProfileStore,
        catalogue_store: CatalogueStore,
    ) -> None:
        self.store = store
        self.profile_store = profile_store
        self.catalogue_store = catalogue_store

    def get_or_create(
        self,
        user_id: str,
        trigger_event: Optional[AppEvent] = None,
        save_to_store: bool = True,
    ) -> ViewerState:
        """Fetch existing state from store or initialize a new one with baseline facts."""
        state = self.store.get(user_id)
        if state:
            return state

        profile = self.profile_store.get_or_synthesize(user_id, trigger_event)
        now_utc = trigger_event.received_at if trigger_event else datetime.now(UTC)

        state = ViewerState(
            user_id=user_id,
            profile=profile,
            updated_at=now_utc,
        )

        # Initialize core provenance facts
        if profile.signup_at:
            state.record_fact("signup_at", profile.signup_at.isoformat(), "profile", profile.signup_at)
        state.record_fact(
            "subscription_status",
            profile.subscription_status,
            "profile" if not profile.is_synthetic else "synthetic",
            now_utc,
        )
        if profile.preferred_dialect:
            state.record_fact(
                "preferred_dialect",
                profile.preferred_dialect,
                "profile" if not profile.is_synthetic else "synthetic",
                now_utc,
            )
        state.record_fact("notifications_opt_in", profile.notifications_opt_in, "profile", now_utc)
        state.record_fact("whatsapp_opt_in", profile.whatsapp_opt_in, "profile", now_utc)

        if save_to_store:
            self.store.save(state)
        return state

    def apply_event(
        self, state: ViewerState, event: AppEvent, save_to_store: bool = True
    ) -> ViewerState:
        """Apply an incoming event to viewer state adhering to strict idempotency."""
        # Idempotency barrier
        if state.is_processed(event.event_id):
            return state

        state.record_processed(event.event_id)
        ev_time = event.received_at
        if state.updated_at is None or ev_time > state.updated_at:
            state.updated_at = ev_time

        ev_name = event.event
        props = event.properties or {}

        # Dialect setting tracking
        if event.app_dialect:
            state.record_fact("app_dialect", event.app_dialect, "app_setting", ev_time)

        if ev_name == "signup_completed":
            state.profile.signup_at = ev_time
            state.record_fact("signup_at", ev_time.isoformat(), "events", ev_time)

        elif ev_name == "app_open":
            state.last_app_open_at = ev_time
            ist_day = ev_time.astimezone(IST).strftime("%Y-%m-%d")
            state.active_days_ist.add(ist_day)
            if event.campaign_dialect:
                state.record_fact(
                    "campaign_dialect", event.campaign_dialect, "campaign_deeplink", ev_time
                )

        elif ev_name == "app_dialect_changed":
            new_dialect = props.get("to") or event.app_dialect
            if new_dialect:
                state.profile.preferred_dialect = new_dialect
                state.record_fact("app_dialect", new_dialect, "app_setting", ev_time)

        elif ev_name == "play_started":
            state.total_plays += 1
            state.last_play_at = ev_time
            if event.session_id:
                state.play_sessions.add(event.session_id)
            ist_day = ev_time.astimezone(IST).strftime("%Y-%m-%d")
            state.active_days_ist.add(ist_day)

            title_id = props.get("title_id")
            if title_id:
                title = self.catalogue_store.get_title(title_id)
                if title:
                    state.last_play_by_slug[title.content_slug] = ev_time
                    for g in title.genres:
                        state.genre_plays[g] = state.genre_plays.get(g, 0) + 1

        elif ev_name == "episode_completed":
            state.total_completes += 1
            ep_id = props.get("episode_id")
            if ep_id:
                state.completed_episodes.add(ep_id)
            title_id = props.get("title_id")
            if title_id:
                title = self.catalogue_store.get_title(title_id)
                if title and ep_id:
                    state.slug_progress[title.content_slug] = ep_id

        elif ev_name == "purchase_completed":
            is_trial = props.get("is_trial", False)
            if isinstance(is_trial, str):
                is_trial = is_trial.lower() == "true"

            if is_trial:
                state.profile.subscription_status = "trial_active"
            else:
                state.profile.subscription_status = "active"

            state.record_fact(
                "subscription_status",
                state.profile.subscription_status,
                "events",
                ev_time,
            )

            # Check if active goal is trial_to_paid or first_paid and was satisfied
            if state.active_goal and state.active_goal.status == "OPEN" and not is_trial:
                if state.active_goal.goal_id in ("G04", "G05"):
                    state.active_goal.status = "SUCCEEDED"
                    state.active_goal.resolved_at = ev_time
                    state.active_goal.qualifying_event_ids.append(event.event_id)
                    state.completed_goals.append(state.active_goal)
                    state.active_goal = None

        elif ev_name == "subscription_renewed":
            state.profile.subscription_status = "active"
            state.record_fact("subscription_status", "active", "events", ev_time)

        elif ev_name == "subscription_lapsed":
            state.profile.subscription_status = "lapsed"
            state.record_fact("subscription_status", "lapsed", "events", ev_time)

        elif ev_name == "notification_opt_out":
            channel = props.get("channel")
            if channel == "push":
                state.profile.notifications_opt_in = False
                state.record_fact("notifications_opt_in", False, "events", ev_time)
            elif channel == "whatsapp":
                state.profile.whatsapp_opt_in = False
                state.record_fact("whatsapp_opt_in", False, "events", ev_time)

        elif ev_name == "message_delivered":
            ch = props.get("channel", "unknown")
            action_id = props.get("action_id", "")
            ist_day = ev_time.astimezone(IST).strftime("%Y-%m-%d")
            state.sent_messages.append({
                "channel": ch,
                "action_id": action_id,
                "delivered_at": ev_time.isoformat(),
                "ist_day": ist_day,
            })

        if save_to_store:
            self.store.save(state)
        return state
