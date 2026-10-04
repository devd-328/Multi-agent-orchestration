import pytest

from orchestration.state import (
    AgentId,
    StateError,
    StateUpdateError,
    Task,
    TaskResult,
    TaskStatus,
    append_errors,
    merge_results,
    merge_tasks,
)


def _task(task_id: str, *, status: TaskStatus = TaskStatus.PENDING) -> Task:
    error = "timeout" if status is TaskStatus.FAILED else None
    return Task(
        id=task_id,
        description=f"Do {task_id}",
        assigned_agent=AgentId.RESEARCH,
        status=status,
        error=error,
    )


def _result(task_id: str, output: str = "found") -> TaskResult:
    return TaskResult(
        task_id=task_id,
        agent=AgentId.RESEARCH,
        output=output,
        sources=["https://example.test/source"],
        status=TaskStatus.DONE,
    )


def test_tasks_merge_by_id_without_dropping_others() -> None:
    original = [_task("a"), _task("b")]
    updated = _task("b", status=TaskStatus.RUNNING)

    merged = merge_tasks(original, [updated])

    assert [task.id for task in merged] == ["a", "b"]
    assert merged[0].status is TaskStatus.PENDING
    assert merged[1].status is TaskStatus.RUNNING
    assert original[1].status is TaskStatus.PENDING


def test_results_merge_by_task_id_and_replace_one_entry() -> None:
    first = merge_results({}, {"a": _result("a", "one")})
    second = merge_results(first, {"b": _result("b", "two"), "a": _result("a", "replaced")})

    assert set(second) == {"a", "b"}
    assert second["a"].output == "replaced"
    assert second["b"].output == "two"
    assert first["a"].output == "one"


def test_errors_append() -> None:
    first = StateError(source=AgentId.RESEARCH.value, message="timeout", task_id="a")
    second = StateError(source=AgentId.REVIEWER.value, message="missing source", task_id="a")

    assert append_errors([first], [second]) == [first, second]


def test_partial_result_is_rejected_and_not_stored() -> None:
    secret = "super-secret-output"
    existing = {"a": _result("a")}

    with pytest.raises(StateUpdateError) as exc_info:
        merge_results(existing, {"b": {"task_id": "b", "output": secret, "sources": []}})

    message = str(exc_info.value)
    assert "results.b.agent" in message
    assert secret not in message
    assert set(existing) == {"a"}


def test_result_key_must_match_task_id() -> None:
    with pytest.raises(StateUpdateError, match="task_id does not match"):
        merge_results({}, {"a": _result("b")})


def test_invalid_error_is_rejected() -> None:
    with pytest.raises(StateUpdateError, match="errors.message"):
        append_errors([], [{"source": "research", "message": "   "}])
