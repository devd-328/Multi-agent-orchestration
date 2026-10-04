import pytest

from orchestration.search import FakeSearchProvider, SearchError, SearchResult


def _result(name: str) -> SearchResult:
    return SearchResult(title=name, url=f"https://{name}.example.test", content=f"About {name}")


def test_fake_returns_scripted_results_and_records_calls() -> None:
    provider = FakeSearchProvider([[_result("a")], [_result("b"), _result("c")]])

    first = provider.search("query one", 3)
    second = provider.search("query two", 4)

    assert [item.title for item in first] == ["a"]
    assert [item.title for item in second] == ["b", "c"]
    assert provider.queries == ["query one", "query two"]
    assert provider.max_results == [3, 4]


def test_fake_raises_scripted_errors() -> None:
    provider = FakeSearchProvider([SearchError("Search request timed out.")])

    with pytest.raises(SearchError, match="timed out"):
        provider.search("query", 3)

    assert provider.queries == ["query"]


def test_fake_fails_when_script_is_exhausted() -> None:
    with pytest.raises(SearchError, match="No scripted search response"):
        FakeSearchProvider([]).search("query", 3)
