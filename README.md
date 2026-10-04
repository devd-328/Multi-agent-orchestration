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

Copy `.env.example` to `.env`, then set `LLM_MODEL` and `LLM_BASE_URL`. `LLM_PROVIDER` defaults to `ollama` when it is unset. Provider name, model name, and base URL are read from the environment only. `.env` is gitignored. Do not commit it.

`make install` runs the same `uv sync` command when `make` is available.

## Run

```text
uv run uvicorn orchestration.api.app:app --host 127.0.0.1 --port 8000
```

`make run` runs that command when `make` is available.

Open `GET /health`. A healthy process returns status `ok` and the package version.

Startup reads settings before the server accepts traffic. Missing or invalid settings stop the process. The error names the setting and the error type, and it does not print setting values.

## Test and lint

```text
uv run pytest
uv run ruff check src tests
```

`make test` and `make lint` run those commands when `make` is available.
