import pytest
from langgraph.graph import END, START, StateGraph

from orchestration.state import (
    AgentId,
    AgentState,
    RunStatus,
    StateError,
    StateUpdateError,
    TaskResult,
    TaskStatus,
)


def _result(task_id: str, output: str) -> TaskResult:
    return TaskResult(
        task_id=task_id,
        agent=AgentId.RESEARCH,
        output=output,
        sources=[f"https://example.test/{task_id}"],
        status=TaskStatus.DONE,
    )


def _first(state: AgentState) -> dict[str, object]:
    del state
    return {
        "results": {"task-1": _result("task-1", "first")},
        "errors": [
            StateError(source=AgentId.RESEARCH.value, message="used a fallback", task_id="task-1")
        ],
    }


def _second(state: AgentState) -> dict[str, object]:
    assert "task-1" in state["results"]
    return {
        "results": {"task-2": _result("task-2", "second")},
        "errors": [
            StateError(source=AgentId.REVIEWER.value, message="needs a source", task_id="task-2")
        ],
    }


def _invalid(state: AgentState) -> dict[str, object]:
    del state
    return {"results": {"task-x": {"task_id": "task-x", "output": "super-secret-output"}}}


def _initial() -> AgentState:
    return {
        "goal": "Collect two notes",
        "tasks": [],
        "results": {},
        "review": None,
        "final_output": None,
        "errors": [],
        "status": RunStatus.RUNNING,
    }


def test_state_graph_merges_results_and_errors() -> None:
    graph = StateGraph(AgentState)
    graph.add_node("first", _first)
    graph.add_node("second", _second)
    graph.add_edge(START, "first")
    graph.add_edge("first", "second")
    graph.add_edge("second", END)
    compiled = graph.compile()

    result = compiled.invoke(_initial())

    assert set(result["results"]) == {"task-1", "task-2"}
    assert result["results"]["task-1"].output == "first"
    assert result["results"]["task-2"].output == "second"
    assert [error.message for error in result["errors"]] == ["used a fallback", "needs a source"]
    assert result["status"] is RunStatus.RUNNING


def test_state_graph_rejects_an_invalid_result_update() -> None:
    graph = StateGraph(AgentState)
    graph.add_node("invalid", _invalid)
    graph.add_edge(START, "invalid")
    graph.add_edge("invalid", END)

    with pytest.raises(StateUpdateError) as exc_info:
        graph.compile().invoke(_initial())

    message = str(exc_info.value)
    assert "results.task-x" in message
    assert "super-secret-output" not in message
