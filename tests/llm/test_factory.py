import pytest

from orchestration.core.config import load_settings
from orchestration.core.errors import ConfigurationError
from orchestration.llm import create_llm_provider, create_reviewer_llm_provider


def test_factory_uses_settings_for_the_known_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class Recording:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def generate(self, prompt: str) -> str:
            return prompt

    monkeypatch.setattr("orchestration.llm.factory.OllamaProvider", Recording)
    monkeypatch.setenv("LLM_PROVIDER", "Ollama")
    monkeypatch.setenv("LLM_MODEL", "configured-model")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "12.5")

    provider = create_llm_provider(load_settings(env_file=None))

    assert isinstance(provider, Recording)
    assert captured["model"] == "configured-model"
    assert captured["timeout_seconds"] == 12.5
    assert str(captured["base_url"]).rstrip("/") == "http://127.0.0.1:11434"


def _recording_provider(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    captured: dict[str, object] = {}

    class Recording:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def generate(self, prompt: str) -> str:
            return prompt

    monkeypatch.setattr("orchestration.llm.factory.OllamaProvider", Recording)
    return captured


def test_reviewer_provider_uses_the_override_only_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _recording_provider(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_MODEL", "shared-model")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("REVIEWER_MODEL", "review-only-model")

    create_reviewer_llm_provider(load_settings(env_file=None))
    reviewer_model = captured["model"]
    create_llm_provider(load_settings(env_file=None))

    assert reviewer_model == "review-only-model"
    assert captured["model"] == "shared-model"


def test_reviewer_provider_falls_back_to_the_shared_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _recording_provider(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_MODEL", "shared-model")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.delenv("REVIEWER_MODEL", raising=False)

    create_reviewer_llm_provider(load_settings(env_file=None))

    assert captured["model"] == "shared-model"


def test_reviewer_provider_still_fails_fast_for_an_unknown_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "not-a-provider")
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("REVIEWER_MODEL", "review-only-model")

    with pytest.raises(ConfigurationError) as exc_info:
        create_reviewer_llm_provider(load_settings(env_file=None))

    assert str(exc_info.value) == "Unknown LLM provider 'not-a-provider'."
    assert "review-only-model" not in str(exc_info.value)


def test_unknown_provider_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    secret_model = "secret-model-value"
    secret_host = "secret.example.test"
    monkeypatch.setenv("LLM_PROVIDER", "not-a-provider")
    monkeypatch.setenv("LLM_MODEL", secret_model)
    monkeypatch.setenv("LLM_BASE_URL", f"http://{secret_host}")

    with pytest.raises(ConfigurationError) as exc_info:
        create_llm_provider(load_settings(env_file=None))

    message = str(exc_info.value)
    assert message == "Unknown LLM provider 'not-a-provider'."
    assert secret_model not in message
    assert secret_host not in message
    assert exc_info.value.__cause__ is None
