"""Distribution specs and samplers.

Every numeric value in a Waterline model is a distribution. Accepted specs:

    3.2                          point mass (bare number)
    {point: 3.2}                 point mass
    {range: [a, b]}              a, b are the 10th/90th percentiles.
                                 Lognormal when a > 0, normal otherwise.
    {normal: {mean: m, sd: s}}   normal
    {uniform: [lo, hi]}          uniform

The range->lognormal default follows keel.md §4.2; the normal fallback exists
because CPI-style m/m components are routinely negative, where a lognormal
is undefined.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

import numpy as np

_STD_NORMAL = NormalDist()
_Z90 = _STD_NORMAL.inv_cdf(0.90)  # 1.2815515655446004


class DistributionError(ValueError):
    pass


@dataclass(frozen=True)
class Distribution:
    kind: str  # point | lognormal | normal | uniform
    params: tuple[float, ...]

    def sample(self, rng: np.random.Generator, n: int) -> np.ndarray:
        if self.kind == "point":
            return np.full(n, self.params[0])
        if self.kind == "lognormal":
            mu, sigma = self.params
            return rng.lognormal(mean=mu, sigma=sigma, size=n)
        if self.kind == "normal":
            mean, sd = self.params
            return rng.normal(loc=mean, scale=sd, size=n)
        if self.kind == "uniform":
            lo, hi = self.params
            return rng.uniform(lo, hi, size=n)
        raise DistributionError(f"unknown distribution kind {self.kind!r}")

    def quantile(self, q: float) -> float:
        if self.kind == "point":
            return self.params[0]
        if self.kind == "lognormal":
            mu, sigma = self.params
            return math.exp(mu + _STD_NORMAL.inv_cdf(q) * sigma)
        if self.kind == "normal":
            mean, sd = self.params
            return mean + _STD_NORMAL.inv_cdf(q) * sd
        if self.kind == "uniform":
            lo, hi = self.params
            return lo + q * (hi - lo)
        raise DistributionError(f"unknown distribution kind {self.kind!r}")

    @property
    def is_point(self) -> bool:
        return self.kind == "point"


def parse(spec: object) -> Distribution:
    """Parse a YAML value spec into a Distribution."""
    if isinstance(spec, bool):
        raise DistributionError(f"boolean is not a valid value spec: {spec!r}")
    if isinstance(spec, (int, float)):
        return Distribution("point", (float(spec),))
    if not isinstance(spec, dict) or len(spec) != 1:
        raise DistributionError(
            f"value spec must be a number or a single-key mapping, got {spec!r}"
        )
    key, val = next(iter(spec.items()))

    if key == "point":
        return Distribution("point", (float(val),))

    if key == "range":
        a, b = _pair(val, "range")
        if a >= b:
            raise DistributionError(f"range must be [low, high] with low < high, got {val!r}")
        if a > 0:
            la, lb = math.log(a), math.log(b)
            sigma = (lb - la) / (2 * _Z90)
            mu = (la + lb) / 2
            return Distribution("lognormal", (mu, sigma))
        sd = (b - a) / (2 * _Z90)
        mean = (a + b) / 2
        return Distribution("normal", (mean, sd))

    if key == "normal":
        if isinstance(val, dict):
            mean, sd = float(val["mean"]), float(val["sd"])
        else:
            mean, sd = _pair(val, "normal")
        if sd <= 0:
            raise DistributionError(f"normal sd must be > 0, got {sd}")
        return Distribution("normal", (mean, sd))

    if key == "uniform":
        lo, hi = _pair(val, "uniform")
        if lo >= hi:
            raise DistributionError(f"uniform must be [low, high] with low < high, got {val!r}")
        return Distribution("uniform", (lo, hi))

    raise DistributionError(f"unknown value spec key {key!r}")


def _pair(val: object, name: str) -> tuple[float, float]:
    if not isinstance(val, (list, tuple)) or len(val) != 2:
        raise DistributionError(f"{name} expects a two-element list, got {val!r}")
    return float(val[0]), float(val[1])
