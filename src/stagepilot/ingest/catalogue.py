"""Catalogue and episode data loader with prompt injection defenses."""

import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from stagepilot.models.catalogue import CatalogueTitle, Episode


class CatalogueStore:
    """In-memory catalogue store managing titles, episodes, and availability."""

    def __init__(self) -> None:
        self.titles: Dict[str, CatalogueTitle] = {}
        self.titles_by_slug: Dict[str, List[CatalogueTitle]] = defaultdict(list)
        self.episodes_by_slug: Dict[str, List[Episode]] = defaultdict(list)
        self.quarantined_titles: Dict[str, str] = {}  # title_id -> quarantined_instruction

    @classmethod
    def load(cls, catalogue_path: Path, episodes_path: Optional[Path] = None) -> "CatalogueStore":
        """Load titles and episodes from CSV files."""
        store = cls()

        with open(catalogue_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                title = CatalogueTitle.create_from_raw(row)
                store.titles[title.title_id] = title
                store.titles_by_slug[title.content_slug].append(title)
                if title.is_sanitized and title.quarantined_instruction:
                    store.quarantined_titles[title.title_id] = title.quarantined_instruction

        if episodes_path and episodes_path.exists():
            with open(episodes_path, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    episode = Episode(
                        episode_id=row["episode_id"],
                        content_slug=row["content_slug"],
                        season=row["season"],
                        episode=row["episode"],
                        minutes=row.get("minutes", 0.0),
                    )
                    store.episodes_by_slug[episode.content_slug].append(episode)

            # Sort episodes by (season, episode)
            for slug in store.episodes_by_slug:
                store.episodes_by_slug[slug].sort(key=lambda ep: (ep.season, ep.episode))

        return store

    def get_title(self, title_id: str) -> Optional[CatalogueTitle]:
        """Fetch title by ID."""
        return self.titles.get(title_id)

    def get_titles_for_slug(self, content_slug: str) -> List[CatalogueTitle]:
        """Fetch all language/dialect variants for a content slug."""
        return self.titles_by_slug.get(content_slug, [])

    def get_episodes_for_slug(self, content_slug: str) -> List[Episode]:
        """Fetch all episodes for a content slug, ordered by season and episode."""
        return self.episodes_by_slug.get(content_slug, [])

    def withdraw_title(self, title_id: str, at: datetime) -> bool:
        """Handle control event: title withdrawn (licence ended early).
        
        Clips the title's available_until to `at`.
        """
        title = self.titles.get(title_id)
        if not title:
            return False
        if title.available_until is None or at < title.available_until:
            title.available_until = at
            return True
        return False

    def is_available(self, title_id: str, at: datetime) -> bool:
        """Check if a title exists and is available at given UTC timestamp."""
        title = self.titles.get(title_id)
        if not title:
            return False
        return title.is_available_at(at)

    def get_available_titles_for_dialect(
        self, dialect: str, at: datetime, content_type: Optional[str] = None
    ) -> List[CatalogueTitle]:
        """Retrieve all available titles for a given dialect at timestamp."""
        results = []
        for title in self.titles.values():
            if title.dialect == dialect and title.is_available_at(at):
                if content_type is None or title.content_type == content_type:
                    results.append(title)
        return results

    def get_next_unwatched_episode(
        self, content_slug: str, completed_episode_ids: Set[str]
    ) -> Optional[Episode]:
        """Find the earliest episode in a show that has not been completed."""
        episodes = self.get_episodes_for_slug(content_slug)
        for ep in episodes:
            if ep.episode_id not in completed_episode_ids:
                return ep
        return None
