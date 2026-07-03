"""Authoring for the weekly initial-jobless-claims model.

Deliberately humble tree — the honest structure for a mean-reverting weekly
series with no free intra-week drivers:

    claims = base_4wk * drift

    base_4wk  data_bound: median of the last 4 published SA weekly values
    drift     assumption: empirical p10/p90 of actual/base ratios over the
              trailing year — i.e. how far a week typically lands from its
              own trailing base. Captures both genuine movement and
              seasonal-adjustment noise without pretending to explain them.

Auto-authored at freeze time (trailing windows move weekly, so unlike CPI
there is no long-lived committed tree; the frozen forecast JSON records the
exact inputs used). The backtest uses the same functions with an as_of
cutoff, so live and backtest cannot diverge.
"""

from __future__ import annotations

import numpy as np

from .cpi_author import AuthoringError, empirical_range

BASE_WEEKS = 4
DRIFT_WINDOW = 52


def trailing_base(values: dict[str, float], as_of: str | None = None) -> tuple[float, list[str]]:
    """Median of the last BASE_WEEKS values with week-ending date <= as_of."""
    periods = sorted(p for p in values if as_of is None or p <= as_of)
    if len(periods) < BASE_WEEKS:
        raise AuthoringError(f"only {len(periods)} weeks of history")
    window = periods[-BASE_WEEKS:]
    return float(np.median([values[p] for p in window])), window


def drift_ratios(values: dict[str, float], as_of: str | None = None) -> list[float]:
    """actual / trailing-base ratio for each week in the trailing DRIFT_WINDOW."""
    periods = sorted(p for p in values if as_of is None or p <= as_of)
    ratios = []
    for i in range(max(BASE_WEEKS, len(periods) - DRIFT_WINDOW), len(periods)):
        base = float(np.median([values[p] for p in periods[i - BASE_WEEKS : i]]))
        ratios.append(values[periods[i]] / base)
    if len(ratios) < 12:
        raise AuthoringError(f"only {len(ratios)} drift observations")
    return ratios


def author_claims_doc(values: dict[str, float], as_of: str | None = None) -> tuple[dict, dict]:
    """Build the model doc for the next unseen week. Returns (doc, meta)."""
    base, base_window = trailing_base(values, as_of)
    drift_spec = empirical_range(drift_ratios(values, as_of))
    doc = {
        "name": "us-initial-claims-sa",
        "output": "claims",
        "unit": "persons",
        "nodes": {
            "base_4wk": {
                "type": "data_bound",
                "value": base,
                "source": "fred.ICSA",
                "provenance": f"median of SA weeks {base_window[0]}..{base_window[-1]}",
            },
            "drift": {
                "type": "assumption",
                "value": drift_spec,
                "epistemic_type": "benchmarked",
                "provenance": (
                    f"trailing-{DRIFT_WINDOW}wk empirical p10/p90 of actual/base ratios"
                    + (f", as of {as_of}" if as_of else "")
                ),
                "owner": "waterline-bot",
            },
            "claims": {"type": "transform", "fn": "product", "inputs": ["base_4wk", "drift"]},
        },
    }
    meta = {"base": base, "base_window": base_window, "drift_spec": drift_spec}
    return doc, meta
