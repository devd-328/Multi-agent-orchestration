from collections.abc import Callable

import pytest

from orchestration.core.config import Settings, load_settings

_SETTING_ENV = (
    "LLM_PROVIDER",
    "LLM_MODEL",
    "LLM_BASE_URL",
    "SEARCH_PROVIDER",
    "SEARCH_API_KEY",
    "REVIEWER_MODEL",
    "MAX_TASK_ATTEMPTS",
    "MAX_REVIEW_REVISIONS",
    "MAX_PLAN_ATTEMPTS",
    "MAX_SEARCH_QUERIES",
    "MAX_RESULTS_PER_QUERY",
    "MAX_SOURCE_CHARS",
    "MAX_RESEARCH_ATTEMPTS",
    "MAX_REVIEW_EXCERPT_CHARS",
    "MAX_REVIEW_ATTEMPTS",
    "MAX_GRAPH_STEPS",
)


@pytest.fixture
def make_settings(monkeypatch: pytest.MonkeyPatch) -> Callable[..., Settings]:
    """Build Settings from defaults plus overrides, ignoring the machine's environment."""

    def build(**overrides: object) -> Settings:
        for name in _SETTING_ENV:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("LLM_MODEL", "test-model")
        monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9")
        for name, value in overrides.items():
            monkeypatch.setenv(name.upper(), str(value))
        return load_settings(env_file=None)

    return build
