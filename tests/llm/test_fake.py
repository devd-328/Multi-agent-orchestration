import pytest

from orchestration.llm import FakeLLMProvider, LLMError


def test_fake_returns_scripted_responses_in_order() -> None:
    provider = FakeLLMProvider(["first", "second"])

    assert provider.generate("prompt-a") == "first"
    assert provider.generate("prompt-b") == "second"
    assert provider.calls == ["prompt-a", "prompt-b"]


def test_fake_raises_scripted_errors() -> None:
    provider = FakeLLMProvider([LLMError("Model request timed out.")])

    with pytest.raises(LLMError, match="timed out"):
        provider.generate("prompt")

    assert provider.calls == ["prompt"]


def test_fake_fails_when_script_is_exhausted() -> None:
    provider = FakeLLMProvider([])

    with pytest.raises(LLMError, match="No scripted model response"):
        provider.generate("prompt")
