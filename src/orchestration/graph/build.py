from collections.abc import Callable
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from orchestration.agents.supervisor import SupervisorRoute, route
from orchestration.graph.nodes import WorkflowNodes
from orchestration.state.schema import AgentState

# One path map for every conditional edge: the Supervisor's answer to node name.
_ROUTE_TO_NODE: dict[SupervisorRoute, str] = {
    SupervisorRoute.RUN: "run_tasks",
    SupervisorRoute.REVIEW: "review",
    SupervisorRoute.REVISE: "revise",
    SupervisorRoute.FAIL: "fail",
    SupervisorRoute.FINISH: "finalize",
}


def build_graph(
    nodes: WorkflowNodes,
    *,
    max_review_revisions: int,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """Compile the V1 workflow.

    plan -> run_tasks (repeat) -> review -> finalize
    review -> revise -> run_tasks -> review ...
    any failure -> fail

    Every branch is a conditional edge that asks the Supervisor's `route`. The
    graph holds no routing rules of its own.
    """

    after_work = _route_after_work(max_review_revisions)
    after_review = _route_after_review(max_review_revisions)

    graph = StateGraph(AgentState)
    graph.add_node("plan", nodes.plan)
    graph.add_node("run_tasks", nodes.run_tasks)
    graph.add_node("review", nodes.review)
    graph.add_node("revise", nodes.revise)
    graph.add_node("finalize", nodes.finalize)
    graph.add_node("fail", nodes.fail)

    graph.add_edge(START, "plan")
    graph.add_conditional_edges("plan", after_work, _ROUTE_TO_NODE)
    graph.add_conditional_edges("run_tasks", after_work, _ROUTE_TO_NODE)
    graph.add_conditional_edges("revise", after_work, _ROUTE_TO_NODE)
    graph.add_conditional_edges("review", after_review, _ROUTE_TO_NODE)
    graph.add_edge("finalize", END)
    graph.add_edge("fail", END)
    return graph.compile()


def _route_after_work(max_review_revisions: int) -> Callable[[AgentState], SupervisorRoute]:
    """Route after planning, running, or revising.

    A review in state is from before this work, so `route` is asked without it.
    Otherwise a `revise` verdict would send the run back to `revise` forever. The
    review stays in state, and the Reviewer reads its revision count next time.
    """

    def decide(state: AgentState) -> SupervisorRoute:
        without_old_review: AgentState = {**state, "review": None}
        return route(without_old_review, max_review_revisions=max_review_revisions)

    return decide


def _route_after_review(max_review_revisions: int) -> Callable[[AgentState], SupervisorRoute]:
    """Route after the Reviewer ran. The review in state is the fresh one."""

    def decide(state: AgentState) -> SupervisorRoute:
        return route(state, max_review_revisions=max_review_revisions)

    return decide
