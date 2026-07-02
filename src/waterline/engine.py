"""Monte Carlo engine and one-at-a-time sensitivity.

Determinism contract: run(model, seed=s) is bit-identical across processes
and platforms for the same model. Each input node draws from its own RNG
stream seeded by (seed, sha256(node_name)), so adding or renaming an
unrelated node never reshuffles another node's draws.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np

from .distributions import Distribution
from .model import InputNode, Model, TransformNode
from .transforms import TRANSFORMS

DEFAULT_DRAWS = 10_000
PERCENTILES = (10, 50, 90)


@dataclass(frozen=True)
class RunResult:
    model_name: str
    output: str
    n_draws: int
    seed: int
    samples: dict[str, np.ndarray]  # node name -> draws

    def percentiles(self, node: str | None = None) -> dict[str, float]:
        node = node or self.output
        p10, p50, p90 = np.percentile(self.samples[node], PERCENTILES)
        return {"p10": float(p10), "p50": float(p50), "p90": float(p90)}

    def mean(self, node: str | None = None) -> float:
        return float(np.mean(self.samples[node or self.output]))


def _node_rng(seed: int, name: str) -> np.random.Generator:
    digest = hashlib.sha256(name.encode("utf-8")).digest()
    node_key = int.from_bytes(digest[:8], "big")
    return np.random.default_rng(np.random.SeedSequence([seed, node_key]))


def run(
    model: Model,
    n_draws: int = DEFAULT_DRAWS,
    seed: int = 0,
    overrides: dict[str, Distribution] | None = None,
) -> RunResult:
    """Sample the full tree. `overrides` swaps an input node's distribution
    (used by sensitivity and, later, actuals attribution)."""
    overrides = overrides or {}
    samples: dict[str, np.ndarray] = {}
    for name in model.order:
        node = model.nodes[name]
        if isinstance(node, InputNode):
            dist = overrides.get(name, node.dist)
            samples[name] = dist.sample(_node_rng(seed, name), n_draws)
        elif isinstance(node, TransformNode):
            arrays = [samples[i] for i in node.inputs]
            samples[name] = TRANSFORMS[node.fn](arrays, node.params)
    return RunResult(
        model_name=model.name,
        output=model.output,
        n_draws=n_draws,
        seed=seed,
        samples=samples,
    )


@dataclass(frozen=True)
class SensitivityRow:
    node: str
    epistemic_type: str
    low_p50: float   # output p50 with node pinned at its own q10
    high_p50: float  # output p50 with node pinned at its own q90
    spread: float    # |high - low|


def sensitivity(
    model: Model,
    n_draws: int = 4_000,
    seed: int = 0,
) -> list[SensitivityRow]:
    """One-at-a-time tornado: pin each non-point input at its own q10/q90,
    re-run, and rank by output p50 spread. Point inputs carry no uncertainty
    and are skipped."""
    from .distributions import Distribution as D

    rows: list[SensitivityRow] = []
    for node in model.input_nodes:
        if node.dist.is_point:
            continue
        outs = []
        for q in (0.10, 0.90):
            pinned = D("point", (node.dist.quantile(q),))
            res = run(model, n_draws=n_draws, seed=seed, overrides={node.name: pinned})
            outs.append(res.percentiles()["p50"])
        rows.append(
            SensitivityRow(
                node=node.name,
                epistemic_type=node.epistemic_type,
                low_p50=outs[0],
                high_p50=outs[1],
                spread=abs(outs[1] - outs[0]),
            )
        )
    rows.sort(key=lambda r: r.spread, reverse=True)
    return rows
