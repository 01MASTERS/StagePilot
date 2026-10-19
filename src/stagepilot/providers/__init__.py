"""Pluggable model providers and auto-discovery."""

from stagepilot.providers.base import ModelProvider, ModelResponse
from stagepilot.providers.mock_provider import MockReplayModelProvider
from stagepilot.providers.gemini_provider import GeminiModelProvider
from stagepilot.providers.ollama_provider import OllamaModelProvider
from stagepilot.providers.selector import discover_available_providers, resolve_provider

__all__ = [
    "ModelProvider",
    "ModelResponse",
    "MockReplayModelProvider",
    "GeminiModelProvider",
    "OllamaModelProvider",
    "discover_available_providers",
    "resolve_provider",
]
