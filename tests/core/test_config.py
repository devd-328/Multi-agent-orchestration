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


def test_limit_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAX_TASK_ATTEMPTS", raising=False)
    monkeypatch.delenv("MAX_REVIEW_REVISIONS", raising=False)
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9")

    settings = load_settings(env_file=None)

    assert settings.max_task_attempts == 3
    assert settings.max_review_revisions == 2
    assert settings.max_plan_attempts == 3
    assert settings.llm_timeout_seconds == 60


def test_limit_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("MAX_TASK_ATTEMPTS", "5")
    monkeypatch.setenv("MAX_REVIEW_REVISIONS", "4")

    settings = load_settings(env_file=None)

    assert settings.max_task_attempts == 5
    assert settings.max_review_revisions == 4


def test_plan_attempt_limit_defaults_and_rejects_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("MAX_PLAN_ATTEMPTS", "0")

    with pytest.raises(ConfigurationError) as exc_info:
        load_settings(env_file=None)

    message = str(exc_info.value)
    assert "max_plan_attempts" in message
    assert "0" not in message


def test_timeout_must_be_greater_than_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "0")

    with pytest.raises(ConfigurationError) as exc_info:
        load_settings(env_file=None)

    message = str(exc_info.value)
    assert "llm_timeout_seconds" in message
    assert "0" not in message


_SEARCH_ENV = (
    "SEARCH_PROVIDER",
    "SEARCH_API_KEY",
    "SEARCH_TIMEOUT_SECONDS",
    "MAX_SEARCH_QUERIES",
    "MAX_RESULTS_PER_QUERY",
    "MAX_SOURCE_CHARS",
    "MAX_RESEARCH_ATTEMPTS",
)


def _base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _SEARCH_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9")


def test_search_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)

    settings = load_settings(env_file=None)

    assert settings.search_provider == "tavily"
    assert settings.search_api_key is None
    assert settings.search_timeout_seconds == 20
    assert settings.max_search_queries == 3
    assert settings.max_results_per_query == 5
    assert settings.max_source_chars == 2000
    assert settings.max_research_attempts == 3


def test_search_overrides_and_key_is_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("SEARCH_PROVIDER", " custom ")
    monkeypatch.setenv("SEARCH_API_KEY", "tvly-secret-value")
    monkeypatch.setenv("SEARCH_TIMEOUT_SECONDS", "7.5")
    monkeypatch.setenv("MAX_SEARCH_QUERIES", "4")
    monkeypatch.setenv("MAX_RESULTS_PER_QUERY", "6")
    monkeypatch.setenv("MAX_SOURCE_CHARS", "900")
    monkeypatch.setenv("MAX_RESEARCH_ATTEMPTS", "2")

    settings = load_settings(env_file=None)

    assert settings.search_provider == "custom"
    assert settings.search_api_key is not None
    assert settings.search_api_key.get_secret_value() == "tvly-secret-value"
    assert "tvly-secret-value" not in repr(settings.search_api_key)
    assert "tvly-secret-value" not in repr(settings)
    assert "tvly-secret-value" not in str(settings)
    assert settings.search_timeout_seconds == 7.5
    assert settings.max_search_queries == 4
    assert settings.max_results_per_query == 6
    assert settings.max_source_chars == 900
    assert settings.max_research_attempts == 2


def test_blank_search_key_counts_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("SEARCH_API_KEY", "   ")

    assert load_settings(env_file=None).search_api_key is None


@pytest.mark.parametrize(
    ("name", "value", "field"),
    [
        ("MAX_SEARCH_QUERIES", "0", "max_search_queries"),
        ("MAX_SEARCH_QUERIES", "11", "max_search_queries"),
        ("MAX_RESULTS_PER_QUERY", "0", "max_results_per_query"),
        ("MAX_RESULTS_PER_QUERY", "21", "max_results_per_query"),
        ("MAX_SOURCE_CHARS", "0", "max_source_chars"),
        ("MAX_RESEARCH_ATTEMPTS", "0", "max_research_attempts"),
        ("SEARCH_TIMEOUT_SECONDS", "0", "search_timeout_seconds"),
        ("SEARCH_PROVIDER", "   ", "search_provider"),
    ],
)
def test_invalid_search_settings_fail_without_values(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
    field: str,
) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("SEARCH_API_KEY", "tvly-secret-value")
    monkeypatch.setenv(name, value)

    with pytest.raises(ConfigurationError) as exc_info:
        load_settings(env_file=None)

    message = str(exc_info.value)
    assert field in message
    assert "tvly-secret-value" not in message


_REVIEW_ENV = ("MAX_REVIEW_EXCERPT_CHARS", "MAX_REVIEW_ATTEMPTS", "REVIEWER_MODEL")


def _review_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _REVIEW_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9")


def test_review_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _review_env(monkeypatch)

    settings = load_settings(env_file=None)

    assert settings.max_review_excerpt_chars == 2000
    assert settings.max_review_attempts == 3
    assert settings.reviewer_model is None


def test_review_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    _review_env(monkeypatch)
    monkeypatch.setenv("MAX_REVIEW_EXCERPT_CHARS", "500")
    monkeypatch.setenv("MAX_REVIEW_ATTEMPTS", "2")
    monkeypatch.setenv("REVIEWER_MODEL", " reviewer-model ")

    settings = load_settings(env_file=None)

    assert settings.max_review_excerpt_chars == 500
    assert settings.max_review_attempts == 2
    assert settings.reviewer_model == "reviewer-model"


def test_blank_reviewer_model_counts_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    _review_env(monkeypatch)
    monkeypatch.setenv("REVIEWER_MODEL", "   ")

    assert load_settings(env_file=None).reviewer_model is None


@pytest.mark.parametrize(
    ("name", "field"),
    [
        ("MAX_REVIEW_EXCERPT_CHARS", "max_review_excerpt_chars"),
        ("MAX_REVIEW_ATTEMPTS", "max_review_attempts"),
    ],
)
def test_review_limits_below_one_fail(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    field: str,
) -> None:
    _review_env(monkeypatch)
    monkeypatch.setenv(name, "0")

    with pytest.raises(ConfigurationError) as exc_info:
        load_settings(env_file=None)

    assert field in str(exc_info.value)


def test_limit_below_one_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("MAX_TASK_ATTEMPTS", "0")

    with pytest.raises(ConfigurationError) as exc_info:
        load_settings(env_file=None)

    message = str(exc_info.value)
    assert "max_task_attempts" in message
    assert "0" not in message


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
