from pathlib import Path

from waterline import load_model, run, sensitivity

FIXTURES = Path(__file__).parent / "fixtures" / "toy_cpi"


def test_toy_cpi_loads_runs_and_ranks():
    m = load_model(FIXTURES / "tree.yaml", FIXTURES / "registry.yaml")
    assert m.output == "core_cpi_mom"
    assert m.nodes["shelter_mom"].epistemic_type == "benchmarked"

    res = run(m, seed=11)
    p = res.percentiles()
    assert p["p10"] < p["p50"] < p["p90"]
    # sanity: a weighted average of sub-percent m/m components stays sub-percent
    assert -0.5 < p["p50"] < 1.0

    rows = sensitivity(m, seed=11)
    ranked = [r.node for r in rows]
    # shelter (weight .44) and used cars (wide range) should dominate the tornado
    assert set(ranked[:2]) >= {"shelter_mom"}
    assert rows[0].spread > 0
