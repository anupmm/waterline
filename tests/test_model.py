import pytest

from waterline.model import ModelError, build_model


def minimal_doc(**overrides):
    doc = {
        "name": "t",
        "output": "out",
        "nodes": {
            "a": {"type": "assumption", "value": 1.0},
            "b": {"type": "assumption", "value": {"range": [1.0, 2.0]}},
            "out": {"type": "transform", "fn": "sum", "inputs": ["a", "b"]},
        },
    }
    doc.update(overrides)
    return doc


def test_builds_and_topo_sorts():
    m = build_model(minimal_doc())
    assert m.order.index("out") > m.order.index("a")
    assert m.order.index("out") > m.order.index("b")


def test_registry_ref_resolution_and_inline_override():
    registry = {
        "shelter_mom": {
            "value": {"range": [0.25, 0.45]},
            "unit": "pct_mom",
            "epistemic_type": "benchmarked",
            "provenance": "https://example.com/bls-weights",
            "owner": "waterline-bot",
        }
    }
    doc = minimal_doc()
    doc["nodes"]["a"] = {"type": "assumption", "ref": "shelter_mom"}
    m = build_model(doc, registry)
    node = m.nodes["a"]
    assert node.epistemic_type == "benchmarked"
    assert node.provenance == "https://example.com/bls-weights"
    assert node.dist.kind == "lognormal"

    # inline value overrides the registry value, metadata kept
    doc["nodes"]["a"] = {"type": "assumption", "ref": "shelter_mom", "value": 0.3}
    node2 = build_model(doc, registry).nodes["a"]
    assert node2.dist.is_point
    assert node2.epistemic_type == "benchmarked"


def test_missing_ref_raises():
    doc = minimal_doc()
    doc["nodes"]["a"] = {"type": "assumption", "ref": "nope"}
    with pytest.raises(ModelError, match="not found in registry"):
        build_model(doc)


def test_cycle_raises():
    doc = minimal_doc()
    doc["nodes"]["a"] = {"type": "transform", "fn": "sum", "inputs": ["out"]}
    with pytest.raises(ModelError, match="cycle"):
        build_model(doc)


def test_dangling_input_raises():
    doc = minimal_doc()
    doc["nodes"]["out"]["inputs"] = ["a", "ghost"]
    with pytest.raises(ModelError, match="ghost"):
        build_model(doc)


def test_missing_output_raises():
    with pytest.raises(ModelError, match="output"):
        build_model(minimal_doc(output="nope"))


def test_weighted_sum_requires_mapping_inputs():
    doc = minimal_doc()
    doc["nodes"]["out"] = {"type": "transform", "fn": "weighted_sum", "inputs": ["a", "b"]}
    with pytest.raises(ModelError, match="weighted_sum"):
        build_model(doc)


def test_data_bound_defaults_epistemic_type():
    doc = minimal_doc()
    doc["nodes"]["a"] = {"type": "data_bound", "value": -0.8, "source": "eia.gasoline_weekly"}
    m = build_model(doc)
    assert m.nodes["a"].epistemic_type == "data_bound"
    assert m.nodes["a"].source == "eia.gasoline_weekly"


def test_unknown_transform_raises():
    doc = minimal_doc()
    doc["nodes"]["out"]["fn"] = "teleport"
    with pytest.raises(ModelError, match="teleport"):
        build_model(doc)
