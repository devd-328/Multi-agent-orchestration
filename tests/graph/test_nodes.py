from collections.abc import Callable, Mapping

import pytest

from orchestration.core.config import Settings
from orchestration.graph.nodes import MAX_FEEDBACK_CHARS, WorkflowContext, WorkflowNodes
from orchestration.graph.runners import TaskUpdate
from orchestration.llm import FakeLLMProvider
from orchestration.state import (
    REVIEW_FEEDBACK_INPUT,
    AgentId,
    AgentState,
    Review,
    ReviewVerdict,
    RunStatus,
    Task,
    TaskResult,
    TaskStatus,
    record_task_success,
)

MakeSettings = Callable[..., Settings]


def _task(
    task_id: str,
    *depends_on: str,
    status: TaskStatus = TaskStatus.PENDING,
    agent: AgentId = AgentId.RESEARCH,
    attempts: int = 0,
) -> Task:
    return Task(
        id=task_id,
        description=f"Do {task_id}",
        assigned_agent=agent,
        depends_on=list(depends_on),
        inputs={"topic": task_id},
        status=status,
        attempts=attempts,
        error="earlier failure" if status is TaskStatus.FAILED else None,
    )


def _result(task_id: str, **overrides: object) -> TaskResult:
    values: dict[str, object] = {
        "task_id": task_id,
        "agent": AgentId.RESEARCH,
        "output": f"Summary of {task_id} [1].",
        "sources": [f"[1] Source ({task_id}.example.test)"],
        "excerpts": ["Excerpt."],
        "status": TaskStatus.DONE,
    }
    values.update(overrides)
    return TaskResult.model_validate(values)


def _state(
    tasks: list[Task],
    results: dict[str, TaskResult] | None = None,
    *,
    review: Review | None = None,
    status: RunStatus = RunStatus.RUNNING,
    errors: list | None = None,
) -> AgentState:
    return {
        "goal": "A goal",
        "tasks": tasks,
        "results": results or {},
        "review": review,
        "final_output": None,
        "errors": errors or [],
        "status": status,
    }


def _nodes(
    settings: Settings,
    runners: Mapping[AgentId, Callable[..., TaskUpdate]] | None = None,
) -> WorkflowNodes:
    llm = FakeLLMProvider([])
    return WorkflowNodes(
        WorkflowContext(
            settings=settings,
            llm=llm,
            reviewer_llm=llm,
            runners=runners or {},
            run_id="test-run",
        )
    )


def _succeeding(order: list[str]) -> Callable[..., TaskUpdate]:
    def run(task: Task, results: Mapping[str, TaskResult]) -> TaskUpdate:
        order.append(task.id)
        done = record_task_success(task, max_attempts=3)
        return {"tasks": [done], "results": {task.id: _result(task.id)}}

    return run


def _review(verdict: ReviewVerdict, *issues: str, count: int = 1) -> Review:
    return Review(verdict=verdict, issues=list(issues), revision_count=count)


# run_tasks


def test_run_tasks_runs_ready_tasks_one_at_a_time_in_plan_order(
    make_settings: MakeSettings,
) -> None:
    order: list[str] = []
    nodes = _nodes(make_settings(), {AgentId.RESEARCH: _succeeding(order)})
    state = _state([_task("a"), _task("b"), _task("c", "a")])

    update = nodes.run_tasks(state)

    assert order == ["a", "b"]
    statuses = {task.id: task.status for task in update["tasks"]}
    assert statuses == {
        "a": TaskStatus.DONE,
        "b": TaskStatus.DONE,
        "c": TaskStatus.PENDING,
    }
    assert set(update["results"]) == {"a", "b"}


def test_run_tasks_dispatches_by_the_assigned_agent(make_settings: MakeSettings) -> None:
    research_order: list[str] = []
    other_order: list[str] = []
    runners = {
        AgentId.RESEARCH: _succeeding(research_order),
        AgentId.REVIEWER: _succeeding(other_order),
    }
    nodes = _nodes(make_settings(), runners)
    state = _state([_task("a"), _task("b", agent=AgentId.REVIEWER)])

    nodes.run_tasks(state)

    assert research_order == ["a"]
    assert other_order == ["b"]


def test_a_task_with_no_runner_fails_at_once_and_blocks_dependents(
    make_settings: MakeSettings,
) -> None:
    nodes = _nodes(make_settings(max_task_attempts=3), {})
    state = _state([_task("a", agent=AgentId.REVIEWER), _task("b", "a")])

    update = nodes.run_tasks(state)

    tasks = {task.id: task for task in update["tasks"]}
    assert tasks["a"].status is TaskStatus.FAILED
    assert tasks["a"].attempts == 1
    assert tasks["b"].status is TaskStatus.BLOCKED
    assert update["results"]["a"].error == "No runner is registered for agent 'reviewer'."
    assert update["errors"][0].task_id == "a"


def test_a_runner_that_raises_is_recorded_without_its_message(
    make_settings: MakeSettings,
) -> None:
    def broken(task: Task, results: Mapping[str, TaskResult]) -> TaskUpdate:
        raise RuntimeError("secret-detail-do-not-print")

    nodes = _nodes(make_settings(max_task_attempts=3), {AgentId.RESEARCH: broken})

    update = nodes.run_tasks(_state([_task("a")]))

    (task,) = update["tasks"]
    assert task.status is TaskStatus.PENDING
    assert task.attempts == 1
    assert task.error == "Task runner failed (RuntimeError)."
    assert "secret-detail" not in repr(update)


def test_a_runner_failing_every_attempt_ends_failed(make_settings: MakeSettings) -> None:
    def broken(task: Task, results: Mapping[str, TaskResult]) -> TaskUpdate:
        raise RuntimeError("boom")

    nodes = _nodes(make_settings(max_task_attempts=2), {AgentId.RESEARCH: broken})

    first = nodes.run_tasks(_state([_task("a")]))
    second = nodes.run_tasks(_state(first["tasks"]))

    assert second["tasks"][0].status is TaskStatus.FAILED
    assert second["tasks"][0].attempts == 2


def test_a_runner_that_returns_no_update_for_its_task_is_a_failure(
    make_settings: MakeSettings,
) -> None:
    nodes = _nodes(make_settings(), {AgentId.RESEARCH: lambda task, results: {}})

    update = nodes.run_tasks(_state([_task("a")]))

    assert update["tasks"][0].error == "Task runner returned no update for its task."


def test_run_tasks_passes_earlier_results_to_the_runner(make_settings: MakeSettings) -> None:
    seen: dict[str, set[str]] = {}

    def run(task: Task, results: Mapping[str, TaskResult]) -> TaskUpdate:
        seen[task.id] = set(results)
        return {"tasks": [record_task_success(task, max_attempts=3)]}

    nodes = _nodes(make_settings(), {AgentId.RESEARCH: run})
    state = _state([_task("a", status=TaskStatus.DONE), _task("b", "a")], {"a": _result("a")})

    nodes.run_tasks(state)

    assert seen == {"b": {"a"}}


# revise


def test_revise_reopens_only_the_named_tasks_with_feedback(make_settings: MakeSettings) -> None:
    review = _review(
        ReviewVerdict.REVISE,
        "[blocking] task a: The date is wrong. Search for it again.",
        "[blocking] task a: The venue is invented. Remove it.",
        "[minor] task b: Tone could be neutral.",
        "[blocking] goal: Something about the goal as a whole.",
    )
    state = _state(
        [
            _task("a", status=TaskStatus.DONE, attempts=2),
            _task("b", status=TaskStatus.DONE, attempts=1),
        ],
        review=review,
    )

    update = _nodes(make_settings()).revise(state)

    (reopened,) = update["tasks"]
    assert reopened.id == "a"
    assert reopened.status is TaskStatus.PENDING
    assert reopened.attempts == 0
    assert reopened.error is None
    assert reopened.inputs["topic"] == "a"
    assert reopened.inputs[REVIEW_FEEDBACK_INPUT] == (
        "- The date is wrong. Search for it again.\n- The venue is invented. Remove it."
    )
    assert update["status"] is RunStatus.RUNNING
    assert "results" not in update


def test_revise_matches_the_longest_task_id(make_settings: MakeSettings) -> None:
    review = _review(ReviewVerdict.REVISE, "[blocking] task a: b: Fix the long one please.")
    state = _state(
        [_task("a", status=TaskStatus.DONE), _task("a: b", status=TaskStatus.DONE)],
        review=review,
    )

    update = _nodes(make_settings()).revise(state)

    assert [task.id for task in update["tasks"]] == ["a: b"]
    assert update["tasks"][0].inputs[REVIEW_FEEDBACK_INPUT] == "- Fix the long one please."


def test_revise_replaces_old_feedback_and_bounds_its_size(make_settings: MakeSettings) -> None:
    old = _task("a", status=TaskStatus.DONE).model_copy(
        update={"inputs": {"topic": "a", REVIEW_FEEDBACK_INPUT: "- old note"}}
    )
    review = _review(ReviewVerdict.REVISE, "[blocking] task a: " + "x" * 5000)

    update = _nodes(make_settings()).revise(_state([old], review=review))

    feedback = update["tasks"][0].inputs[REVIEW_FEEDBACK_INPUT]
    assert "old note" not in feedback
    assert len(feedback) == MAX_FEEDBACK_CHARS


@pytest.mark.parametrize(
    "issues",
    [
        ["[blocking] goal: Nothing names a task here."],
        ["[minor] task a: Only a minor note."],
        ["[blocking] task unknown: Names a task that is not in the plan."],
    ],
)
def test_revise_with_nothing_to_re_run_fails_clearly(
    make_settings: MakeSettings,
    issues: list[str],
) -> None:
    review = Review(verdict=ReviewVerdict.REVISE, issues=issues)
    state = _state([_task("a", status=TaskStatus.DONE)], review=review)

    update = _nodes(make_settings()).revise(state)

    assert update["status"] is RunStatus.FAILED
    assert update["final_output"] is None
    assert "name no finished task" in update["errors"][0].message
    assert "tasks" not in update


def test_revise_without_a_review_fails_clearly(make_settings: MakeSettings) -> None:
    state = _state([_task("a", status=TaskStatus.DONE)], review=None)

    update = _nodes(make_settings()).revise(state)

    assert update["status"] is RunStatus.FAILED
    assert "tasks" not in update


def test_revise_ignores_a_named_task_that_is_not_done(make_settings: MakeSettings) -> None:
    review = _review(ReviewVerdict.REVISE, "[blocking] task a: Fix this please.")

    update = _nodes(make_settings()).revise(
        _state([_task("a", status=TaskStatus.SKIPPED)], review=review)
    )

    assert update["status"] is RunStatus.FAILED


# finalize


@pytest.mark.parametrize(
    "review",
    [
        None,
        _review(ReviewVerdict.REVISE, "[blocking] task a: Fix it please."),
        _review(ReviewVerdict.REJECTED, "[blocking] task a: Unusable output."),
    ],
    ids=["no-review", "revise", "rejected"],
)
def test_finalize_without_an_approved_review_makes_no_output(
    make_settings: MakeSettings,
    review: Review | None,
) -> None:
    state = _state(
        [_task("a", status=TaskStatus.DONE)],
        {"a": _result("a")},
        review=review,
    )

    update = _nodes(make_settings()).finalize(state)

    assert update["status"] is RunStatus.FAILED
    assert update["final_output"] is None
    assert "not approved" in update["errors"][0].message


def test_finalize_with_an_approved_review_builds_the_answer(make_settings: MakeSettings) -> None:
    state = _state(
        [_task("a", status=TaskStatus.DONE)],
        {"a": _result("a")},
        review=_review(ReviewVerdict.APPROVED, count=0),
    )

    update = _nodes(make_settings()).finalize(state)

    assert update["status"] is RunStatus.DONE
    assert "Summary of a [1]." in update["final_output"]


def test_finalize_refuses_when_a_task_has_no_finished_result(
    make_settings: MakeSettings,
) -> None:
    state = _state(
        [_task("a", status=TaskStatus.DONE), _task("b", status=TaskStatus.DONE)],
        {"a": _result("a")},
        review=_review(ReviewVerdict.APPROVED, count=0),
    )

    update = _nodes(make_settings()).finalize(state)

    assert update["status"] is RunStatus.FAILED
    assert update["final_output"] is None


# fail


def test_fail_names_the_failed_and_blocked_tasks_only_by_id(make_settings: MakeSettings) -> None:
    state = _state(
        [
            _task("a", status=TaskStatus.FAILED),
            _task("b", "a", status=TaskStatus.BLOCKED),
            _task("c", "a", status=TaskStatus.BLOCKED),
        ],
        {"a": _result("a", status=TaskStatus.FAILED, error="private detail", output="")},
    )

    update = _nodes(make_settings()).fail(state)

    assert update["status"] is RunStatus.FAILED
    assert update["final_output"] is None
    (error,) = update["errors"]
    assert error.source == "workflow"
    assert error.message == "Run failed because task a failed and tasks b, c could not run."
    assert "private detail" not in error.message


def test_fail_always_leaves_a_clear_error(make_settings: MakeSettings) -> None:
    update = _nodes(make_settings()).fail(_state([], status=RunStatus.FAILED))

    assert update["errors"][0].message == "Run failed."
