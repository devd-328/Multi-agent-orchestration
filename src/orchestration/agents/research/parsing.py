import json
import re

from orchestration.agents.research.prompt import MAX_QUERY_CHARS

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)
_CITATION = re.compile(r"\[(\d{1,9}(?:\s*,\s*\d{1,9})*)\]")


class Rejected(Exception):
    """Model output failed a check. The message is safe to send back to the model."""

    def __init__(self, message: str, error_type: str) -> None:
        super().__init__(message)
        self.error_type = error_type


def parse_queries(raw: object, *, max_queries: int) -> list[str]:
    """Return 1 to `max_queries` distinct, non-empty queries or raise Rejected."""
    if not isinstance(raw, str) or not raw.strip():
        raise Rejected("Model output is empty.", "invalid_json")
    payload = _load_json(_strip_fences(raw))
    if isinstance(payload, dict) and "queries" in payload:
        payload = payload["queries"]
    if not isinstance(payload, list):
        raise Rejected("Output must be a JSON object with a queries array.", "invalid_queries")
    queries: list[str] = []
    seen: set[str] = set()
    for item in payload:
        if not isinstance(item, str):
            raise Rejected("Every query must be a string.", "invalid_queries")
        query = " ".join(item.split())
        if not query:
            raise Rejected("A query is empty.", "invalid_queries")
        if len(query) > MAX_QUERY_CHARS:
            raise Rejected(
                f"A query is longer than {MAX_QUERY_CHARS} characters.", "invalid_queries"
            )
        key = query.casefold()
        if key not in seen:
            seen.add(key)
            queries.append(query)
    if not queries:
        raise Rejected("Return at least one query.", "invalid_queries")
    if len(queries) > max_queries:
        raise Rejected(f"Return at most {max_queries} queries.", "invalid_queries")
    return queries


def check_summary(raw: object, *, source_count: int) -> str:
    """Return the summary text or raise Rejected.

    The summary needs at least one citation, and every cited number must be a
    retrieved source number (1 to `source_count`). This does not prove that each
    claim is supported by its source.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise Rejected("Summary is empty.", "invalid_summary")
    text = raw.strip()
    cited = cited_numbers(text)
    if not cited:
        raise Rejected(
            "Summary has no citations. Cite claims with source numbers in square brackets.",
            "invalid_citation",
        )
    missing = sorted(number for number in cited if not 1 <= number <= source_count)
    if missing:
        listed = ", ".join(str(number) for number in missing)
        raise Rejected(
            f"Summary cites source {listed}, which does not exist. "
            f"Valid source numbers are 1 to {source_count}.",
            "invalid_citation",
        )
    return text


def cited_numbers(text: str) -> set[int]:
    """Return every source number cited as [n] or [n, m] in the text."""
    numbers: set[int] = set()
    for match in _CITATION.finditer(text):
        for part in match.group(1).split(","):
            numbers.add(int(part.strip()))
    return numbers


def _strip_fences(text: str) -> str:
    stripped = text.strip()
    match = _FENCE.match(stripped)
    return match.group(1).strip() if match else stripped


def _load_json(text: str) -> object:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for index, char in enumerate(text):
        if char in "{[":
            try:
                value, _end = json.JSONDecoder().raw_decode(text[index:])
            except json.JSONDecodeError:
                break
            return value
    raise Rejected("Model output is not valid JSON.", "invalid_json")
