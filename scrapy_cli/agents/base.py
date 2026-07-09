"""Single-shot LLM client — no tool calling.

Supports two backends:
- Anthropic (default): uses the official `anthropic` SDK.
- OpenAI-compatible: any endpoint exposing `/v1/chat/completions` (vLLM,
  Ollama, LM Studio, LiteLLM, on-prem Qwen/LLaMA, etc.).

The two share an `AgentResult` shape so callers don't care which backend ran.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from rich.console import Console

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 8192


@dataclass
class AgentResult:
    final_text: str
    usage: dict = field(default_factory=dict)
    stop_reason: str | None = None


class AnthropicAgentClient:
    """Plain single-shot Anthropic call (no tool_use)."""

    def __init__(
        self,
        *,
        name: str,
        system: str,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        console: Console | None = None,
        api_key: str | None = None,
    ) -> None:
        from anthropic import Anthropic  # local import keeps import cheap

        self.name = name
        self.system = system
        self.model = model
        self.max_tokens = max_tokens
        self.console = console or Console(legacy_windows=False)
        self.client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    def run(self, user_message: str) -> AgentResult:
        self.console.log(f"[bold cyan]\\[{self.name}][/bold cyan] calling Anthropic")
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=[{"type": "text", "text": self.system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_message}],
        )
        text_parts = [b.text for b in response.content if getattr(b, "type", "") == "text"]
        final_text = _strip_thinking("\n".join(text_parts).strip())

        usage: dict[str, int] = {}
        if response.usage:
            for k in (
                "input_tokens",
                "output_tokens",
                "cache_creation_input_tokens",
                "cache_read_input_tokens",
            ):
                usage[k] = getattr(response.usage, k, 0) or 0

        return AgentResult(
            final_text=final_text,
            usage=usage,
            stop_reason=response.stop_reason,
        )


class CustomAgentClient:
    """Plain single-shot call against an OpenAI-compatible /v1/chat/completions endpoint."""

    def __init__(
        self,
        *,
        name: str,
        system: str,
        model: str = "default",
        max_tokens: int = DEFAULT_MAX_TOKENS,
        console: Console | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "Install the 'openai' package to use a custom endpoint: pip install openai"
            ) from exc

        self.name = name
        self.system = system
        self.model = model
        self.max_tokens = max_tokens
        self.console = console or Console(legacy_windows=False)

        resolved_key = api_key or os.environ.get("CUSTOM_LLM_API_KEY") or "no-key"
        resolved_url = base_url or os.environ.get("CUSTOM_LLM_BASE_URL")
        self.client = OpenAI(api_key=resolved_key, base_url=resolved_url)

    def run(self, user_message: str) -> AgentResult:
        self.console.log(f"[bold cyan]\\[{self.name}][/bold cyan] calling {self.client.base_url}")
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[
                {"role": "system", "content": self.system},
                {"role": "user", "content": user_message},
            ],
        )
        choice = response.choices[0]
        final_text = _strip_thinking(choice.message.content or "")

        usage: dict[str, int] = {}
        if response.usage:
            usage["input_tokens"] = response.usage.prompt_tokens or 0
            usage["output_tokens"] = response.usage.completion_tokens or 0

        return AgentResult(
            final_text=final_text,
            usage=usage,
            stop_reason=choice.finish_reason,
        )


def make_agent(
    *,
    name: str,
    system: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    console: Console | None = None,
    api_key: str | None = None,
    api_base_url: str | None = None,
) -> "AnthropicAgentClient | CustomAgentClient":
    """Pick the backend based on whether a custom base URL was provided."""
    if api_base_url:
        return CustomAgentClient(
            name=name,
            system=system,
            model=model,
            max_tokens=max_tokens,
            console=console,
            api_key=api_key,
            base_url=api_base_url,
        )
    return AnthropicAgentClient(
        name=name,
        system=system,
        model=model,
        max_tokens=max_tokens,
        console=console,
        api_key=api_key,
    )


def _strip_thinking(text: str) -> str:
    """Strip <think>...</think> reasoning blocks (Qwen3, DeepSeek-R1, etc.)."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
