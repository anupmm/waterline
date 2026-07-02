"""Command-line interface.

    waterline run models/cpi/tree.yaml --registry registry/assumptions.yaml

Prints the forecast percentiles, the input nodes with their epistemic status,
and the sensitivity tornado. This is the manual inspection surface until the
static site (Milestone 3) exists; CI reuses it for smoke checks.
"""

from __future__ import annotations

import argparse
import sys

from .engine import run, sensitivity
from .model import Model, load_model

# keel-v2 standing constraint: never render a number without its epistemic color.
EPISTEMIC_MARK = {"guess": "red:guess", "benchmarked": "amber:benchmarked", "data_bound": "green:data-bound"}


def cmd_run(args: argparse.Namespace) -> int:
    model = load_model(args.tree, args.registry)
    res = run(model, n_draws=args.draws, seed=args.seed)
    p = res.percentiles()

    unit = f" {model.unit}" if model.unit else ""
    print(f"model: {model.name}   (draws={args.draws}, seed={args.seed})")
    print(f"output: {model.output}")
    print(f"  p10 {p['p10']:+.3f}{unit}   p50 {p['p50']:+.3f}{unit}   p90 {p['p90']:+.3f}{unit}")

    print("\ninputs:")
    width = max(len(n.name) for n in model.input_nodes)
    for node in sorted(model.input_nodes, key=lambda n: n.name):
        q10, q50, q90 = (node.dist.quantile(q) for q in (0.10, 0.50, 0.90))
        spread = f"{q10:+.3f} .. {q90:+.3f}" if not node.dist.is_point else f"{q50:+.3f} (point)"
        mark = EPISTEMIC_MARK[node.epistemic_type]
        prov = f"  <- {node.provenance or node.source}" if (node.provenance or node.source) else ""
        print(f"  {node.name:<{width}}  [{mark:<17}]  {spread}{prov}")

    rows = sensitivity(model, seed=args.seed)
    if rows:
        print("\ntornado (output p50 spread, one-at-a-time q10->q90):")
        top = rows[: args.top]
        max_spread = top[0].spread or 1.0
        for r in top:
            bar = "#" * max(1, round(24 * r.spread / max_spread))
            print(f"  {r.node:<{width}}  {bar:<24} {r.spread:.3f}  [{EPISTEMIC_MARK[r.epistemic_type]}]")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="waterline", description="Waterline driver-model runtime")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="run a model and print percentiles + tornado")
    p_run.add_argument("tree", help="path to the model tree.yaml")
    p_run.add_argument("--registry", default=None, help="path to the shared assumption registry")
    p_run.add_argument("--draws", type=int, default=10_000)
    p_run.add_argument("--seed", type=int, default=0)
    p_run.add_argument("--top", type=int, default=10, help="tornado rows to show")
    p_run.set_defaults(fn=cmd_run)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
