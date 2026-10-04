from collections.abc import Sequence

from orchestration.search.errors import SearchError
from orchestration.search.provider import SearchResult


class FakeSearchProvider:
    """Deterministic provider for tests. One scripted response per call, in order."""

    def __init__(self, responses: Sequence[Sequence[SearchResult] | Exception]) -> None:
        self._responses = list(responses)
        self.queries: list[str] = []
        self.max_results: list[int] = []

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        """Return the next scripted response and record the call."""
        self.queries.append(query)
        self.max_results.append(max_results)
        if not self._responses:
            raise SearchError("No scripted search response is left.")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return list(item)
