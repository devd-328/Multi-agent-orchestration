from collections.abc import Collection
from dataclasses import dataclass
from enum import StrEnum

from orchestration.llm.json_output import JsonOutputError, extract_json
from orchestration.state.models import ReviewVerdict

MAX_ISSUES = 20
MIN_BLOCKING_CHARS = 10
MAX_DESCRIPTION_CHARS = 500


class Severity(StrEnum):
    BLOCKING = "blocking"
    MINOR = "minor"


class Rejected(Exception):
    """Model output failed a check. The message is safe to send back to the model."""

    def __init__(self, message: str, error_type: str) -> None:
        super().__init__(message)
        self.error_type = error_type


@dataclass(frozen=True)
class ReviewIssue:
    """One finding. `task_id` is None for an issue about the goal as a whole."""

    severity: Severity
    task_id: str | None
    description: str

    def render(self) -> str:
        """Return the text stored in `Review.issues`."""
        scope = f"task {self.task_id}" if self.task_id else "goal"
        return f"[{self.severity.value}] {scope}: {self.description}"


@dataclass(frozen=True)
class Decision:
    """A verdict and the issues behind it."""

    verdict: ReviewVerdict
    issues: tuple[ReviewIssue, ...]

    def rendered_issues(self) -> list[str]:
        """Blocking issues first, then minor ones, each in the order given."""
        ordered = sorted(self.issues, key=lambda issue: issue.severity is not Severity.BLOCKING)
        return [issue.render() for issue in ordered]

    def count(self, severity: Severity) -> int:
        return sum(1 for issue in self.issues if issue.severity is severity)


def parse_review(raw: object, *, task_ids: Collection[str]) -> Decision:
    """Return a consistent Decision or raise Rejected.

    Consistency rules: `approved` has no blocking issue. `revise` and `rejected`
    have at least one blocking issue. A blocking description is a length check
    only. It cannot prove that the wording is actionable.
    """
    try:
        payload = extract_json(raw)
    except JsonOutputError as exc:
        raise Rejected(str(exc), "invalid_json") from None
    if not isinstance(payload, dict):
        raise Rejected("Output must be a JSON object with verdict and issues.", "invalid_review")
    verdict = _parse_verdict(payload.get("verdict"))
    issues = _parse_issues(payload.get("issues"), set(task_ids))
    blocking = sum(1 for issue in issues if issue.severity is Severity.BLOCKING)
    if verdict is ReviewVerdict.APPROVED and blocking:
        raise Rejected(
            "An approved verdict cannot have blocking issues. "
            "Use revise or rejected, or remove the blocking issues.",
            "inconsistent_review",
        )
    if verdict is not ReviewVerdict.APPROVED and not blocking:
        raise Rejected(
            "A revise or rejected verdict needs at least one blocking issue "
            "that says what to change.",
            "inconsistent_review",
        )
    return Decision(verdict=verdict, issues=tuple(issues))


def _parse_verdict(value: object) -> ReviewVerdict:
    if isinstance(value, str):
        try:
            return ReviewVerdict(value.strip().lower())
        except ValueError:
            pass
    raise Rejected("Unknown verdict. Use approved, revise, or rejected.", "invalid_review")


def _parse_issues(value: object, task_ids: set[str]) -> list[ReviewIssue]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise Rejected("issues must be a list.", "invalid_review")
    if len(value) > MAX_ISSUES:
        raise Rejected(f"Return at most {MAX_ISSUES} issues.", "invalid_review")
    return [_parse_issue(item, task_ids) for item in value]


def _parse_issue(item: object, task_ids: set[str]) -> ReviewIssue:
    if not isinstance(item, dict):
        raise Rejected("Every issue must be an object.", "invalid_review")
    severity = _parse_severity(item.get("severity"))
    description = item.get("description")
    if not isinstance(description, str) or not description.strip():
        raise Rejected("Every issue needs a description.", "invalid_review")
    text = " ".join(description.split())
    if len(text) > MAX_DESCRIPTION_CHARS:
        raise Rejected(
            f"An issue description is longer than {MAX_DESCRIPTION_CHARS} characters.",
            "invalid_review",
        )
    if severity is Severity.BLOCKING and len(text) < MIN_BLOCKING_CHARS:
        raise Rejected(
            "A blocking issue must say what is wrong and what to change "
            f"(at least {MIN_BLOCKING_CHARS} characters).",
            "invalid_review",
        )
    task_id = _parse_task_id(item.get("task_id"), task_ids)
    return ReviewIssue(severity=severity, task_id=task_id, description=text)


def _parse_severity(value: object) -> Severity:
    if isinstance(value, str):
        try:
            return Severity(value.strip().lower())
        except ValueError:
            pass
    raise Rejected("Unknown severity. Use blocking or minor.", "invalid_review")


def _parse_task_id(value: object, task_ids: set[str]) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise Rejected("task_id must be a task id or null.", "invalid_review")
    task_id = value.strip()
    if not task_id:
        return None
    if task_id not in task_ids:
        raise Rejected(
            "An issue refers to a task id that is not in the results. "
            "Use one of the listed task ids, or null for the goal.",
            "invalid_review",
        )
    return task_id
