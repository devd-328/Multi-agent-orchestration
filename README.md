# Multi-Agent Orchestration System

Open-source, modular multi-agent system.

Plan, architecture, and conventions live in [`brain/`](brain/README.md). Read that folder before changing code.

## Requirements

- Python 3.11 or newer
- uv

Dependency versions are pinned in `pyproject.toml` and locked in `uv.lock`.

## Setup

```text
uv sync
```

Copy `.env.example` to `.env`, then set `LLM_MODEL` and `LLM_BASE_URL`. `LLM_PROVIDER` defaults to `ollama` when it is unset. Set `SEARCH_API_KEY` for the Research Agent. `SEARCH_PROVIDER` defaults to `tavily`. Provider names, the model name, the base URL, and the search key are read from the environment only. `.env` is gitignored. Do not commit it.

`make install` runs the same `uv sync` command when `make` is available.

## Run

```text
uv run uvicorn orchestration.api.app:app --host 127.0.0.1 --port 8000
```

`make run` runs that command when `make` is available.

Open `GET /health`. A healthy process returns status `ok` and the package version.

Open `http://127.0.0.1:8000/` for the web interface. Type a goal, press Run, and watch the plan, research, and review steps. The final answer shows as markdown with numbered sources, and you can copy or download it. The page needs the same settings as the command line (`LLM_MODEL`, `LLM_BASE_URL`, `SEARCH_API_KEY`) and shows what is missing. `.env` is read on each run.

API used by the page: `GET /api/status`, `POST /api/runs` with `{"goal": "..."}`, `GET /api/runs`, and `GET /api/runs/{id}`. At most 2 runs work at once. Runs are kept in memory only and are lost on restart. A running goal cannot be cancelled yet.

Startup reads settings before the server accepts traffic. Missing or invalid settings stop the process. The error names the setting and the error type, and it does not print setting values.

## Run a goal

The workflow plans the goal, researches it on the web, reviews the result, and prints a final answer with sources. It needs a model provider (Ollama by default, with `LLM_MODEL` and `LLM_BASE_URL` set) and a search key (`SEARCH_API_KEY`).

```text
uv run python -m orchestration run "Research upcoming technology events and summarize the useful findings with sources."
```

`make run-goal GOAL="..."` runs the same command when `make` is available.

- On success, the final answer is printed to stdout as markdown, one section per task with its own numbered sources, and the exit code is 0.
- On failure, nothing is printed to stdout. A safe summary of the errors goes to stderr, and the exit code is 1. A review that never approves ends here too, after `MAX_REVIEW_REVISIONS` tries.
- Missing or invalid configuration, such as a missing `SEARCH_API_KEY`, stops the run before any model call. The message names the setting and never prints its value. The exit code is 2.
- Logs are JSON lines on stderr. Each run has a run id, printed on stderr and on every log line of that run.
- `MAX_GRAPH_STEPS` (default 100) caps the number of graph steps, so a bug cannot loop forever.

The run makes model calls and web searches only. It sends nothing, publishes nothing, and writes no files.

## Test and lint

```text
uv run pytest
uv run ruff check src tests
```

`make test` and `make lint` run those commands when `make` is available.
