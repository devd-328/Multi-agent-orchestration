from collections.abc import Mapping, Sequence

from orchestration.agents.research.parsing import cited_numbers
from orchestration.agents.reviewer.parsing import Decision, ReviewIssue, Severity
from orchestration.state.models import ReviewVerdict, Task, TaskResult, TaskStatus

NO_SOURCES_PHRASE = "no useful sources"

_MAX_ERROR_CHARS = 200


def reviewable_tasks(tasks: Sequence[Task]) -> list[Task]:
    """Tasks the Reviewer looks at. Skipped tasks are left out."""
    return [task for task in tasks if task.status is not TaskStatus.SKIPPED]


def run_checks(tasks: Sequence[Task], results: Mapping[str, TaskResult]) -> Decision | None:
    """Run the checks that need no model. Return a Decision on a hard failure, else None.

    A hard failure is a missing or failed result, an unfinished task, a citation
    that points at no source, a summary with nothing to check it against, or a
    run where every result reports no useful sources. A done result that carries
    an `error` is a tolerated partial failure (the Research Agent records failed
    searches that way) and is not a hard failure.

    The verdict is `rejected` when no reviewed task has a done result. Otherwise
    it is `revise`. The Supervisor routes both the same way until the revision
    limit, so the split only tells a reader whether anything was usable.
    """

    reviewed = reviewable_tasks(tasks)
    if not reviewed:
        return _decision(
            ReviewVerdict.REJECTED,
            [_blocking(None, "The plan has no tasks to review. Plan the work again.")],
        )

    issues: list[ReviewIssue] = []
    done_results = 0
    for task in reviewed:
        result = results.get(task.id)
        if result is not None and result.status is TaskStatus.DONE:
            done_results += 1
        issues.extend(_check_task(task, result))

    if issues:
        verdict = ReviewVerdict.REJECTED if done_results == 0 else ReviewVerdict.REVISE
        return _decision(verdict, issues)

    if all(not results[task.id].sources for task in reviewed):
        return _decision(
            ReviewVerdict.REVISE,
            [
                _blocking(
                    None,
                    "Every result reports no useful sources. "
                    "Search again with different queries.",
                )
            ],
        )
    return None


def _check_task(task: Task, result: TaskResult | None) -> list[ReviewIssue]:
    if result is None:
        return [
            _blocking(
                task.id,
                f"Task has no result (task status {task.status.value}). Run the task again.",
            )
        ]
    if result.status is TaskStatus.FAILED:
        reason = (result.error or "no error recorded")[:_MAX_ERROR_CHARS]
        return [_blocking(task.id, f"Result failed: {reason} Run the task again.")]
    if result.status is not TaskStatus.DONE:
        return [
            _blocking(
                task.id,
                f"Result is not finished (status {result.status.value}). "
                "Run the task to completion.",
            )
        ]
    if task.status is not TaskStatus.DONE:
        return [
            _blocking(
                task.id,
                f"Task is not done (status {task.status.value}) although a result exists. "
                "Run the task again.",
            )
        ]
    return _check_summary(task.id, result)


def _check_summary(task_id: str, result: TaskResult) -> list[ReviewIssue]:
    output = result.output.strip()
    if not output:
        return [_blocking(task_id, "Summary is empty. Write a cited summary.")]

    source_count = len(result.sources)
    cited = cited_numbers(output)
    if source_count == 0:
        if cited:
            numbers = ", ".join(str(number) for number in sorted(cited))
            return [
                _blocking(
                    task_id,
                    f"Summary cites source {numbers} but the result has no sources. "
                    "Remove the citations or search again.",
                )
            ]
        if NO_SOURCES_PHRASE not in output.lower():
            return [
                _blocking(
                    task_id,
                    "Result has no sources, so its claims cannot be checked. "
                    "Search again and cite the sources.",
                )
            ]
        return []

    missing = sorted(number for number in cited if not 1 <= number <= source_count)
    if missing:
        numbers = ", ".join(str(number) for number in missing)
        return [
            _blocking(
                task_id,
                f"Summary cites source {numbers}, which does not exist. "
                f"Valid source numbers are 1 to {source_count}. Cite only listed sources.",
            )
        ]
    if not cited:
        return [
            _blocking(
                task_id,
                "Summary has no citations. Cite each claim with its source number.",
            )
        ]
    if len(result.excerpts) != source_count:
        return [
            _blocking(
                task_id,
                "Result has no source excerpts, so its claims cannot be checked. "
                "Run the task again.",
            )
        ]
    empty = sorted(number for number in cited if not result.excerpts[number - 1].strip())
    if empty:
        numbers = ", ".join(str(number) for number in empty)
        return [
            _blocking(
                task_id,
                f"Cited source {numbers} has an empty excerpt, so its claims cannot be "
                "checked. Run the task again.",
            )
        ]
    return []


def _blocking(task_id: str | None, description: str) -> ReviewIssue:
    return ReviewIssue(severity=Severity.BLOCKING, task_id=task_id, description=description)


def _decision(verdict: ReviewVerdict, issues: list[ReviewIssue]) -> Decision:
    return Decision(verdict=verdict, issues=tuple(issues))
