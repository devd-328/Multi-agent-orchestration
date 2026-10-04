# State

Shared LangGraph state. One object for the whole run. Field owners are below. Reliability rules: [architecture.md](architecture.md).

## Schema

```text
goal: string                      # required user goal
plan: list[Task]
current_task_id: string | null
outputs: map[task_id, string]     # specialist output only
review:
  status: pending | approved | rejected
  notes: string
final_result: string | null       # set only when review.status is approved
errors: list[Error]
retry_count: integer              # bounded; limit TBD
```

```text
Task:
  id: string
  agent: string                   # agent id from agents.md
  instruction: string
  status: pending | running | done | failed

Error:
  source: string                  # agent id or component
  message: string
```

Extra fields need an update to this file before code uses them.

## Conventions

- The Supervisor writes `plan` and `current_task_id`. It does not write specialist `outputs`.
- A specialist writes only its own `outputs` entry and its own task status.
- The Reviewer writes only `review`.
- `final_result` is set only after `review.status` is `approved`. Which node writes it: TBD.
- Append errors. Do not clear another agent's output.
- An empty `final_result` with any unresolved error is a failed run.
- Do not store secrets or credentials in state.
- `retry_count` increments on a retriable failure or a reviewer rejection. Stop at the limit (TBD). No infinite loop.
- Status values are only the sets above.
