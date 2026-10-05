from collections.abc import Callable, Mapping
from typing import TypedDict

from orchestration.agents.research import ResearchLimits, run_research_task
from orchestration.core.config import Settings
from orchestration.llm import LLMProvider
from orchestration.search import SearchProvider
from orchestration.state.models import StateError, Task, TaskResult
from orchestration.state.registry import AgentId


class TaskUpdate(TypedDict, total=False):
    """What a specialist returns: its own task, its own result, and any errors."""

    tasks: list[Task]
    results: dict[str, TaskResult]
    errors: list[StateError]


TaskRunner = Callable[[Task, Mapping[str, TaskResult]], TaskUpdate]
"""Runs one task. Gets the task and the results so far, and returns a TaskUpdate."""


def build_task_runners(
    *,
    llm: LLMProvider,
    search: SearchProvider,
    settings: Settings,
) -> dict[AgentId, TaskRunner]:
    """Return the dispatch table from agent id to runner.

    The graph looks agents up here by `Task.assigned_agent`. A new specialist is
    one `AgentId` member plus one entry in this table. The graph is unchanged.
    """

    research_limits = ResearchLimits.from_settings(settings)

    def run_research(task: Task, results: Mapping[str, TaskResult]) -> TaskUpdate:
        return run_research_task(
            task,
            llm=llm,
            search=search,
            limits=research_limits,
            dependency_results=results,
        )

    return {AgentId.RESEARCH: run_research}
