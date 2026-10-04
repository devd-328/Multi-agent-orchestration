import pytest

from orchestration.core.config import load_settings
from orchestration.state import (
    AgentId,
    PlanValidationError,
    ReviewVerdict,
    RunStatus,
    StateUpdateError,
    Task,
    TaskStatus,
    apply_review,
    block_downstream,
    ready_tasks,
    record_task_failure,
    record_task_success,
)


def _task(
    task_id: str,
    *depends_on: str,
    status: TaskStatus = TaskStatus.PENDING,
    attempts: int = 0,
    error: str | None = None,
) -> Task:
    return Task(
        id=task_id,
        description=f"Do {task_id}",
        assigned_agent=AgentId.RESEARCH,
        depends_on=list(depends_on),
        status=status,
        attempts=attempts,
        error=error,
    )


def test_ready_tasks_wait_for_dependencies() -> None:
    first = _task("a", status=TaskStatus.DONE)
    second = _task("b", "a")
    third = _task("c", "b")

    assert [task.id for task in ready_tasks([first, second, third])] == ["b"]


def test_ready_tasks_skip_non_pending_statuses() -> None:
    tasks = [
        _task("a", status=TaskStatus.RUNNING),
        _task("b", status=TaskStatus.BLOCKED),
        _task("c", status=TaskStatus.FAILED, error="timeout"),
        _task("d", status=TaskStatus.SKIPPED),
        _task("e", status=TaskStatus.DONE),
    ]

    assert ready_tasks(tasks) == []


def test_skipped_dependency_is_not_ready() -> None:
    tasks = [_task("a", status=TaskStatus.SKIPPED), _task("b", "a")]

    assert ready_tasks(tasks) == []


def test_ready_tasks_reject_a_missing_dependency() -> None:
    with pytest.raises(PlanValidationError, match="depends on missing task 'gone'"):
        ready_tasks([_task("b", "gone")])


def test_failed_task_blocks_downstream_pending_and_running() -> None:
    original = [
        _task("a", status=TaskStatus.FAILED, error="timeout"),
        _task("b", "a"),
        _task("c", "b", status=TaskStatus.RUNNING),
        _task("d"),
        _task("e", "a", status=TaskStatus.DONE),
    ]

    updated = block_downstream(original)

    assert [task.status for task in updated] == [
        TaskStatus.FAILED,
        TaskStatus.BLOCKED,
        TaskStatus.BLOCKED,
        TaskStatus.PENDING,
        TaskStatus.DONE,
    ]
    assert original[1].status is TaskStatus.PENDING
    assert ready_tasks(updated) == [updated[3]]


def test_block_downstream_leaves_an_unrelated_plan_pending() -> None:
    tasks = [_task("a"), _task("b", "a")]

    assert [task.status for task in block_downstream(tasks)] == [
        TaskStatus.PENDING,
        TaskStatus.PENDING,
    ]


def test_task_retries_stop_at_the_configured_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("MAX_TASK_ATTEMPTS", "2")
    limit = load_settings(env_file=None).max_task_attempts
    task = _task("a")

    first = record_task_failure(task, "timeout", max_attempts=limit)
    second = record_task_failure(first, "timeout", max_attempts=limit)
    third = record_task_failure(second, "still down", max_attempts=limit)

    assert first.status is TaskStatus.PENDING
    assert first.attempts == 1
    assert second.status is TaskStatus.FAILED
    assert second.attempts == 2
    assert third.status is TaskStatus.FAILED
    assert third.attempts == 2
    assert third.error == "still down"


def test_default_attempt_limit_allows_two_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAX_TASK_ATTEMPTS", raising=False)
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9")
    limit = load_settings(env_file=None).max_task_attempts
    task = _task("a")

    for _ in range(limit - 1):
        task = record_task_failure(task, "timeout", max_attempts=limit)

    assert task.status is TaskStatus.PENDING
    assert task.attempts == 2
    failed = record_task_failure(task, "timeout", max_attempts=limit)
    assert failed.status is TaskStatus.FAILED
    assert failed.attempts == 3


def test_success_within_the_limit_marks_the_task_done() -> None:
    done = record_task_success(_task("a", attempts=1), max_attempts=3)

    assert done.status is TaskStatus.DONE
    assert done.attempts == 2
    assert done.error is None


def test_success_after_the_limit_is_rejected() -> None:
    failed = _task("a", status=TaskStatus.FAILED, attempts=3, error="timeout")

    with pytest.raises(StateUpdateError, match="cannot succeed"):
        record_task_success(failed, max_attempts=3)


def test_revision_limit_fails_the_run_and_stops_the_counter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("MAX_REVIEW_REVISIONS", "2")
    limit = load_settings(env_file=None).max_review_revisions

    first = apply_review(None, ReviewVerdict.REVISE, ["missing source"], max_revisions=limit)
    second = apply_review(
        first.review,
        ReviewVerdict.REJECTED,
        ["still missing"],
        max_revisions=limit,
    )
    third = apply_review(
        second.review,
        ReviewVerdict.REVISE,
        ["again"],
        max_revisions=limit,
    )

    assert first.run_status is RunStatus.REVIEWING
    assert first.review.revision_count == 1
    assert second.run_status is RunStatus.FAILED
    assert second.review.revision_count == 2
    assert second.review.verdict is ReviewVerdict.REJECTED
    assert third.run_status is RunStatus.FAILED
    assert third.review.revision_count == 2


def test_approved_review_does_not_spend_a_revision_or_finish_the_run() -> None:
    outcome = apply_review(None, ReviewVerdict.APPROVED, [], max_revisions=2)

    assert outcome.review.verdict is ReviewVerdict.APPROVED
    assert outcome.review.revision_count == 0
    assert outcome.run_status is RunStatus.REVIEWING


def test_blank_failure_error_is_rejected() -> None:
    with pytest.raises(StateUpdateError, match="requires an error"):
        record_task_failure(_task("a"), "   ", max_attempts=3)
