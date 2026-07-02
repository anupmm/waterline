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

from waterline.cpi_author import author_assumptions, fit_weights, write_model_files
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
    write_model_files(ROOT, fit, assumptions, SERIES, date.today().isoformat())

    print(f"\nweights: {fit.weights}")
    print(f"fit: resid_std={fit.resid_std:.3f}pp R2={fit.r2:.3f} n={fit.n_months}")
    print("\nwrote registry/assumptions.yaml and models/cpi/tree.yaml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
