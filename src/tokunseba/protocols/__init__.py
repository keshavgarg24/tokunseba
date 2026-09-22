from .anthropic import AnthropicAdapter
from .base import Adapter
from .gemini import GeminiAdapter
from .ollama import OllamaAdapter
from .openai import OpenAIAdapter

ADAPTERS: dict[str, Adapter] = {
    "anthropic": AnthropicAdapter(),
    "openai": OpenAIAdapter(),
    "ollama": OllamaAdapter(),
    "gemini": GeminiAdapter(),
}


def register(kind: str, adapter: Adapter) -> None:
    ADAPTERS[kind] = adapter


__all__ = ["ADAPTERS", "Adapter", "AnthropicAdapter", "GeminiAdapter", "OllamaAdapter", "OpenAIAdapter", "register"]
