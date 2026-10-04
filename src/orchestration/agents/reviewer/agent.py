import logging
import time
from dataclasses import dataclass
from typing import Self, TypedDict

from orchestration.agents.reviewer.checks import reviewable_tasks, run_checks
from orchestration.agents.reviewer.parsing import Decision, Rejected, Severity, parse_review
from orchestration.agents.reviewer.prompt import (
    ReviewEntry,
    ReviewSource,
    build_review_prompt,
)
from orchestration.core.config import Settings
from orchestration.llm import LLMError, LLMProvider
from orchestration.state.errors import StateUpdateError
from orchestration.state.helpers import apply_review
from orchestration.state.models import Review, RunStatus, StateError, Task, TaskResult
from orchestration.state.registry import AgentId
from orchestration.state.schema import AgentState

logger = logging.getLogger(__name__)

MAX_GOAL_CHARS = 8_000


class ReviewerUpdate(TypedDict, total=False):
    """Partial state write from the Reviewer.

    A completed review writes `review` and the run `status` from `apply_review`.
    A review that cannot be completed writes a failed `status` and one error,
    and no `review`.
    """

    review: Review
    status: RunStatus
    errors: list[StateError]


@dataclass(frozen=True)
class ReviewerLimits:
    """Bounds for one review. Every limit is at least 1."""

    max_review_attempts: int
    max_review_revisions: int
    max_review_excerpt_chars: int

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            if value < 1:
                raise StateUpdateError(f"{name} must be at least 1.")

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        return cls(
            max_review_attempts=settings.max_review_attempts,
            max_review_revisions=settings.max_review_revisions,
            max_review_excerpt_chars=settings.max_review_excerpt_chars,
        )


class _Failed(Exception):
    def __init__(self, message: str, error_type: str) -> None:
        super().__init__(message)
        self.error_type = error_type


def review_results(
    state: AgentState,
    *,
    provider: LLMProvider,
    limits: ReviewerLimits,
) -> ReviewerUpdate:
    """Review the completed task results against the user goal.

    Deterministic checks run first. A hard failure there returns a verdict and
    does not call the model. Otherwise the model reviews the results. Any
    failure to finish the review fails the run. It never produces `approved`.
    The revision count follows `apply_review`, and the verdict is reported
    honestly even when the revision limit is already reached.
    """

    started = time.monotonic()
    goal = state["goal"]
    if not isinstance(goal, str) or not goal.strip():
        return _failed("Goal is missing.", "missing_goal", started)
    if len(goal) > MAX_GOAL_CHARS:
        return _failed("Goal exceeds the maximum length.", "goal_too_long", started)

    tasks = list(state["tasks"])
    results = dict(state["results"])
    hard_failure = run_checks(tasks, results)
    if hard_failure is not None:
        return _recorded(state, hard_failure, limits, stage="checks", started=started)

    entries = [_entry(task, results[task.id]) for task in reviewable_tasks(tasks)]
    try:
        decision = _model_review(goal, entries, provider, limits)
    except _Failed as exc:
        return _failed(str(exc), exc.error_type, started)
    return _recorded(state, decision, limits, stage="model", started=started)


def _entry(task: Task, result: TaskResult) -> ReviewEntry:
    sources = [
        ReviewSource(
            label=label,
            excerpt=result.excerpts[index] if index < len(result.excerpts) else "",
        )
        for index, label in enumerate(result.sources)
    ]
    return ReviewEntry(
        task_id=task.id,
        description=task.description,
        summary=result.output,
        note=result.error,
        sources=sources,
    )


def _model_review(
    goal: str,
    entries: list[ReviewEntry],
    provider: LLMProvider,
    limits: ReviewerLimits,
) -> Decision:
    task_ids = {entry.task_id for entry in entries}
    feedback: str | None = None
    last = Rejected("Model output is not valid JSON.", "invalid_json")
    for attempt in range(1, limits.max_review_attempts + 1):
        prompt = build_review_prompt(
            goal,
            entries,
            max_excerpt_chars=limits.max_review_excerpt_chars,
            validation_error=feedback,
        )
        try:
            raw = provider.generate(prompt)
        except LLMError as exc:
            raise _Failed(str(exc), "provider") from None
        try:
            return parse_review(raw, task_ids=task_ids)
        except Rejected as exc:
            last = exc
            feedback = str(exc)
            logger.info(
                "review_rejected",
                extra={
                    "agent_id": AgentId.REVIEWER.value,
                    "error_type": exc.error_type,
                    "attempt": attempt,
                },
            )
    word = "attempt" if limits.max_review_attempts == 1 else "attempts"
    raise _Failed(
        f"Review output was invalid after {limits.max_review_attempts} {word}. {last}",
        last.error_type,
    )


def _recorded(
    state: AgentState,
    decision: Decision,
    limits: ReviewerLimits,
    *,
    stage: str,
    started: float,
) -> ReviewerUpdate:
    outcome = apply_review(
        state["review"],
        decision.verdict,
        decision.rendered_issues(),
        max_revisions=limits.max_review_revisions,
    )
    logger.info(
        "review_finished",
        extra={
            "agent_id": AgentId.REVIEWER.value,
            "status": outcome.run_status.value,
            "verdict": decision.verdict.value,
            "stage": stage,
            "blocking_count": decision.count(Severity.BLOCKING),
            "minor_count": decision.count(Severity.MINOR),
            "revision_count": outcome.review.revision_count,
            "duration_ms": round((time.monotonic() - started) * 1000),
        },
    )
    return {"review": outcome.review, "status": outcome.run_status}


def _failed(message: str, error_type: str, started: float) -> ReviewerUpdate:
    logger.info(
        "review_failed",
        extra={
            "agent_id": AgentId.REVIEWER.value,
            "status": RunStatus.FAILED.value,
            "error_type": error_type,
            "duration_ms": round((time.monotonic() - started) * 1000),
        },
    )
    return {
        "status": RunStatus.FAILED,
        "errors": [
            StateError(source=AgentId.REVIEWER.value, message=f"Review failed. {message}")
        ],
    }
