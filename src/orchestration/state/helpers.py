from collections.abc import Mapping, Sequence

from pydantic import ValidationError

from orchestration.state.errors import PlanValidationError, StateUpdateError
from orchestration.state.models import (
    Review,
    ReviewOutcome,
    ReviewVerdict,
    RunStatus,
    Task,
    TaskStatus,
)
from orchestration.state.registry import AgentId, known_agent_ids


def validate_task_plan(tasks: Sequence[Task | Mapping[str, object]]) -> list[Task]:
    """Return a validated plan or raise PlanValidationError.

    Checks, in order: the plan is non-empty, each task is valid, ids are unique,
    dependencies are unique and exist, and dependencies are acyclic.
    """

    if not tasks:
        raise PlanValidationError("Task plan is empty.")
    parsed = [_coerce_task(item, index) for index, item in enumerate(tasks)]
    _reject_duplicate_task_ids(parsed)
    by_id = {task.id: task for task in parsed}
    for task in parsed:
        _reject_duplicate_dependencies(task)
        for dependency_id in task.depends_on:
            if dependency_id not in by_id:
                raise PlanValidationError(
                    f"Task '{task.id}' depends on missing task '{dependency_id}'."
                )
    cycle = _find_cycle(parsed)
    if cycle is not None:
        path = " -> ".join(cycle)
        raise PlanValidationError(f"Task plan has a cycle: {path}.")
    return parsed


def ready_tasks(tasks: Sequence[Task]) -> list[Task]:
    """Return pending tasks whose dependencies are all done."""

    by_id = _index_tasks(tasks)
    ready: list[Task] = []
    for task in tasks:
        if task.status is not TaskStatus.PENDING:
            continue
        dependencies_done = all(
            _dependency_status(by_id, task.id, dependency_id) is TaskStatus.DONE
            for dependency_id in task.depends_on
        )
        if dependencies_done:
            ready.append(task)
    return ready


def block_downstream(tasks: Sequence[Task]) -> list[Task]:
    """Mark pending and running descendants of a failed task as blocked.

    Done, skipped, and failed tasks keep their status. Descendants are reached
    through `depends_on`, so a later task cannot stay pending after an upstream
    failure.
    """

    by_id = _index_tasks(tasks)
    dependents: dict[str, list[str]] = {task_id: [] for task_id in by_id}
    for task in tasks:
        for dependency_id in task.depends_on:
            dependents[dependency_id].append(task.id)
    seen = {task.id for task in tasks if task.status is TaskStatus.FAILED}
    queue = list(seen)
    downstream: set[str] = set()
    while queue:
        current = queue.pop()
        for child_id in dependents[current]:
            if child_id in seen:
                continue
            seen.add(child_id)
            downstream.add(child_id)
            queue.append(child_id)
    updated: list[Task] = []
    for task in tasks:
        if task.id in downstream and task.status in {TaskStatus.PENDING, TaskStatus.RUNNING}:
            updated.append(task.model_copy(update={"status": TaskStatus.BLOCKED}))
        else:
            updated.append(task)
    return updated


def record_task_failure(task: Task, error: str, *, max_attempts: int) -> Task:
    """Count one failed attempt. At the limit the task status becomes failed.

    A later call does not increment `attempts`. The task does not return to pending.
    """

    _check_limit(max_attempts, "max_task_attempts")
    message = error.strip()
    if not message:
        raise StateUpdateError(f"Task '{task.id}' failure requires an error.")
    if task.status in {TaskStatus.DONE, TaskStatus.SKIPPED, TaskStatus.BLOCKED}:
        raise StateUpdateError(
            f"Task '{task.id}' cannot record a failure from status '{task.status.value}'."
        )
    if task.attempts >= max_attempts:
        return task.model_copy(update={"status": TaskStatus.FAILED, "error": message})
    attempts = task.attempts + 1
    status = TaskStatus.FAILED if attempts >= max_attempts else TaskStatus.PENDING
    return task.model_copy(update={"attempts": attempts, "status": status, "error": message})


def record_task_success(task: Task, *, max_attempts: int) -> Task:
    """Count one successful attempt. A task already at the failure limit stays failed."""

    _check_limit(max_attempts, "max_task_attempts")
    if task.status in {TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.SKIPPED}:
        raise StateUpdateError(
            f"Task '{task.id}' cannot succeed from status '{task.status.value}'."
        )
    if task.attempts >= max_attempts:
        raise StateUpdateError(
            f"Task '{task.id}' has reached max_task_attempts ({max_attempts})."
        )
    return task.model_copy(
        update={"attempts": task.attempts + 1, "status": TaskStatus.DONE, "error": None}
    )


def apply_review(
    review: Review | None,
    verdict: ReviewVerdict,
    issues: list[str],
    *,
    max_revisions: int,
) -> ReviewOutcome:
    """Record a review. Revise and rejected share one bounded counter.

    When `revision_count` reaches `max_revisions`, `run_status` becomes failed
    and the counter stops. Approved does not increment the counter and does not
    mark the run done, because the writer of `final_output` is still TBD.
    """

    _check_limit(max_revisions, "max_review_revisions")
    current = 0 if review is None else review.revision_count
    if verdict is ReviewVerdict.APPROVED:
        recorded = Review(verdict=verdict, issues=list(issues), revision_count=current)
        return ReviewOutcome(review=recorded, run_status=RunStatus.REVIEWING)
    if current >= max_revisions:
        recorded = Review(verdict=verdict, issues=list(issues), revision_count=current)
        return ReviewOutcome(review=recorded, run_status=RunStatus.FAILED)
    revision_count = current + 1
    run_status = RunStatus.FAILED if revision_count >= max_revisions else RunStatus.REVIEWING
    recorded = Review(verdict=verdict, issues=list(issues), revision_count=revision_count)
    return ReviewOutcome(review=recorded, run_status=run_status)


def _check_limit(limit: int, name: str) -> None:
    if limit < 1:
        raise StateUpdateError(f"{name} must be at least 1.")


def _coerce_task(item: Task | Mapping[str, object], index: int) -> Task:
    if isinstance(item, Task):
        return item
    if not isinstance(item, Mapping):
        raise PlanValidationError(f"Task at index {index} must be an object.")
    task_id = item.get("id")
    label = task_id.strip() if isinstance(task_id, str) and task_id.strip() else f"index {index}"
    agent = item.get("assigned_agent")
    if isinstance(agent, AgentId):
        agent_value = agent.value
    else:
        agent_value = agent
    if isinstance(agent_value, str) and agent_value not in known_agent_ids():
        raise PlanValidationError(f"Unknown agent '{agent_value}' on task '{label}'.")
    try:
        return Task.model_validate(item)
    except ValidationError as exc:
        raise PlanValidationError(_format_task_error(label, exc)) from None


def _format_task_error(label: str, exc: ValidationError) -> str:
    parts: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", ())) or "task"
        error_type = str(error.get("type", "invalid"))
        parts.append(f"{location}: {error_type}")
    detail = "; ".join(parts) if parts else "invalid task"
    return f"Invalid task '{label}'. {detail}"


def _reject_duplicate_task_ids(tasks: list[Task]) -> None:
    seen: set[str] = set()
    for task in tasks:
        if task.id in seen:
            raise PlanValidationError(f"Duplicate task id '{task.id}'.")
        seen.add(task.id)


def _reject_duplicate_dependencies(task: Task) -> None:
    seen: set[str] = set()
    for dependency_id in task.depends_on:
        if dependency_id in seen:
            raise PlanValidationError(
                f"Task '{task.id}' lists dependency '{dependency_id}' more than once."
            )
        seen.add(dependency_id)


def _index_tasks(tasks: Sequence[Task]) -> dict[str, Task]:
    by_id: dict[str, Task] = {}
    for task in tasks:
        if task.id in by_id:
            raise PlanValidationError(f"Duplicate task id '{task.id}'.")
        by_id[task.id] = task
    return by_id


def _dependency_status(by_id: dict[str, Task], task_id: str, dependency_id: str) -> TaskStatus:
    dependency = by_id.get(dependency_id)
    if dependency is None:
        raise PlanValidationError(f"Task '{task_id}' depends on missing task '{dependency_id}'.")
    return dependency.status


def _find_cycle(tasks: Sequence[Task]) -> list[str] | None:
    dependencies = {task.id: list(task.depends_on) for task in tasks}
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def walk(task_id: str) -> list[str] | None:
        if task_id in visited:
            return None
        if task_id in visiting:
            start = stack.index(task_id)
            return [*stack[start:], task_id]
        visiting.add(task_id)
        stack.append(task_id)
        for dependency_id in dependencies[task_id]:
            found = walk(dependency_id)
            if found is not None:
                return found
        stack.pop()
        visiting.remove(task_id)
        visited.add(task_id)
        return None

    for task_id in dependencies:
        found = walk(task_id)
        if found is not None:
            return found
    return None
