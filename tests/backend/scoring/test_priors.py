"""Cold-start priors from NCPT correlations (docs/plan/10, WP2.7)."""

from pathlib import Path

import numpy as np

from backend.registry.loader import load_registry
from backend.scoring.kalman_elo import SIGMA_START, Belief
from backend.scoring.priors import cold_start, nearest_correlation
from simulator.population import ability_dims, correlation_matrix

REGISTRY = load_registry()
PRIORS = REGISTRY.priors


def test_priors_file_is_valid_and_has_no_demographics() -> None:
    assert PRIORS is not None and "CC BY 4.0" in PRIORS.source
    dims = {d.id for d in REGISTRY.dimensions}
    for a, b, r, n in PRIORS.correlations:
        assert a in dims and b in dims and -1 < r < 1 and n > 1000
    text = Path("registry/priors.yaml").read_text().lower()
    assert "age" not in text.split() and "gender" not in text


def test_a_strong_measured_skill_lifts_a_correlated_new_one() -> None:
    sure = {"processing_speed": Belief(1.5, 0.3, 30)}
    vague = {"processing_speed": Belief(1.5, 1.2, 2)}
    prior = cold_start("working_memory", sure, PRIORS)
    assert 0.2 < prior.mu < 1.0 and prior.n == 0
    assert SIGMA_START * 0.8 < prior.sigma < SIGMA_START  # still wide
    assert 0 < cold_start("working_memory", vague, PRIORS).mu < prior.mu  # vaguer, smaller move
    low = cold_start("working_memory", {"processing_speed": Belief(-1.5, 0.3, 30)}, PRIORS)
    assert low.mu < 0


def test_no_information_means_the_usual_start() -> None:
    assert cold_start("working_memory", {}, PRIORS) == Belief()
    assert cold_start("spatial_thinking", {"reasoning": Belief(1, 0.3, 9)}, PRIORS) == Belief()
    assert cold_start("working_memory", {"reasoning": Belief(1, 0.3, 9)}, None) == Belief()
    unmeasured = {"processing_speed": Belief(1.5, 0.3, 0)}  # n = 0: not a measurement
    assert cold_start("working_memory", unmeasured, PRIORS) == Belief()


def test_simulator_population_uses_a_valid_correlation_matrix() -> None:
    dims = ability_dims(REGISTRY)
    m = correlation_matrix(dims, PRIORS)
    assert np.allclose(m, m.T) and np.allclose(np.diag(m), 1.0)
    assert np.linalg.eigvalsh(m).min() > 0
    i, j = dims.index("processing_speed"), dims.index("cognitive_flexibility")
    assert abs(m[i, j] - 0.554) < 0.05  # the NCPT value, barely changed by the repair
    fixed = nearest_correlation(np.array([[1, 0.9, -0.9], [0.9, 1, 0.9], [-0.9, 0.9, 1.0]]))
    assert np.linalg.eigvalsh(fixed).min() > 0
