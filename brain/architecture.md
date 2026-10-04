# Architecture

V1 scope: [vision.md](vision.md). Agent specs: [agents.md](agents.md). State: [state.md](state.md).

## Components

- **API (FastAPI):** accepts a user goal and returns the final result or a recorded failure.
- **Workflow (LangGraph):** runs the graph from goal to final result.
- **Supervisor:** plans and routes. Does not do specialist work.
- **Specialist agents:** one narrow job each. V1 specialist: Research.
- **Reviewer:** approves or rejects specialist output. Does not do the specialist job.
- **Model provider:** configurable adapter. Ollama now, vLLM later.
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

The API does not plan or review. The Supervisor writes the plan and chooses the next agent. Specialists write their own output. The Reviewer writes approve or reject. `final_result` is set only after approval. Who writes it: TBD (see [state.md](state.md)).

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

Retries are bounded. Limit: TBD. No infinite retry loops. No silent failures. Invalid model output is a failure, not a final answer.
