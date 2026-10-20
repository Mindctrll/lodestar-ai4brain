import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.api.main import app
from backend.registry.loader import load_registry
from backend.registry.models import Game, Knob, Registry

PLAN_DIMENSIONS = {
    "selective_attention", "sustained_attention", "divided_attention", "inhibition",
    "working_memory", "short_term_memory", "processing_speed", "cognitive_flexibility",
    "planning", "reasoning", "spatial_thinking", "verbal_skill", "numerical_thinking",
    "decision_style", "accuracy_awareness", "creativity",
}  # fmt: skip

# docs/plan/06, "Core set".
PLAN_P1_GAMES = {
    "quick_draw", "ink_clash", "arrow_storm", "odd_one_out", "hold_it", "echo", "light_path",
    "market_list", "souk_rush", "symbol_code", "switch", "pattern_gap", "spot_the_mistake",
    "turn_it", "number_line",
}  # fmt: skip


@pytest.fixture(scope="module")
def registry() -> Registry:
    return load_registry()


def test_dimensions_match_plan(registry: Registry) -> None:
    assert {d.id for d in registry.dimensions} == PLAN_DIMENSIONS


def test_p1_games_match_plan(registry: Registry) -> None:
    assert {g.id for g in registry.games if g.phase == "P1"} == PLAN_P1_GAMES


def test_core_set_covers_established_skills_except_sustained_attention(
    registry: Registry,
) -> None:
    established = {d.id for d in registry.dimensions if d.badge == "established"}
    covered = {d for g in registry.games if g.phase == "P1" for d in g.primary_dims}
    assert established - covered == {"sustained_attention"}


def test_experimental_dimensions_stay_out_of_overall(registry: Registry) -> None:
    for dim in registry.dimensions:
        if dim.badge == "experimental":
            assert not dim.in_overall


def test_onboarding_battery_uses_core_games(registry: Registry) -> None:
    battery = registry.batteries["onboarding"]
    assert battery.games[0] == "quick_draw"  # also measures device lag (UW1)
    assert all(registry.game(g).phase == "P1" for g in battery.games)
    assert registry.core_skills() == {
        "processing_speed", "inhibition", "selective_attention",
        "working_memory", "spatial_thinking", "reasoning",
    }  # fmt: skip


def test_knobs_move_from_easy_to_hard(registry: Registry) -> None:
    for game in registry.games:
        for name, knob in game.knobs.items():
            assert game.knobs_at(0.0)[name] == knob.easy
            assert game.knobs_at(1.0)[name] == knob.hard
            values = [knob.at(i / 10) for i in range(11)]
            assert values == sorted(values) or values == sorted(values, reverse=True), name


def test_int_knob_rounds_half_up() -> None:
    assert Knob(easy=1, hard=4).at(0.5) == 3.0


def test_reliability_follows_origin(registry: Registry) -> None:
    assert registry.game("echo").effective_reliability == 1.0
    assert registry.game("souk_rush").effective_reliability == 0.8
    assert registry.game("teach_me").effective_reliability == 0.5


def test_providers(registry: Registry) -> None:
    hosted = {p.id for p in registry.providers if p.needs_key}
    assert hosted == {
        "anthropic", "openai", "gemini", "deepseek", "xai", "mistral", "groq", "openrouter",
    }  # fmt: skip
    assert not registry.provider("anthropic").capabilities.forced_tool_choice


def _game(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "test_game", "name": "Test", "kind": "game", "phase": "P1",
        "dims": {"reasoning": 1.0}, "origin": "classic", "paradigm": "x", "code_source": "own",
        "does": "x", "scoring": "binary", "duration_s": 60, "metrics": ["accuracy"],
        "knobs": {"n": {"easy": 1, "hard": 3}}, "level_map": "linear", "content": "code",
        "modalities": ["keyboard"], "acs_hooks": [], "practice_trials": 3,
    }  # fmt: skip
    return base | overrides


def test_game_needs_a_primary_dimension() -> None:
    with pytest.raises(ValidationError, match="primary"):
        Game.model_validate(_game(dims={"reasoning": 0.5}))


def test_level_map_needs_knobs() -> None:
    with pytest.raises(ValidationError, match="level_map"):
        Game.model_validate(_game(knobs={}))


def test_unknown_dimension_is_rejected(registry: Registry) -> None:
    bad = Game.model_validate(_game(id="bad", dims={"telepathy": 1.0}))
    with pytest.raises(ValidationError, match="unknown dimensions"):
        Registry.model_validate(registry.model_dump() | {"games": [*registry.games, bad]})


def test_registry_endpoint_hides_test_provider() -> None:
    body = TestClient(app).get("/registry").json()
    assert len(body["dimensions"]) == 16
    assert "stub" not in {p["id"] for p in body["providers"]}
