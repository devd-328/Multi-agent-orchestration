import json
from urllib.parse import urlsplit, urlunsplit

import httpx

from orchestration.llm.errors import LLMError

# Non-streaming generate: POST {base}/api/generate with stream false.
# The completion text is the response field. Checked against the Ollama API
# document "Generate a completion" (request with stream false).


class OllamaProvider:
    """LLMProvider adapter for one configured model endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise LLMError("Model request timeout must be greater than zero.")
        if not isinstance(model, str) or not model.strip():
            raise LLMError("Model name is missing.")
        self._url = _generate_url(base_url)
        self._model = model.strip()
        self._timeout = timeout_seconds
        self._transport = transport

    def generate(self, prompt: str) -> str:
        """Return completion text for one prompt."""
        if not isinstance(prompt, str) or not prompt.strip():
            raise LLMError("Model prompt is empty.")
        payload = {"model": self._model, "prompt": prompt, "stream": False}
        try:
            with httpx.Client(transport=self._transport, timeout=self._timeout) as client:
                response = client.post(self._url, json=payload)
        except httpx.TimeoutException:
            raise LLMError("Model request timed out.") from None
        except httpx.HTTPError:
            raise LLMError("Model provider is unreachable.") from None
        if response.status_code != 200:
            raise LLMError(f"Model request failed with status {response.status_code}.")
        return _completion_text(response)


def _generate_url(base_url: str) -> str:
    if not isinstance(base_url, str):
        raise LLMError("Model base URL is invalid.")
    parsed = urlsplit(base_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise LLMError("Model base URL is invalid.")
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, f"{path}/api/generate", "", ""))


def _completion_text(response: httpx.Response) -> str:
    try:
        body = response.json()
    except json.JSONDecodeError:
        raise LLMError("Model provider returned a malformed response.") from None
    if not isinstance(body, dict) or body.get("done") is False:
        raise LLMError("Model provider returned a malformed response.")
    text = body.get("response")
    if not isinstance(text, str):
        raise LLMError("Model provider returned a malformed response.")
    if not text.strip():
        raise LLMError("Model provider returned an empty response.")
    return text
