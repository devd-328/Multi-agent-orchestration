import json
from functools import cache

import httpx
import pytest

from orchestration.llm.ollama import OllamaProvider

_LIVE_BASE = "http://127.0.0.1:11434"


@cache
def _local_model() -> str | None:
    """Return a local model name, or None when Ollama is not running."""
    try:
        response = httpx.get(f"{_LIVE_BASE}/api/tags", timeout=0.5)
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    try:
        body = response.json()
    except json.JSONDecodeError:
        return None
    models = body.get("models") if isinstance(body, dict) else None
    if not isinstance(models, list) or not models or not isinstance(models[0], dict):
        return None
    name = models[0].get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    return name


@pytest.mark.skipif(_local_model() is None, reason="Ollama is not running")
def test_live_generate() -> None:
    model = _local_model()
    assert model is not None
    provider = OllamaProvider(base_url=_LIVE_BASE, model=model, timeout_seconds=30)

    text = provider.generate("Reply with the single word ok.")

    assert text.strip()
