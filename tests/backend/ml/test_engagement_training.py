"""WP3.3 engagement training on a synthetic OULAD (the real files stay out of CI; `make
ml-engagement` reports the real numbers in the model card): the pipeline reads the OULAD tables,
builds weekly examples without demographics, and the served model ranks and is calibrated on
held-out students."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backend.ml import train_engagement
from backend.ml.engagement import EngagementModel


def write_oulad(folder: Path, students: int = 900, days: int = 200, seed: int = 0) -> None:
    """Students with their own habit; some drift away and stop, some of those unregister."""
    rng = np.random.default_rng(seed)
    pd.DataFrame(
        {
            "code_module": ["AAA"],
            "code_presentation": ["2013J"],
            "module_presentation_length": [days],
        }
    ).to_csv(folder / "courses.csv", index=False)
    vle, reg, subs = [], [], []
    assessments = pd.DataFrame(
        {
            "code_module": "AAA",
            "code_presentation": "2013J",
            "id_assessment": [1, 2, 3],
            "assessment_type": "TMA",
            "date": [50, 100, 150],
            "weight": 10,
        }
    )
    for s in range(students):
        habit = float(rng.beta(2, 2))
        quits = int(rng.integers(30, days)) if rng.random() < 0.4 else None
        gone = quits + 3 if quits is not None and rng.random() < 0.5 else None
        reg.append(("AAA", "2013J", s, -10, gone if gone is not None else np.nan))
        for d in range(-5, days):
            fading = 1.0 if quits is None else max(0.0, 1 - (d - (quits - 20)) / 20)
            if d >= (quits or days + 1):
                break
            if rng.random() < habit * min(1.0, fading):
                vle.append(("AAA", "2013J", s, 1, d, int(rng.poisson(5)) + 1))
        for a, due in zip((1, 2, 3), (50, 100, 150), strict=True):
            if quits is None or due < quits:
                subs.append((a, s, due, 0, 70 if habit > 0.4 else 30))
    pd.DataFrame(
        vle,
        columns=["code_module", "code_presentation", "id_student", "id_site", "date", "sum_click"],
    ).to_csv(folder / "studentVle.csv", index=False)
    pd.DataFrame(
        reg,
        columns=[
            "code_module",
            "code_presentation",
            "id_student",
            "date_registration",
            "date_unregistration",
        ],
    ).to_csv(folder / "studentRegistration.csv", index=False, na_rep="?")
    assessments.to_csv(folder / "assessments.csv", index=False)
    pd.DataFrame(
        subs, columns=["id_assessment", "id_student", "date_submitted", "is_banked", "score"]
    ).to_csv(folder / "studentAssessment.csv", index=False)


def test_training_on_a_synthetic_oulad(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_oulad(tmp_path)
    monkeypatch.setattr(train_engagement, "DATA", tmp_path)
    result = train_engagement.train()
    lr = result["results"]["logistic regression"]
    assert lr["auc"] > 0.75
    assert lr["ece"] < 0.05 and lr["brier"] <= lr["brier_raw"] + 0.01
    assert result["deciles_inside_range"] >= 5
    assert set(result["examples"]) == {"train", "calib", "test"}
    model = EngagementModel.from_metrics(result["version"], result)
    quiet = [30.0, 0, 0, 0, 0.0, 0, 0, 60]  # away a month
    busy = [0.0, 7, 7, 28, 0.0, 28, 0, 60]  # every day
    assert model.risk(quiet).p > model.risk(busy).p
    card = train_engagement.card(result)
    assert "No demographics" in card and "| logistic regression |" in card
