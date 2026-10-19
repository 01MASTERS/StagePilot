"""Deterministic mock and replay model provider reproducing evaluation faults."""

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from stagepilot.providers.base import ModelProvider, ModelResponse


class MockReplayModelProvider(ModelProvider):
    """Deterministic mock provider that reproduces injected evaluation faults and simulates fast LLM inference."""

    def __init__(self, model_faults_path: Optional[Path] = None, model_name: str = "mock-stagepilot-v1") -> None:
        self.model_name = model_name
        self.provider_name = "mock"
        self.faults: Dict[str, Dict[str, Any]] = {}
        if model_faults_path and model_faults_path.exists():
            self._load_faults(model_faults_path)

    def _load_faults(self, path: Path) -> None:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if line_str:
                    item = json.loads(line_str)
                    trigger_id = item.get("trigger_event_id")
                    if trigger_id:
                        self.faults[trigger_id] = item

    def list_available_models(self) -> List[str]:
        return ["mock-stagepilot-v1", "mock-deterministic-fast"]

    def generate(
        self,
        prompt: str,
        trigger_event_id: Optional[str] = None,
        user_id: Optional[str] = None,
        timeout_seconds: float = 10.0,
    ) -> ModelResponse:
        start_t = time.perf_counter()

        # Check for scripted faults on this trigger
        if trigger_event_id and trigger_event_id in self.faults:
            fault_spec = self.faults[trigger_event_id]
            fault_type = fault_spec.get("fault")

            if fault_type == "timeout":
                sec = fault_spec.get("seconds", 45)
                # If configured timeout is lower than simulated fault, catch timeout
                elapsed_ms = int(min(sec, timeout_seconds) * 1000)
                if sec > timeout_seconds:
                    return ModelResponse(
                        content="",
                        model_name=self.model_name,
                        provider_name=self.provider_name,
                        latency_ms=elapsed_ms,
                        error=f"TimeoutError: Model execution exceeded timeout of {timeout_seconds}s (fault simulated {sec}s)",
                        is_fallback=True,
                    )

            elif fault_type == "malformed_output":
                elapsed_ms = int((time.perf_counter() - start_t) * 1000) + 15
                return ModelResponse(
                    content=fault_spec.get("model_output", "{malformed"),
                    model_name=self.model_name,
                    provider_name=self.provider_name,
                    latency_ms=elapsed_ms,
                    raw_payload=fault_spec,
                )

            elif fault_type == "unsupported_claim":
                elapsed_ms = int((time.perf_counter() - start_t) * 1000) + 20
                output_val = fault_spec.get("model_output", {})
                content_str = json.dumps(output_val) if isinstance(output_val, dict) else str(output_val)
                return ModelResponse(
                    content=content_str,
                    model_name=self.model_name,
                    provider_name=self.provider_name,
                    latency_ms=elapsed_ms,
                    raw_payload=fault_spec,
                )

        # Normal deterministic generation
        elapsed_ms = int((time.perf_counter() - start_t) * 1000) + 5
        standard_response = {
            "status": "success",
            "confidence": 0.82,
            "reason": "Viewer engagement pattern matches active lifecycle goal.",
            "recommended_action": "HOME_PAGE",
        }
        return ModelResponse(
            content=json.dumps(standard_response),
            model_name=self.model_name,
            provider_name=self.provider_name,
            latency_ms=elapsed_ms,
        )
