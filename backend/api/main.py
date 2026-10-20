"""FastAPI entry point. Routes are added by later work packages (see docs/plan/02)."""

from fastapi import FastAPI

app = FastAPI(title="Najma API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
