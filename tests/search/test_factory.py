import pytest

from orchestration.core.config import load_settings
from orchestration.core.errors import ConfigurationError
from orchestration.search import create_search_provider

_KEY = "tvly-super-secret-key-value"


@pytest.fixture(autouse=True)
def _clean_search_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("SEARCH_PROVIDER", "SEARCH_API_KEY", "SEARCH_TIMEOUT_SECONDS"):
        monkeypatch.delenv(name, raising=False)


def test_factory_builds_the_default_adapter_from_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Recording:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def search(self, query: str, max_results: int) -> list[object]:
            return []

    monkeypatch.setattr("orchestration.search.factory.TavilyProvider", Recording)
    monkeypatch.setenv("SEARCH_API_KEY", _KEY)
    monkeypatch.setenv("SEARCH_TIMEOUT_SECONDS", "7.5")

    provider = create_search_provider(load_settings(env_file=None))

    assert isinstance(provider, Recording)
    assert captured == {"api_key": _KEY, "timeout_seconds": 7.5}


def test_provider_name_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEARCH_PROVIDER", " Tavily ")
    monkeypatch.setenv("SEARCH_API_KEY", _KEY)

    assert create_search_provider(load_settings(env_file=None)) is not None


def test_unknown_provider_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEARCH_PROVIDER", "not-a-provider")
    monkeypatch.setenv("SEARCH_API_KEY", _KEY)

    with pytest.raises(ConfigurationError) as exc_info:
        create_search_provider(load_settings(env_file=None))

    assert str(exc_info.value) == "Unknown search provider 'not-a-provider'."
    assert _KEY not in str(exc_info.value)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_key_fails_fast_without_printing_it(
    monkeypatch: pytest.MonkeyPatch,
    value: str | None,
) -> None:
    if value is not None:
        monkeypatch.setenv("SEARCH_API_KEY", value)

    with pytest.raises(ConfigurationError) as exc_info:
        create_search_provider(load_settings(env_file=None))

    assert str(exc_info.value) == "Search API key is missing. Set SEARCH_API_KEY."
