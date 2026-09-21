from .anthropic import AnthropicAdapter
from .gemini import GeminiAdapter
from .ollama import OllamaAdapter
from .openai import OpenAIAdapter

ADAPTERS = {
    "anthropic": AnthropicAdapter(),
    "openai": OpenAIAdapter(),
    "ollama": OllamaAdapter(),
    "gemini": GeminiAdapter(),
}


def register(kind: str, adapter) -> None:
    ADAPTERS[kind] = adapter


__all__ = ["ADAPTERS", "AnthropicAdapter", "GeminiAdapter", "OllamaAdapter", "OpenAIAdapter", "register"]
