"""Walk-forward backtest of the claims model over the last 26 resolvable weeks.

Same code path as the live freeze (author_claims_doc with an as_of cutoff =
the week before the target), so no lookahead. Baselines: naive-last and
4-week mean. Honesty rule: report as computed; do not tune.

Run:  uv run python scripts/backtest_claims.py
Writes docs/backtest-claims.md and docs/backtest-claims.json.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from waterline.claims_author import author_claims_doc
from waterline.engine import run
from waterline.ingest.fred import ICSA, fetch_series
from waterline.model import build_model

N_TARGETS = 26
SEED = 20260702


def main() -> int:
    values = fetch_series(ICSA, cache_dir=ROOT / "data/fred")
    periods = sorted(values)
    targets = periods[-N_TARGETS:]

    rows = []
    for t in targets:
        as_of = periods[periods.index(t) - 1]
        doc, _ = author_claims_doc(values, as_of=as_of)
        res = run(build_model(doc), seed=SEED)
        p = res.percentiles()
        history = [values[q] for q in periods if q <= as_of]
        rows.append({
            "period": t,
            "p10": p["p10"], "p50": p["p50"], "p90": p["p90"],
            "actual": values[t],
            "hit": p["p10"] <= values[t] <= p["p90"],
            "naive_last": history[-1],
            "mean4": float(np.mean(history[-4:])),
        })

    n = len(rows)
    mae = lambda k: float(np.mean([abs(r[k] - r["actual"]) for r in rows]))  # noqa: E731
    mae_model, mae_naive, mae_m4 = mae("p50"), mae("naive_last"), mae("mean4")
    coverage = sum(r["hit"] for r in rows) / n
    bias = float(np.mean([r["p50"] - r["actual"] for r in rows]))

    lines = [
        "# Initial claims (SA) — walk-forward backtest",
        "",
        f"*Generated {date.today().isoformat()}; seed {SEED}; last {n} weekly prints;"
        " same authoring code as the live freeze, as-of cutoffs, no lookahead.*",
        "",
        "| week ending | p10 | p50 | p90 | actual | hit | naive-last | 4wk mean |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['period']} | {r['p10']:,.0f} | {r['p50']:,.0f} | {r['p90']:,.0f} "
            f"| {r['actual']:,.0f} | {'yes' if r['hit'] else 'NO'} "
            f"| {r['naive_last']:,.0f} | {r['mean4']:,.0f} |"
        )
    lines += [
        "",
        "## Summary",
        "",
        f"- MAE of model p50: **{mae_model:,.0f}**",
        f"- MAE of naive-last: {mae_naive:,.0f}",
        f"- MAE of 4-week mean: {mae_m4:,.0f}",
        f"- 80% interval coverage: **{coverage:.0%}** (nominal 80%)",
        f"- Bias (p50 minus actual): {bias:+,.0f}",
        "",
        "Verdict written as computed: the model "
        + (
            "beats both baselines on MAE."
            if mae_model < min(mae_naive, mae_m4)
            else "does NOT beat the stronger baseline on MAE — expected for a "
            "persistence-shaped series; the interval honesty is the deliverable."
        ),
    ]
    (ROOT / "docs" / "backtest-claims.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (ROOT / "docs" / "backtest-claims.json").write_text(
        json.dumps(
            {
                "generated": date.today().isoformat(),
                "seed": SEED,
                "summary": {
                    "n": n, "mae_model": mae_model, "mae_naive_last": mae_naive,
                    "mae_mean4": mae_m4, "coverage_80": coverage, "bias": bias,
                },
                "rows": rows,
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
