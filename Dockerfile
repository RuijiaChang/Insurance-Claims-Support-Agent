FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
COPY backend/ /app/backend/
COPY apps/ /app/apps/
WORKDIR /app/backend
RUN uv sync --frozen --no-dev
ENV FIXTURES_DIR=/app/apps/insurance_claims/fixtures
ENV PATH="/app/backend/.venv/bin:$PATH"
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import os,urllib.request;urllib.request.urlopen('http://localhost:'+os.environ.get('PORT','8000')+'/api/health')" || exit 1
CMD uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
