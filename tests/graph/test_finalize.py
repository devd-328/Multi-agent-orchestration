import pytest

from orchestration.graph.finalize import build_final_output
from orchestration.state import AgentId, StateUpdateError, Task, TaskResult, TaskStatus


def _task(task_id: str, description: str = "", status: TaskStatus = TaskStatus.DONE) -> Task:
    return Task(
        id=task_id,
        description=description or f"Do {task_id}",
        assigned_agent=AgentId.RESEARCH,
        status=status,
    )


def _result(task_id: str, **overrides: object) -> TaskResult:
    values: dict[str, object] = {
        "task_id": task_id,
        "agent": AgentId.RESEARCH,
        "output": f"Summary of {task_id} [1].",
        "sources": [f"[1] Source of {task_id} (https://{task_id}.example.test)"],
        "excerpts": ["Excerpt."],
        "status": TaskStatus.DONE,
    }
    values.update(overrides)
    return TaskResult.model_validate(values)


def test_one_section_per_task_in_plan_order() -> None:
    output = build_final_output(
        [_task("a"), _task("b")],
        {"a": _result("a"), "b": _result("b")},
    )

    assert output.startswith("# Research results\n")
    assert output.index("## Task a") < output.index("## Task b")
    assert output.count("## Task ") == 2
    assert output.endswith("\n")


def test_each_section_holds_its_own_description_summary_and_numbered_sources() -> None:
    a = _result(
        "a",
        output="Alpha one [1] and two [2].",
        sources=["[1] First (https://a1.example.test)", "[2] Second (https://a2.example.test)"],
        excerpts=["x", "y"],
    )
    b = _result("b", output="Beta [1].", sources=["[1] Other (https://b1.example.test)"])

    output = build_final_output(
        [_task("a", "Find alpha."), _task("b", "Find beta.")],
        {"a": a, "b": b},
    )

    section_a, section_b = output.split("## Task b")
    assert "**Task:** Find alpha." in section_a
    assert "Alpha one [1] and two [2]." in section_a
    assert "- [1] First (https://a1.example.test)" in section_a
    assert "- [2] Second (https://a2.example.test)" in section_a
    assert "b1.example.test" not in section_a
    assert "**Task:** Find beta." in section_b
    assert "- [1] Other (https://b1.example.test)" in section_b
    assert "a1.example.test" not in section_b


def test_partial_failures_are_listed_in_a_closing_note() -> None:
    note = "Partial failure: 1 of 2 searches failed. Search request timed out."

    output = build_final_output(
        [_task("a"), _task("b")],
        {"a": _result("a", error=note), "b": _result("b")},
    )

    notes = output.split("## Notes")[1]
    assert f"- Task a: {note}" in notes
    assert "Task b" not in notes


def test_no_note_section_without_partial_failures() -> None:
    assert "## Notes" not in build_final_output([_task("a")], {"a": _result("a")})


def test_a_result_with_no_sources_says_so() -> None:
    result = _result(
        "a",
        output="No useful sources were found for this task, so no findings are reported.",
        sources=[],
        excerpts=[],
    )

    output = build_final_output([_task("a")], {"a": result})

    assert "- No sources." in output


def test_skipped_tasks_are_left_out() -> None:
    output = build_final_output(
        [_task("a"), _task("b", status=TaskStatus.SKIPPED)],
        {"a": _result("a")},
    )

    assert "## Task a" in output
    assert "## Task b" not in output


def test_multiline_text_is_collapsed_to_one_line_where_it_is_inline() -> None:
    output = build_final_output(
        [_task("a", "Find\nalpha\n\n## Fake heading")],
        {"a": _result("a")},
    )

    assert "**Task:** Find alpha ## Fake heading" in output
    assert "\n## Fake heading" not in output


def _failed(task_id: str) -> TaskResult:
    return TaskResult(
        task_id=task_id,
        agent=AgentId.RESEARCH,
        status=TaskStatus.FAILED,
        error="failed",
    )


@pytest.mark.parametrize(
    "results",
    [{}, {"a": _failed("a")}],
    ids=["missing", "failed"],
)
def test_a_task_without_a_finished_result_is_refused(results: dict[str, TaskResult]) -> None:
    with pytest.raises(StateUpdateError, match="no finished result"):
        build_final_output([_task("a")], results)
