import pytest

from orchestration.agents.supervisor import SupervisorRoute, route
from orchestration.state import (
    AgentId,
    AgentState,
    Review,
    ReviewVerdict,
    RunStatus,
    StateUpdateError,
    Task,
    TaskStatus,
)


def _task(
    task_id: str,
    *depends_on: str,
    status: TaskStatus = TaskStatus.PENDING,
    error: str | None = None,
) -> Task:
    return Task(
        id=task_id,
        description=f"Do {task_id}",
        assigned_agent=AgentId.RESEARCH,
        depends_on=list(depends_on),
        status=status,
        error=error,
    )


def _state(
    tasks: list[Task],
    *,
    status: RunStatus = RunStatus.RUNNING,
    review: Review | None = None,
) -> AgentState:
    return {
        "goal": "Research upcoming technology events.",
        "tasks": tasks,
        "results": {},
        "review": review,
        "final_output": None,
        "errors": [],
        "status": status,
    }


def _review(verdict: ReviewVerdict, count: int) -> Review:
    issues = [] if verdict is ReviewVerdict.APPROVED else ["missing source"]
    return Review(verdict=verdict, issues=issues, revision_count=count)


@pytest.mark.parametrize(
    ("state", "limit", "expected"),
    [
        pytest.param(_state([_task("a")]), 2, SupervisorRoute.RUN, id="ready"),
        pytest.param(
            _state([_task("a", status=TaskStatus.DONE), _task("b", "a")]),
            2,
            SupervisorRoute.RUN,
            id="ready-after-dependency",
        ),
        pytest.param(
            _state([_task("a", status=TaskStatus.DONE), _task("b", status=TaskStatus.DONE)]),
            2,
            SupervisorRoute.REVIEW,
            id="all-done",
        ),
        pytest.param(
            _state(
                [_task("a", status=TaskStatus.DONE)],
                review=_review(ReviewVerdict.REVISE, 1),
            ),
            2,
            SupervisorRoute.REVISE,
            id="revise-under-limit",
        ),
        pytest.param(
            _state(
                [_task("a", status=TaskStatus.DONE)],
                review=_review(ReviewVerdict.REJECTED, 1),
            ),
            2,
            SupervisorRoute.REVISE,
            id="rejected-under-limit",
        ),
        pytest.param(
            _state(
                [_task("a", status=TaskStatus.DONE)],
                review=_review(ReviewVerdict.APPROVED, 0),
            ),
            2,
            SupervisorRoute.FINISH,
            id="approved",
        ),
        pytest.param(
            _state(
                [_task("a", status=TaskStatus.FAILED, error="timeout")],
            ),
            2,
            SupervisorRoute.FAIL,
            id="task-failed",
        ),
        pytest.param(
            _state(
                [
                    _task("a", status=TaskStatus.FAILED, error="timeout"),
                    _task("b"),
                ]
            ),
            2,
            SupervisorRoute.FAIL,
            id="failed-task-blocks-other-ready-work",
        ),
        pytest.param(
            _state(
                [
                    _task("a", status=TaskStatus.FAILED, error="timeout"),
                    _task("b", "a"),
                ]
            ),
            2,
            SupervisorRoute.FAIL,
            id="failed-and-blocked",
        ),
        pytest.param(
            _state([_task("a", status=TaskStatus.BLOCKED), _task("b", "a")]),
            2,
            SupervisorRoute.FAIL,
            id="blocked-without-ready-work",
        ),
        pytest.param(
            _state([_task("a", status=TaskStatus.BLOCKED), _task("b")]),
            2,
            SupervisorRoute.RUN,
            id="blocked-with-independent-ready-work",
        ),
        pytest.param(
            _state(
                [_task("a", status=TaskStatus.DONE)],
                review=_review(ReviewVerdict.REVISE, 2),
            ),
            2,
            SupervisorRoute.FAIL,
            id="revision-limit",
        ),
        pytest.param(
            _state(
                [_task("a", status=TaskStatus.DONE)],
                review=_review(ReviewVerdict.REJECTED, 2),
            ),
            2,
            SupervisorRoute.FAIL,
            id="rejected-at-limit",
        ),
        pytest.param(
            _state([_task("a")], status=RunStatus.FAILED),
            2,
            SupervisorRoute.FAIL,
            id="run-already-failed",
        ),
        pytest.param(_state([]), 2, SupervisorRoute.FAIL, id="empty-plan"),
        pytest.param(
            _state([_task("a", status=TaskStatus.RUNNING)]),
            2,
            SupervisorRoute.FAIL,
            id="running-and-nothing-ready",
        ),
        pytest.param(
            _state([_task("a", status=TaskStatus.SKIPPED)]),
            2,
            SupervisorRoute.FAIL,
            id="skipped-and-nothing-ready",
        ),
    ],
)
def test_route(state: AgentState, limit: int, expected: SupervisorRoute) -> None:
    assert route(state, max_review_revisions=limit) is expected


def test_route_does_not_mutate_tasks() -> None:
    pending = _task("b", "a")
    state = _state([_task("a", status=TaskStatus.FAILED, error="timeout"), pending])

    assert route(state, max_review_revisions=2) is SupervisorRoute.FAIL

    assert pending.status is TaskStatus.PENDING


def test_revision_limit_below_one_is_rejected() -> None:
    with pytest.raises(StateUpdateError, match="max_review_revisions must be at least 1"):
        route(_state([_task("a")]), max_review_revisions=0)
