import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langgraph.errors import GraphRecursionError
from langgraph.graph.state import CompiledStateGraph

from orchestration.core.config import Settings, load_settings
from orchestration.core.logging import run_id_var
from orchestration.graph.build import build_graph
from orchestration.graph.nodes import WORKFLOW_SOURCE, WorkflowContext, WorkflowNodes
from orchestration.graph.runners import build_task_runners
from orchestration.llm import LLMProvider, create_llm_provider, create_reviewer_llm_provider
from orchestration.search import SearchProvider, create_search_provider
from orchestration.state.models import RunStatus, StateError
from orchestration.state.schema import AgentState

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Providers:
    """The model and search providers one run uses."""

    llm: LLMProvider
    search: SearchProvider
    reviewer_llm: LLMProvider


def build_default_providers(settings: Settings | None = None) -> Providers:
    """Build the providers named in settings, using the existing factories.

    Raises ConfigurationError for a missing search key or an unknown provider.
    The error message never includes a secret.
    """
    active = settings if settings is not None else load_settings()
    return Providers(
        llm=create_llm_provider(active),
        search=create_search_provider(active),
        reviewer_llm=create_reviewer_llm_provider(active),
    )


def initial_state(goal: str) -> AgentState:
    return {
        "goal": goal,
        "tasks": [],
        "results": {},
        "review": None,
        "final_output": None,
        "errors": [],
        "status": RunStatus.PLANNING,
    }


def run_workflow(
    goal: str,
    *,
    llm: LLMProvider,
    search: SearchProvider,
    reviewer_llm: LLMProvider | None = None,
    settings: Settings | None = None,
    run_id: str | None = None,
    on_update: Callable[[AgentState], None] | None = None,
) -> AgentState:
    """Run a goal from plan to final answer and return the final state.

    On success `status` is `done` and `final_output` holds the answer. Every other
    outcome, including a step limit or an internal error, is returned as a state
    with `status` `failed`, no `final_output`, and at least one recorded error.
    `reviewer_llm` defaults to `llm`.

    `on_update`, when given, is called with the state after each graph step so a
    caller can show progress. It is read-only. An error inside it is logged by
    type and never stops the run.
    """

    active = settings if settings is not None else load_settings()
    identifier = run_id if run_id is not None else uuid.uuid4().hex[:12]
    context = WorkflowContext(
        settings=active,
        llm=llm,
        reviewer_llm=reviewer_llm if reviewer_llm is not None else llm,
        runners=build_task_runners(llm=llm, search=search, settings=active),
        run_id=identifier,
    )
    graph = build_graph(WorkflowNodes(context), max_review_revisions=active.max_review_revisions)

    token = run_id_var.set(identifier)
    started = time.monotonic()
    try:
        logger.info("workflow_started", extra={"run_id": identifier, "goal_chars": len(goal)})
        final = _execute(
            graph, initial_state(goal), active.max_graph_steps, identifier, on_update
        )
        logger.info(
            "workflow_finished",
            extra={
                "run_id": identifier,
                "status": final["status"].value,
                "error_count": len(final["errors"]),
                "duration_ms": round((time.monotonic() - started) * 1000),
            },
        )
        return final
    finally:
        run_id_var.reset(token)


def _execute(
    graph: CompiledStateGraph[Any, Any, Any, Any],
    state: AgentState,
    step_limit: int,
    run_id: str,
    on_update: Callable[[AgentState], None] | None = None,
) -> AgentState:
    # Streaming keeps the last good state if the step limit or an error stops the run.
    last = state
    try:
        for last in graph.stream(
            state,
            config={"recursion_limit": step_limit},
            stream_mode="values",
        ):
            _notify(on_update, last, run_id)
    except GraphRecursionError:
        logger.error("workflow_step_limit", extra={"run_id": run_id, "step_limit": step_limit})
        return _stopped(last, f"Workflow stopped after reaching the step limit ({step_limit}).")
    except Exception as exc:
        logger.error(
            "workflow_internal_error",
            extra={"run_id": run_id, "error_type": type(exc).__name__},
        )
        return _stopped(last, f"Workflow stopped on an internal error ({type(exc).__name__}).")
    return last


def _notify(
    on_update: Callable[[AgentState], None] | None,
    state: AgentState,
    run_id: str,
) -> None:
    if on_update is None:
        return
    try:
        on_update(state)
    except Exception as exc:
        logger.error(
            "workflow_update_callback_error",
            extra={"run_id": run_id, "error_type": type(exc).__name__},
        )


def _stopped(state: AgentState, message: str) -> AgentState:
    """Turn the last good state into a failed one. Nothing unreviewed is kept as output."""
    error = StateError(source=WORKFLOW_SOURCE, message=message)
    return {
        **state,
        "status": RunStatus.FAILED,
        "final_output": None,
        "errors": [*state["errors"], error],
    }
