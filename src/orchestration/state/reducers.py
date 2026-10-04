from collections.abc import Mapping

from pydantic import ValidationError

from orchestration.state.errors import StateUpdateError
from orchestration.state.models import StateError, Task, TaskResult


def merge_tasks(left: list[Task], right: list[Task]) -> list[Task]:
    """Merge task writes by id.

    Existing ids keep their order and are replaced. New ids append.
    Last-write would drop tasks a node did not include, so a specialist can
    update one task without rewriting the plan.
    """

    if not isinstance(right, list):
        raise StateUpdateError("Invalid state update. tasks: list_type")
    incoming = [_coerce(Task, item, "tasks") for item in right]
    _reject_duplicate_ids(incoming)
    merged = list(left)
    index = {task.id: position for position, task in enumerate(merged)}
    for task in incoming:
        position = index.get(task.id)
        if position is None:
            index[task.id] = len(merged)
            merged.append(task)
        else:
            merged[position] = task
    return merged


def merge_results(
    left: dict[str, TaskResult],
    right: dict[str, TaskResult],
) -> dict[str, TaskResult]:
    """Merge result writes by task id. One id does not delete the others."""

    if not isinstance(right, Mapping):
        raise StateUpdateError("Invalid state update. results: dict_type")
    incoming: dict[str, TaskResult] = {}
    for key, value in right.items():
        result = _coerce(TaskResult, value, f"results.{key}")
        if result.task_id != key:
            raise StateUpdateError(
                f"Invalid state update. results.{key}: task_id does not match the key."
            )
        incoming[str(key)] = result
    merged = dict(left)
    merged.update(incoming)
    return merged


def append_errors(left: list[StateError], right: list[StateError]) -> list[StateError]:
    """Append errors. Existing errors stay in place."""

    if not isinstance(right, list):
        raise StateUpdateError("Invalid state update. errors: list_type")
    incoming = [_coerce(StateError, item, "errors") for item in right]
    return [*left, *incoming]


def _reject_duplicate_ids(tasks: list[Task]) -> None:
    seen: set[str] = set()
    for task in tasks:
        if task.id in seen:
            raise StateUpdateError(f"Invalid state update. tasks: duplicate id {task.id}.")
        seen.add(task.id)


def _coerce(
    model: type[Task] | type[TaskResult] | type[StateError],
    value: object,
    label: str,
) -> Task | TaskResult | StateError:
    if isinstance(value, model):
        return value
    try:
        return model.model_validate(value)
    except ValidationError as exc:
        raise StateUpdateError(_format_validation_error(label, exc)) from None


def _format_validation_error(label: str, exc: ValidationError) -> str:
    parts: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", ()))
        error_type = str(error.get("type", "invalid"))
        field = f"{label}.{location}" if location else label
        parts.append(f"{field}: {error_type}")
    detail = "; ".join(parts) if parts else label
    return f"Invalid state update. {detail}"
