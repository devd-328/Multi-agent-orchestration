# Core structure

- **Title:** Core structure
- **Date:** 2026-10-04
- **Status:** accepted

## Context

Roadmap step 1 needs a Python package, a dependency manager, environment-based settings, and logging. [conventions.md](../conventions.md) left the package name, test runner, settings loader, and log format as TBD. Its planned layout also differs from the folders this step creates.

## Decision

- Package name: `orchestration`, under `src/orchestration/`.
- Dependency manager: uv. Direct dependencies are pinned in `pyproject.toml` after the versions were confirmed on PyPI, and the full set is locked in `uv.lock`.
- Layout for this step: `api/`, `agents/`, `graph/`, `state/`, `llm/`, `tools/`, and `core/` (`config.py`, `logging.py`, `errors.py`).
- Settings loader: pydantic-settings. Provider, model, and base URL come from environment variables.
- Log format: one JSON object per line, written with the standard library.
- Test runner: pytest.
- Lint: ruff.

## Why

- uv 0.9.18 is installed here and locks the dependency set that was verified to exist.
- The step 1 task asks for this package layout, including `llm/` and `core/`.
- pydantic-settings reads the environment and rejects invalid settings before the API serves traffic.
- JSON logging needs no extra library. The formatter redacts extra fields whose names look like secrets.

## Consequences

- Later agents call `LLMProvider.generate`. Provider adapters are not implemented in this step.
- [conventions.md](../conventions.md) still says the package name is TBD and shows `providers/`, `state.py`, and a top-level `config.py`. That file was not edited in this step. A later docs pass should align it with this record.
- `make` is not installed on the current Windows machine. The Makefile targets are `uv sync`, `uv run uvicorn`, `uv run pytest`, and `uv run ruff check`.
