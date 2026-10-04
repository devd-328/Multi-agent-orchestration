.PHONY: install run test lint

install:
	uv sync

run:
	uv run uvicorn orchestration.api.app:app --host 127.0.0.1 --port 8000

test:
	uv run pytest

lint:
	uv run ruff check src tests
