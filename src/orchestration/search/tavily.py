import json
from urllib.parse import urlsplit

import httpx

from orchestration.search.errors import SearchError
from orchestration.search.provider import SearchResult

# Request and response shape checked against the Tavily Search API reference
# (POST /search, bearer auth). Request body: query, max_results (0 to 20),
# search_depth, include_published_date. Response body: results[] with title,
# url, content, and published_date.
TAVILY_SEARCH_URL = "https://api.tavily.com/search"
_MAX_RESULTS_LIMIT = 20


class TavilyProvider:
    """SearchProvider adapter for the Tavily Search API."""

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float,
        base_url: str = TAVILY_SEARCH_URL,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise SearchError("Search API key is missing.")
        if timeout_seconds <= 0:
            raise SearchError("Search request timeout must be greater than zero.")
        self._api_key = api_key.strip()
        self._timeout = timeout_seconds
        self._url = base_url
        self._transport = transport

    def __repr__(self) -> str:
        return "TavilyProvider(redacted)"

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        """Return at most `max_results` results for one query."""
        if not isinstance(query, str) or not query.strip():
            raise SearchError("Search query is empty.")
        if not 1 <= max_results <= _MAX_RESULTS_LIMIT:
            raise SearchError(f"Search max_results must be between 1 and {_MAX_RESULTS_LIMIT}.")
        payload = {
            "query": query.strip(),
            "max_results": max_results,
            "search_depth": "basic",
            "include_published_date": True,
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            with httpx.Client(transport=self._transport, timeout=self._timeout) as client:
                response = client.post(self._url, json=payload, headers=headers)
        except httpx.TimeoutException:
            raise SearchError("Search request timed out.") from None
        except httpx.HTTPError:
            raise SearchError("Search provider is unreachable.") from None
        if response.status_code != 200:
            raise SearchError(f"Search request failed with status {response.status_code}.")
        return _parse_results(response)[:max_results]


def _parse_results(response: httpx.Response) -> list[SearchResult]:
    try:
        body = response.json()
    except json.JSONDecodeError:
        raise SearchError("Search provider returned a malformed response.") from None
    items = body.get("results") if isinstance(body, dict) else None
    if not isinstance(items, list):
        raise SearchError("Search provider returned a malformed response.")
    return [_parse_item(item) for item in items]


def _parse_item(item: object) -> SearchResult:
    if not isinstance(item, dict):
        raise SearchError("Search provider returned a malformed response.")
    url = item.get("url")
    if not isinstance(url, str) or not _is_http_url(url):
        raise SearchError("Search provider returned a malformed response.")
    title = item.get("title")
    content = item.get("content")
    published = item.get("published_date")
    return SearchResult(
        title=title if isinstance(title, str) else "",
        url=url.strip(),
        content=content if isinstance(content, str) else "",
        published_date=published if isinstance(published, str) and published.strip() else None,
    )


def _is_http_url(url: str) -> bool:
    parts = urlsplit(url.strip())
    return parts.scheme in {"http", "https"} and bool(parts.netloc)
