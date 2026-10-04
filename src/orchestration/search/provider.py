from typing import Protocol

from pydantic import BaseModel, ConfigDict


class SearchResult(BaseModel):
    """One web search hit. All fields are untrusted data from the open web."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str
    url: str
    content: str
    published_date: str | None = None


class SearchProvider(Protocol):
    """Web search used by agents. Adapters live behind this interface."""

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        """Return at most `max_results` results for one query."""
        ...
