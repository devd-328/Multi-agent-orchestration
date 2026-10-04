import os

import pytest

from orchestration.core.config import load_settings
from orchestration.core.errors import ConfigurationError
from orchestration.search.tavily import TavilyProvider

_PLACEHOLDER = "replace-with-your-search-api-key"


def _live_key() -> str | None:
    """Return the configured Tavily key, or None when no real key is set."""
    try:
        settings = load_settings()
    except ConfigurationError:
        return None
    if settings.search_provider.lower() != "tavily" or settings.search_api_key is None:
        return None
    key = settings.search_api_key.get_secret_value().strip()
    return None if not key or key == _PLACEHOLDER else key


_KEY = _live_key()
_OPTED_IN = os.environ.get("RUN_LIVE_SEARCH_TEST") == "1"


@pytest.mark.skipif(
    _KEY is None or not _OPTED_IN,
    reason="Needs a search API key and RUN_LIVE_SEARCH_TEST=1 (each run spends one credit)",
)
def test_live_search() -> None:
    assert _KEY is not None
    provider = TavilyProvider(api_key=_KEY, timeout_seconds=20)

    results = provider.search("python programming language", 2)

    assert 1 <= len(results) <= 2
    assert all(result.url.startswith("http") for result in results)
