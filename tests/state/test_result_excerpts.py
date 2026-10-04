import pytest
from pydantic import ValidationError

from orchestration.state import AgentId, TaskResult, TaskStatus, merge_results


def _result(**overrides: object) -> TaskResult:
    values: dict[str, object] = {
        "task_id": "t1",
        "agent": AgentId.RESEARCH,
        "output": "Fact [1].",
        "sources": ["[1] Title (https://a.example.test)"],
        "excerpts": ["Excerpt text."],
        "status": TaskStatus.DONE,
    }
    values.update(overrides)
    return TaskResult.model_validate(values)


def test_excerpts_default_to_empty_so_existing_results_stay_valid() -> None:
    result = TaskResult(task_id="t1", agent=AgentId.RESEARCH, output="ok", status=TaskStatus.DONE)

    assert result.excerpts == []


def test_excerpts_must_match_sources_one_to_one() -> None:
    with pytest.raises(ValidationError):
        _result(excerpts=["one", "two"])


def test_excerpts_may_be_absent_or_contain_empty_text() -> None:
    assert _result(excerpts=[]).excerpts == []
    assert _result(excerpts=[""]).excerpts == [""]


def test_excerpts_survive_the_results_reducer() -> None:
    merged = merge_results({}, {"t1": _result()})

    assert merged["t1"].excerpts == ["Excerpt text."]
