from collections.abc import Sequence
from urllib.parse import urlsplit

from orchestration.search import SearchResult

_MAX_TITLE_CHARS = 200


def collect_sources(
    batches: Sequence[Sequence[SearchResult]],
    *,
    max_results_per_query: int,
    max_source_chars: int,
) -> list[SearchResult]:
    """Merge search batches into one numbered source list.

    Each batch is cut to `max_results_per_query`. Results with a non-http url or
    no content are dropped. Duplicate urls keep the first entry, and take the
    later content only when the first had none. Content is cut to
    `max_source_chars`. Source number n is the entry at index n - 1.
    """

    merged: dict[tuple[str, str, str, str], SearchResult] = {}
    for batch in batches:
        for result in list(batch)[:max_results_per_query]:
            key = _url_key(result.url)
            if key is None:
                continue
            existing = merged.get(key)
            if existing is None or (not existing.content.strip() and result.content.strip()):
                merged[key] = result
    sources: list[SearchResult] = []
    for result in merged.values():
        content = result.content.strip()
        if not content:
            continue
        title = " ".join(result.title.split())[:_MAX_TITLE_CHARS] or result.url.strip()
        sources.append(
            SearchResult(
                title=title,
                url=result.url.strip(),
                content=content[:max_source_chars],
                published_date=result.published_date,
            )
        )
    return sources


def format_sources(sources: Sequence[SearchResult]) -> list[str]:
    """Return the `TaskResult.sources` entries. Entry n matches citation [n]."""
    return [
        f"[{number}] {' '.join(source.title.split())} ({source.url})"
        for number, source in enumerate(sources, start=1)
    ]


def _url_key(url: str) -> tuple[str, str, str, str] | None:
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        return None
    return (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), parts.query)
