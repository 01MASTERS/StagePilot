"""Unit tests for intervention planning, homepage composition, push constraints, and abstention."""

from datetime import datetime, timedelta, timezone
import pytest

from stagepilot.ingest.catalogue import CatalogueStore
from stagepilot.models.events import AppEvent
from stagepilot.models.profiles import ViewerProfile
from stagepilot.planner.interventions import (
    FORBIDDEN_PUSH_PHRASES,
    HomePageComposer,
    InterventionPlanner,
    PushCopyGenerator,
    WhatsAppTemplateSelector,
)
from stagepilot.state.models import ViewerState

UTC = timezone.utc


class TestInterventionPlanner:
    """Verifies homepage constraints, push copy safety, and deliberate abstention."""

    @pytest.fixture
    def planner(self, catalogue_store: CatalogueStore) -> InterventionPlanner:
        return InterventionPlanner(catalogue_store)

    def test_homepage_slug_deduplication(self, planner: InterventionPlanner, catalogue_store: CatalogueStore):
        """Verify the same content_slug never appears more than once across the entire homepage."""
        now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
        profile = ViewerProfile(user_id="U-HOME-01", preferred_dialect="d1")
        state = ViewerState(user_id="U-HOME-01", profile=profile)

        trigger = AppEvent(
            event_id="TRIG-01",
            user_id="U-HOME-01",
            event="app_open",
            received_at=now,
            app_dialect="d1",
        )

        proposed = planner.plan_intervention(state, trigger)
        assert proposed.action_type == "home_page"
        payload = proposed.payload

        hero_id = payload.get("hero_title_id")
        rows = payload.get("rows", [])
        assert len(rows) > 0

        # Collect all slugs
        seen_slugs = set()
        if hero_id:
            hero_title = catalogue_store.get_title(hero_id)
            assert hero_title is not None
            seen_slugs.add(hero_title.content_slug)

        for row in rows:
            for tid in row["title_ids"]:
                t = catalogue_store.get_title(tid)
                assert t is not None
                assert t.content_slug not in seen_slugs, f"Duplicate content_slug {t.content_slug} found on homepage!"
                seen_slugs.add(t.content_slug)

    def test_push_copy_constraints_and_forbidden_phrases(
        self, planner: InterventionPlanner, catalogue_store: CatalogueStore
    ):
        """Verify push title <= 40 chars, body <= 120 chars, and no forbidden phrases."""
        profile = ViewerProfile(user_id="U-PUSH-01", notifications_opt_in=True)
        state = ViewerState(user_id="U-PUSH-01", profile=profile)

        avail_titles = catalogue_store.get_available_titles_for_dialect("d1", datetime(2026, 10, 1, tzinfo=UTC))
        assert len(avail_titles) > 0
        sample_tid = avail_titles[0].title_id

        proposed = planner.push_generator.generate(state, sample_tid)
        assert proposed.action_type == "push"
        text = proposed.payload.get("text", {})
        title_txt = text.get("title", "")
        body_txt = text.get("body", "")

        assert len(title_txt) <= 40
        assert len(body_txt) <= 120
        assert proposed.payload.get("deeplink") == f"ott://title/{sample_tid}"

        # Assert zero forbidden phrases
        for phrase in FORBIDDEN_PUSH_PHRASES:
            assert phrase not in body_txt.lower()
            assert phrase not in title_txt.lower()

    def test_whatsapp_approved_templates(
        self, planner: InterventionPlanner, catalogue_store: CatalogueStore
    ):
        """Verify WhatsApp generator uses only approved templates and verified variables."""
        profile = ViewerProfile(user_id="U-WA-01", whatsapp_opt_in=True)
        state = ViewerState(user_id="U-WA-01", profile=profile)

        avail_titles = catalogue_store.get_available_titles_for_dialect("d2", datetime(2026, 10, 1, tzinfo=UTC))
        sample_tid = avail_titles[0].title_id

        proposed = planner.wa_selector.generate(state, sample_tid)
        assert proposed.action_type == "whatsapp"
        assert proposed.payload.get("template_id") in (
            "wa_new_episode_v2", "wa_recommend_title_v1", "wa_trial_ending_v1"
        )
        assert "variables" in proposed.payload

    def test_abstention_on_stale_offline_trigger(self, planner: InterventionPlanner):
        """Verify stale offline-buffered triggers (> 600s) deliberately produce NO_ACTION."""
        now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
        profile = ViewerProfile(user_id="U-STALE-01")
        state = ViewerState(user_id="U-STALE-01", profile=profile)

        # Trigger occurred 2 hours before sent/received (stale offline buffer)
        stale_trigger = AppEvent(
            event_id="STALE-TRIG-01",
            user_id="U-STALE-01",
            event="app_open",
            occurred_at=now - timedelta(hours=2),
            sent_at=now,
            received_at=now,
        )

        assert stale_trigger.is_stale_buffer is True
        proposed = planner.plan_intervention(state, stale_trigger)
        assert proposed.action_type == "no_action"
        assert proposed.no_action_reason == "stale_offline_trigger"
