import pytest

from orchestration.state import (
    AgentId,
    PlanValidationError,
    Task,
    TaskStatus,
    validate_task_plan,
)


def _raw(task_id: str, **overrides: object) -> dict[str, object]:
    task: dict[str, object] = {
        "id": task_id,
        "description": f"Do {task_id}",
        "assigned_agent": AgentId.RESEARCH.value,
    }
    task.update(overrides)
    return task


def test_validate_accepts_a_small_plan() -> None:
    plan = validate_task_plan(
        [
            _raw("a"),
            _raw("b", depends_on=["a"], assigned_agent=AgentId.REVIEWER.value),
        ]
    )

    assert [task.id for task in plan] == ["a", "b"]
    assert plan[1].assigned_agent is AgentId.REVIEWER
    assert plan[0].status is TaskStatus.PENDING


def test_empty_plan_is_rejected() -> None:
    with pytest.raises(PlanValidationError, match="Task plan is empty"):
        validate_task_plan([])


def test_duplicate_task_ids_are_rejected() -> None:
    with pytest.raises(PlanValidationError, match="Duplicate task id 'a'"):
        validate_task_plan([_raw("a"), _raw("a")])


def test_unknown_agent_is_rejected() -> None:
    with pytest.raises(PlanValidationError, match="Unknown agent 'content' on task 'a'"):
        validate_task_plan([_raw("a", assigned_agent="content")])


def test_missing_dependency_is_rejected() -> None:
    with pytest.raises(PlanValidationError, match="depends on missing task 'missing'"):
        validate_task_plan([_raw("a", depends_on=["missing"])])


def test_self_cycle_is_rejected() -> None:
    with pytest.raises(PlanValidationError, match="cycle: a -> a"):
        validate_task_plan([_raw("a", depends_on=["a"])])


def test_longer_cycle_is_rejected() -> None:
    with pytest.raises(PlanValidationError, match="cycle: a -> b -> c -> a"):
        validate_task_plan(
            [
                _raw("a", depends_on=["b"]),
                _raw("b", depends_on=["c"]),
                _raw("c", depends_on=["a"]),
            ]
        )


def test_duplicate_dependency_is_rejected() -> None:
    with pytest.raises(PlanValidationError, match="lists dependency 'a' more than once"):
        validate_task_plan([_raw("a"), _raw("b", depends_on=["a", "a"])])


def test_partial_task_is_rejected_without_input_values() -> None:
    secret = "super-secret-input"
    with pytest.raises(PlanValidationError) as exc_info:
        validate_task_plan(
            [
                {
                    "id": "a",
                    "assigned_agent": AgentId.RESEARCH.value,
                    "inputs": {"note": secret},
                }
            ]
        )

    message = str(exc_info.value)
    assert "description" in message
    assert secret not in message


def test_existing_task_models_are_accepted() -> None:
    task = Task(id="a", description="Look up", assigned_agent=AgentId.SUPERVISOR)
    assert validate_task_plan([task]) == [task]
