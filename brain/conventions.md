# Conventions

Coding agents also follow [agent-instructions.md](agent-instructions.md).

## Code

- Python.
- Package name: `orchestration`, under `src/orchestration/`.
- One agent per module. Agent ids: `supervisor`, `research`, `content`, `marketing`, `events`, `coding`, `ad`, `reviewer`.
- V1 state registers `supervisor`, `research`, and `reviewer` in `AgentId`. Adding an agent starts with that registry. See [state.md](state.md).
- Agents call the shared model interface. No Ollama- or vLLM-specific branches in agent code. See [architecture.md](architecture.md).
- Implement the failure cases in architecture.md. Bounded retries. No silent failures.
- Keep changes small. Reuse an existing module before adding one.

## Layout

```text
brain/                         this documentation
src/orchestration/             Python package
  api/                         FastAPI entry
  agents/                      one module per agent
  graph/                       LangGraph workflow
  state/                       shared state schema, reducers, and plan helpers
  cli.py                       command line entry (python -m orchestration run "<goal>")
  llm/                         model provider interface
  search/                      web search interface and adapters
  tools/                       tool adapters
  core/                        config.py, logging.py, errors.py
tests/                         mirrors the package
```

A new agent adds one registry member, one module under `agents/`, one spec in [agents.md](agents.md), and one graph entry. A new tool is registered on one agent only.

## Naming

- Files, modules, and functions: `snake_case`.
- Agent ids match [agents.md](agents.md).
- Tools are named by action, not by vendor.

## Testing

- Cover routing, state updates, approve/reject, and bounded failure paths.
- Fake model and tool calls in unit tests.
- Test runner: pytest.

## Logging

- Log agent id, task id, status, and error type.
- Never log secrets, tokens, or environment values. See [security-and-approvals.md](security-and-approvals.md).
- Log format: one JSON object per line, written with the standard library in `orchestration.core.logging`.

## Config

- Read settings from environment variables through pydantic-settings in `orchestration.core.config`.
- Provider name, model name, and endpoints are config.
- `max_task_attempts` defaults to 3. `max_review_revisions` defaults to 2. `max_plan_attempts` defaults to 3. Each limit must be at least 1. `llm_timeout_seconds` defaults to 60 and must be greater than 0. Search settings: `search_provider` (default `tavily`), `search_api_key` (secret, from the environment only), `search_timeout_seconds` (default 20, above 0), `max_search_queries` (default 3, 1 to 10), `max_results_per_query` (default 5, 1 to 20), `max_source_chars` (default 2000, at least 1), and `max_research_attempts` (default 3, at least 1). A missing search key fails when the search provider is created, not at startup. Review settings: `max_review_excerpt_chars` (default 2000, at least 1), `max_review_attempts` (default 3, at least 1), and `reviewer_model` (optional; when set it replaces `llm_model` for review calls only, and a blank value counts as unset). Workflow setting: `max_graph_steps` (default 100, at least 1) is the LangGraph recursion limit for one run. Retries stay finite. See [state.md](state.md) and [agents.md](agents.md).

## Tooling

- Dependency manager: uv. Direct versions are pinned in `pyproject.toml` and locked in `uv.lock`.
- Lint: ruff.
