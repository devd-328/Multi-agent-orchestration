from typing import Protocol


class LLMProvider(Protocol):
    """Model call used by agents. Provider adapters are added in a later step."""

    def generate(self, prompt: str) -> str:
        """Return generated text for one prompt."""
        ...
