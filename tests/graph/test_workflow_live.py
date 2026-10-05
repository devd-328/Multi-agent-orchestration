import os

import httpx
import pytest

from orchestration.core.config import load_settings
from orchestration.core.errors import ConfigurationError
from orchestration.graph import run_workflow
from orchestration.llm.ollama import OllamaProvider
from orchestration.search.tavily import TavilyProvider
from orchestration.state import RunStatus

_OLLAMA_URL = "http://127.0.0.1:11434"
_PLACEHOLDER = "replace-with-your-search-api-key"
_GOAL = "Research upcoming technology events and summarize the useful findings with sources."


def _local_model() -> str | None:
    """Return a local Ollama model name, or None when Ollama is not reachable."""
    try:
        response = httpx.get(f"{_OLLAMA_URL}/api/tags", timeout=0.5)
        models = response.json().get("models") if response.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        return None
    if not isinstance(models, list) or not models or not isinstance(models[0], dict):
        return None
    name = models[0].get("name")
    return name if isinstance(name, str) and name.strip() else None


def _search_key() -> str | None:
    try:
        key = load_settings().search_api_key
    except ConfigurationError:
        return None
    value = key.get_secret_value().strip() if key is not None else ""
    return None if not value or value == _PLACEHOLDER else value


_OPTED_IN = os.environ.get("RUN_LIVE_SEARCH_TEST") == "1"
_KEY = _search_key() if _OPTED_IN else None
_MODEL = _local_model() if _KEY is not None else None


@pytest.mark.skipif(
    _MODEL is None,
    reason="Needs Ollama running, a search API key, and RUN_LIVE_SEARCH_TEST=1",
)
def test_live_end_to_end_run() -> None:
    assert _MODEL is not None
    assert _KEY is not None
    settings = load_settings(env_file=None)
    llm = OllamaProvider(base_url=_OLLAMA_URL, model=_MODEL, timeout_seconds=180)
    search = TavilyProvider(api_key=_KEY, timeout_seconds=20)

    state = run_workflow(_GOAL, llm=llm, search=search, settings=settings)

    # A small local model may fail review. Either outcome must be coherent.
    if state["status"] is RunStatus.DONE:
        assert state["final_output"] is not None
        assert "## Task" in state["final_output"]
    else:
        assert state["status"] is RunStatus.FAILED
        assert state["final_output"] is None
        assert state["errors"]
