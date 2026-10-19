"""Local Ollama model provider with dynamic model discovery."""

import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from stagepilot.providers.base import ModelProvider, ModelResponse


class OllamaModelProvider(ModelProvider):
    """Local Ollama model provider communicating with the local Ollama daemon."""

    def __init__(self, base_url: str = "http://localhost:11434", model_name: str = "llama3") -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.provider_name = "ollama"

    def is_available(self) -> bool:
        """Check if local Ollama daemon is reachable."""
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags", headers={"User-Agent": "StagePilot/1.0"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                return resp.status == 200
        except Exception:
            return False

    def list_available_models(self) -> List[str]:
        """Fetch names of locally pulled models from Ollama."""
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags", headers={"User-Agent": "StagePilot/1.0"})
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
                return sorted(models)
        except Exception:
            return []

    def generate(
        self,
        prompt: str,
        trigger_event_id: Optional[str] = None,
        user_id: Optional[str] = None,
        timeout_seconds: float = 10.0,
    ) -> ModelResponse:
        start_t = time.perf_counter()
        if not self.is_available():
            return ModelResponse(
                content="",
                model_name=self.model_name,
                provider_name=self.provider_name,
                error=f"Local Ollama daemon at {self.base_url} is unreachable",
                is_fallback=True,
            )

        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
        }

        try:
            data_bytes = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data_bytes,
                headers={"Content-Type": "application/json", "User-Agent": "StagePilot/1.0"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                elapsed_ms = int((time.perf_counter() - start_t) * 1000)

                return ModelResponse(
                    content=result.get("response", ""),
                    model_name=self.model_name,
                    provider_name=self.provider_name,
                    latency_ms=elapsed_ms,
                    raw_payload=result,
                )

        except Exception as e:
            elapsed_ms = int((time.perf_counter() - start_t) * 1000)
            return ModelResponse(
                content="",
                model_name=self.model_name,
                provider_name=self.provider_name,
                latency_ms=elapsed_ms,
                error=f"Ollama generation error: {str(e)}",
                is_fallback=True,
            )
