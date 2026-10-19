"""Google Gemini API provider with automated model discovery."""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from stagepilot.providers.base import ModelProvider, ModelResponse


class GeminiModelProvider(ModelProvider):
    """Google Gemini model provider with auto-discovery and timeout controls."""

    def __init__(self, api_key: Optional[str] = None, model_name: str = "gemini-1.5-flash") -> None:
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
        self.model_name = model_name
        self.provider_name = "gemini"
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"

    def is_configured(self) -> bool:
        """Return True if an API key is available."""
        return bool(self.api_key.strip())

    def list_available_models(self) -> List[str]:
        """Fetch models supporting generateContent from Gemini API."""
        if not self.is_configured():
            return []

        url = f"{self.base_url}/models?key={self.api_key}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "StagePilot/1.0"})
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = []
                for m in data.get("models", []):
                    methods = m.get("supportedGenerationMethods", [])
                    if "generateContent" in methods:
                        # Strip "models/" prefix
                        name = m.get("name", "").replace("models/", "")
                        if "gemini" in name:
                            models.append(name)
                return sorted(models)
        except Exception:
            return ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash"]

    def generate(
        self,
        prompt: str,
        trigger_event_id: Optional[str] = None,
        user_id: Optional[str] = None,
        timeout_seconds: float = 10.0,
    ) -> ModelResponse:
        start_t = time.perf_counter()
        if not self.is_configured():
            return ModelResponse(
                content="",
                model_name=self.model_name,
                provider_name=self.provider_name,
                error="GEMINI_API_KEY is not configured",
                is_fallback=True,
            )

        url = f"{self.base_url}/models/{self.model_name}:generateContent?key={self.api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1024},
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

                candidates = result.get("candidates", [])
                text_content = ""
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    text_content = "".join(p.get("text", "") for p in parts)

                return ModelResponse(
                    content=text_content,
                    model_name=self.model_name,
                    provider_name=self.provider_name,
                    latency_ms=elapsed_ms,
                    raw_payload=result,
                )

        except urllib.error.HTTPError as e:
            elapsed_ms = int((time.perf_counter() - start_t) * 1000)
            return ModelResponse(
                content="",
                model_name=self.model_name,
                provider_name=self.provider_name,
                latency_ms=elapsed_ms,
                error=f"Gemini API HTTP {e.code}: {e.reason}",
                is_fallback=True,
            )
        except Exception as e:
            elapsed_ms = int((time.perf_counter() - start_t) * 1000)
            return ModelResponse(
                content="",
                model_name=self.model_name,
                provider_name=self.provider_name,
                latency_ms=elapsed_ms,
                error=f"Gemini invocation error: {str(e)}",
                is_fallback=True,
            )
