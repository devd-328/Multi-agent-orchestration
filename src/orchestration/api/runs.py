import logging
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel

from orchestration.core.config import Settings
from orchestration.graph import Providers, build_default_providers, run_workflow
from orchestration.state import AgentState, ReviewVerdict, RunStatus, TaskStatus

logger = logging.getLogger(__name__)

MAX_ACTIVE_RUNS = 2
"""Runs that may work at once. More are refused, so one page cannot burn the search quota."""
MAX_KEPT_RUNS = 50
"""Finished runs kept in memory. The oldest finished run is dropped first."""
MAX_LISTED_ERRORS = 10
MAX_TEXT_CHARS = 300
_SUMMARY_GOAL_CHARS = 120


class TooManyRunsError(Exception):
    """Raised when MAX_ACTIVE_RUNS runs are already working."""


class JobStatus(StrEnum):
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Stage(StrEnum):
    """Which part of the workflow is working now. Derived from state, never stored by agents."""

    PLAN = "plan"
    RESEARCH = "research"
    REVIEW = "review"
    REVISE = "revise"
    FINALIZE = "finalize"
    DONE = "done"
    FAILED = "failed"


class TaskView(BaseModel):
    id: str
    description: str
    agent: str
    status: str
    attempts: int
    error: str | None = None


class ReviewView(BaseModel):
    verdict: str
    issues: list[str]
    revision_count: int


class RunView(BaseModel):
    id: str
    goal: str
    status: JobStatus
    stage: Stage
    created_at: str
    elapsed_seconds: float
    tasks: list[TaskView]
    review: ReviewView | None
    errors: list[str]
    final_output: str | None


class RunSummary(BaseModel):
    id: str
    goal: str
    status: JobStatus
    stage: Stage
    created_at: str
    elapsed_seconds: float


def derive_stage(state: AgentState) -> Stage:
    """Say which step the workflow is on, from a state it streamed after a node."""
    status = state["status"]
    if status is RunStatus.DONE:
        return Stage.DONE
    if status is RunStatus.FAILED:
        return Stage.FAILED
    tasks = state["tasks"]
    if not tasks:
        return Stage.PLAN
    review = state["review"]
    if status is RunStatus.REVIEWING and review is not None:
        return Stage.FINALIZE if review.verdict is ReviewVerdict.APPROVED else Stage.REVISE
    open_states = {TaskStatus.PENDING, TaskStatus.RUNNING}
    if any(task.status in open_states for task in tasks):
        return Stage.RESEARCH
    return Stage.REVIEW


def _cut(text: str, limit: int = MAX_TEXT_CHARS) -> str:
    return text[:limit]


class _Run:
    """One run and its latest view. Only RunManager changes it, under its lock."""

    def __init__(self, run_id: str, goal: str) -> None:
        self.id = run_id
        self.goal = goal
        self.created_at = datetime.now(UTC).isoformat(timespec="seconds")
        self.started = time.monotonic()
        self.finished: float | None = None
        self.status = JobStatus.RUNNING
        self.stage = Stage.PLAN
        self.tasks: list[TaskView] = []
        self.review: ReviewView | None = None
        self.errors: list[str] = []
        self.final_output: str | None = None

    def apply(self, state: AgentState) -> None:
        self.stage = derive_stage(state)
        self.tasks = [
            TaskView(
                id=task.id,
                description=_cut(task.description),
                agent=task.assigned_agent.value,
                status=task.status.value,
                attempts=task.attempts,
                error=_cut(task.error) if task.error else None,
            )
            for task in state["tasks"]
        ]
        review = state["review"]
        self.review = (
            ReviewView(
                verdict=review.verdict.value,
                issues=[_cut(issue) for issue in review.issues[:MAX_LISTED_ERRORS]],
                revision_count=review.revision_count,
            )
            if review is not None
            else None
        )
        self.errors = [_cut(error.message) for error in state["errors"][:MAX_LISTED_ERRORS]]

    def finish(self, state: AgentState) -> None:
        self.apply(state)
        output = state["final_output"]
        if state["status"] is RunStatus.DONE and output:
            self.status = JobStatus.DONE
            self.final_output = output
        else:
            self.status = JobStatus.FAILED
            self.stage = Stage.FAILED
            self.final_output = None
        self.finished = time.monotonic()

    def fail(self, message: str) -> None:
        self.status = JobStatus.FAILED
        self.stage = Stage.FAILED
        self.errors = [*self.errors, message][:MAX_LISTED_ERRORS]
        self.final_output = None
        self.finished = time.monotonic()

    def elapsed(self) -> float:
        end = self.finished if self.finished is not None else time.monotonic()
        return round(end - self.started, 1)

    def view(self) -> RunView:
        return RunView(
            id=self.id,
            goal=self.goal,
            status=self.status,
            stage=self.stage,
            created_at=self.created_at,
            elapsed_seconds=self.elapsed(),
            tasks=list(self.tasks),
            review=self.review,
            errors=list(self.errors),
            final_output=self.final_output,
        )

    def summary(self) -> RunSummary:
        return RunSummary(
            id=self.id,
            goal=self.goal[:_SUMMARY_GOAL_CHARS],
            status=self.status,
            stage=self.stage,
            created_at=self.created_at,
            elapsed_seconds=self.elapsed(),
        )


class RunManager:
    """Start workflow runs in background threads and report their progress.

    Runs live in memory only. A restart forgets them. Nothing is written to disk.
    """

    def __init__(
        self,
        *,
        max_active: int = MAX_ACTIVE_RUNS,
        max_kept: int = MAX_KEPT_RUNS,
    ) -> None:
        self._max_active = max_active
        self._max_kept = max_kept
        self._lock = threading.Lock()
        self._runs: OrderedDict[str, _Run] = OrderedDict()
        self._pool = ThreadPoolExecutor(max_workers=max_active, thread_name_prefix="run")

    def start(self, goal: str, settings: Settings) -> RunView:
        """Start one run. Raises ConfigurationError, or TooManyRunsError when busy.

        Providers are built here, so a missing key fails the request, not a thread.
        """
        providers = build_default_providers(settings)
        run = _Run(uuid.uuid4().hex[:12], goal)
        with self._lock:
            if self._active_count() >= self._max_active:
                raise TooManyRunsError
            self._runs[run.id] = run
            self._drop_old_runs()
            view = run.view()
        self._pool.submit(self._work, run, goal, providers, settings)
        return view

    def get(self, run_id: str) -> RunView | None:
        with self._lock:
            run = self._runs.get(run_id)
            return run.view() if run is not None else None

    def recent(self) -> list[RunSummary]:
        """Newest run first."""
        with self._lock:
            return [run.summary() for run in reversed(self._runs.values())]

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _active_count(self) -> int:
        return sum(1 for run in self._runs.values() if run.status is JobStatus.RUNNING)

    def _drop_old_runs(self) -> None:
        while len(self._runs) > self._max_kept:
            oldest_finished = next(
                (key for key, run in self._runs.items() if run.status is not JobStatus.RUNNING),
                None,
            )
            if oldest_finished is None:
                return
            del self._runs[oldest_finished]

    def _update(self, run: _Run, state: AgentState) -> None:
        with self._lock:
            run.apply(state)

    def _work(self, run: _Run, goal: str, providers: Providers, settings: Settings) -> None:
        try:
            final = run_workflow(
                goal,
                llm=providers.llm,
                search=providers.search,
                reviewer_llm=providers.reviewer_llm,
                settings=settings,
                run_id=run.id,
                on_update=lambda state: self._update(run, state),
            )
        except Exception as exc:
            logger.error(
                "api_run_error", extra={"run_id": run.id, "error_type": type(exc).__name__}
            )
            with self._lock:
                run.fail(f"Run stopped on an internal error ({type(exc).__name__}).")
            return
        with self._lock:
            run.finish(final)
