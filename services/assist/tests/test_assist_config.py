from assist.config import OLLAMA_DEFAULTS, Settings
from assist.providers import make_provider
from assist.providers.fake import FakeProvider
from assist.providers.openai_compat import OpenAICompatProvider

ENV_KEYS = ["ASSIST_PROVIDER", "ASSIST_BASE_URL", "ASSIST_API_KEY", "ASSIST_MODEL", "ASSIST_FAST_MODEL",
            "ASSIST_DEFAULT_TIMEOUT_S"]


def clean_env(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_local_ollama_is_the_default(monkeypatch):
    clean_env(monkeypatch)
    s = Settings.from_env()
    assert s.provider == "ollama"
    assert (s.base_url, s.api_key, s.model, s.fast_model) == (
        "http://localhost:11434/v1", "ollama", "qwen2.5:3b", "qwen2.5:1.5b",
    )
    assert s.default_timeout_s == 60
    assert isinstance(make_provider(s), OpenAICompatProvider)


def test_ollama_settings_can_be_overridden(monkeypatch):
    clean_env(monkeypatch)
    monkeypatch.setenv("ASSIST_BASE_URL", "http://ollama:11434/v1")
    monkeypatch.setenv("ASSIST_MODEL", "llama3.2:3b")
    s = Settings.from_env()
    assert (s.base_url, s.model, s.fast_model) == ("http://ollama:11434/v1", "llama3.2:3b", OLLAMA_DEFAULTS["fast_model"])


def test_fake_provider(monkeypatch):
    clean_env(monkeypatch)
    monkeypatch.setenv("ASSIST_PROVIDER", "fake")
    assert isinstance(make_provider(Settings.from_env()), FakeProvider)
