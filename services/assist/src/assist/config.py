"""Settings for the Assist service, read from environment variables or .env.

The default is a local, CPU-friendly model served by Ollama, so the LLM runs
on its own machine (node 1) with no API key and no data leaving the cluster.
"""

import os
from dataclasses import dataclass

from dotenv import find_dotenv, load_dotenv

# Look for a .env file starting from the folder you run the command in
# (the repo root) and walking upwards.
load_dotenv(find_dotenv(usecwd=True))

# What ASSIST_PROVIDER=ollama means unless overridden. Ollama exposes an
# OpenAI-compatible API, so the same provider class talks to it.
OLLAMA_DEFAULTS = {
    "base_url": "http://localhost:11434/v1",
    "api_key": "ollama",  # Ollama ignores it, but the client requires one
    "model": "qwen2.5:3b",
    "fast_model": "qwen2.5:1.5b",
}


@dataclass(frozen=True)
class Settings:
    provider: str  # "ollama", "openai_compat" or "fake"
    base_url: str
    api_key: str
    model: str  # used for grammar, summaries, enhancement and questions
    fast_model: str  # used for autocomplete, where speed matters most
    reasoning_effort: str | None  # "low" / "medium" / "high", or None to omit
    port: int
    max_input_chars: int  # longest text accepted in one request
    max_summary_chars: int  # longest document accepted for summarizing
    default_timeout_s: float  # used when the caller sets no gRPC deadline

    @staticmethod
    def from_env() -> "Settings":
        provider = os.getenv("ASSIST_PROVIDER", "ollama").strip().lower()
        defaults = OLLAMA_DEFAULTS if provider == "ollama" else {}
        model = os.getenv("ASSIST_MODEL") or defaults.get("model", "")
        return Settings(
            provider=provider,
            base_url=os.getenv("ASSIST_BASE_URL") or defaults.get("base_url", ""),
            api_key=os.getenv("ASSIST_API_KEY") or defaults.get("api_key", ""),
            model=model,
            fast_model=os.getenv("ASSIST_FAST_MODEL") or defaults.get("fast_model") or model,
            reasoning_effort=os.getenv("ASSIST_REASONING_EFFORT") or None,
            port=int(os.getenv("ASSIST_PORT", "50061")),
            max_input_chars=int(os.getenv("ASSIST_MAX_INPUT_CHARS", "8000")),
            max_summary_chars=int(os.getenv("ASSIST_MAX_SUMMARY_CHARS", "60000")),
            default_timeout_s=float(os.getenv("ASSIST_DEFAULT_TIMEOUT_S", "60")),
        )
