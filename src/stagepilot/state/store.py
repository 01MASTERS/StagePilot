"""Durable SQLite state store with atomic per-viewer JSON export."""

import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Union

from stagepilot.config import to_iso_timestamp, parse_iso_timestamp
from stagepilot.state.models import ViewerState


class SQLiteViewerStateStore:
    """High-performance SQLite store for durable per-viewer agent state."""

    def __init__(self, db_path: Union[str, Path] = ":memory:") -> None:
        self.db_path = str(db_path)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            if self.db_path != ":memory:":
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn = conn
        return self._conn

    def _init_db(self) -> None:
        conn = self._get_connection()
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS viewers (
                    user_id TEXT PRIMARY KEY,
                    subscription_status TEXT,
                    active_goal_id TEXT,
                    preferred_dialect TEXT,
                    total_plays INTEGER DEFAULT 0,
                    updated_at TEXT,
                    state_json TEXT
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_viewers_status ON viewers(subscription_status);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_viewers_goal ON viewers(active_goal_id);")

    def save(self, state: ViewerState) -> None:
        """Persist or update viewer state atomically."""
        conn = self._get_connection()
        state_dict = state.to_dict()
        state_json = json.dumps(state_dict, ensure_ascii=False)
        active_goal_id = state.active_goal.goal_id if state.active_goal else None

        with conn:
            conn.execute("""
                INSERT INTO viewers (
                    user_id, subscription_status, active_goal_id, preferred_dialect,
                    total_plays, updated_at, state_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    subscription_status=excluded.subscription_status,
                    active_goal_id=excluded.active_goal_id,
                    preferred_dialect=excluded.preferred_dialect,
                    total_plays=excluded.total_plays,
                    updated_at=excluded.updated_at,
                    state_json=excluded.state_json;
            """, (
                state.user_id,
                state.profile.subscription_status,
                active_goal_id,
                state.profile.preferred_dialect,
                state.total_plays,
                to_iso_timestamp(state.updated_at),
                state_json,
            ))

    def get(self, user_id: str) -> Optional[ViewerState]:
        """Retrieve viewer state by user_id."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT state_json FROM viewers WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if not row or not row[0]:
            return None

        data = json.loads(row[0])
        return ViewerState(**data)

    def exists(self, user_id: str) -> bool:
        """Check if viewer exists in store."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM viewers WHERE user_id = ?", (user_id,))
        return cursor.fetchone() is not None

    def count(self) -> int:
        """Return total count of stored viewers."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM viewers")
        row = cursor.fetchone()
        return row[0] if row else 0

    def get_all_user_ids(self) -> List[str]:
        """Return all stored user IDs."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM viewers")
        return [row[0] for row in cursor.fetchall()]

    def export_all_json(self, output_dir: Path) -> int:
        """Export each viewer's state to <output_dir>/viewer_state/<user_id>.json."""
        target_dir = output_dir / "viewer_state"
        target_dir.mkdir(parents=True, exist_ok=True)

        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, state_json FROM viewers")

        count = 0
        for uid, state_json in cursor.fetchall():
            file_path = target_dir / f"{uid}.json"
            # Format cleanly with indent for inspectability
            state_dict = json.loads(state_json)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(state_dict, f, indent=2, ensure_ascii=False)
            count += 1
        return count

    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
