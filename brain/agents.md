# Agents

Eight agents. Each has one narrow job and a short tool list. No agent does another agent's work.

V1: Supervisor, Research, Reviewer. All others are planned. Workflow: [vision.md](vision.md). Failure rules: [architecture.md](architecture.md). Approval rules: [security-and-approvals.md](security-and-approvals.md).

## Supervisor

Status: V1. Code: `src/orchestration/agents/supervisor/`.

- **Role:** Orchestrate. Turn the user goal into a task plan and choose the next step. Do not research, draft, code, or review. Plan output is tasks only. It does not include specialist findings.
- **Inputs:** user goal; shared state; a model provider that implements `LLMProvider`. Provider and model name come from settings.
- **Outputs:** validated `tasks`; run `status` (`running` or `failed`); a routing decision: `run`, `review`, `revise`, `fail`, or `finish`.
- **Tools:** none. `plan` calls the shared model interface. `route` is a pure function and does not call a model.
- **Planning:** Prompt version `supervisor-plan-v1` lives in `prompt.py`. The goal is inserted as data, not as instructions. The model must return a JSON plan. Each task needs `id`, `description`, `assigned_agent`, `depends_on`, and `inputs`. `plan` parses that JSON (including a fenced or surrounded object) and checks it with `validate_task_plan`. Tasks may be assigned only to specialist agents in `AgentId`. V1 specialist: `research`. `supervisor` and `reviewer` cannot be assigned tasks. Invalid JSON or a failed check is sent back to the model with the validation error, up to `max_plan_attempts` (default 3, minimum 1). After that limit, `status` is `failed` and one error is appended. A missing goal, a goal longer than 8000 characters, or a model request failure stops immediately and does not use the remaining plan attempts.
- **Routing:** `route` uses `ready_tasks`, `block_downstream`, and `max_review_revisions`. It does not write state.
  - `run`: at least one task is ready, and no task has failed.
  - `review`: every task is done, and there is no review verdict that already chooses another step.
  - `revise`: the verdict is `revise` or `rejected`, and `revision_count` is below `max_review_revisions`. This sends control back to the Supervisor. Applying a revised plan is a later step. `plan` writes the first plan and does not delete tasks already in state, because the task reducer merges by id.
  - `fail`: the run status is `failed`, a task has failed, nothing is ready (including when work is blocked), or the revision limit is reached.
  - `finish`: the verdict is `approved`.
- **Failure:** The cases above write `status: failed` and a `StateError` from `supervisor` when `plan` is the caller. `route` only returns `fail`. Logs include the agent id, status, error type, and, after a plan is accepted, the task count and assigned agents. Logs do not include the prompt, the goal, or secrets.
- **Model calls:** Agents depend on `LLMProvider` only. The Ollama adapter and the provider factory live under `llm/`. A request uses `llm_timeout_seconds` (default 60). Timeout, an unreachable provider, a non-200 response, and a malformed response raise `LLMError` with a fixed message. The message does not include the prompt, the URL, or the response body.

## Research

Status: V1. Code: `src/orchestration/agents/research/`.

- **Role:** Run one research task from the plan. Search the web, then summarize only what the retrieved sources say, with a source number on each claim.
- **Inputs:** one `Task` assigned to `research`; the `TaskResult` of each task in its `depends_on`; an `LLMProvider`; a `SearchProvider`; `ResearchLimits` (built from settings).
- **Outputs:** an update with its own task and its own `TaskResult`. `output` is the cited summary. `sources` lists every retrieved source as `[n] title (url)`, and entry n is the source that citation `[n]` refers to. A result with partial search failures is still `done` and carries the failure text in `error`.
- **Tools:** `SearchProvider.search` only. The agent cannot send, publish, spend, or write anywhere. The Tavily adapter sits behind `SearchProvider`, selected by `search_provider`. The key comes from `SEARCH_API_KEY` and is never logged.
- **Steps:**
  1. Ask the model for 1 to `max_search_queries` search queries as JSON. Invalid JSON, zero queries, too many queries, or an invalid query is sent back with the error, up to `max_research_attempts` model calls (default 3).
  2. Run each query for up to `max_results_per_query` results. Merge the results by url, drop results with no content or a non-http url, and cut each content to `max_source_chars`.
  3. Ask the model to summarize using only those sources. The summary must cite at least one source, and every cited number must be a retrieved source number. A summary that fails is sent back with the error, within the same `max_research_attempts` limit.
- **Untrusted content:** The task text, inputs, dependency outputs, and every source are placed in the prompt as delimited data, and the summary prompt tells the model to ignore instructions inside them. Text that looks like a prompt delimiter is broken up before it is inserted. Prompt version `research-v1` lives in `prompt.py`. The citation check proves only that cited numbers exist. It does not prove that a source supports a claim.
- **Failure:** The result is `failed` with a safe message (no key, no raw response body, no prompt) when: the task text is empty or over 4000 characters, a dependency has no usable `done` result, the model request fails, queries or the summary stay invalid after the attempt limit, or every search fails. If only some searches fail, the agent continues with the rest and records the partial failure. If no usable source remains, the result is `done` with a plain statement that nothing useful was found, and the agent does not call the model for a summary. A failed summary step keeps the retrieved sources in `sources`.
- **Task status:** The task follows `record_task_success` and `record_task_failure`. A failed attempt returns the task to `pending` until `max_task_attempts` is reached, then it is `failed`. The `TaskResult` is `failed` for every failed attempt.
- **Logs:** agent id, task id, status, query count, failed query count, result count, source count, duration in milliseconds, and the error type. No prompts, queries, source text, or keys.

## Content

Status: planned

- **Role:** Draft content for an assigned task. Do not publish.
- **Inputs:** TBD.
- **Outputs:** content draft. Shape TBD.
- **Tools:** TBD. No publishing tools.
- **Failure:** Use the reliability rules in [architecture.md](architecture.md) when this agent is built.

## Marketing

Status: planned

- **Role:** Draft marketing material for an assigned task. Do not send or publish it.
- **Inputs:** TBD.
- **Outputs:** marketing draft. Shape TBD.
- **Tools:** TBD. No send or publish tools.
- **Failure:** Use the reliability rules in [architecture.md](architecture.md) when this agent is built.

## Events

Status: planned

- **Role:** Event specialist for an assigned task. V1 research about events stays with the Research Agent.
- **Inputs:** TBD.
- **Outputs:** TBD.
- **Tools:** TBD. No send or publish tools.
- **Failure:** Use the reliability rules in [architecture.md](architecture.md) when this agent is built.

## Coding

Status: planned

- **Role:** Carry out an assigned coding task. Do not deploy and do not push to main.
- **Inputs:** TBD.
- **Outputs:** TBD.
- **Tools:** TBD. Production deploy and push to main require human approval.
- **Failure:** Use the reliability rules in [architecture.md](architecture.md) when this agent is built.

## Ad

Status: planned

- **Role:** Draft ad material for an assigned task. Do not spend money and do not publish ads.
- **Inputs:** TBD.
- **Outputs:** ad draft. Shape TBD.
- **Tools:** TBD. Paid ads require human approval.
- **Failure:** Use the reliability rules in [architecture.md](architecture.md) when this agent is built.

## Reviewer

Status: V1

- **Role:** Check specialist output against the user goal. Approve or reject with notes. Do not redo the specialist work.
- **Inputs:** user goal; specialist output; shared state.
- **Outputs:** `approved` or `rejected`, plus notes.
- **Tools:** read-only. Exact tools: TBD. No side-effect tools.
- **Failure:** Missing or invalid output is a rejection with notes. Rejection returns to the Supervisor. Retries are bounded (limit TBD). Do not loop without a bound.
