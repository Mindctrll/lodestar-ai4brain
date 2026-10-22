"""Train and evaluate the engagement-risk model on OULAD (docs/plan/10, section 2). Run with
`make ml-engagement` after `make ml-data`.

Examples: one per enrolment and week of a course, from the second week on, while the student is
still registered. Label: no activity at all in the next 7 days (or unregistering in them).
Features: `backend.ml.engagement.FEATURES`, behaviour only.

Compared on held-out students (never the same student in two splits): the days-since-last rule,
logistic regression and LightGBM, by AUC, Brier score and calibration. The served model is the
logistic regression unless LightGBM is clearly better (AUC +0.01), because its few numbers live
in the database and anyone can read them. Its probabilities get Venn-Abers ranges, calibrated on
the calibration students.
"""

import argparse
import datetime as dt
import hashlib
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler

from backend.ml.engagement import FEATURES, HORIZON_DAYS, feature_row, venn_abers, venn_abers_grid

DATA = Path("data/oulad")
CARD = Path("backend/ml/model_cards/engagement_risk.md")
OFFSET = 30  # OULAD days start before the course (registration, early access)
FAIL_SCORE = 40  # OULAD's pass mark
STEP = 7
LGB_PARAMS: dict[str, Any] = {
    "objective": "binary",
    "learning_rate": 0.05,
    "num_leaves": 31,
    "min_data_in_leaf": 200,
    "verbose": -1,
}


def split_of(student: np.ndarray) -> np.ndarray:
    """Students, not weeks: 60% train, 20% calibration, 20% test, fixed by a hash of the id."""
    h = np.array([int(hashlib.sha256(str(s).encode()).hexdigest()[:8], 16) % 10 for s in student])
    return np.where(h < 6, "train", np.where(h < 8, "calib", "test"))


def load() -> pd.DataFrame:
    """One row per example: features, label, student, course day."""
    courses = pd.read_csv(DATA / "courses.csv")
    length = {
        (r.code_module, r.code_presentation): int(r.module_presentation_length)
        for r in courses.itertuples()
    }
    reg = pd.read_csv(DATA / "studentRegistration.csv", na_values="?")
    unreg = {
        (r.code_module, r.code_presentation, r.id_student): r.date_unregistration
        for r in reg.itertuples()
    }
    vle = pd.read_csv(
        DATA / "studentVle.csv",
        usecols=["code_module", "code_presentation", "id_student", "date", "sum_click"],
        dtype={"id_student": "int32", "date": "int16", "sum_click": "int32"},
    )
    daily = (
        vle.groupby(["code_module", "code_presentation", "id_student", "date"], observed=True)[
            "sum_click"
        ]
        .sum()
        .reset_index()
    )
    assess = pd.read_csv(DATA / "assessments.csv")
    sub = pd.read_csv(DATA / "studentAssessment.csv", na_values="?").merge(
        assess[["id_assessment", "code_module", "code_presentation"]], on="id_assessment"
    )
    failed = sub[(sub["score"] < FAIL_SCORE) & sub["date_submitted"].notna()]
    fails: dict[tuple[str, str, int], list[int]] = {}
    for r in failed.itertuples():
        fails.setdefault((r.code_module, r.code_presentation, r.id_student), []).append(
            int(r.date_submitted)
        )

    rows: list[list[float]] = []
    meta: list[tuple[int, int, int]] = []
    for (module, pres, student), g in daily.groupby(
        ["code_module", "code_presentation", "id_student"], observed=True
    ):
        key = (str(module), str(pres), int(student))
        n_days = length[key[:2]] + OFFSET + 1
        volume = np.zeros(n_days)
        days = g["date"].to_numpy() + OFFSET
        keep = (days >= 0) & (days < n_days)
        volume[days[keep]] = g["sum_click"].to_numpy()[keep]
        fail = np.zeros(n_days)
        for d in fails.get(key, []):
            if 0 <= d + OFFSET < n_days:
                fail[d + OFFSET] += 1
        gone = unreg.get(key)
        gone_day = None if gone is None or np.isnan(gone) else int(gone) + OFFSET
        started = np.flatnonzero(volume > 0)
        if not len(started):
            continue
        for t in range(OFFSET + STEP, n_days - HORIZON_DAYS, STEP):
            if t < started[0] or (gone_day is not None and gone_day <= t):
                continue
            ahead = volume[t + 1 : t + 1 + HORIZON_DAYS]
            leaves = gone_day is not None and gone_day <= t + HORIZON_DAYS
            label = int(leaves or not np.any(ahead > 0))
            rows.append(feature_row(volume, fail, t))
            meta.append((int(student), t - OFFSET, label))
    frame = pd.DataFrame(rows, columns=list(FEATURES))
    frame[["student", "day", "label"]] = np.array(meta)
    return frame


def ece(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0.0, 1.0, bins + 1)
    which = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    total = 0.0
    for b in range(bins):
        m = which == b
        if m.any():
            total += m.mean() * abs(y[m].mean() - p[m].mean())
    return float(total)


def reliability(
    y: np.ndarray, low: np.ndarray, high: np.ndarray, p: np.ndarray
) -> list[dict[str, float]]:
    """Deciles of predicted risk: mean range against the observed rate."""
    order = np.argsort(p)
    out = []
    for chunk in np.array_split(order, 10):
        out.append(
            {
                "low": float(low[chunk].mean()),
                "high": float(high[chunk].mean()),
                "observed": float(y[chunk].mean()),
                "n": len(chunk),
            }
        )
    return out


def train(seed: int = 2026) -> dict[str, Any]:
    import lightgbm as lgb

    frame = load()
    split = split_of(frame["student"].to_numpy())
    x = frame[list(FEATURES)].to_numpy(dtype=float)
    y = frame["label"].to_numpy(dtype=float)
    tr, ca, te = (split == s for s in ("train", "calib", "test"))

    scaler = StandardScaler().fit(x[tr])
    lr = LogisticRegression(max_iter=2000, random_state=seed).fit(scaler.transform(x[tr]), y[tr])
    booster = lgb.train(LGB_PARAMS, lgb.Dataset(x[tr], y[tr]), num_boost_round=300)

    def lr_score(rows: np.ndarray) -> np.ndarray:
        return np.asarray(lr.decision_function(scaler.transform(rows)))

    results: dict[str, dict[str, float]] = {}
    rule = x[te][:, FEATURES.index("days_since_last")]
    results["days since last activity (rule)"] = {"auc": float(roc_auc_score(y[te], rule))}
    for name, scores in (
        ("logistic regression", lr_score(x[te])),
        ("LightGBM", booster.predict(x[te], raw_score=True)),
    ):
        results[name] = {"auc": float(roc_auc_score(y[te], scores))}
    use_lgb = results["LightGBM"]["auc"] > results["logistic regression"]["auc"] + 0.01

    rng = np.random.default_rng(seed)
    cal_idx = np.flatnonzero(ca)
    cal_idx = rng.choice(cal_idx, size=min(len(cal_idx), 40_000), replace=False)
    cal_scores = lr_score(x[cal_idx])
    grid, p0, p1 = venn_abers_grid(cal_scores, y[cal_idx])
    te_scores = lr_score(x[te])
    risks = [venn_abers(s, grid, p0, p1) for s in te_scores]
    low = np.array([r.low for r in risks])
    high = np.array([r.high for r in risks])
    merged = np.array([r.p for r in risks])
    raw_p = 1.0 / (1.0 + np.exp(-te_scores))
    served = results["logistic regression"]
    served.update(
        {
            "brier_raw": float(brier_score_loss(y[te], raw_p)),
            "brier": float(brier_score_loss(y[te], merged)),
            "ece_raw": ece(y[te], raw_p),
            "ece": ece(y[te], merged),
            "mean_width": float((high - low).mean()),
        }
    )
    table = reliability(y[te], low, high, merged)
    inside = sum(r["low"] - 0.01 <= r["observed"] <= r["high"] + 0.01 for r in table)
    version = dt.datetime.now(dt.UTC).strftime("%Y%m%d%H%M")
    return {
        "version": version,
        "examples": {s: int((split == s).sum()) for s in ("train", "calib", "test")},
        "students": int(frame["student"].nunique()),
        "base_rate": float(y.mean()),
        "results": results,
        "lightgbm_clearly_better": bool(use_lgb),
        "reliability": table,
        "deciles_inside_range": int(inside),
        "coefficients": dict(zip(FEATURES, lr.coef_[0].tolist(), strict=True)),
        "serving": {
            "mean": scaler.mean_.tolist(),
            "scale": scaler.scale_.tolist(),
            "coef": lr.coef_[0].tolist(),
            "intercept": float(lr.intercept_[0]),
            "grid": grid,
            "p0": p0,
            "p1": p1,
        },
    }


def card(r: dict[str, Any]) -> str:
    res = r["results"]
    lr = res["logistic regression"]
    why = (
        " (LightGBM was more than 0.01 AUC better: consider serving it)"
        if r["lightgbm_clearly_better"]
        else ", because LightGBM is not clearly better and the regression's few numbers can be "
        "read by anyone"
    )
    lines = [
        "# Model card: Engagement Risk",
        "",
        f"Generated by `backend/ml/train_engagement.py` (version {r['version']}). Do not edit by "
        "hand; run `make ml-engagement`.",
        "",
        "## What it predicts",
        "",
        "The chance that a person has no activity at all in the next 7 days, as a range "
        "(inductive Venn-Abers). Lodestar uses it to offer a shorter, easier session to someone "
        "who is drifting away. It is never shown as a score of the person.",
        "",
        "## Data",
        "",
        f"OULAD (Kuzilek et al. 2017, *Scientific Data*), CC BY 4.0: {r['students']:,} students "
        "in 22 course presentations, daily activity summaries. One example per enrolment and "
        f"course week while the student is registered: {r['examples']['train']:,} train, "
        f"{r['examples']['calib']:,} calibration and {r['examples']['test']:,} test examples, "
        f"split by student. A week off happens in {r['base_rate'] * 100:.0f}% of examples.",
        "",
        "Features are behaviour only, the ones Lodestar has too: days since last activity, active "
        "days in the last 7 days, the 7 before and the last 28, the trend in activity per active "
        "day, the current streak, failures in the last 28 days and days since starting. "
        "**No demographics** (gender, age, region, disability and deprivation are left out).",
        "",
        "## Results on held-out students",
        "",
        "| Model | AUC |",
        "|---|---|",
        *(f"| {name} | {m['auc']:.3f} |" for name, m in res.items()),
        "",
        f"Served: logistic regression{why}. Brier score {lr['brier']:.3f} (raw logistic "
        f"{lr['brier_raw']:.3f}); expected calibration error {lr['ece']:.3f} (raw "
        f"{lr['ece_raw']:.3f}); mean range width {lr['mean_width']:.3f}.",
        "",
        f"Calibration by decile of predicted risk ({r['deciles_inside_range']} of 10 observed "
        "rates fall inside the mean range, within 0.01):",
        "",
        "| Decile | Mean range | Observed | Examples |",
        "|---|---|---|---|",
        *(
            f"| {i + 1} | {d['low']:.2f}-{d['high']:.2f} | {d['observed']:.2f} | {d['n']:,} |"
            for i, d in enumerate(r["reliability"])
        ),
        "",
        "Standardised coefficients:",
        "",
        "| Feature | Coefficient |",
        "|---|---|",
        *(f"| {f} | {c:+.2f} |" for f, c in r["coefficients"].items()),
        "",
        "## Limits",
        "",
        "- OULAD is about online courses, not brain games. This is a transfer of behaviour "
        "patterns, and it has not been validated on Lodestar users yet; that needs pilot data.",
        '- "Activity" is clicks in OULAD and rounds in Lodestar. The trend feature is a ratio, so '
        "the scale doesn't matter, but habits around a course and a game differ.",
        "- A course has deadlines and an end; practice doesn't.",
        "",
        "## Must not be used for",
        "",
        "Judging, ranking or comparing people, streaks or guilt messages, or anything clinical. "
        "Only to make a session shorter and easier, or to offer one friendly nudge.",
        "",
    ]
    return "\n".join(lines)


def register(result: dict[str, Any]) -> None:
    from sqlalchemy import create_engine, update

    from backend.db import tables as t
    from backend.db.engine import sync_url

    engine = create_engine(sync_url())
    with engine.begin() as conn:
        conn.execute(
            update(t.ml_models).where(t.ml_models.c.name == "engagement_risk").values(active=False)
        )
        conn.execute(
            t.ml_models.insert().values(
                name="engagement_risk",
                version=result["version"],
                metrics=result,
                artefact_path="(in metrics.serving)",
                trained_at=dt.datetime.now(dt.UTC),
                active=True,
            )
        )
    engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--register", action="store_true", help="make it the active model")
    args = parser.parse_args(argv)
    result = train()
    CARD.write_text(card(result), encoding="utf-8")
    lr = result["results"]["logistic regression"]
    print(f"AUC {lr['auc']:.3f}, ECE {lr['ece']:.3f}; card at {CARD}")
    if args.register:
        register(result)
    return 0 if lr["auc"] >= 0.7 else 1


if __name__ == "__main__":
    sys.exit(main())
