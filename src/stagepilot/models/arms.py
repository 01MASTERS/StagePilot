"""Assignment arm models for replay and pilot analysis."""

from typing import Optional
from pydantic import BaseModel


class ViewerArm(BaseModel):
    """Represents a viewer's experiment arm assignment."""
    user_id: str
    arm: str  # 'agent' | 'holdout' | 'treatment'
    served: Optional[bool] = None

    @property
    def is_holdout(self) -> bool:
        """Returns True if user is assigned to holdout (must receive zero interventions)."""
        return self.arm.strip().lower() == "holdout"

    @property
    def is_agent_arm(self) -> bool:
        """Returns True if user is assigned to agent/treatment arm."""
        return self.arm.strip().lower() in ("agent", "treatment")
