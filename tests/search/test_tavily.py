import json

import httpx
import pytest

from orchestration.search import SearchError
from orchestration.search.tavily import TAVILY_SEARCH_URL, TavilyProvider

_KEY = "tvly-super-secret-key-value"


def _provider(
    handler: httpx.MockTransport | None = None,
    *,
    api_key: str = _KEY,
    timeout_seconds: float = 5,
) -> TavilyProvider:
    return TavilyProvider(api_key=api_key, timeout_seconds=timeout_seconds, transport=handler)


def _item(**overrides: object) -> dict[str, object]:
    item: dict[str, object] = {
        "title": "Tech Summit 2027",
        "url": "https://summit.example.test/2027",
        "content": "A conference about technology.",
        "score": 0.9,
        "published_date": "Tue, 11 Mar 2025 17:00:00 GMT",
    }
    item.update(overrides)
    return item


def test_search_sends_the_documented_request_and_parses_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == TAVILY_SEARCH_URL
        assert request.headers["authorization"] == f"Bearer {_KEY}"
        body = json.loads(request.content.decode())
        assert body["query"] == "tech events"
        assert body["max_results"] == 3
        assert _KEY not in request.content.decode()
        return httpx.Response(
            200,
            json={
                "query": "tech events",
                "results": [_item(), _item(url="https://other.example.test", published_date=None)],
                "response_time": 0.4,
            },
        )

    results = _provider(httpx.MockTransport(handler)).search("  tech events  ", 3)

    assert [result.url for result in results] == [
        "https://summit.example.test/2027",
        "https://other.example.test",
    ]
    assert results[0].title == "Tech Summit 2027"
    assert results[0].content == "A conference about technology."
    assert results[0].published_date == "Tue, 11 Mar 2025 17:00:00 GMT"
    assert results[1].published_date is None


def test_results_are_cut_to_max_results() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        urls = [f"https://site{n}.example.test" for n in range(5)]
        return httpx.Response(200, json={"results": [_item(url=url) for url in urls]})

    assert len(_provider(httpx.MockTransport(handler)).search("query", 2)) == 2


def test_missing_optional_fields_are_tolerated() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [{"url": "https://a.example.test"}]})

    (result,) = _provider(httpx.MockTransport(handler)).search("query", 3)

    assert result.title == ""
    assert result.content == ""
    assert result.published_date is None


def test_timeout_value_is_passed_to_the_client(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    class RecordingClient(httpx.Client):
        def __init__(self, *args: object, **kwargs: object) -> None:
            seen["timeout"] = kwargs.get("timeout")
            super().__init__(*args, **kwargs)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": []})

    monkeypatch.setattr("orchestration.search.tavily.httpx.Client", RecordingClient)

    _provider(httpx.MockTransport(handler), timeout_seconds=4.5).search("query", 3)

    assert seen["timeout"] == 4.5


def test_timeout_is_a_safe_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(f"timed out with {request.headers['authorization']}")

    with pytest.raises(SearchError) as exc_info:
        _provider(httpx.MockTransport(handler)).search("secret query", 3)

    assert str(exc_info.value) == "Search request timed out."
    assert exc_info.value.__cause__ is None
    assert _KEY not in str(exc_info.value)
    assert "secret query" not in str(exc_info.value)


def test_unreachable_provider_is_a_safe_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"refused for {request.headers['authorization']}")

    with pytest.raises(SearchError) as exc_info:
        _provider(httpx.MockTransport(handler)).search("query", 3)

    assert str(exc_info.value) == "Search provider is unreachable."
    assert _KEY not in str(exc_info.value)


@pytest.mark.parametrize("status", [400, 401, 429, 432, 500])
def test_non_200_hides_the_response_body(status: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        echoed = request.headers["authorization"]
        return httpx.Response(status, json={"detail": {"error": f"bad key {echoed}"}})

    with pytest.raises(SearchError) as exc_info:
        _provider(httpx.MockTransport(handler)).search("query", 3)

    assert str(exc_info.value) == f"Search request failed with status {status}."
    assert _KEY not in str(exc_info.value)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not-json"),
        httpx.Response(200, json=["nope"]),
        httpx.Response(200, json={"query": "x"}),
        httpx.Response(200, json={"results": "none"}),
        httpx.Response(200, json={"results": ["nope"]}),
        httpx.Response(200, json={"results": [{"title": "no url"}]}),
        httpx.Response(200, json={"results": [{"url": "javascript:alert(1)"}]}),
        httpx.Response(200, json={"results": [{"url": 5}]}),
    ],
)
def test_malformed_responses(response: httpx.Response) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return response

    with pytest.raises(SearchError) as exc_info:
        _provider(httpx.MockTransport(handler)).search("query", 3)

    assert str(exc_info.value) == "Search provider returned a malformed response."


@pytest.mark.parametrize("api_key", ["", "   "])
def test_missing_key_fails_fast(api_key: str) -> None:
    with pytest.raises(SearchError) as exc_info:
        TavilyProvider(api_key=api_key, timeout_seconds=5)

    assert str(exc_info.value) == "Search API key is missing."


def test_timeout_must_be_positive() -> None:
    with pytest.raises(SearchError, match="greater than zero") as exc_info:
        TavilyProvider(api_key=_KEY, timeout_seconds=0)

    assert _KEY not in str(exc_info.value)


@pytest.mark.parametrize("max_results", [0, 21, -1])
def test_max_results_is_bounded(max_results: int) -> None:
    with pytest.raises(SearchError, match="between 1 and 20"):
        _provider().search("query", max_results)


def test_empty_query_is_rejected() -> None:
    with pytest.raises(SearchError, match="query is empty"):
        _provider().search("   ", 3)


def test_repr_hides_the_key() -> None:
    assert _KEY not in repr(_provider())
