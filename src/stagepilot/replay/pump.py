"""Chronological event pump merging triggers, live events, and control interventions."""

import heapq
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from stagepilot.config import parse_iso_timestamp


@dataclass(order=True)
class ReplayItem:
    """An individual event or trigger in the chronological replay stream."""
    timestamp: datetime
    priority: int  # 0: control_event, 1: live_event, 2: trigger (ensures control/live apply before trigger)
    item_type: str  # 'control_event' | 'live_event' | 'trigger'
    data: Dict[str, Any]


class ReplayEventPump:
    """Chronologically merges triggers, live events, and control events for the replay day."""

    def __init__(
        self,
        triggers_path: Path,
        live_events_path: Optional[Path] = None,
        control_events_path: Optional[Path] = None,
    ) -> None:
        self.triggers_path = triggers_path
        self.live_events_path = live_events_path
        self.control_events_path = control_events_path

    def _stream_triggers(self) -> Iterator[ReplayItem]:
        if not self.triggers_path.exists():
            return
        with open(self.triggers_path, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if line_str:
                    item = json.loads(line_str)
                    ts = parse_iso_timestamp(item.get("deliver_at") or item.get("received_at"))
                    if ts:
                        yield ReplayItem(timestamp=ts, priority=2, item_type="trigger", data=item)

    def _stream_live_events(self) -> Iterator[ReplayItem]:
        if not self.live_events_path or not self.live_events_path.exists():
            return
        with open(self.live_events_path, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if line_str:
                    item = json.loads(line_str)
                    ts = parse_iso_timestamp(item.get("received_at"))
                    if ts:
                        yield ReplayItem(timestamp=ts, priority=1, item_type="live_event", data=item)

    def _stream_control_events(self) -> Iterator[ReplayItem]:
        if not self.control_events_path or not self.control_events_path.exists():
            return
        with open(self.control_events_path, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if line_str:
                    item = json.loads(line_str)
                    ts = parse_iso_timestamp(item.get("at"))
                    if ts:
                        yield ReplayItem(timestamp=ts, priority=0, item_type="control_event", data=item)

    def stream_merged(self) -> Iterator[ReplayItem]:
        """Stream all items merged in strict chronological order."""
        iterators = [
            self._stream_control_events(),
            self._stream_live_events(),
            self._stream_triggers(),
        ]
        for item in heapq.merge(*iterators):
            yield item
