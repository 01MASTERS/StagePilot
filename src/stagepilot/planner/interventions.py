"""Intervention planning: home page composition, message generation, and deliberate abstention."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from stagepilot.config import IST, UTC, parse_iso_timestamp
from stagepilot.ingest.catalogue import CatalogueStore
from stagepilot.models.events import AppEvent
from stagepilot.state.models import ActiveGoal, ViewerState


FORBIDDEN_PUSH_PHRASES = [
    "last chance",
    "hurry",
    "only today",
    "free forever",
    "guaranteed",
]


@dataclass
class ProposedIntervention:
    """An intervention proposed by the planner before independent verification."""
    action_type: str  # 'home_page' | 'push' | 'whatsapp' | 'in_app_message' | 'no_action'
    payload: Dict[str, Any]
    dialect: Optional[str] = None
    target_title_id: Optional[str] = None
    confidence: float = 0.80
    confidence_reason: str = ""
    evidence: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    no_action_reason: Optional[str] = None


class HomePageComposer:
    """Composes personalized home pages conforming to row, dialect, and slug uniqueness rules."""

    def __init__(self, catalogue_store: CatalogueStore) -> None:
        self.catalogue = catalogue_store

    def compose(
        self, state: ViewerState, dialect: str, at: datetime, goal: Optional[ActiveGoal] = None
    ) -> ProposedIntervention:
        """Compose a structured personalized home page."""
        available_titles = self.catalogue.get_available_titles_for_dialect(dialect, at)
        if not available_titles:
            return ProposedIntervention(
                action_type="no_action",
                payload={},
                dialect=dialect,
                confidence=0.50,
                confidence_reason="No available titles found for dialect",
                no_action_reason="no_titles_available_for_dialect",
            )

        used_slugs: Set[str] = set()
        hero_title_id: Optional[str] = None

        # 1. Select Hero Title (prefer goal target, top genre, or new release)
        hero_candidate = None
        if goal and goal.target_content_slug:
            slug_titles = self.catalogue.get_titles_for_slug(goal.target_content_slug)
            for t in slug_titles:
                if t.dialect == dialect and t.is_available_at(at):
                    hero_candidate = t
                    break

        if not hero_candidate:
            # Fallback to first available title
            hero_candidate = available_titles[0]

        hero_title_id = hero_candidate.title_id
        used_slugs.add(hero_candidate.content_slug)

        # 2. Build Rows (up to 6 rows, 3-10 titles each, unique slugs only)
        rows: List[Dict[str, Any]] = []

        # Row A: Next Episode / Series resume (if applicable)
        if goal and goal.target_content_slug and goal.target_content_slug in state.last_play_by_slug:
            slug_titles = [
                t for t in self.catalogue.get_titles_for_slug(goal.target_content_slug)
                if t.dialect == dialect and t.is_available_at(at)
            ]
            # Need at least 3 titles for a valid row; if single show, supplement with related show
            resume_tids = [t.title_id for t in slug_titles]
            for t in available_titles:
                if t.content_type in ("show", "micro_drama") and t.content_slug not in used_slugs:
                    resume_tids.append(t.title_id)
                    used_slugs.add(t.content_slug)
                if len(resume_tids) >= 5:
                    break
            if len(resume_tids) >= 3:
                rows.append({"row_type": "next_episode", "title_ids": resume_tids[:10]})

        # Row B: Popular in Dialect
        pop_tids = []
        for t in available_titles:
            if t.content_slug not in used_slugs:
                pop_tids.append(t.title_id)
                used_slugs.add(t.content_slug)
            if len(pop_tids) >= 8:
                break
        if len(pop_tids) >= 3:
            rows.append({"row_type": "popular_in_dialect", "title_ids": pop_tids})

        # Row C: New Releases
        new_rel_tids = []
        cutoff_30d = at - timedelta(days=30)
        for t in available_titles:
            if t.available_from >= cutoff_30d and t.content_slug not in used_slugs:
                new_rel_tids.append(t.title_id)
                used_slugs.add(t.content_slug)
            if len(new_rel_tids) >= 6:
                break
        if len(new_rel_tids) >= 3:
            rows.append({"row_type": "new_releases", "title_ids": new_rel_tids})

        # Row D: Top Genre (if viewer has genre affinity)
        top_genre = None
        if state.genre_plays:
            top_genre = max(state.genre_plays, key=state.genre_plays.get)
            genre_tids = []
            for t in available_titles:
                if top_genre in t.genres and t.content_slug not in used_slugs:
                    genre_tids.append(t.title_id)
                    used_slugs.add(t.content_slug)
                if len(genre_tids) >= 6:
                    break
            if len(genre_tids) >= 3:
                rows.append({"row_type": "genre", "title_ids": genre_tids})

        # If we have zero valid rows, drop to no_action
        if not rows:
            return ProposedIntervention(
                action_type="no_action",
                payload={},
                dialect=dialect,
                confidence=0.40,
                confidence_reason="Fewer than 3 valid titles available for any row",
                no_action_reason="insufficient_row_titles",
            )

        payload = {
            "type": "home_page",
            "dialect": dialect,
            "hero_title_id": hero_title_id,
            "rows": rows[:6],
        }

        return ProposedIntervention(
            action_type="home_page",
            payload=payload,
            dialect=dialect,
            target_title_id=hero_title_id,
            confidence=0.85,
            confidence_reason="Personalized homepage aligned with active goal and dialect catalog.",
            evidence=[f"dialect:{dialect}", f"hero:{hero_title_id}", f"rows_count:{len(rows)}"],
            assumptions=["viewer will explore personalized layout during current live visit"],
        )


class PushCopyGenerator:
    """Generates push notification copy conforming to length limits and policy constraints."""

    def __init__(self, catalogue_store: CatalogueStore) -> None:
        self.catalogue = catalogue_store

    def generate(
        self, state: ViewerState, title_id: str, goal: Optional[ActiveGoal] = None
    ) -> ProposedIntervention:
        title_obj = self.catalogue.get_title(title_id)
        if not title_obj:
            return ProposedIntervention(
                action_type="no_action", payload={}, no_action_reason="push_title_not_found"
            )

        title_name = title_obj.title
        # Safe approved copy avoiding forbidden phrases
        if goal and goal.goal_id == "G04":
            title_text = "Aapka STAGE Trial"
            body_text = f"Trial ka aanand lijiye! Dekhiye {title_name} sirf ₹149/mahine mein."
        elif goal and goal.goal_id == "G07":
            title_text = "Episode Chhuta Toh Nahi?"
            body_text = f"{title_name} ka agla episode aapka intezar kar raha hai. Abhi dekhiye!"
        else:
            title_text = f"Nayi Kahani: {title_name}"[:40]
            body_text = f"Apni bhasha mein dekhiye {title_name}. Sirf STAGE par."[:120]

        # Enforce character bounds
        title_text = title_text[:40].strip()
        body_text = body_text[:120].strip()

        # Sanitize any forbidden phrases
        for phrase in FORBIDDEN_PUSH_PHRASES:
            if phrase in body_text.lower():
                body_text = body_text.replace(phrase, "aaj hi")

        payload = {
            "type": "push",
            "title_id": title_id,
            "text": {"title": title_text, "body": body_text},
            "deeplink": f"ott://title/{title_id}",
        }

        return ProposedIntervention(
            action_type="push",
            payload=payload,
            dialect=title_obj.dialect,
            target_title_id=title_id,
            confidence=0.75,
            confidence_reason="Push copy tailored to active lifecycle goal and opt-in status.",
            evidence=[f"title:{title_id}", f"notifications_opt_in:{state.profile.notifications_opt_in}"],
            assumptions=["viewer device token is active and delivers notification"],
        )


class WhatsAppTemplateSelector:
    """Selects and populates approved WhatsApp templates without free text."""

    def __init__(self, catalogue_store: CatalogueStore) -> None:
        self.catalogue = catalogue_store

    def generate(
        self, state: ViewerState, title_id: str, goal: Optional[ActiveGoal] = None
    ) -> ProposedIntervention:
        title_obj = self.catalogue.get_title(title_id)
        if not title_obj:
            return ProposedIntervention(
                action_type="no_action", payload={}, no_action_reason="whatsapp_title_not_found"
            )

        if goal and goal.goal_id == "G04":
            template_id = "wa_trial_ending_v1"
            variables = {"plan_price": "₹149"}
        elif goal and goal.goal_id == "G07":
            template_id = "wa_new_episode_v2"
            variables = {"title_name": title_obj.title, "episode_number": "2"}
        else:
            template_id = "wa_recommend_title_v1"
            dialect_names = {"d1": "Haryanvi", "d2": "Rajasthani", "d3": "Bhojpuri", "d4": "Maithili", "d5": "Gujarati", "d6": "Punjabi"}
            d_name = dialect_names.get(title_obj.dialect, title_obj.dialect)
            variables = {"title_name": title_obj.title, "dialect_name": d_name}

        payload = {
            "type": "whatsapp",
            "template_id": template_id,
            "title_id": title_id,
            "variables": variables,
        }

        return ProposedIntervention(
            action_type="whatsapp",
            payload=payload,
            dialect=title_obj.dialect,
            target_title_id=title_id,
            confidence=0.78,
            confidence_reason="Approved WhatsApp template populated from verified catalog variables.",
            evidence=[f"whatsapp_opt_in:{state.profile.whatsapp_opt_in}", f"template:{template_id}"],
            assumptions=["viewer reads WhatsApp messages during awake hours"],
        )


class InterventionPlanner:
    """Master intervention planner synthesizing channel selection, proposals, and abstention."""

    def __init__(self, catalogue_store: CatalogueStore) -> None:
        self.catalogue = catalogue_store
        self.home_composer = HomePageComposer(catalogue_store)
        self.push_generator = PushCopyGenerator(catalogue_store)
        self.wa_selector = WhatsAppTemplateSelector(catalogue_store)

    def plan_intervention(
        self,
        state: ViewerState,
        trigger: AppEvent,
        goal: Optional[ActiveGoal] = None,
        force_action_type: Optional[str] = None,
    ) -> ProposedIntervention:
        """Propose an action or decide to deliberately abstain."""
        # 1. Deliberate Abstention Gate: Stale Offline Trigger
        if trigger.is_stale_buffer:
            return ProposedIntervention(
                action_type="no_action",
                payload={},
                confidence=0.95,
                confidence_reason=f"Trigger was buffered offline for {trigger.buffer_delay_seconds:.1f}s (> 600s); viewer is not live.",
                evidence=[f"buffer_delay_s:{trigger.buffer_delay_seconds:.1f}"],
                assumptions=["delivering homepage to absent viewer is ineffective"],
                no_action_reason="stale_offline_trigger",
            )

        # 2. Determine Action Type
        action_type = force_action_type or "home_page"

        # Resolve active dialect: app_dialect takes precedence
        dialect = trigger.app_dialect or state.profile.preferred_dialect or "d1"

        if action_type == "home_page":
            return self.home_composer.compose(state, dialect, trigger.received_at, goal)

        target_title = None
        if goal and goal.target_content_slug:
            slug_titles = self.catalogue.get_titles_for_slug(goal.target_content_slug)
            for t in slug_titles:
                if t.dialect == dialect and t.is_available_at(trigger.received_at):
                    target_title = t.title_id
                    break
        if not target_title:
            avail = self.catalogue.get_available_titles_for_dialect(dialect, trigger.received_at)
            if avail:
                target_title = avail[0].title_id

        if not target_title:
            return ProposedIntervention(
                action_type="no_action", payload={}, no_action_reason="no_titles_available"
            )

        if action_type == "push":
            return self.push_generator.generate(state, target_title, goal)
        elif action_type == "whatsapp":
            return self.wa_selector.generate(state, target_title, goal)

        return ProposedIntervention(action_type="no_action", payload={}, no_action_reason="unknown_action_type")
