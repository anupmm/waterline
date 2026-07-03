import numpy as np
import pytest

from waterline.claims_author import author_claims_doc, drift_ratios, trailing_base
from waterline.engine import run
from waterline.model import build_model


def synthetic_weeks(n=80, level=225_000, seed=3):
    rng = np.random.default_rng(seed)
    # Saturdays: ISO dates spaced 7 days
    from datetime import date, timedelta

    start = date(2025, 1, 4)
    vals = level * np.exp(rng.normal(0, 0.04, n))
    return {(start + timedelta(weeks=i)).isoformat(): float(v) for i, v in enumerate(vals)}


def test_trailing_base_and_as_of_cutoff():
    values = synthetic_weeks()
    periods = sorted(values)
    base, window = trailing_base(values, as_of=periods[10])
    assert window[-1] == periods[10]
    assert len(window) == 4
    assert min(values[p] for p in window) <= base <= max(values[p] for p in window)


def test_drift_ratios_are_near_one_for_stationary_series():
    ratios = drift_ratios(synthetic_weeks())
    assert 0.85 < float(np.median(ratios)) < 1.15


def test_authored_doc_builds_and_runs():
    doc, meta = author_claims_doc(synthetic_weeks())
    model = build_model(doc)
    res = run(model, seed=7)
    p = res.percentiles()
    assert p["p10"] < p["p50"] < p["p90"]
    assert 150_000 < p["p50"] < 320_000
    assert model.nodes["base_4wk"].epistemic_type == "data_bound"


def test_as_of_excludes_future_weeks():
    values = synthetic_weeks()
    periods = sorted(values)
    cut = periods[30]
    _, meta = author_claims_doc(values, as_of=cut)
    assert meta["base_window"][-1] <= cut
