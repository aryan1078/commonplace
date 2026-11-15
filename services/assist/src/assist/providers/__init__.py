from ..config import Settings
from .base import Provider, ProviderError, ProviderTimeout, RateLimited


def make_provider(settings: Settings) -> Provider:
    if settings.provider == "fake":
        from .fake import FakeProvider

        return FakeProvider()
    if settings.provider in ("ollama", "openai_compat"):
        # Ollama speaks the OpenAI chat API, so one provider covers both; only
        # the base URL, key and model names (from settings) differ.
        from .openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(settings)
    raise ValueError(f"Unknown ASSIST_PROVIDER: {settings.provider!r} (use ollama, openai_compat or fake)")


__all__ = ["Provider", "ProviderError", "ProviderTimeout", "RateLimited", "make_provider"]
