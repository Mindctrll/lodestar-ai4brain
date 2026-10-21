# Build context is the repo root (pyproject.toml and uv.lock live there).
FROM python:3.14.5-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.19 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    FASTEMBED_CACHE_PATH=/opt/fastembed

WORKDIR /app
COPY pyproject.toml uv.lock .python-version README.md ./
RUN uv sync --frozen --no-dev --no-install-project
# Bake the local embedding models into the image (no download at first request).
RUN python -c "from fastembed import TextEmbedding, SparseTextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5'); SparseTextEmbedding('Qdrant/bm25')" \
    && chmod -R a+rX /opt/fastembed

RUN useradd --create-home --uid 1000 najma && mkdir -p /app/memory /app/models && chown najma /app/memory /app/models
COPY alembic.ini ./
COPY backend ./backend
COPY registry ./registry

USER najma
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn backend.api.main:app --host 0.0.0.0 --port 8000"]
