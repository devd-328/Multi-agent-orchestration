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
- **Outputs:** an update with its own task and its own `TaskResult`. `output` is the cited summary. `sources` lists every retrieved source as `[n] title (url)`, and entry n is the source that citation `[n]` refers to. `excerpts[n - 1]` is the text of that source the summary was written from, cut to `max_source_chars` and then to `max_review_excerpt_chars`, so the Reviewer can check claims. A result with partial search failures is still `done` and carries the failure text in `error`.
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

Status: V1. Code: `src/orchestration/agents/reviewer/`.

- **Role:** Check the completed task results against the user goal. Report a verdict with issues. Do not redo the specialist work and do not search.
- **Inputs:** `goal`, `tasks`, `results`, and `review` from shared state; an `LLMProvider`; `ReviewerLimits` (built from settings).
- **Outputs:** a `Review` with a verdict (`approved`, `revise`, or `rejected`), the issues, and the revision count, plus the run `status` from `apply_review`. Each issue is stored as text: `[blocking] task t1: what is wrong and what to change`, or `[minor] goal: ...` for an issue about the goal as a whole. Blocking issues are listed first. If the review cannot be completed, the output is run `status` `failed` and one `StateError` from `reviewer`, and no `Review`.
- **Tools:** none. The Reviewer reads state and calls the shared model interface. It cannot search, send, publish, or write anywhere else. The provider can use a different model for review when `reviewer_model` is set (see Config in [conventions.md](conventions.md)).
- **Order of checks:**
  1. Deterministic checks, no model call. Skipped tasks are ignored. Every other task needs a result, that result must not be `failed` or unfinished, and the task must be `done`. A `done` result that carries an `error` is a tolerated partial failure (the Research Agent records failed searches that way) and is passed to the model as a note. Each summary must be non-empty. Every `[n]` citation must map to a source of that result. A result with sources must cite at least one, and each cited source needs a non-empty excerpt. A result with no sources must state "no useful sources". If every result has no sources, the review is `revise`. Any hard failure returns a verdict at once and lists every failing task. The verdict is `rejected` when no reviewed task has a `done` result, and `revise` otherwise. The Supervisor routes both the same way until the revision limit.
  2. Model review, only if step 1 passes. The prompt (version `reviewer-v1`, in `prompt.py`) carries the goal, each task description, each summary, and the numbered source excerpts, and asks for (a) completeness, (b) claims supported by the cited excerpt, (c) no invented names, dates, or numbers, (d) quality, and (e) policy: no external action asked for or claimed, no secrets or personal data. The model returns JSON with a verdict and issues, each with a severity (`blocking` or `minor`), a task id or null, and a description.
- **Validation:** `approved` needs zero blocking issues. `revise` and `rejected` need at least one blocking issue. A blocking description must be at least 10 characters, which is a length check only and cannot prove the wording is actionable. Unknown verdicts or severities, unknown task ids, more than 20 issues, and descriptions over 500 characters are invalid. Invalid output is sent back with the error, up to `max_review_attempts` model calls (default 3).
- **Fail closed:** A provider error, a missing or overlong goal, or invalid output after the attempt limit fails the run with a safe error. The Reviewer never defaults to `approved`.
- **Revisions:** The count and the stop come from `apply_review` and `max_review_revisions`. When the limit is already reached, the Reviewer still runs and reports its honest verdict. The count does not grow past the limit, the run `status` is `failed`, and the Supervisor's `route` returns `fail`.
- **Untrusted content:** The goal, task text, summaries, notes, and excerpts are placed in the prompt as delimited data. Text that looks like a prompt delimiter is broken up first, and the prompt tells the model to ignore instructions inside the data. This does not stop a model from being fooled. The deterministic checks and the verdict rules run in code regardless of what the data says.
- **Logs:** agent id, run status, verdict, stage (`checks` or `model`), blocking and minor counts, revision count, and duration in milliseconds. No goals, summaries, excerpts, prompts, or keys.
