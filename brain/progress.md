# Progress

## Done

- 2026-10-04: Created `brain/` as the source of truth (plan, architecture, conventions). No application code.
- 2026-10-04: Added `brain/RULES.md`. `agent-instructions.md` now points to it. No application code.
- 2026-10-04: Published `brain/` and the root README to https://github.com/devd-328/Multi-agent-orchestration. Kept the existing MIT license.
- 2026-10-04: Roadmap step 1, core structure. Package `orchestration`, settings, logging, and `GET /health`. No agents, graphs, or model calls. See [decisions/core-structure.md](decisions/core-structure.md).
- 2026-10-04: Roadmap step 2, LangGraph state. Typed state, reducers, and plan helpers. No agents or model calls. See [state.md](state.md).
- 2026-10-04: Roadmap step 3, Supervisor. Planning, routing, and an Ollama adapter behind `LLMProvider`. No Research Agent, Reviewer, or workflow graph. See [agents.md](agents.md).
- 2026-10-05: Roadmap step 4, Research Agent. Search layer with a Tavily adapter behind `SearchProvider`, and the agent that returns a cited `TaskResult`. No Reviewer or workflow graph. See [agents.md](agents.md).
- 2026-10-05: Roadmap step 5, Reviewer. Deterministic checks, then a model review with a validated verdict, on branch `step-5-reviewer`. Added `TaskResult.excerpts` and filled it in the Research Agent. Declared `httpx` in `pyproject.toml`. No workflow graph or final answer composition. See [agents.md](agents.md).
- 2026-10-05: Roadmap step 6, Basic workflow. One LangGraph graph runs plan, research, review, revise, finalize, and fail, routed only by the Supervisor's `route`. `run_workflow`, `build_default_providers`, and the CLI `python -m orchestration run "<goal>"`. The Research Agent accepts revise feedback. No new agents, API endpoint, persistence, or tracing. See [architecture.md](architecture.md).

- 2026-10-06: Web interface. `GET /` serves a single page (plain HTML, CSS, and JS, no new dependency) with a goal box, live progress, the Reviewer verdict, the final answer with copy and download, recent runs, and a light and dark theme. New API: `GET /api/status`, `POST /api/runs`, `GET /api/runs`, `GET /api/runs/{id}`. `run_workflow` gained an optional `on_update` callback for progress. Runs are in memory, capped at 2 active, and cannot be cancelled. Not verified: a full run against the real Ollama model, which answered 402 in `tests/llm/test_ollama_live.py` for the `:cloud` model in `.env`.

## In progress

- None.

## Blocked

- None.

## Next step

- Roadmap step 7, Testing. Not started.
