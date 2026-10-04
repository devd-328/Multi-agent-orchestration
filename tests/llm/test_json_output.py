import pytest

from orchestration.llm.json_output import JsonOutputError, extract_json


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"a": 1}', {"a": 1}),
        ('  {"a": 1}  ', {"a": 1}),
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ('```JSON {"a": 1} ```', {"a": 1}),
        ('```\n{"a": 1}\n```', {"a": 1}),
        ('Here you go:\n{"a": 1}\nHope that helps.', {"a": 1}),
        ("[1, 2]", [1, 2]),
    ],
)
def test_extracts_json_from_common_model_output(raw: str, expected: object) -> None:
    assert extract_json(raw) == expected


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("", "Model output is empty."),
        ("   ", "Model output is empty."),
        (None, "Model output is empty."),
        ("no json here", "Model output is not valid JSON."),
        ('{"a": 1', "Model output is not valid JSON."),
    ],
)
def test_rejects_output_without_json(raw: object, message: str) -> None:
    with pytest.raises(JsonOutputError) as exc_info:
        extract_json(raw)

    assert str(exc_info.value) == message
