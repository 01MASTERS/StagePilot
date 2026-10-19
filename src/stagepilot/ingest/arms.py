"""Assignment arm loader for replay and pilot datasets."""

import csv
from pathlib import Path
from typing import Dict, Optional

from stagepilot.models.arms import ViewerArm


class ArmStore:
    """In-memory store of viewer experimental arm assignments."""

    def __init__(self) -> None:
        self.arms: Dict[str, ViewerArm] = {}

    @classmethod
    def load(cls, arms_path: Path) -> "ArmStore":
        """Load arms from CSV file (supports both replay/arms.csv and pilot_assignment.csv)."""
        store = cls()

        with open(arms_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                served_val = row.get("served")
                served = None
                if served_val is not None:
                    served = served_val.strip().lower() in ("true", "1", "yes")

                arm = ViewerArm(
                    user_id=row["user_id"],
                    arm=row["arm"].strip(),
                    served=served,
                )
                store.arms[arm.user_id] = arm

        return store

    def get(self, user_id: str) -> Optional[ViewerArm]:
        """Fetch assignment arm for viewer."""
        return self.arms.get(user_id)

    def is_holdout(self, user_id: str) -> bool:
        """Returns True if user is assigned to holdout (must receive zero actions)."""
        arm = self.arms.get(user_id)
        return arm.is_holdout if arm else False

    def is_agent_arm(self, user_id: str) -> bool:
        """Returns True if user is assigned to agent/treatment arm."""
        arm = self.arms.get(user_id)
        return arm.is_agent_arm if arm else False
