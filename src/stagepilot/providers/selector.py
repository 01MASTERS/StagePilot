"""Provider selector and dynamic model resolution."""

from typing import Dict, List, Optional

from stagepilot.config import AppConfig
from stagepilot.providers.base import ModelProvider
from stagepilot.providers.gemini_provider import GeminiModelProvider
from stagepilot.providers.mock_provider import MockReplayModelProvider
from stagepilot.providers.ollama_provider import OllamaModelProvider


def discover_available_providers(app_config: Optional[AppConfig] = None) -> Dict[str, List[str]]:
    """Discover all reachable providers and their accessible models."""
    cfg = app_config or AppConfig()
    result: Dict[str, List[str]] = {}

    # Mock is always available
    mock = MockReplayModelProvider(cfg.paths.replay_model_faults_path)
    result["mock"] = mock.list_available_models()

    # Gemini
    gemini = GeminiModelProvider()
    if gemini.is_configured():
        models = gemini.list_available_models()
        if models:
            result["gemini"] = models

    # Ollama
    ollama = OllamaModelProvider(base_url=cfg.ollama_base_url)
    if ollama.is_available():
        models = ollama.list_available_models()
        if models:
            result["ollama"] = models

    return result


def resolve_provider(
    provider_name: Optional[str] = None,
    model_name: Optional[str] = None,
    app_config: Optional[AppConfig] = None,
) -> ModelProvider:
    """Resolve and instantiate the requested model provider with automatic fallback."""
    cfg = app_config or AppConfig()
    name = (provider_name or cfg.default_provider).lower().strip()

    if name == "gemini":
        gemini = GeminiModelProvider(model_name=model_name or cfg.gemini_model)
        if gemini.is_configured():
            return gemini

    elif name == "ollama":
        ollama = OllamaModelProvider(base_url=cfg.ollama_base_url, model_name=model_name or cfg.ollama_model)
        if ollama.is_available():
            return ollama

    # Default fallback: MockReplayModelProvider (guarantees 100% reproducible test suite and evaluation)
    return MockReplayModelProvider(
        model_faults_path=cfg.paths.replay_model_faults_path,
        model_name=model_name or "mock-stagepilot-v1",
    )
