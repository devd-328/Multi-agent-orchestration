"""Web search interface and adapters."""

from orchestration.search.errors import SearchError
from orchestration.search.factory import create_search_provider
from orchestration.search.fake import FakeSearchProvider
from orchestration.search.provider import SearchProvider, SearchResult

__all__ = [
    "FakeSearchProvider",
    "SearchError",
    "SearchProvider",
    "SearchResult",
    "create_search_provider",
]
