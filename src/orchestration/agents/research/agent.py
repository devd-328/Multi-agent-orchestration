import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Self, TypedDict

from orchestration.agents.research.parsing import Rejected, check_summary, parse_queries
from orchestration.agents.research.prompt import build_query_prompt, build_summary_prompt
from orchestration.agents.research.sources import collect_sources, format_sources
from orchestration.core.config import Settings
from orchestration.llm import LLMError, LLMProvider
from orchestration.search import SearchError, SearchProvider, SearchResult
from orchestration.state.errors import StateUpdateError
from orchestration.state.helpers import record_task_failure, record_task_success
from orchestration.state.models import StateError, Task, TaskResult, TaskStatus
from orchestration.state.registry import AgentId

logger = logging.getLogger(__name__)

MAX_TASK_DESCRIPTION_CHARS = 4_000

NO_RESULTS_OUTPUT = "No useful sources were found for this task, so no findings are reported."


class ResearchUpdate(TypedDict, total=False):
    """Partial state write from the Research Agent: its own task and its own result."""

    tasks: list[Task]
    results: dict[str, TaskResult]
    errors: list[StateError]


@dataclass(frozen=True)
class ResearchLimits:
    """Bounds for one research run. Every limit is at least 1."""

    max_search_queries: int
    max_results_per_query: int
    max_source_chars: int
    max_attempts: int
    max_task_attempts: int

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            if value < 1:
                raise StateUpdateError(f"{name} must be at least 1.")

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        return cls(
            max_search_queries=settings.max_search_queries,
            max_results_per_query=settings.max_results_per_query,
            max_source_chars=settings.max_source_chars,
            max_attempts=settings.max_research_attempts,
            max_task_attempts=settings.max_task_attempts,
        )


class _Failed(Exception):
    def __init__(
        self,
        message: str,
        error_type: str,
        sources: list[SearchResult] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.sources = sources or []


@dataclass
class _Stats:
    queries: int = 0
    failed_searches: list[str] = field(default_factory=list)
    results: int = 0
    sources: int = 0


def run_research_task(
    task: Task,
    *,
    llm: LLMProvider,
    search: SearchProvider,
    limits: ResearchLimits,
    dependency_results: Mapping[str, TaskResult] | None = None,
) -> ResearchUpdate:
    """Run one research task and return a sourced summary as a TaskResult.

    The agent writes only its own task and its own result. Failures are returned
    as a failed result with a safe message. The task status follows
    `record_task_failure`, so it returns to pending until `max_task_attempts`.
    """

    _check_task(task)
    started = time.monotonic()
    stats = _Stats()
    try:
        result = _research(task, llm, search, limits, dependency_results or {}, stats)
    except _Failed as exc:
        return _finish_failed(task, limits, exc, stats, started)
    return _finish_done(task, limits, result, stats, started)


def _check_task(task: Task) -> None:
    if task.assigned_agent is not AgentId.RESEARCH:
        raise StateUpdateError(f"Task '{task.id}' is not assigned to research.")
    if task.status not in {TaskStatus.PENDING, TaskStatus.RUNNING}:
        raise StateUpdateError(
            f"Task '{task.id}' cannot run from status '{task.status.value}'."
        )


def _research(
    task: Task,
    llm: LLMProvider,
    search: SearchProvider,
    limits: ResearchLimits,
    dependency_results: Mapping[str, TaskResult],
    stats: _Stats,
) -> TaskResult:
    if not task.description.strip():
        raise _Failed("Task description is missing.", "missing_description")
    if len(task.description) > MAX_TASK_DESCRIPTION_CHARS:
        raise _Failed("Task description exceeds the maximum length.", "description_too_long")
    dependencies = _dependency_outputs(task, dependency_results)

    queries = _plan_queries(task, dependencies, llm, limits)
    stats.queries = len(queries)
    batches = _run_searches(queries, search, limits, stats)
    if len(stats.failed_searches) == len(queries):
        raise _Failed(_failure_text("All searches failed", stats.failed_searches), "search")
    sources = collect_sources(
        batches,
        max_results_per_query=limits.max_results_per_query,
        max_source_chars=limits.max_source_chars,
    )
    stats.results = sum(len(batch) for batch in batches)
    stats.sources = len(sources)
    if not sources:
        return TaskResult(
            task_id=task.id,
            agent=AgentId.RESEARCH,
            output=NO_RESULTS_OUTPUT,
            status=TaskStatus.DONE,
            error=_partial_error(stats),
        )

    summary = _write_summary(task, dependencies, sources, llm, limits)
    return TaskResult(
        task_id=task.id,
        agent=AgentId.RESEARCH,
        output=summary,
        sources=format_sources(sources),
        status=TaskStatus.DONE,
        error=_partial_error(stats),
    )


def _dependency_outputs(task: Task, results: Mapping[str, TaskResult]) -> dict[str, str]:
    outputs: dict[str, str] = {}
    for dependency_id in task.depends_on:
        result = results.get(dependency_id)
        if result is None or result.status is not TaskStatus.DONE or not result.output.strip():
            raise _Failed(f"Dependency '{dependency_id}' has no usable result.", "dependency")
        outputs[dependency_id] = result.output
    return outputs


def _plan_queries(
    task: Task,
    dependencies: Mapping[str, str],
    llm: LLMProvider,
    limits: ResearchLimits,
) -> list[str]:
    feedback: str | None = None
    last = Rejected("Model output is not valid JSON.", "invalid_json")
    for attempt in range(1, limits.max_attempts + 1):
        prompt = build_query_prompt(
            task.description,
            inputs=task.inputs,
            dependencies=dependencies,
            max_queries=limits.max_search_queries,
            max_chars=limits.max_source_chars,
            validation_error=feedback,
        )
        try:
            raw = llm.generate(prompt)
        except LLMError as exc:
            raise _Failed(str(exc), "provider") from None
        try:
            return parse_queries(raw, max_queries=limits.max_search_queries)
        except Rejected as exc:
            last = exc
            feedback = str(exc)
            _log_rejection(task, "queries", exc.error_type, attempt)
    raise _Failed(
        f"Search queries could not be formed after {_attempts(limits)}. {last}",
        last.error_type,
    )


def _run_searches(
    queries: list[str],
    search: SearchProvider,
    limits: ResearchLimits,
    stats: _Stats,
) -> list[list[SearchResult]]:
    batches: list[list[SearchResult]] = []
    for query in queries:
        try:
            batches.append(search.search(query, limits.max_results_per_query))
        except SearchError as exc:
            stats.failed_searches.append(str(exc))
    return batches


def _write_summary(
    task: Task,
    dependencies: Mapping[str, str],
    sources: list[SearchResult],
    llm: LLMProvider,
    limits: ResearchLimits,
) -> str:
    feedback: str | None = None
    last = Rejected("Summary is empty.", "invalid_summary")
    for attempt in range(1, limits.max_attempts + 1):
        prompt = build_summary_prompt(
            task.description,
            inputs=task.inputs,
            dependencies=dependencies,
            sources=sources,
            max_chars=limits.max_source_chars,
            validation_error=feedback,
        )
        try:
            raw = llm.generate(prompt)
        except LLMError as exc:
            raise _Failed(str(exc), "provider", sources) from None
        try:
            return check_summary(raw, source_count=len(sources))
        except Rejected as exc:
            last = exc
            feedback = str(exc)
            _log_rejection(task, "summary", exc.error_type, attempt)
    raise _Failed(
        f"Summary could not be formed after {_attempts(limits)}. {last}",
        last.error_type,
        sources,
    )


def _finish_done(
    task: Task,
    limits: ResearchLimits,
    result: TaskResult,
    stats: _Stats,
    started: float,
) -> ResearchUpdate:
    updated = record_task_success(task, max_attempts=limits.max_task_attempts)
    errors: list[StateError] = []
    if result.error is not None:
        errors.append(
            StateError(source=AgentId.RESEARCH.value, message=result.error, task_id=task.id)
        )
    _log_finished(task, TaskStatus.DONE, stats, started, None)
    update: ResearchUpdate = {"tasks": [updated], "results": {task.id: result}}
    if errors:
        update["errors"] = errors
    return update


def _finish_failed(
    task: Task,
    limits: ResearchLimits,
    failure: _Failed,
    stats: _Stats,
    started: float,
) -> ResearchUpdate:
    message = f"Research failed. {failure}"
    updated = record_task_failure(task, message, max_attempts=limits.max_task_attempts)
    result = TaskResult(
        task_id=task.id,
        agent=AgentId.RESEARCH,
        sources=format_sources(failure.sources),
        status=TaskStatus.FAILED,
        error=message,
    )
    _log_finished(task, TaskStatus.FAILED, stats, started, failure.error_type)
    return {
        "tasks": [updated],
        "results": {task.id: result},
        "errors": [StateError(source=AgentId.RESEARCH.value, message=message, task_id=task.id)],
    }


def _partial_error(stats: _Stats) -> str | None:
    if not stats.failed_searches:
        return None
    detail = f"{len(stats.failed_searches)} of {stats.queries} searches failed"
    return _failure_text(f"Partial failure: {detail}", stats.failed_searches)


def _failure_text(prefix: str, messages: list[str]) -> str:
    distinct = list(dict.fromkeys(messages))
    return f"{prefix}. {' '.join(distinct)}"


def _attempts(limits: ResearchLimits) -> str:
    word = "attempt" if limits.max_attempts == 1 else "attempts"
    return f"{limits.max_attempts} {word}"


def _log_rejection(task: Task, step: str, error_type: str, attempt: int) -> None:
    logger.info(
        "research_rejected",
        extra={
            "agent_id": AgentId.RESEARCH.value,
            "task_id": task.id,
            "step": step,
            "error_type": error_type,
            "attempt": attempt,
        },
    )


def _log_finished(
    task: Task,
    status: TaskStatus,
    stats: _Stats,
    started: float,
    error_type: str | None,
) -> None:
    extra: dict[str, object] = {
        "agent_id": AgentId.RESEARCH.value,
        "task_id": task.id,
        "status": status.value,
        "query_count": stats.queries,
        "failed_query_count": len(stats.failed_searches),
        "result_count": stats.results,
        "source_count": stats.sources,
        "duration_ms": round((time.monotonic() - started) * 1000),
    }
    if error_type is not None:
        extra["error_type"] = error_type
    logger.info("research_finished", extra=extra)
