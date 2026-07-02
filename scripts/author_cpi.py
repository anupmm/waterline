"""Author models/cpi/tree.yaml and registry/assumptions.yaml from BLS history.

Run:  uv run python scripts/author_cpi.py
Idempotent; regenerates both files and prints the fit report. Data pulls are
disk-cached under data/bls/ (committed).
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from waterline.cpi_author import author_assumptions, fit_weights
from waterline.ingest.bls import SERIES, fetch_levels, load_env_key, mom

START_YEAR, END_YEAR = 2018, 2026


def main() -> int:
    key = load_env_key(ROOT)
    levels = fetch_levels(
        list(SERIES.values()), START_YEAR, END_YEAR, key=key, cache_dir=ROOT / "data/bls"
    )
    moms = {name: mom(levels[sid]) for name, sid in SERIES.items()}

    for name in SERIES:
        missing = [p for p in ("2025-10", "2025-11") if p not in moms[name]]
        print(f"{name}: {len(moms[name])} m/m values; hole months absent as expected: {missing}")

    fit = fit_weights(moms)
    assumptions = author_assumptions(moms)
    today = date.today().isoformat()
    weights_prov = (
        f"least-squares reconstruction of {SERIES['core_cpi']} m/m from components, "
        f"{fit.window[0]}..{fit.window[1]} ({fit.n_months} months), "
        f"resid_std={fit.resid_std:.3f}pp, R2={fit.r2:.3f}, authored {today}"
    )

    print(f"\nweights: {fit.weights}")
    print(f"fit: resid_std={fit.resid_std:.3f}pp R2={fit.r2:.3f} n={fit.n_months}")

    registry_lines = ["# Shared assumption registry. Authored by scripts/author_cpi.py — edit via PR.\n"]
    for comp, spec in assumptions.items():
        lo, hi = spec["value"]["range"]
        first, last = spec["window"]
        caveat = ""
        if comp == "shelter" and first <= "2026-04":
            caveat = (
                "  # window includes Oct-2025..Apr-2026 shelter imputation artifacts"
                " (see docs/verify-cpi.md item 6.3)\n"
            )
        registry_lines.append(
            f"{comp}_mom:\n"
            f"  value: {{range: [{lo}, {hi}]}}\n"
            f"  unit: pct_mom\n"
            f"  epistemic_type: benchmarked\n"
            f"  provenance: trailing-12m empirical p10/p90 of BLS {SERIES[comp]},"
            f" {first}..{last}, authored {today}\n"
            f"{caveat}"
            f"  owner: waterline-bot\n"
        )
    (ROOT / "registry" / "assumptions.yaml").parent.mkdir(exist_ok=True)
    (ROOT / "registry" / "assumptions.yaml").write_text("\n".join(registry_lines), encoding="utf-8")

    w = fit.weights
    tree = f"""# US core CPI m/m driver tree. Authored by scripts/author_cpi.py — edit via PR.
# Weights: {weights_prov}
# Resolution rule: models/cpi/resolution.md
name: us-core-cpi-mom
output: core_cpi_mom
unit: pct_mom
nodes:
  shelter_mom:
    type: assumption
    ref: shelter_mom
  supercore_mom:
    type: assumption
    ref: supercore_mom
  core_goods_mom:
    type: assumption
    ref: core_goods_mom
  decomposition_resid:
    # what the 3-component reconstruction cannot explain; omitting it makes
    # the interval dishonestly narrow (measured in the weight fit above)
    type: assumption
    value: {{normal: {{mean: 0.0, sd: {fit.resid_std:.4f}}}}}
    unit: pct_mom
    epistemic_type: benchmarked
    provenance: residual std of the weight fit, {fit.window[0]}..{fit.window[1]}
    owner: waterline-bot
  core_cpi_mom:
    type: transform
    fn: weighted_sum
    inputs:
      shelter_mom: {w['shelter']:.4f}
      supercore_mom: {w['supercore']:.4f}
      core_goods_mom: {w['core_goods']:.4f}
      decomposition_resid: 1.0
"""
    (ROOT / "models" / "cpi" / "tree.yaml").write_text(tree, encoding="utf-8")
    print("\nwrote registry/assumptions.yaml and models/cpi/tree.yaml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
