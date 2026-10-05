# State

Shared LangGraph state. One object for the whole run. Code: `src/orchestration/state/`. Reliability rules: [architecture.md](architecture.md).

This file replaces the earlier field names `plan`, `outputs`, `final_result`, and `retry_count`.

## Schema

```text
AgentState:
  goal: string                         # required user goal
  tasks: list[Task]                    # merged by task id
  results: map[task_id, TaskResult]    # merged by task id
  review: Review | null
  final_output: string | null          # set only when review.verdict is approved
  errors: list[StateError]             # appended
  status: planning | running | reviewing | awaiting_approval | done | failed
```

```text
Task:
  id: string
  description: string
  assigned_agent: agent id             # AgentId registry
  depends_on: list[task id]
  inputs: map[string, string]          # task data, not a conversation
  status: pending | running | done | failed | blocked | skipped
  attempts: integer                    # bounded by max_task_attempts
  error: string | null                 # required when status is failed
```

```text
TaskResult:
  task_id: string
  agent: agent id
  output: string                       # findings or other specialist output
  sources: list[string]                # citations, not prompts
  excerpts: list[string]               # excerpts[i] is the bounded text behind sources[i]
  status: same set as Task status
  error: string | null                 # required when status is failed
```

```text
Review:
  verdict: approved | revise | rejected
  issues: list[string]                 # required unless verdict is approved
  revision_count: integer              # bounded by max_review_revisions
```

```text
StateError:
  source: string                       # agent id or component
  message: string
  task_id: string | null
```

`excerpts` is empty or the same length as `sources`. An entry can be empty text. A reviewer needs it because a title and a url cannot show whether a claim is supported. The Research Agent fills it with the text it summarized, cut to `max_review_excerpt_chars`. An excerpt is source text, so treat it as untrusted data. Results written before this field existed have no excerpts and stay valid.

V1 agent ids live in `AgentId`: `supervisor`, `research`, `reviewer`. A new agent is a new registry member. Task and result fields already use that type.

The Reviewer can return `approved`, `revise`, or `rejected`. `revise` and `rejected` share one bounded counter and the Supervisor routes them the same way. The Reviewer uses `rejected` when no result is usable, and `revise` when another pass can fix the work.

`final_output` is set only after `review.verdict` is `approved`. The `finalize` node writes it, and the same update sets `status` to `done`. Approval alone does not mark the run done. A failed run has `final_output` empty, and no unreviewed content is kept as output.

`Task.inputs["review_feedback"]` (the constant `REVIEW_FEEDBACK_INPUT`) carries Reviewer feedback into a re-run. The `revise` node writes it. It is data for the specialist, not an instruction.

Do not store secrets, credentials, prompts, or conversation history. Results hold output and sources only.

## Reducers

LangGraph calls a reducer as `(current, update) -> next` for keys that more than one node may write. Installed langgraph 1.2.12 reads that function from `Annotated`.

- `tasks`: merge by id. The existing order stays. An update replaces one id or appends a new id.
- `results`: merge by task id. Replacing one id leaves the other ids in place.
- `errors`: append. Older errors stay.
- `goal`, `review`, `final_output`, and `status`: latest write wins.

A partial or invalid update raises `StateUpdateError` and is not stored. The error names the field and the problem. It does not include the rejected values.

## Helpers

Pure functions in `orchestration.state.helpers`. No I/O and no model calls.

- `validate_task_plan` rejects an empty plan, a duplicate task id, an unknown agent, a missing dependency, a repeated dependency, and a cycle.
- `ready_tasks` returns pending tasks whose dependencies are all done.
- `block_downstream` marks pending and running descendants of a failed task as blocked. Call it after a task becomes failed so those descendants do not stay pending.
- `record_task_failure` increments `attempts`. While `attempts` is below `max_task_attempts`, status returns to pending. The attempt that reaches the limit sets status to failed. A later call does not increment `attempts`.
- `record_task_success` marks the task done when an attempt remains. A failed task at the limit cannot succeed.
- `apply_review` counts `revise` and `rejected` together. The update that makes `revision_count` reach `max_review_revisions` sets run status to failed and later updates do not increment the counter. `approved` does not spend a revision.

## Limits

Settings, from the environment:

- `max_task_attempts`: default 3, minimum 1.
- `max_review_revisions`: default 2, minimum 1.

The helpers take these numbers as arguments. They do not read the environment themselves.

## Ownership

- The Supervisor writes `tasks` and the run `status` while planning. It does not write specialist `results`.
- A specialist writes only its own `results` entry and its own task.
- The Reviewer writes `review` and the run `status` that `apply_review` returns (`reviewing`, or `failed` when the revision limit is reached). If a review cannot be completed, it writes `status` `failed` and one error, and no `review`. It never writes `tasks` or `results`.
- The workflow nodes in `graph/` write the rest, and only these fields:
  - `run_tasks` passes on each specialist's own task, result, and errors. It also marks the dependents of a failed task `blocked`. If a runner crashes, returns nothing, or does not exist, it records that task as failed through `record_task_failure`, with a failed result and an error from `workflow`. It never writes `review`.
  - `revise` sets the tasks named in the Reviewer's blocking issues back to `pending` with `attempts` at 0 and the feedback in their inputs, and sets `status` to `running`. It leaves their old results in place until the re-run replaces them. If no finished task is named, it fails the run.
  - `finalize` writes `final_output` and `status` `done`, and only after an approved review.
  - `fail` writes `status` `failed`, leaves `final_output` empty, and appends one error.
  - A step limit or an unexpected error writes `status` `failed`, empties `final_output`, and appends one error.
- Append errors. Do not clear another task's result.
- Status values are only the sets above.
