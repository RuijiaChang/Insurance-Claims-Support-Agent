dev:
	$(MAKE) -j2 dev-backend dev-frontend

dev-backend:
	cd backend && set -a; [ -f ../.env ] && . ../.env; set +a; uv run uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd frontend && npm run dev

test:
	cd backend && uv run pytest

lint:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy

docker:
	docker build -t sop-agent .

eval:
	cd backend && set -a; [ ! -f ../.env ] || . ../.env; set +a; uv run python -m evals.run_evals

.PHONY: dev dev-backend dev-frontend test lint docker eval
