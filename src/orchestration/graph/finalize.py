from collections.abc import Mapping, Sequence

from orchestration.state.errors import StateUpdateError
from orchestration.state.models import Task, TaskResult, TaskStatus


def reviewed_tasks(tasks: Sequence[Task]) -> list[Task]:
    """Tasks that belong in the final answer. Skipped tasks are left out."""
    return [task for task in tasks if task.status is not TaskStatus.SKIPPED]


def build_final_output(tasks: Sequence[Task], results: Mapping[str, TaskResult]) -> str:
    """Build the final markdown answer. Deterministic, no model call.

    One section per task, in plan order. Each section holds the task description,
    the summary, and that task's own source list. Citation `[n]` in a summary
    refers to entry `[n]` of the list in the same section. Tolerated partial
    failures (a done result that carries an `error`) are listed in a closing note.
    """

    sections = ["# Research results"]
    notes: list[str] = []
    for task in reviewed_tasks(tasks):
        result = results.get(task.id)
        if result is None or result.status is not TaskStatus.DONE:
            raise StateUpdateError(f"Task '{task.id}' has no finished result.")
        sections.append(_task_section(task, result))
        if result.error:
            notes.append(f"- Task {_one_line(task.id)}: {_one_line(result.error)}")
    if notes:
        intro = "Some searches failed. The results above use the searches that worked."
        sections.append("\n".join(["## Notes", "", intro, "", *notes]))
    return "\n\n".join(sections) + "\n"


def _task_section(task: Task, result: TaskResult) -> str:
    lines = [
        f"## Task {_one_line(task.id)}",
        "",
        f"**Task:** {_one_line(task.description)}",
        "",
        result.output.strip(),
        "",
        "**Sources**",
        "",
    ]
    if result.sources:
        lines.extend(f"- {_one_line(source)}" for source in result.sources)
    else:
        lines.append("- No sources.")
    return "\n".join(lines)


def _one_line(text: str) -> str:
    return " ".join(text.split())
