dev:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

test:
	cd backend && uv run pytest

lint:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy

docker:
	docker build -t sop-agent .

eval:
	cd backend && uv run python -m app.eval

.PHONY: dev test lint docker eval
