"""Single OpenAI-compatible LLM client, shared by all four reasoning stages."""

from .client import LLMClient

__all__ = ["LLMClient"]
