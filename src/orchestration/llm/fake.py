from collections.abc import Sequence

from orchestration.llm.errors import LLMError


class FakeLLMProvider:
    """Deterministic provider for tests. Responses are returned in order."""

    def __init__(self, responses: Sequence[str | Exception]) -> None:
        self._responses = list(responses)
        self.calls: list[str] = []

    def generate(self, prompt: str) -> str:
        """Return the next scripted response and record the prompt."""
        self.calls.append(prompt)
        if not self._responses:
            raise LLMError("No scripted model response is left.")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        if not isinstance(item, str):
            raise LLMError("Scripted model response is not text.")
        return item
