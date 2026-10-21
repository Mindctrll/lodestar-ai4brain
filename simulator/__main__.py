"""`make sim N=200`: simulate users, run experiments 1-5, write figures, enforce thresholds."""

import argparse
import sys
from pathlib import Path

import numpy as np

from backend.registry.loader import load_registry
from simulator.experiments import gate
from simulator.population import make_population
from simulator.run import simulate_user

SESSIONS = 10


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--users", type=int, default=200)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--out", type=Path, default=Path("docs/figures"))
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args()

    registry = load_registry()
    rng = np.random.default_rng(args.seed)
    users = make_population(registry, args.users, rng)
    runs = [simulate_user(u, registry, SESSIONS, rng) for u in users]
    bad_users = make_population(
        registry,
        max(40, args.users // 5),
        rng,
        kinds={"normal": 0.6, "random_clicker": 0.2, "cheater": 0.2},
    )
    bad_runs = [simulate_user(u, registry, 3, rng) for u in bad_users]
    result = gate(runs, bad_runs, registry)
    dims, rec, succ, checks = result.dims, result.recovery, result.success, result.checks

    lines = [
        f"# Simulator results ({args.users} users, {SESSIONS} sessions, seed {args.seed})",
        "",
        "| Experiment | Result | Target | Pass |",
        "|---|---|---|---|",
        *(
            f"| {name} | {value} | {target} | {'yes' if ok else 'NO'} |"
            for name, value, target, ok in checks
        ),
        "",
        "Recovery r by session: "
        + ", ".join(f"after {s}: {rec[s].mean_r:.3f}" for s in (1, 3, 10)),
        "",
        "| Skill | r after 3 | r after 10 | RMSE after 10 | practised by 3 |",
        "|---|---|---|---|---|",
        *(
            f"| {d} | {rec[3].r_by_dim.get(d, float('nan')):.3f} | "
            f"{rec[10].r_by_dim.get(d, float('nan')):.3f} | "
            f"{rec[10].rmse_by_dim.get(d, float('nan')):.3f} | {rec[3].practised_share[d]:.0%} |"
            for d in dims
        ),
        "",
        "Success in Balanced mode by ability third (low, middle, high): "
        + ", ".join(f"{x:.3f}" for x in succ.by_tertile)
        + f" over {succ.rounds} rounds.",
    ]
    report = "\n".join(lines) + "\n"
    print(report)

    if not args.no_plots:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "sim_summary.md").write_text(report, encoding="utf-8")
        _plots(runs, dims, rec, succ, args.out)

    return 0 if all(ok for *_, ok in checks) else 1


def _plots(runs, dims, rec, succ, out: Path) -> None:  # type: ignore[no-untyped-def]
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(5, 5))
    for dim in dims:
        pts = [
            (r.snapshots[2].truth[dim], r.snapshots[2].beliefs[dim].mu)
            for r in runs
            if r.snapshots[2].beliefs[dim].n > 0
        ]
        if pts:
            xs, ys = zip(*pts, strict=True)
            ax.scatter(xs, ys, s=6, alpha=0.35)
    ax.plot([-3, 3], [-3, 3], color="grey", linewidth=1)
    ax.set_xlabel("True skill (simulated)")
    ax.set_ylabel("Estimate after 3 sessions")
    ax.set_title(f"Recovery, mean r = {rec[3].mean_r:.2f}")
    fig.tight_layout()
    fig.savefig(out / "sim_recovery.png", dpi=120)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(5, 3.5))
    ax.bar(["Low", "Middle", "High"], succ.by_tertile, color="#2f6fed")
    ax.axhspan(0.75, 0.85, color="grey", alpha=0.2, label="Target 80% +/- 5")
    ax.set_ylim(0, 1)
    ax.set_ylabel("Achieved success")
    ax.set_title("Balanced mode by ability third")
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(out / "sim_success.png", dpi=120)
    plt.close(fig)


if __name__ == "__main__":
    sys.exit(main())
