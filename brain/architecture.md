# Architecture

V1 scope: [vision.md](vision.md). Agent specs: [agents.md](agents.md). State: [state.md](state.md).

## Components

- **API (FastAPI):** accepts a user goal and returns the final result or a recorded failure.
- **Workflow (LangGraph):** runs the graph from goal to final result.
- **Supervisor:** plans and routes. Does not do specialist work.
- **Specialist agents:** one narrow job each. V1 specialist: Research.
- **Reviewer:** approves or rejects specialist output. Does not do the specialist job.
- **Model provider:** configurable adapter. Ollama now, vLLM later.
- **Search provider:** configurable adapter for web search. Tavily now. The Research Agent calls only the `SearchProvider` interface.
- **Qdrant:** part of the chosen stack. Role TBD.
- **PostgreSQL:** part of the chosen stack. Role TBD.
- **Langfuse:** observability. Roadmap step 8. Not part of the V1 workflow.
- **MCP:** tool integration. Roadmap step 14. V1 non-goal.

Stack record: [decisions/stack.md](decisions/stack.md).

## Data flow

Full system:

User Goal -> Supervisor -> Task Planning -> Specialist Agents -> Reviewer -> Final Result

V1 uses one specialist (Research):

User Goal -> Supervisor -> Research Agent -> Reviewer -> Final Answer

The API does not plan or review. The Supervisor writes the plan and chooses the next agent. Specialists write their own output. The Reviewer writes approve, revise, or reject. `final_output` is set only after approval, by the `finalize` node (see [state.md](state.md)).

## Workflow

Code: `src/orchestration/graph/`. Run it with `python -m orchestration run "<goal>"` (see the README). The graph is a LangGraph `StateGraph` over `AgentState` with six nodes:

- `plan`: the Supervisor turns the goal into a validated task plan.
- `run_tasks`: runs every ready task once, one at a time in plan order, and looks each runner up by `Task.assigned_agent` in the table in `graph/runners.py`. A new specialist is one `AgentId` member plus one table entry. A failed task goes through `record_task_failure`, so it retries up to `max_task_attempts`, and its dependents are marked blocked.
- `review`: the Reviewer checks the results against the goal.
- `revise`: sets the tasks named in the Reviewer's blocking issues back to `pending` and adds that issue text to their inputs as feedback. No re-plan and no deleted tasks. Only those tasks run again.
- `finalize`: builds `final_output` as markdown with no model call, one section per task with its own numbered source list, and sets `status` to `done`. It refuses unless the review is `approved`.
- `fail`: sets `status` to `failed`, leaves `final_output` empty, and records a safe error.

Every branch is a conditional edge that asks the Supervisor's `route`. The graph holds no routing rules. After `plan`, `run_tasks`, and `revise`, `route` is asked about the state without the review in it, because that review is from before the work. Otherwise a `revise` verdict would send the run back to `revise` again without a new review. The review stays in state, so the Reviewer still reads its revision count.

Loop safety: the LangGraph recursion limit is `max_graph_steps` (default 100). Reaching it, or an unexpected error in a node, returns a `failed` state with a recorded error. It never raises out of `run_workflow`. Revisions stop at `max_review_revisions` through the Reviewer's count and `route`.

Every node logs its name, status, task counts, and duration with a run id. The same run id is on every other log line of the run. Logs never carry the goal, summaries, excerpts, prompts, or keys.

## Boundaries

- Adding an agent or a tool must not require a new architecture. Add a spec, a module, and a graph entry. See [conventions.md](conventions.md).
- Agent code contains no provider-specific logic. Agents call a shared model interface. Ollama and vLLM stay behind that interface. Provider and model name come from config.
- Each agent receives only the tools in its spec. Default is no tool.
- External side effects stop for human approval. See [security-and-approvals.md](security-and-approvals.md).

## Reliability

Record every failure in state and return it to the caller. Do not mark a run successful while an error is unresolved.

Handle:

- Tool or API failure
- Invalid model output
- Timeout
- Missing information
- Reviewer rejection
- Partial failure (some tasks done, at least one failed)

Retries are bounded. `max_plan_attempts` defaults to 3, `max_research_attempts` defaults to 3, `max_review_attempts` defaults to 3, `max_graph_steps` defaults to 100, `max_task_attempts` defaults to 3, and `max_review_revisions` defaults to 2. No infinite retry loops. No silent failures. Invalid model output is a failure, not a final answer.
