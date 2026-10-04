import json

import httpx
import pytest

from orchestration.llm import LLMError
from orchestration.llm.ollama import OllamaProvider

_MODEL = "configured-model"
_BASE = "http://127.0.0.1:11434"


def _provider(
    handler: httpx.MockTransport | None = None,
    *,
    base_url: str = _BASE,
    timeout_seconds: float = 5,
    transport: httpx.BaseTransport | None = None,
) -> OllamaProvider:
    return OllamaProvider(
        base_url=base_url,
        model=_MODEL,
        timeout_seconds=timeout_seconds,
        transport=transport if transport is not None else handler,
    )


def test_generate_posts_the_configured_model_and_returns_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        assert payload == {"model": _MODEL, "prompt": "hello", "stream": False}
        assert request.url.path == "/api/generate"
        return httpx.Response(
            200,
            json={"response": "planned", "done": True, "context": [1, 2, 3]},
        )

    provider = _provider(transport=httpx.MockTransport(handler))

    assert provider.generate("hello") == "planned"


def test_generate_joins_a_base_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/api/generate"
        return httpx.Response(200, json={"response": "ok", "done": True})

    provider = _provider(
        base_url="https://models.example.test/v1",
        transport=httpx.MockTransport(handler),
    )

    assert provider.generate("hello") == "ok"


def test_timeout_value_is_passed_to_the_client(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    class RecordingClient(httpx.Client):
        def __init__(self, *args: object, **kwargs: object) -> None:
            seen["timeout"] = kwargs.get("timeout")
            super().__init__(*args, **kwargs)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": "ok"})

    monkeypatch.setattr("orchestration.llm.ollama.httpx.Client", RecordingClient)
    provider = _provider(timeout_seconds=3.5, transport=httpx.MockTransport(handler))

    assert provider.generate("hello") == "ok"
    assert seen["timeout"] == 3.5


def test_timeout_is_a_safe_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out talking to secret-host")

    provider = _provider(transport=httpx.MockTransport(handler))

    with pytest.raises(LLMError) as exc_info:
        provider.generate("secret prompt")

    assert str(exc_info.value) == "Model request timed out."
    assert "secret" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


def test_unreachable_provider_is_a_safe_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused to secret-host")

    provider = _provider(transport=httpx.MockTransport(handler))

    with pytest.raises(LLMError) as exc_info:
        provider.generate("secret prompt")

    assert str(exc_info.value) == "Model provider is unreachable."
    assert "secret" not in str(exc_info.value)


def test_non_200_hides_the_response_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        secret = json.loads(request.content.decode())["prompt"]
        return httpx.Response(503, text=secret)

    provider = _provider(transport=httpx.MockTransport(handler))

    with pytest.raises(LLMError) as exc_info:
        provider.generate("do-not-leak")

    assert str(exc_info.value) == "Model request failed with status 503."
    assert "do-not-leak" not in str(exc_info.value)


@pytest.mark.parametrize(
    ("response", "match"),
    [
        (httpx.Response(200, text="not-json"), "malformed response"),
        (httpx.Response(200, json={"done": True}), "malformed response"),
        (httpx.Response(200, json=["nope"]), "malformed response"),
        (httpx.Response(200, json={"response": "", "done": True}), "empty response"),
        (httpx.Response(200, json={"response": "partial", "done": False}), "malformed response"),
    ],
)
def test_malformed_responses(response: httpx.Response, match: str) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return response

    provider = _provider(transport=httpx.MockTransport(handler))

    with pytest.raises(LLMError, match=match):
        provider.generate("hello")


def test_invalid_base_url_fails_before_a_request() -> None:
    with pytest.raises(LLMError, match="base URL is invalid"):
        OllamaProvider(base_url="ftp://example.test", model=_MODEL, timeout_seconds=1)


def test_timeout_must_be_positive() -> None:
    with pytest.raises(LLMError, match="greater than zero"):
        OllamaProvider(base_url=_BASE, model=_MODEL, timeout_seconds=0)
