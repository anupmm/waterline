import numpy as np
import pytest

from waterline.cpi_author import (
    AuthoringError,
    author_assumptions,
    empirical_range,
    fit_weights,
)


def synthetic_moms(n=60, true_w=(0.5, 0.2, 0.3), noise=0.01, seed=1):
    rng = np.random.default_rng(seed)
    periods = [f"{2020 + i // 12}-{i % 12 + 1:02d}" for i in range(n)]
    comp = {
        "shelter": rng.normal(0.35, 0.08, n),
        "supercore": rng.normal(0.25, 0.10, n),
        "core_goods": rng.normal(0.00, 0.15, n),
    }
    core = (
        true_w[0] * comp["shelter"]
        + true_w[1] * comp["supercore"]
        + true_w[2] * comp["core_goods"]
        + rng.normal(0, noise, n)
    )
    moms = {k: dict(zip(periods, v)) for k, v in comp.items()}
    moms["core_cpi"] = dict(zip(periods, core))
    return moms


def test_fit_recovers_known_weights():
    fit = fit_weights(synthetic_moms())
    assert fit.weights["shelter"] == pytest.approx(0.5, abs=0.03)
    assert fit.weights["supercore"] == pytest.approx(0.2, abs=0.03)
    assert fit.weights["core_goods"] == pytest.approx(0.3, abs=0.03)
    assert fit.r2 > 0.9


def test_fit_fails_loudly_on_garbage_decomposition():
    moms = synthetic_moms(noise=0.2)  # residual >> MAX_RESID_STD
    with pytest.raises(AuthoringError, match="residual"):
        fit_weights(moms)


def test_as_of_cutoff_excludes_future_data():
    moms = synthetic_moms()
    fit = fit_weights(moms, as_of="2022-12")
    assert fit.window[1] <= "2022-12"
    assumptions = author_assumptions(moms, as_of="2022-12")
    for spec in assumptions.values():
        assert spec["window"][1] <= "2022-12"


def test_empirical_range_widens_degenerate_input():
    spec = empirical_range([0.3] * 12)
    lo, hi = spec["range"]
    assert hi > lo
