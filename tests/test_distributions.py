import math

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from waterline.distributions import DistributionError, parse

RNG = lambda: np.random.default_rng(42)  # noqa: E731


def test_bare_number_is_point():
    d = parse(3.2)
    assert d.kind == "point"
    assert np.all(d.sample(RNG(), 100) == 3.2)
    assert d.quantile(0.5) == 3.2


def test_positive_range_is_lognormal_with_matching_percentiles():
    d = parse({"range": [4.0, 9.0]})
    assert d.kind == "lognormal"
    s = d.sample(RNG(), 200_000)
    assert np.percentile(s, 10) == pytest.approx(4.0, rel=0.02)
    assert np.percentile(s, 90) == pytest.approx(9.0, rel=0.02)
    assert d.quantile(0.10) == pytest.approx(4.0, rel=1e-9)
    assert d.quantile(0.90) == pytest.approx(9.0, rel=1e-9)


def test_range_spanning_zero_falls_back_to_normal():
    d = parse({"range": [-1.0, 0.5]})
    assert d.kind == "normal"
    s = d.sample(RNG(), 200_000)
    assert np.percentile(s, 10) == pytest.approx(-1.0, abs=0.02)
    assert np.percentile(s, 90) == pytest.approx(0.5, abs=0.02)


def test_explicit_normal_and_uniform():
    n = parse({"normal": {"mean": 2.0, "sd": 0.5}})
    assert n.quantile(0.5) == pytest.approx(2.0)
    u = parse({"uniform": [0.0, 10.0]})
    assert u.quantile(0.5) == pytest.approx(5.0)
    assert u.sample(RNG(), 1000).min() >= 0.0


@pytest.mark.parametrize(
    "bad",
    [
        {"range": [9, 4]},           # inverted
        {"range": [4]},              # not a pair
        {"normal": {"mean": 0, "sd": -1}},
        {"volcano": [1, 2]},         # unknown key
        {"range": [1, 2], "point": 3},  # multi-key
        True,
    ],
)
def test_bad_specs_raise(bad):
    with pytest.raises(DistributionError):
        parse(bad)


@settings(max_examples=50, deadline=None)
@given(
    a=st.floats(min_value=0.01, max_value=1e4),
    ratio=st.floats(min_value=1.05, max_value=100.0),
    q=st.floats(min_value=0.01, max_value=0.99),
)
def test_lognormal_quantile_is_monotone_and_bracketed(a, ratio, q):
    d = parse({"range": [a, a * ratio]})
    v = d.quantile(q)
    assert v > 0
    if 0.10 <= q <= 0.90:
        assert a * 0.999 <= v <= a * ratio * 1.001
    assert d.quantile(min(q + 0.005, 0.995)) >= v


def test_median_of_range_is_geometric_mean():
    d = parse({"range": [4.0, 9.0]})
    assert d.quantile(0.5) == pytest.approx(math.sqrt(36.0))
