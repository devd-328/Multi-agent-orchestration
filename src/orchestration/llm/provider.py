from typing import Protocol


class LLMProvider(Protocol):
    """Model call used by agents. Adapters live behind this interface."""

    def generate(self, prompt: str) -> str:
        """Return generated text for one prompt."""
        ...
