"""Forecast delta between two versions of the model (keel-v2 §6, Milestone 5).

Powers the PR comment ("this change moves the frozen-candidate forecast by X")
and the post-resolve re-authoring PR body. Determinism makes this exact: same
seed + same per-node RNG streams means an untouched input contributes zero
delta, so any nonzero movement is attributable to the edit itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .engine import run
from .loop import SEED
from .model import InputNode, Model, TransformNode, load_model


@dataclass(frozen=True)
class Snapshot:
    name: str
    percentiles: dict[str, float]
    inputs: dict[str, dict]   # node -> {desc, q10, q50, q90}
    weights: dict[str, float]


def snapshot(root: str | Path) -> Snapshot:
    """Load and run the model found under `root` (tree + registry)."""
    root = Path(root)
    model = load_model(root / "models/cpi/tree.yaml", root / "registry/assumptions.yaml")
    res = run(model, seed=SEED)
    inputs = {}
    for node in model.input_nodes:
        inputs[node.name] = {
            "desc": f"{node.dist.kind}{tuple(round(p, 5) for p in node.dist.params)}",
            "q10": node.dist.quantile(0.10),
            "q50": node.dist.quantile(0.50),
            "q90": node.dist.quantile(0.90),
        }
    out = model.nodes[model.output]
    weights = (
        dict(zip(out.inputs, out.params.get("_weights", [])))
        if isinstance(out, TransformNode)
        else {}
    )
    return Snapshot(model.name, res.percentiles(), inputs, weights)


def compare(base: Snapshot, head: Snapshot) -> tuple[str, bool]:
    """Return (markdown, changed). `changed` is true when any input
    distribution or weight differs — not on floating noise, which the seeded
    engine doesn't produce."""
    lines = [f"### Forecast delta — `{head.name}`", ""]
    lines += ["| percentile | base | head | delta |", "|---|---|---|---|"]
    for k in ("p10", "p50", "p90"):
        b, h = base.percentiles[k], head.percentiles[k]
        lines.append(f"| {k} | {b:+.3f} | {h:+.3f} | {h - b:+.3f} |")
    lines.append("")

    changed_inputs = []
    for name in sorted(set(base.inputs) | set(head.inputs)):
        b, h = base.inputs.get(name), head.inputs.get(name)
        if b == h:
            continue
        fmt = lambda s: "&mdash;" if s is None else f"{s['q10']:+.3f} … {s['q90']:+.3f}"  # noqa: E731
        changed_inputs.append(f"| `{name}` | {fmt(b)} | {fmt(h)} |")
    changed_weights = []
    for name in sorted(set(base.weights) | set(head.weights)):
        b, h = base.weights.get(name), head.weights.get(name)
        if b != h:
            changed_weights.append(
                f"| `{name}` (weight) | {'' if b is None else f'{b:.4f}'} "
                f"| {'' if h is None else f'{h:.4f}'} |"
            )

    if changed_inputs or changed_weights:
        lines += ["**Changed nodes**", "", "| node | base | head |", "|---|---|---|"]
        lines += changed_inputs + changed_weights
    else:
        lines.append("_No input or weight changes; forecast is unchanged._")
    lines += [
        "",
        "_All figures are % m/m core CPI; p10–p90 is an 80% interval. Same seed both sides —_"
        " _any delta is caused by this change alone._",
    ]
    changed = bool(changed_inputs or changed_weights)
    return "\n".join(lines), changed
