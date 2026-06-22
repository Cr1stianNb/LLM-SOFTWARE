"""Shared agent loops with tool use — Anthropic and OpenAI-compatible backends."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from anthropic import Anthropic
from rich.console import Console

ToolDispatcher = Callable[[str, dict], dict]

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_MAX_ITERATIONS = 20


@dataclass
class AgentResult:
    final_text: str
    messages: list[dict]
    tool_calls: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    stop_reason: str | None = None
    iterations: int = 0


class AgentClient:
    """Generic Anthropic agent loop.

    Each agent in the pipeline instantiates this with its own system prompt,
    tool list, and dispatcher. We enable prompt caching on the system block
    and on the tools array so repeated calls within a run stay cheap.
    """

    def __init__(
        self,
        *,
        name: str,
        system: str,
        tools: list[dict],
        dispatcher: ToolDispatcher,
        model: str = DEFAULT_MODEL,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        console: Console | None = None,
        api_key: str | None = None,
    ) -> None:
        self.name = name
        self.system = system
        self.tools = tools
        self.dispatcher = dispatcher
        self.model = model
        self.max_iterations = max_iterations
        self.max_tokens = max_tokens
        self.console = console or Console(legacy_windows=False)
        self.client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    # ------------------------------------------------------------------
    def _system_blocks(self) -> list[dict]:
        return [
            {
                "type": "text",
                "text": self.system,
                "cache_control": {"type": "ephemeral"},
            }
        ]

    def _tools_with_cache(self) -> list[dict]:
        if not self.tools:
            return []
        out = [dict(t) for t in self.tools]
        out[-1] = {**out[-1], "cache_control": {"type": "ephemeral"}}
        return out

    # ------------------------------------------------------------------
    def run(self, user_message: str | list[dict]) -> AgentResult:
        if isinstance(user_message, str):
            messages: list[dict] = [{"role": "user", "content": user_message}]
        else:
            messages = [{"role": "user", "content": user_message}]

        tool_calls: list[dict] = []
        usage_totals: dict[str, int] = {}
        stop_reason: str | None = None

        for iteration in range(1, self.max_iterations + 1):
            self.console.log(
                f"[bold cyan]\\[{self.name}][/bold cyan] iteration {iteration}"
            )
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self._system_blocks(),
                tools=self._tools_with_cache(),
                messages=messages,
            )

            usage = getattr(response, "usage", None)
            if usage is not None:
                for k in (
                    "input_tokens",
                    "output_tokens",
                    "cache_creation_input_tokens",
                    "cache_read_input_tokens",
                ):
                    v = getattr(usage, k, 0) or 0
                    usage_totals[k] = usage_totals.get(k, 0) + v

            assistant_content = [block.model_dump() for block in response.content]
            messages.append({"role": "assistant", "content": assistant_content})
            stop_reason = response.stop_reason

            if response.stop_reason != "tool_use":
                final_text = _extract_text(assistant_content)
                return AgentResult(
                    final_text=final_text,
                    messages=messages,
                    tool_calls=tool_calls,
                    usage=usage_totals,
                    stop_reason=stop_reason,
                    iterations=iteration,
                )

            tool_results: list[dict] = []
            for block in assistant_content:
                if block.get("type") != "tool_use":
                    continue
                name = block["name"]
                args = block.get("input") or {}
                tool_id = block["id"]
                self.console.log(
                    f"  [dim]-> {name}({_short_args(args)})[/dim]"
                )
                try:
                    result = self.dispatcher(name, args)
                except Exception as exc:  # noqa: BLE001
                    result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
                tool_calls.append({"name": name, "input": args, "output": result})
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    }
                )

            messages.append({"role": "user", "content": tool_results})

        # Hit iteration cap
        final_text = _extract_text(messages[-1]["content"]) if messages else ""
        return AgentResult(
            final_text=final_text,
            messages=messages,
            tool_calls=tool_calls,
            usage=usage_totals,
            stop_reason="max_iterations",
            iterations=self.max_iterations,
        )


class CustomAgentClient:
    """Agent loop for OpenAI-compatible LLM endpoints (custom/local models).

    Uses the standard /v1/chat/completions API format with function calling.
    Configure via CUSTOM_LLM_BASE_URL and CUSTOM_LLM_API_KEY env vars, or pass
    base_url/api_key directly.
    """

    def __init__(
        self,
        *,
        name: str,
        system: str,
        tools: list[dict],
        dispatcher: ToolDispatcher,
        model: str = "default",
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        console: Console | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        try:
            from openai import OpenAI  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError(
                "The 'openai' package is required for custom API endpoints. "
                "Install it with: pip install openai"
            ) from exc

        self.name = name
        self.system = system
        self.tools = tools
        self.dispatcher = dispatcher
        self.model = model
        self.max_iterations = max_iterations
        self.max_tokens = max_tokens
        self.console = console or Console(legacy_windows=False)

        resolved_key = api_key or os.environ.get("CUSTOM_LLM_API_KEY") or "no-key"
        resolved_url = base_url or os.environ.get("CUSTOM_LLM_BASE_URL")
        self.client = OpenAI(api_key=resolved_key, base_url=resolved_url)

    # ------------------------------------------------------------------
    def _to_openai_tools(self) -> list[dict]:
        """Convert Anthropic-style tool schemas to OpenAI function-calling format."""
        result = []
        for t in self.tools:
            t = {k: v for k, v in t.items() if k != "cache_control"}
            result.append(
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get(
                            "input_schema", {"type": "object", "properties": {}}
                        ),
                    },
                }
            )
        return result

    # ------------------------------------------------------------------
    def run(self, user_message: str | list[dict]) -> AgentResult:
        messages: list[dict] = [{"role": "system", "content": self.system}]

        if isinstance(user_message, str):
            messages.append({"role": "user", "content": user_message})
        else:
            # Anthropic tool-result content blocks — extract plain text
            messages.append({"role": "user", "content": _extract_text(user_message)})

        openai_tools = self._to_openai_tools()
        tool_calls_log: list[dict] = []
        usage_totals: dict[str, int] = {}

        for iteration in range(1, self.max_iterations + 1):
            self.console.log(
                f"[bold cyan]\\[{self.name}][/bold cyan] iteration {iteration}"
            )

            kwargs: dict = {
                "model": self.model,
                "messages": messages,
                "max_tokens": self.max_tokens,
            }
            if openai_tools:
                kwargs["tools"] = openai_tools

            response = self.client.chat.completions.create(**kwargs)
            choice = response.choices[0]
            msg = choice.message

            if response.usage:
                usage_totals["input_tokens"] = (
                    usage_totals.get("input_tokens", 0) + (response.usage.prompt_tokens or 0)
                )
                usage_totals["output_tokens"] = (
                    usage_totals.get("output_tokens", 0) + (response.usage.completion_tokens or 0)
                )

            # Record assistant turn (preserve tool_calls for multi-turn history)
            asst_dict: dict = {"role": "assistant", "content": msg.content}
            if msg.tool_calls:
                asst_dict["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ]
            messages.append(asst_dict)

            if choice.finish_reason != "tool_calls" or not msg.tool_calls:
                return AgentResult(
                    final_text=_strip_thinking(msg.content or ""),
                    messages=messages,
                    tool_calls=tool_calls_log,
                    usage=usage_totals,
                    stop_reason=choice.finish_reason,
                    iterations=iteration,
                )

            # Dispatch each tool call and add results to history
            for tc in msg.tool_calls:
                tc_name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                self.console.log(f"  [dim]-> {tc_name}({_short_args(args)})[/dim]")

                try:
                    result = self.dispatcher(tc_name, args)
                except Exception as exc:  # noqa: BLE001
                    result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

                tool_calls_log.append({"name": tc_name, "input": args, "output": result})
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    }
                )

        # Hit iteration cap — return the last assistant text we saw
        final_text = ""
        for m in reversed(messages):
            if m.get("role") == "assistant" and isinstance(m.get("content"), str) and m["content"]:
                final_text = _strip_thinking(m["content"])
                break

        return AgentResult(
            final_text=final_text,
            messages=messages,
            tool_calls=tool_calls_log,
            usage=usage_totals,
            stop_reason="max_iterations",
            iterations=self.max_iterations,
        )


def make_agent(
    *,
    name: str,
    system: str,
    tools: list[dict],
    dispatcher: ToolDispatcher,
    model: str = DEFAULT_MODEL,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    console: Console | None = None,
    api_key: str | None = None,
    api_base_url: str | None = None,
) -> "AgentClient | CustomAgentClient":
    """Factory: returns CustomAgentClient when api_base_url is set, else AgentClient."""
    if api_base_url:
        return CustomAgentClient(
            name=name,
            system=system,
            tools=tools,
            dispatcher=dispatcher,
            model=model,
            max_iterations=max_iterations,
            max_tokens=max_tokens,
            console=console,
            api_key=api_key,
            base_url=api_base_url,
        )
    return AgentClient(
        name=name,
        system=system,
        tools=tools,
        dispatcher=dispatcher,
        model=model,
        max_iterations=max_iterations,
        max_tokens=max_tokens,
        console=console,
        api_key=api_key,
    )


def _strip_thinking(text: str) -> str:
    """Remove Qwen3 <think>...</think> reasoning blocks from the response text."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(parts).strip()
    return ""


def _short_args(args: dict, limit: int = 120) -> str:
    s = json.dumps(args, ensure_ascii=False, default=str)
    return s if len(s) <= limit else s[: limit - 3] + "..."
