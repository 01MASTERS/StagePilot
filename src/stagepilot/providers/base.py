"""Abstract base classes and response models for model providers."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ModelResponse(BaseModel):
    """Normalized response from a model provider invocation."""
    content: str
    model_name: str
    provider_name: str
    latency_ms: int = 0
    call_count: int = 1
    error: Optional[str] = None
    is_fallback: bool = False
    raw_payload: Optional[Dict[str, Any]] = None


class ModelProvider(ABC):
    """Abstract model provider interface."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        trigger_event_id: Optional[str] = None,
        user_id: Optional[str] = None,
        timeout_seconds: float = 10.0,
    ) -> ModelResponse:
        """Generate response given prompt and execution context."""
        pass

    @abstractmethod
    def list_available_models(self) -> List[str]:
        """Query and return names of available models."""
        pass
