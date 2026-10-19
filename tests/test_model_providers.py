"""Unit tests for model providers, fault reproduction, and dynamic model discovery."""

from pathlib import Path
import pytest

from stagepilot.config import PathConfig, AppConfig
from stagepilot.providers.base import ModelResponse
from stagepilot.providers.mock_provider import MockReplayModelProvider
from stagepilot.providers.selector import discover_available_providers, resolve_provider


class TestModelProviders:
    """Verifies that model providers handle normal generation, dynamic discovery, and all scripted evaluation faults."""

    @pytest.fixture
    def mock_provider(self, path_config: PathConfig) -> MockReplayModelProvider:
        return MockReplayModelProvider(model_faults_path=path_config.replay_model_faults_path)

    def test_mock_provider_normal_generation(self, mock_provider: MockReplayModelProvider):
        """Verify normal trigger produces fast, valid JSON reasoning."""
        resp = mock_provider.generate(
            prompt="Evaluate viewer U-100",
            trigger_event_id="NORMAL-TRIGGER-ID",
            user_id="U-100",
        )
        assert resp.error is None
        assert resp.is_fallback is False
        assert "confidence" in resp.content
        assert resp.latency_ms >= 0

    def test_reproduce_unsupported_claim_fault(self, mock_provider: MockReplayModelProvider):
        """Verify model reproduces unsupported billing claim on U-01991."""
        resp = mock_provider.generate(
            prompt="Evaluate viewer U-01991",
            trigger_event_id="202cccb8-8127-465f-b2d0-038cf533197e",
            user_id="U-01991",
        )
        assert resp.error is None
        assert "G04" in resp.content
        assert "confirmed in billing" in resp.content

    def test_reproduce_malformed_output_fault(self, mock_provider: MockReplayModelProvider):
        """Verify model reproduces malformed JSON output on U-02563."""
        resp = mock_provider.generate(
            prompt="Evaluate viewer U-02563",
            trigger_event_id="76b138f6-0952-456d-904a-bd0d04497cf7",
            user_id="U-02563",
        )
        # Should return the truncated syntax
        assert '{"goal_id": "G02", "eligible": tr' in resp.content

    def test_reproduce_timeout_fault(self, mock_provider: MockReplayModelProvider):
        """Verify model enforces timeout bounds on 45s fault (U-01090)."""
        resp = mock_provider.generate(
            prompt="Evaluate viewer U-01090",
            trigger_event_id="5edb5b00-0773-4063-8da8-40929553233c",
            user_id="U-01090",
            timeout_seconds=5.0,  # 5s timeout vs 45s fault
        )
        assert resp.is_fallback is True
        assert resp.error is not None
        assert "TimeoutError" in resp.error

    def test_provider_discovery_and_resolution(self, app_config: AppConfig):
        """Verify discover_available_providers returns available models and selector falls back to mock."""
        discovered = discover_available_providers(app_config)
        assert "mock" in discovered
        assert len(discovered["mock"]) > 0

        # Resolving default
        provider = resolve_provider(app_config=app_config)
        assert provider.provider_name == "mock"
