import pytest

from orchestration.api.app import create_app
from orchestration.core.config import load_settings
from orchestration.core.errors import ConfigurationError

_SECRET_MODEL = "super-secret-model-value"


def test_settings_use_provider_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9")

    settings = load_settings(env_file=None)

    assert settings.llm_provider == "ollama"
    assert settings.llm_model == "test-model"
    assert settings.llm_base_url.host == "127.0.0.1"
    assert "test-model" not in repr(settings)
    assert str(settings) == "Settings(redacted)"


def test_settings_override_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "custom-provider")
    monkeypatch.setenv("LLM_MODEL", "custom-model")
    monkeypatch.setenv("LLM_BASE_URL", "https://models.example.test/v1")

    settings = load_settings(env_file=None)

    assert settings.llm_provider == "custom-provider"
    assert settings.llm_model == "custom-model"
    assert settings.llm_base_url.scheme == "https"
    assert settings.llm_base_url.host == "models.example.test"


def test_missing_model_fails_without_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9")

    with pytest.raises(ConfigurationError) as exc_info:
        load_settings(env_file=None)

    message = str(exc_info.value)
    assert message == "Invalid configuration. llm_model: missing"
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__


def test_invalid_settings_do_not_reveal_values(monkeypatch: pytest.MonkeyPatch) -> None:
    invalid_url = "not-a-url"
    monkeypatch.setenv("LLM_MODEL", _SECRET_MODEL)
    monkeypatch.setenv("LLM_BASE_URL", invalid_url)

    with pytest.raises(ConfigurationError) as exc_info:
        load_settings(env_file=None)

    message = str(exc_info.value)
    assert message == "Invalid configuration. llm_base_url: invalid URL"
    assert _SECRET_MODEL not in message
    assert invalid_url not in message


def test_empty_provider_is_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "   ")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9")

    with pytest.raises(ConfigurationError) as exc_info:
        load_settings(env_file=None)

    assert "llm_provider" in str(exc_info.value)
    assert "   " not in str(exc_info.value)


def test_startup_fails_when_settings_are_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODEL", _SECRET_MODEL)
    monkeypatch.setenv("LLM_BASE_URL", "ftp://example.test/models")

    with pytest.raises(ConfigurationError) as exc_info:
        create_app()

    message = str(exc_info.value)
    assert message == "Invalid configuration. llm_base_url: URL scheme must be http or https"
    assert _SECRET_MODEL not in message
    assert "ftp://example.test/models" not in message
    assert exc_info.value.__cause__ is None
