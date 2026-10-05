.PHONY: install run run-goal test lint

install:
	uv sync

run:
	uv run uvicorn orchestration.api.app:app --host 127.0.0.1 --port 8000

run-goal:
	uv run python -m orchestration run "$(GOAL)"

test:
	uv run pytest

lint:
	uv run ruff check src tests
