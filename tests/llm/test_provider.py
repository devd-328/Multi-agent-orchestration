import inspect

from orchestration.llm.provider import LLMProvider


def test_provider_protocol_declares_generate() -> None:
    signature = inspect.signature(LLMProvider.generate)
    assert list(signature.parameters) == ["self", "prompt"]
    assert signature.return_annotation is str
