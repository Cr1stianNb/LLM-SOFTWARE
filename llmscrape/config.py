"""Runtime configuration.

The LLM connection is configured through three values, read from the
environment (or overridden by CLI flags) and *never* hardcoded:

    LLM_BASE_URL   OpenAI-compatible endpoint (local vLLM/Ollama/LM Studio or
                   a remote provider). Default: http://localhost:8000/v1
    LLM_API_KEY    API key, read from the environment only. Never committed.
    LLM_MODEL      Qwen3 model id. Default: qwen3-32b

The api key is intentionally optional for local servers that do not require it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

DEFAULT_BASE_URL = "http://localhost:8000/v1"
DEFAULT_MODEL = "qwen3-32b"


@dataclass
class LLMConfig:
    base_url: str = DEFAULT_BASE_URL
    api_key: Optional[str] = None
    model: str = DEFAULT_MODEL
    # "live" hits the endpoint; "replay" reads a recorded cassette; "record"
    # does both. The bundled example uses "replay" so it runs with no model.
    mode: str = "live"
    cassette: Optional[str] = None
    timeout: float = 120.0
    temperature: float = 0.0

    @classmethod
    def from_env(cls) -> "LLMConfig":
        return cls(
            base_url=os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL),
            api_key=os.environ.get("LLM_API_KEY"),
            model=os.environ.get("LLM_MODEL", DEFAULT_MODEL),
            mode=os.environ.get("LLM_MODE", "live"),
        )
