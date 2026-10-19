"""Viewer profile snapshot loader with deduplication and dynamic hydration."""

import csv
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from stagepilot.models.events import AppEvent
from stagepilot.models.profiles import ViewerProfile


class ProfileStore:
    """In-memory store of viewer profiles with conflict resolution and synthetic fallback."""

    def __init__(self) -> None:
        self.profiles: Dict[str, ViewerProfile] = {}
        self.duplicates_resolved: int = 0
        self.synthesized_count: int = 0

    @classmethod
    def load(cls, profiles_path: Path) -> "ProfileStore":
        """Load profiles_snapshot.csv, resolving duplicates by keeping latest updated_at."""
        store = cls()

        with open(profiles_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                profile = ViewerProfile(
                    user_id=row["user_id"],
                    signup_at=row.get("signup_at"),
                    subscription_status=row.get("subscription_status", "never"),
                    plan_started_at=row.get("plan_started_at") or None,
                    plan_ends_at=row.get("plan_ends_at") or None,
                    preferred_dialect=row.get("preferred_dialect"),
                    preferred_language=row.get("preferred_language"),
                    notifications_opt_in=row.get("notifications_opt_in", "false"),
                    whatsapp_opt_in=row.get("whatsapp_opt_in", "false"),
                    platform=row.get("platform"),
                    updated_at=row.get("updated_at"),
                    snapshot_at=row.get("snapshot_at"),
                    is_synthetic=False,
                )

                existing = store.profiles.get(profile.user_id)
                if existing is None:
                    store.profiles[profile.user_id] = profile
                else:
                    store.duplicates_resolved += 1
                    # Conflict resolution rule: row with latest updated_at wins
                    if profile.updated_at and existing.updated_at:
                        if profile.updated_at > existing.updated_at:
                            store.profiles[profile.user_id] = profile
                    elif profile.updated_at and not existing.updated_at:
                        store.profiles[profile.user_id] = profile

        return store

    def get(self, user_id: str) -> Optional[ViewerProfile]:
        """Fetch profile by user_id if present."""
        return self.profiles.get(user_id)

    def get_or_synthesize(
        self, user_id: str, trigger_event: Optional[AppEvent] = None
    ) -> ViewerProfile:
        """Fetch profile or dynamically synthesize one from trigger event if missing."""
        existing = self.profiles.get(user_id)
        if existing:
            return existing

        # Synthesize profile from trigger event
        signup_at = trigger_event.received_at if trigger_event else None
        dialect = trigger_event.app_dialect if trigger_event else None
        language = trigger_event.app_language if trigger_event else None
        platform = trigger_event.platform if trigger_event else None

        synthetic = ViewerProfile.create_synthetic(
            user_id=user_id,
            signup_at=signup_at,
            dialect=dialect,
            language=language,
            platform=platform,
            updated_at=signup_at,
        )
        self.profiles[user_id] = synthetic
        self.synthesized_count += 1
        return synthetic
