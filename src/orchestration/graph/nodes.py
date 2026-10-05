import functools
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from orchestration.agents.reviewer import ReviewerLimits, review_results
from orchestration.agents.supervisor import plan as plan_goal
from orchestration.core.config import Settings
from orchestration.core.logging import run_id_var
from orchestration.graph.finalize import build_final_output
from orchestration.graph.runners import TaskRunner
from orchestration.llm import LLMProvider
from orchestration.state.helpers import block_downstream, ready_tasks, record_task_failure
from orchestration.state.models import (
    REVIEW_FEEDBACK_INPUT,
    ReviewVerdict,
    RunStatus,
    StateError,
    Task,
    TaskResult,
    TaskStatus,
)
from orchestration.state.reducers import merge_tasks
from orchestration.state.registry import AgentId
from orchestration.state.schema import AgentState

logger = logging.getLogger(__name__)

WORKFLOW_SOURCE = "workflow"
MAX_FEEDBACK_CHARS = 1_000
_MAX_LISTED_TASKS = 5
_MAX_LISTED_ID_CHARS = 40

NodeUpdate = dict[str, Any]

_BLOCKING_PREFIX = "[blocking] task "


@dataclass(frozen=True)
class WorkflowContext:
    """Everything a node needs besides the state. Built once per run."""

    settings: Settings
    llm: LLMProvider
    reviewer_llm: LLMProvider
    runners: Mapping[AgentId, TaskRunner]
    run_id: str


def _node(name: str) -> Callable[[Callable[..., NodeUpdate]], Callable[..., NodeUpdate]]:
    """Time a node and log its name, resulting status, task counts, and duration.

    The log never carries the goal, summaries, excerpts, prompts, or keys.
    """

    def decorate(method: Callable[..., NodeUpdate]) -> Callable[..., NodeUpdate]:
        @functools.wraps(method)
        def wrapper(self: "WorkflowNodes", state: AgentState) -> NodeUpdate:
            token = run_id_var.set(self.ctx.run_id)
            started = time.monotonic()
            try:
                try:
                    update = method(self, state)
                except Exception as exc:
                    logger.error(
                        "workflow_node_error",
                        extra={
                            "run_id": self.ctx.run_id,
                            "node": name,
                            "error_type": type(exc).__name__,
                        },
                    )
                    raise
                _log_node(self.ctx.run_id, name, state, update, started)
                return update
            finally:
                run_id_var.reset(token)

        return wrapper

    return decorate


def _log_node(
    run_id: str,
    name: str,
    state: AgentState,
    update: NodeUpdate,
    started: float,
) -> None:
    tasks = list(state["tasks"])
    if "tasks" in update:
        tasks = merge_tasks(tasks, update["tasks"])
    status = update.get("status", state["status"])

    def count(task_status: TaskStatus) -> int:
        return sum(1 for task in tasks if task.status is task_status)

    logger.info(
        "workflow_node",
        extra={
            "run_id": run_id,
            "node": name,
            "status": status.value,
            "task_count": len(tasks),
            "pending_count": count(TaskStatus.PENDING),
            "done_count": count(TaskStatus.DONE),
            "failed_count": count(TaskStatus.FAILED),
            "blocked_count": count(TaskStatus.BLOCKED),
            "duration_ms": round((time.monotonic() - started) * 1000),
        },
    )


class WorkflowNodes:
    """The graph nodes. Each takes the state and returns a partial update.

    Nodes do the work and never choose the next node. The Supervisor's `route`
    does that (see `graph.build`).
    """

    def __init__(self, ctx: WorkflowContext) -> None:
        self.ctx = ctx

    @_node("plan")
    def plan(self, state: AgentState) -> NodeUpdate:
        return dict(
            plan_goal(
                state,
                provider=self.ctx.llm,
                max_plan_attempts=self.ctx.settings.max_plan_attempts,
            )
        )

    @_node("run_tasks")
    def run_tasks(self, state: AgentState) -> NodeUpdate:
        """Run every ready task once, one at a time, in plan order."""
        order = [task.id for task in state["tasks"]]
        current = {task.id: task for task in state["tasks"]}
        results = dict(state["results"])
        new_results: dict[str, TaskResult] = {}
        new_errors: list[StateError] = []

        for task in ready_tasks(state["tasks"]):
            outcome = self._run_one(task, results)
            current[task.id] = outcome.task
            if outcome.result is not None:
                results[task.id] = outcome.result
                new_results[task.id] = outcome.result
            new_errors.extend(outcome.errors)

        tasks = block_downstream([current[task_id] for task_id in order])
        return {"tasks": tasks, "results": new_results, "errors": new_errors}

    @_node("review")
    def review(self, state: AgentState) -> NodeUpdate:
        return dict(
            review_results(
                state,
                provider=self.ctx.reviewer_llm,
                limits=ReviewerLimits.from_settings(self.ctx.settings),
            )
        )

    @_node("revise")
    def revise(self, state: AgentState) -> NodeUpdate:
        """Re-open the tasks the Reviewer's blocking issues name, with that feedback.

        No re-plan and no deleted tasks. Reopened tasks get `attempts` back at 0,
        because a revision pass is bounded by `max_review_revisions`, not by the
        failure-retry limit.
        """
        review = state["review"]
        feedback = _feedback_by_task(review.issues if review is not None else [], state["tasks"])
        reopened: list[Task] = []
        for task in state["tasks"]:
            lines = feedback.get(task.id)
            if lines is None or task.status is not TaskStatus.DONE:
                continue
            inputs = {**task.inputs, REVIEW_FEEDBACK_INPUT: _join_feedback(lines)}
            reopened.append(
                task.model_copy(
                    update={
                        "status": TaskStatus.PENDING,
                        "attempts": 0,
                        "error": None,
                        "inputs": inputs,
                    }
                )
            )
        if not reopened:
            return _failure_update(
                "The review asked for changes that name no finished task, "
                "so there is nothing to re-run."
            )
        return {"tasks": reopened, "status": RunStatus.RUNNING}

    @_node("finalize")
    def finalize(self, state: AgentState) -> NodeUpdate:
        """Build the final answer. Only an approved review gets here with output."""
        review = state["review"]
        if review is None or review.verdict is not ReviewVerdict.APPROVED:
            return _failure_update("The results were not approved, so no final answer was made.")
        try:
            output = build_final_output(state["tasks"], state["results"])
        except ValueError:
            return _failure_update("A task has no finished result, so no final answer was made.")
        return {"final_output": output, "status": RunStatus.DONE}

    @_node("fail")
    def fail(self, state: AgentState) -> NodeUpdate:
        return _failure_update(_failure_reason(state))

    def _run_one(self, task: Task, results: Mapping[str, TaskResult]) -> "_Outcome":
        runner = self.ctx.runners.get(task.assigned_agent)
        if runner is None:
            return _failed_outcome(
                task,
                f"No runner is registered for agent '{task.assigned_agent.value}'.",
                max_attempts=1,
            )
        try:
            update = runner(task, results)
        except Exception as exc:
            return _failed_outcome(
                task,
                f"Task runner failed ({type(exc).__name__}).",
                max_attempts=self.ctx.settings.max_task_attempts,
            )
        updated = next((item for item in update.get("tasks", []) if item.id == task.id), None)
        if updated is None:
            return _failed_outcome(
                task,
                "Task runner returned no update for its task.",
                max_attempts=self.ctx.settings.max_task_attempts,
            )
        return _Outcome(
            task=updated,
            result=update.get("results", {}).get(task.id),
            errors=list(update.get("errors", [])),
        )


@dataclass(frozen=True)
class _Outcome:
    task: Task
    result: TaskResult | None
    errors: list[StateError]


def _failed_outcome(task: Task, message: str, *, max_attempts: int) -> _Outcome:
    updated = record_task_failure(task, message, max_attempts=max_attempts)
    result = TaskResult(
        task_id=task.id,
        agent=task.assigned_agent,
        status=TaskStatus.FAILED,
        error=message,
    )
    error = StateError(source=WORKFLOW_SOURCE, message=message, task_id=task.id)
    return _Outcome(task=updated, result=result, errors=[error])


def _feedback_by_task(issues: list[str], tasks: list[Task]) -> dict[str, list[str]]:
    """Group blocking issue text by the task it names.

    Issues are stored as `[blocking] task <id>: <text>`. The longest matching id
    wins, so an id that contains another id is not mistaken for it.
    """
    by_length = sorted((task.id for task in tasks), key=len, reverse=True)
    grouped: dict[str, list[str]] = {}
    for issue in issues:
        for task_id in by_length:
            prefix = f"{_BLOCKING_PREFIX}{task_id}: "
            if issue.startswith(prefix):
                grouped.setdefault(task_id, []).append(issue[len(prefix) :])
                break
    return grouped


def _join_feedback(lines: list[str]) -> str:
    return "\n".join(f"- {line}" for line in lines)[:MAX_FEEDBACK_CHARS]


def _failure_update(message: str) -> NodeUpdate:
    return {
        "status": RunStatus.FAILED,
        "final_output": None,
        "errors": [StateError(source=WORKFLOW_SOURCE, message=message)],
    }


def _failure_reason(state: AgentState) -> str:
    """Say why the run failed, using task ids and counts only."""
    failed = [task.id for task in state["tasks"] if task.status is TaskStatus.FAILED]
    if failed:
        blocked = [task.id for task in state["tasks"] if task.status is TaskStatus.BLOCKED]
        text = f"Run failed because {_listed_tasks(failed)} failed"
        if blocked:
            text += f" and {_listed_tasks(blocked)} could not run"
        return text + "."
    if state["errors"]:
        return "Run failed. See the recorded errors."
    review = state["review"]
    if review is not None and review.verdict is not ReviewVerdict.APPROVED:
        return (
            f"Run failed because the review did not approve the results "
            f"after {review.revision_count} revisions."
        )
    return "Run failed."


def _listed_tasks(task_ids: list[str]) -> str:
    shown = [task_id[:_MAX_LISTED_ID_CHARS] for task_id in task_ids[:_MAX_LISTED_TASKS]]
    extra = len(task_ids) - len(shown)
    label = "task " if len(task_ids) == 1 else "tasks "
    text = label + ", ".join(shown)
    return text + (f" and {extra} more" if extra > 0 else "")


__all__ = [
    "MAX_FEEDBACK_CHARS",
    "WORKFLOW_SOURCE",
    "WorkflowContext",
    "WorkflowNodes",
]
