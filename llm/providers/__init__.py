"""AgentCore — llm/providers/__init__.py"""
from llm.providers.base import (BaseProvider, ProviderError, RateLimitError, AuthError,
                   ContextOverflowError, ProviderUnavailableError)
from .mock import MockProvider
from .openai_compat import OpenAICompatProvider, DeepSeekProvider, OpenRouterProvider
from .misc import GeminiProvider, ClaudeProvider, OllamaProvider

PROVIDER_CLASSES = {
    "mock": MockProvider,
    "openai": OpenAICompatProvider,
    "openrouter": OpenRouterProvider,   # OpenAI-compatible (base_url + headers from config)
    "deepseek": DeepSeekProvider,
    "gemini": GeminiProvider,
    "claude": ClaudeProvider,
    "ollama": OllamaProvider,
}

__all__ = [
    "BaseProvider", "ProviderError", "RateLimitError", "AuthError",
    "ContextOverflowError", "ProviderUnavailableError", "MockProvider",
    "OpenAICompatProvider", "DeepSeekProvider", "OpenRouterProvider",
    "GeminiProvider", "ClaudeProvider", "OllamaProvider", "PROVIDER_CLASSES",
]
