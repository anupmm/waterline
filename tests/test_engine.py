import time

import numpy as np
import pytest

from waterline.engine import run, sensitivity
from waterline.model import build_model


def test_point_only_tree_is_exact():
    doc = {
        "name": "points",
        "output": "out",
        "nodes": {
            "x": {"type": "assumption", "value": 2.0},
            "y": {"type": "assumption", "value": 3.0},
            "out": {"type": "transform", "fn": "weighted_sum", "inputs": {"x": 0.5, "y": 2.0}},
        },
    }
    res = run(build_model(doc), n_draws=100, seed=1)
    assert np.all(res.samples["out"] == pytest.approx(0.5 * 2.0 + 2.0 * 3.0))


def test_same_seed_bit_identical_different_seed_close():
    doc = _mixed_doc()
    m = build_model(doc)
    r1 = run(m, seed=7)
    r2 = run(m, seed=7)
    assert np.array_equal(r1.samples["out"], r2.samples["out"])
    r3 = run(m, seed=8)
    assert not np.array_equal(r1.samples["out"], r3.samples["out"])
    assert r1.percentiles()["p50"] == pytest.approx(r3.percentiles()["p50"], rel=0.05)


def test_node_streams_stable_under_unrelated_edits():
    """Adding an unrelated node must not change another node's draws."""
    doc = _mixed_doc()
    m1 = build_model(doc)
    doc2 = {**doc, "nodes": {**doc["nodes"], "zzz_new": {"type": "assumption", "value": {"range": [1, 2]}}}}
    m2 = build_model(doc2)
    r1, r2 = run(m1, seed=3), run(m2, seed=3)
    assert np.array_equal(r1.samples["a"], r2.samples["a"])


def test_linear_and_ratio_transforms():
    doc = {
        "name": "t",
        "output": "out",
        "nodes": {
            "x": {"type": "assumption", "value": 10.0},
            "y": {"type": "assumption", "value": 4.0},
            "scaled": {"type": "transform", "fn": "linear", "inputs": ["x"], "params": {"a": 2, "b": 1}},
            "out": {"type": "transform", "fn": "ratio", "inputs": ["scaled", "y"]},
        },
    }
    res = run(build_model(doc), n_draws=10, seed=0)
    assert res.samples["out"][0] == pytest.approx((2 * 10 + 1) / 4)


def test_sensitivity_ranks_dominant_assumption_first():
    doc = {
        "name": "t",
        "output": "out",
        "nodes": {
            "big": {"type": "assumption", "value": {"range": [1.0, 100.0]}},
            "small": {"type": "assumption", "value": {"range": [1.0, 1.1]}},
            "fixed": {"type": "assumption", "value": 5.0},
            "out": {"type": "transform", "fn": "sum", "inputs": ["big", "small", "fixed"]},
        },
    }
    rows = sensitivity(build_model(doc), seed=2)
    assert [r.node for r in rows][0] == "big"
    assert all(r.node != "fixed" for r in rows)  # point nodes carry no uncertainty
    assert rows[0].spread > rows[-1].spread


def _mixed_doc(n_leaves: int = 6) -> dict:
    nodes = {}
    names = []
    for i in range(n_leaves):
        name = chr(ord("a") + i)
        names.append(name)
        if i % 3 == 0:
            nodes[name] = {"type": "assumption", "value": {"range": [1.0 + i, 3.0 + i]}}
        elif i % 3 == 1:
            nodes[name] = {"type": "assumption", "value": float(i + 1)}
        else:
            nodes[name] = {"type": "assumption", "value": {"normal": {"mean": i, "sd": 0.5}}}
    nodes["out"] = {"type": "transform", "fn": "sum", "inputs": names}
    return {"name": "mixed", "output": "out", "nodes": nodes}


def test_acceptance_30_node_tree_stable_and_fast():
    """Milestone 1 acceptance (keel-v2 §9.1): a 30-node mixed point/range tree
    produces stable seeded percentiles, sub-second warm."""
    nodes = {}
    layer1 = []
    for i in range(24):
        name = f"leaf_{i:02d}"
        layer1.append(name)
        if i % 2 == 0:
            nodes[name] = {"type": "assumption", "value": {"range": [0.5 + i * 0.1, 2.0 + i * 0.2]}}
        else:
            nodes[name] = {"type": "assumption", "value": float(i) * 0.1 + 0.05}
    groups = [layer1[i::4] for i in range(4)]
    mids = []
    for gi, group in enumerate(groups):
        name = f"mid_{gi}"
        mids.append(name)
        nodes[name] = {"type": "transform", "fn": "weighted_sum",
                       "inputs": {g: 1.0 / len(group) for g in group}}
    nodes["subtotal"] = {"type": "transform", "fn": "sum", "inputs": mids[:2]}
    nodes["out"] = {"type": "transform", "fn": "weighted_sum",
                    "inputs": {"subtotal": 0.5, "mid_2": 0.25, "mid_3": 0.25}}
    doc = {"name": "acceptance", "output": "out", "nodes": nodes}
    m = build_model(doc)
    assert len(m.nodes) == 30

    run(m, seed=0)  # warm
    t0 = time.perf_counter()
    r1 = run(m, seed=123)
    elapsed = time.perf_counter() - t0
    r2 = run(m, seed=123)

    p1, p2 = r1.percentiles(), r2.percentiles()
    assert p1 == p2, "same seed must be bit-identical"
    assert p1["p10"] < p1["p50"] < p1["p90"]
    assert elapsed < 1.0, f"warm 10k-draw run took {elapsed:.3f}s"
