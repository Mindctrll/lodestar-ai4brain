"""GET /registry: the skills, games and AI providers that drive the UI."""

from fastapi import APIRouter

from backend.registry.loader import load_registry
from backend.registry.models import Registry

router = APIRouter(tags=["registry"])


@router.get("/registry", response_model=Registry)
def get_registry() -> Registry:
    registry = load_registry()
    visible = [p for p in registry.providers if not p.hidden]
    return registry.model_copy(update={"providers": visible})
