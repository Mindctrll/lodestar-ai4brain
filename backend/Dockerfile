# Build context is the repo root (pyproject.toml and uv.lock live there).
FROM python:3.14.5-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.19 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    FASTEMBED_CACHE_PATH=/opt/fastembed \
    HF_HOME=/opt/hf

# LightGBM (growth forecast, docs/plan/10) needs the OpenMP runtime.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml uv.lock .python-version README.md ./
RUN uv sync --frozen --no-dev --no-install-project --extra whisper
# Bake the local embedding models and the private-voice speech model into the image (no download
# at first request).
RUN python -c "from fastembed import TextEmbedding, SparseTextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5'); SparseTextEmbedding('Qdrant/bm25')" \
    && python -c "from faster_whisper import WhisperModel; WhisperModel('base.en', device='cpu', compute_type='int8')" \
    && chmod -R a+rX /opt/fastembed /opt/hf

RUN useradd --create-home --uid 1000 lodestar && mkdir -p /app/memory /app/models && chown lodestar /app/memory /app/models
COPY alembic.ini ./
COPY backend ./backend
COPY registry ./registry

USER lodestar
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn backend.api.main:app --host 0.0.0.0 --port 8000"]
