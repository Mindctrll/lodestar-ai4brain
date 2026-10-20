"""From the registry to update weights: w = loading x reliability x context_weight x trust."""

from backend.registry.models import Registry


def loading_matrix(registry: Registry) -> dict[str, dict[str, float]]:
    """game id -> {dimension id -> loading}, skipping dimensions shown as a style or measured
    only by calibration (they aren't ability scores)."""
    ability_dims = {d.id for d in registry.dimensions if not d.style}
    matrix: dict[str, dict[str, float]] = {}
    for game in registry.games:
        if game.scoring in {"style", "calibration", "none"}:
            continue
        dims = {d: w for d, w in game.dims.items() if d in ability_dims}
        if dims:
            matrix[game.id] = dims
    return matrix


def update_weight(loading: float, reliability: float, context_weight: float, trust: float) -> float:
    for name, value in (
        ("loading", loading),
        ("reliability", reliability),
        ("context_weight", context_weight),
        ("trust", trust),
    ):
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{name} must be in [0, 1], got {value}")
    return loading * reliability * context_weight * trust
