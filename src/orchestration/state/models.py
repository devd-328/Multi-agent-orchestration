from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from orchestration.state.registry import AgentId

REVIEW_FEEDBACK_INPUT = "review_feedback"
"""Task input key that carries Reviewer feedback into a re-run. The value is data."""


class _StateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class RunStatus(StrEnum):
    PLANNING = "planning"
    RUNNING = "running"
    REVIEWING = "reviewing"
    AWAITING_APPROVAL = "awaiting_approval"
    DONE = "done"
    FAILED = "failed"


class ReviewVerdict(StrEnum):
    APPROVED = "approved"
    REVISE = "revise"
    REJECTED = "rejected"


def _blank(value: str) -> bool:
    return not value.strip()


class Task(_StateModel):
    """One unit of work. `inputs` holds task data, not a conversation."""

    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    assigned_agent: AgentId
    depends_on: list[str] = Field(default_factory=list)
    inputs: dict[str, str] = Field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    attempts: int = Field(default=0, ge=0)
    error: str | None = None

    @model_validator(mode="after")
    def check_task(self) -> Self:
        if _blank(self.id):
            raise ValueError("id must not be empty")
        if _blank(self.description):
            raise ValueError("description must not be empty")
        if any(_blank(dep) for dep in self.depends_on):
            raise ValueError("depends_on must not contain an empty id")
        if any(_blank(key) for key in self.inputs):
            raise ValueError("inputs must not contain an empty key")
        if self.status is TaskStatus.FAILED and (self.error is None or _blank(self.error)):
            raise ValueError("failed status requires an error")
        if self.status is TaskStatus.DONE and self.error is not None:
            raise ValueError("done status cannot include an error")
        return self


class TaskResult(_StateModel):
    """Specialist output for one task. Sources are citations, not prompts.

    `excerpts[i]` is the bounded text excerpt of `sources[i]`, so a reviewer can
    check a claim without the original page. It is empty or the same length as
    `sources`. An entry may be empty text.
    """

    task_id: str = Field(min_length=1)
    agent: AgentId
    output: str = ""
    sources: list[str] = Field(default_factory=list)
    excerpts: list[str] = Field(default_factory=list)
    status: TaskStatus
    error: str | None = None

    @model_validator(mode="after")
    def check_result(self) -> Self:
        if _blank(self.task_id):
            raise ValueError("task_id must not be empty")
        if any(_blank(source) for source in self.sources):
            raise ValueError("sources must not contain an empty entry")
        if self.excerpts and len(self.excerpts) != len(self.sources):
            raise ValueError("excerpts must match sources one to one")
        if self.status is TaskStatus.FAILED and (self.error is None or _blank(self.error)):
            raise ValueError("failed status requires an error")
        if self.status is TaskStatus.DONE and _blank(self.output):
            raise ValueError("done status requires output")
        return self


class Review(_StateModel):
    verdict: ReviewVerdict
    issues: list[str] = Field(default_factory=list)
    revision_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def check_review(self) -> Self:
        if any(_blank(issue) for issue in self.issues):
            raise ValueError("issues must not contain an empty entry")
        if self.verdict is not ReviewVerdict.APPROVED and not self.issues:
            raise ValueError("revise and rejected verdicts require an issue")
        return self


class ReviewOutcome(_StateModel):
    """Review plus the run status that keeps the revision loop finite."""

    review: Review
    run_status: RunStatus


class StateError(_StateModel):
    source: str = Field(min_length=1)
    message: str = Field(min_length=1)
    task_id: str | None = None

    @field_validator("source", "message", mode="before")
    @classmethod
    def required_text(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                raise ValueError("must not be empty")
            return stripped
        return value

    @field_validator("task_id", mode="before")
    @classmethod
    def optional_task_id(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                raise ValueError("must not be empty")
            return stripped
        return value
