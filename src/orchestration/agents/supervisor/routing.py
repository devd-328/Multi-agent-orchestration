from enum import StrEnum

from orchestration.state.errors import StateUpdateError
from orchestration.state.helpers import block_downstream, ready_tasks
from orchestration.state.models import ReviewVerdict, RunStatus, TaskStatus
from orchestration.state.schema import AgentState


class SupervisorRoute(StrEnum):
    """Next step chosen by the Supervisor. Routing does not call a model."""

    RUN = "run"
    REVIEW = "review"
    REVISE = "revise"
    FAIL = "fail"
    FINISH = "finish"


def route(state: AgentState, *, max_review_revisions: int) -> SupervisorRoute:
    """Choose the next step from state.

    `revise` and `rejected` both return to the Supervisor while the revision
    limit remains. A failed task fails the run even when other tasks are ready.
    """

    if max_review_revisions < 1:
        raise StateUpdateError("max_review_revisions must be at least 1.")
    if state["status"] is RunStatus.FAILED:
        return SupervisorRoute.FAIL

    tasks = block_downstream(state["tasks"])
    if any(task.status is TaskStatus.FAILED for task in tasks):
        return SupervisorRoute.FAIL

    review = state["review"]
    if review is not None:
        if review.verdict is ReviewVerdict.APPROVED:
            return SupervisorRoute.FINISH
        if review.verdict in {ReviewVerdict.REVISE, ReviewVerdict.REJECTED}:
            if review.revision_count >= max_review_revisions:
                return SupervisorRoute.FAIL
            return SupervisorRoute.REVISE

    if tasks and all(task.status is TaskStatus.DONE for task in tasks):
        return SupervisorRoute.REVIEW
    if ready_tasks(tasks):
        return SupervisorRoute.RUN
    return SupervisorRoute.FAIL
