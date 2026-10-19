"""Streaming event reader with streaming deduplication and anomaly tracking."""

import json
from pathlib import Path
from typing import Dict, Iterator, Optional, Set, Tuple

from stagepilot.models.events import AppEvent


class EventStreamReader:
    """Streaming reader for JSONL event streams with in-memory deduplication."""

    def __init__(self, filter_duplicates: bool = True) -> None:
        self.filter_duplicates = filter_duplicates
        self.seen_event_ids: Set[str] = set()
        self.total_lines: int = 0
        self.unique_events: int = 0
        self.duplicate_events: int = 0
        self.clock_skews_gt_1h: int = 0
        self.max_clock_skew_s: float = 0.0
        self.stale_buffered_events: int = 0

    def reset(self) -> None:
        """Reset deduplication cache and statistics."""
        self.seen_event_ids.clear()
        self.total_lines = 0
        self.unique_events = 0
        self.duplicate_events = 0
        self.clock_skews_gt_1h = 0
        self.max_clock_skew_s = 0.0
        self.stale_buffered_events = 0

    def stream(self, file_path: Path) -> Iterator[Tuple[AppEvent, bool]]:
        """Stream events from a JSONL file.
        
        Yields:
            (event: AppEvent, is_duplicate: bool)
        """
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue

                self.total_lines += 1
                raw = json.loads(line_str)
                event = AppEvent(**raw)

                # Anomaly tracking
                skew = event.clock_skew_seconds
                if skew > 3600.0:
                    self.clock_skews_gt_1h += 1
                if skew > self.max_clock_skew_s:
                    self.max_clock_skew_s = skew

                if event.is_stale_buffer:
                    self.stale_buffered_events += 1

                # Deduplication check
                is_duplicate = event.event_id in self.seen_event_ids
                if is_duplicate:
                    self.duplicate_events += 1
                else:
                    self.seen_event_ids.add(event.event_id)
                    self.unique_events += 1

                if self.filter_duplicates and is_duplicate:
                    continue

                yield event, is_duplicate

    def get_stats(self) -> Dict[str, float]:
        """Return summary of streaming ingestion statistics."""
        return {
            "total_lines": self.total_lines,
            "unique_events": self.unique_events,
            "duplicate_events": self.duplicate_events,
            "clock_skews_gt_1h": self.clock_skews_gt_1h,
            "max_clock_skew_hours": round(self.max_clock_skew_s / 3600.0, 2),
            "stale_buffered_events": self.stale_buffered_events,
        }
