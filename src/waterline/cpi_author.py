"""Authoring logic for the core-CPI driver tree.

The tree decomposes core CPI m/m into three observable components:

    core_cpi_mom ~ w_sh * shelter + w_sc * supercore + w_cg * core_goods

Weights are NOT taken from the BLS relative-importance page (it blocks
automated retrieval and drifts monthly); they are fit by constrained least
squares on component history, with the fit quality reported. That makes the
decomposition empirical and its provenance checkable — if the residual is
large, the tree is dishonest and authoring fails loudly.

Assumption distributions are trailing empirical quantiles: range = [p10, p90]
of the last `assump_window` valid monthly prints. Deliberately naive — the
news-analyst bot's whole job (Milestone 5) is to beat this by proposing
informed updates. The backtest uses this same code with an `as_of` cutoff,
so backtest and live authoring cannot diverge.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

COMPONENTS = ("shelter", "supercore", "core_goods")
TARGET = "core_cpi"
MAX_RESID_STD = 0.05  # pp of m/m; above this the 3-component decomposition is judged dishonest


class AuthoringError(RuntimeError):
    pass


@dataclass(frozen=True)
class WeightFit:
    weights: dict[str, float]
    resid_std: float
    r2: float
    n_months: int
    window: tuple[str, str]  # first, last period used


def common_periods(moms: dict[str, dict[str, float]], as_of: str | None = None) -> list[str]:
    """Periods where the target and every component have a valid m/m,
    optionally truncated at `as_of` (inclusive). Sorted ascending."""
    keys = set(moms[TARGET])
    for c in COMPONENTS:
        keys &= set(moms[c])
    periods = sorted(keys)
    if as_of is not None:
        periods = [p for p in periods if p <= as_of]
    return periods


def fit_weights(
    moms: dict[str, dict[str, float]],
    as_of: str | None = None,
    window: int = 48,
) -> WeightFit:
    periods = common_periods(moms, as_of)[-window:]
    if len(periods) < 24:
        raise AuthoringError(f"only {len(periods)} usable months; need >= 24")
    y = np.array([moms[TARGET][p] for p in periods])
    X = np.column_stack([[moms[c][p] for p in periods] for c in COMPONENTS])

    active = list(range(len(COMPONENTS)))
    while True:
        w, *_ = np.linalg.lstsq(X[:, active], y, rcond=None)
        if np.all(w >= 0) or len(active) == 1:
            break
        active = [a for a, wi in zip(active, w) if wi > 0]  # drop negatives, refit

    weights = {c: 0.0 for c in COMPONENTS}
    for a, wi in zip(active, w):
        weights[COMPONENTS[a]] = float(wi)

    resid = y - X @ np.array([weights[c] for c in COMPONENTS])
    resid_std = float(np.std(resid, ddof=1))
    ss_res = float(np.sum(resid**2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")

    if resid_std > MAX_RESID_STD:
        raise AuthoringError(
            f"decomposition residual std {resid_std:.3f}pp exceeds {MAX_RESID_STD}pp — "
            "the 3-component tree does not honestly reconstruct core CPI"
        )
    return WeightFit(weights, resid_std, r2, len(periods), (periods[0], periods[-1]))


def empirical_range(values: list[float]) -> dict:
    """Trailing-history value spec: range = empirical [p10, p90], widened if
    degenerate. Spec semantics (lognormal vs normal fallback) come from
    distributions.parse."""
    arr = np.asarray(values, dtype=float)
    lo, hi = float(np.percentile(arr, 10)), float(np.percentile(arr, 90))
    if hi - lo < 1e-6:
        pad = max(0.05, float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.05)
        lo, hi = lo - pad, hi + pad
    return {"range": [round(lo, 3), round(hi, 3)]}


def author_assumptions(
    moms: dict[str, dict[str, float]],
    as_of: str | None = None,
    assump_window: int = 12,
) -> dict[str, dict]:
    """{component: {"value": spec, "window": [first, last]}} using only data <= as_of."""
    out: dict[str, dict] = {}
    for c in COMPONENTS:
        periods = sorted(p for p in moms[c] if as_of is None or p <= as_of)[-assump_window:]
        if len(periods) < 6:
            raise AuthoringError(f"{c}: only {len(periods)} months of history")
        out[c] = {
            "value": empirical_range([moms[c][p] for p in periods]),
            "window": (periods[0], periods[-1]),
        }
    return out
