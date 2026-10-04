import json
import logging
import re
from collections.abc import Mapping
from typing import TypedDict

from orchestration.agents.supervisor.prompt import build_plan_prompt
from orchestration.agents.supervisor.specialists import specialist_agent_ids
from orchestration.llm import LLMError, LLMProvider
from orchestration.state.errors import PlanValidationError, StateUpdateError
from orchestration.state.helpers import validate_task_plan
from orchestration.state.models import RunStatus, StateError, Task
from orchestration.state.registry import AgentId
from orchestration.state.schema import AgentState

logger = logging.getLogger(__name__)

MAX_GOAL_CHARS = 8_000

_REQUIRED_FIELDS = ("id", "description", "assigned_agent", "depends_on", "inputs")


class SupervisorUpdate(TypedDict, total=False):
    """Partial state write from the Supervisor."""

    tasks: list[Task]
    status: RunStatus
    errors: list[StateError]


class _Rejected(Exception):
    def __init__(self, message: str, error_type: str) -> None:
        super().__init__(message)
        self.error_type = error_type


def plan(
    state: AgentState,
    *,
    provider: LLMProvider,
    max_plan_attempts: int,
    max_goal_chars: int = MAX_GOAL_CHARS,
) -> SupervisorUpdate:
    """Turn the user goal into a validated task plan.

    The goal is sent to the model as data. Invalid JSON and failed checks are
    sent back up to `max_plan_attempts`. Provider failures are not retried.
    """

    if max_plan_attempts < 1:
        raise StateUpdateError("max_plan_attempts must be at least 1.")
    if max_goal_chars < 1:
        raise StateUpdateError("max_goal_chars must be at least 1.")

    goal = state["goal"]
    if not isinstance(goal, str) or not goal.strip():
        return _failure("Goal is missing.", "missing_goal")
    if len(goal) > max_goal_chars:
        return _failure("Goal exceeds the maximum length.", "goal_too_long")

    allowed = sorted(agent.value for agent in specialist_agent_ids())
    if not allowed:
        return _failure("No specialist agent is registered.", "no_specialist")

    feedback: str | None = None
    last_message = "Model output is not valid JSON."
    last_error_type = "invalid_json"
    for attempt in range(1, max_plan_attempts + 1):
        prompt = build_plan_prompt(goal, allowed_agents=allowed, validation_error=feedback)
        try:
            raw = provider.generate(prompt)
        except LLMError as exc:
            return _failure(str(exc), "provider")
        try:
            tasks = _parse_plan(raw)
        except _Rejected as exc:
            last_message = str(exc)
            last_error_type = exc.error_type
            feedback = last_message
            logger.info(
                "plan_rejected",
                extra={
                    "agent_id": AgentId.SUPERVISOR.value,
                    "status": state["status"].value,
                    "error_type": exc.error_type,
                    "attempt": attempt,
                },
            )
            continue
        logger.info(
            "plan_created",
            extra={
                "agent_id": AgentId.SUPERVISOR.value,
                "status": RunStatus.RUNNING.value,
                "task_count": len(tasks),
                "agents": sorted({task.assigned_agent.value for task in tasks}),
            },
        )
        return {"tasks": tasks, "status": RunStatus.RUNNING}

    attempt_word = "attempt" if max_plan_attempts == 1 else "attempts"
    return _failure(
        f"Plan could not be formed after {max_plan_attempts} {attempt_word}. {last_message}",
        last_error_type,
    )


def _parse_plan(raw: object) -> list[Task]:
    if not isinstance(raw, str) or not raw.strip():
        raise _Rejected("Model output is empty.", "invalid_json")
    payload = _load_json(_strip_fences(raw))
    tasks = _tasks_from_payload(payload)
    _require_fields(tasks)
    try:
        parsed = validate_task_plan(tasks)
    except PlanValidationError as exc:
        raise _Rejected(str(exc), "invalid_plan") from None
    _reject_non_specialists(parsed)
    return parsed


_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)


def _strip_fences(text: str) -> str:
    stripped = text.strip()
    match = _FENCE.match(stripped)
    if match:
        return match.group(1).strip()
    return stripped


def _load_json(text: str) -> object:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = _json_start(text)
        if start is None:
            raise _Rejected("Model output is not valid JSON.", "invalid_json") from None
        try:
            value, _end = json.JSONDecoder().raw_decode(text[start:])
        except json.JSONDecodeError:
            raise _Rejected("Model output is not valid JSON.", "invalid_json") from None
        return value


def _json_start(text: str) -> int | None:
    for index, char in enumerate(text):
        if char in "{[":
            return index
    return None


def _tasks_from_payload(payload: object) -> list[object]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and "tasks" in payload:
        tasks = payload["tasks"]
        if isinstance(tasks, list):
            return tasks
        raise _Rejected("Plan tasks must be a list.", "invalid_plan")
    raise _Rejected("Plan must be a JSON object with a tasks array.", "invalid_plan")


def _require_fields(tasks: list[object]) -> None:
    for index, item in enumerate(tasks):
        if not isinstance(item, Mapping):
            continue
        missing = [key for key in _REQUIRED_FIELDS if key not in item]
        if missing:
            task_id = item.get("id")
            if isinstance(task_id, str) and task_id.strip():
                label = task_id.strip()
            else:
                label = f"index {index}"
            names = ", ".join(missing)
            raise _Rejected(f"Task '{label}' is missing {names}.", "invalid_plan")


def _reject_non_specialists(tasks: list[Task]) -> None:
    allowed = specialist_agent_ids()
    for task in tasks:
        if task.assigned_agent not in allowed:
            raise _Rejected(
                f"Task '{task.id}' cannot be assigned to '{task.assigned_agent.value}'.",
                "invalid_plan",
            )


def _failure(message: str, error_type: str) -> SupervisorUpdate:
    logger.info(
        "plan_failed",
        extra={
            "agent_id": AgentId.SUPERVISOR.value,
            "status": RunStatus.FAILED.value,
            "error_type": error_type,
        },
    )
    return {
        "status": RunStatus.FAILED,
        "errors": [StateError(source=AgentId.SUPERVISOR.value, message=message)],
    }
