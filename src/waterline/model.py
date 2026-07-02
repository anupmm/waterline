"""Model loading and validation.

A model is a YAML driver tree (keel-v2 §5):

    name: us-core-cpi-mom
    output: core_cpi_mom
    unit: pct_mom
    nodes:
      shelter_mom:
        type: assumption
        ref: shelter_mom              # key in the shared registry
      used_cars_mom:
        type: assumption
        value: {range: [-1.0, 0.5]}   # inline distribution spec
      gasoline_mom:
        type: data_bound
        value: -0.8
        source: eia.gasoline_weekly
      core_cpi_mom:
        type: transform
        fn: weighted_sum
        inputs: {shelter_mom: 0.44, used_cars_mom: 0.03, ...}

Registry entries (registry/assumptions.yaml) carry the epistemic metadata:

    shelter_mom:
      value: {range: [0.25, 0.45]}
      unit: pct_mom
      epistemic_type: benchmarked     # guess | benchmarked | data_bound
      provenance: https://...
      owner: waterline-bot
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .distributions import Distribution, parse
from .transforms import TRANSFORMS

INPUT_TYPES = {"assumption", "data_bound"}
EPISTEMIC_TYPES = {"guess", "benchmarked", "data_bound"}


class ModelError(ValueError):
    pass


@dataclass(frozen=True)
class InputNode:
    name: str
    dist: Distribution
    epistemic_type: str = "guess"
    unit: str | None = None
    provenance: str | None = None
    owner: str | None = None
    source: str | None = None  # data_bound binding id


@dataclass(frozen=True)
class TransformNode:
    name: str
    fn: str
    inputs: list[str]
    params: dict = field(default_factory=dict)


Node = InputNode | TransformNode


@dataclass(frozen=True)
class Model:
    name: str
    output: str
    nodes: dict[str, Node]
    order: tuple[str, ...]  # topological, inputs first
    unit: str | None = None

    @property
    def input_nodes(self) -> list[InputNode]:
        return [n for n in self.nodes.values() if isinstance(n, InputNode)]


def load_model(path: str | Path, registry_path: str | Path | None = None) -> Model:
    path = Path(path)
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    registry: dict = {}
    if registry_path is not None:
        registry = yaml.safe_load(Path(registry_path).read_text(encoding="utf-8")) or {}
    return build_model(doc, registry)


def build_model(doc: dict, registry: dict | None = None) -> Model:
    registry = registry or {}
    for key in ("name", "output", "nodes"):
        if key not in doc:
            raise ModelError(f"model is missing required key {key!r}")

    nodes: dict[str, Node] = {}
    for name, spec in doc["nodes"].items():
        nodes[name] = _build_node(name, spec, registry)

    output = doc["output"]
    if output not in nodes:
        raise ModelError(f"output node {output!r} is not defined")

    order = _topo_sort(nodes)
    return Model(
        name=doc["name"],
        output=output,
        nodes=nodes,
        order=order,
        unit=doc.get("unit"),
    )


def _build_node(name: str, spec: dict, registry: dict) -> Node:
    if not isinstance(spec, dict) or "type" not in spec:
        raise ModelError(f"node {name!r}: spec must be a mapping with a 'type'")
    ntype = spec["type"]

    if ntype in INPUT_TYPES:
        meta: dict = {}
        if "ref" in spec:
            ref = spec["ref"]
            if ref not in registry:
                raise ModelError(f"node {name!r}: ref {ref!r} not found in registry")
            meta = dict(registry[ref])
        # inline keys override registry metadata
        meta.update({k: v for k, v in spec.items() if k not in ("type", "ref")})
        if "value" not in meta:
            raise ModelError(f"node {name!r}: no value (inline or via ref)")
        epistemic = meta.get("epistemic_type", "data_bound" if ntype == "data_bound" else "guess")
        if epistemic not in EPISTEMIC_TYPES:
            raise ModelError(f"node {name!r}: unknown epistemic_type {epistemic!r}")
        return InputNode(
            name=name,
            dist=parse(meta["value"]),
            epistemic_type=epistemic,
            unit=meta.get("unit"),
            provenance=meta.get("provenance"),
            owner=meta.get("owner"),
            source=meta.get("source"),
        )

    if ntype == "transform":
        fn = spec.get("fn")
        if fn not in TRANSFORMS:
            raise ModelError(f"node {name!r}: unknown transform fn {fn!r}")
        raw_inputs = spec.get("inputs")
        params = dict(spec.get("params", {}))
        if isinstance(raw_inputs, dict):  # weighted form: {node: weight}
            inputs = list(raw_inputs.keys())
            params["_weights"] = [float(w) for w in raw_inputs.values()]
        elif isinstance(raw_inputs, list):
            inputs = list(raw_inputs)
        elif isinstance(raw_inputs, str):
            inputs = [raw_inputs]
        else:
            raise ModelError(f"node {name!r}: inputs must be a list, mapping, or node name")
        if fn == "weighted_sum" and "_weights" not in params:
            raise ModelError(f"node {name!r}: weighted_sum needs mapping inputs {{node: weight}}")
        return TransformNode(name=name, fn=fn, inputs=inputs, params=params)

    raise ModelError(f"node {name!r}: unknown type {ntype!r}")


def _topo_sort(nodes: dict[str, Node]) -> tuple[str, ...]:
    """Kahn's algorithm; raises on cycles and dangling references."""
    deps: dict[str, list[str]] = {}
    for name, node in nodes.items():
        ins = node.inputs if isinstance(node, TransformNode) else []
        for i in ins:
            if i not in nodes:
                raise ModelError(f"node {name!r}: input {i!r} is not defined")
        deps[name] = list(ins)

    order: list[str] = []
    ready = sorted(n for n, d in deps.items() if not d)
    remaining = {n: set(d) for n, d in deps.items() if d}
    while ready:
        n = ready.pop()
        order.append(n)
        newly_ready = []
        for m, d in remaining.items():
            d.discard(n)
            if not d:
                newly_ready.append(m)
        for m in newly_ready:
            del remaining[m]
        ready.extend(sorted(newly_ready))
    if remaining:
        raise ModelError(f"cycle detected among nodes: {sorted(remaining)}")
    return tuple(order)
