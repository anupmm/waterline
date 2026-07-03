from pathlib import Path

from waterline.delta import compare, snapshot

ROOT = Path(__file__).resolve().parents[1]


def test_identical_snapshots_report_no_change():
    a = snapshot(ROOT)
    b = snapshot(ROOT)
    md, changed = compare(a, b)
    assert not changed
    assert "unchanged" in md
    # seeded determinism: percentile deltas are exactly zero, not just small
    assert "| p50 | " in md and "+0.000" in md


def test_changed_input_is_detected_and_attributed(tmp_path):
    import shutil

    work = tmp_path / "repo"
    for rel in ("models/cpi", "registry"):
        shutil.copytree(ROOT / rel, work / rel)
    import yaml

    reg = work / "registry/assumptions.yaml"
    doc = yaml.safe_load(reg.read_text(encoding="utf-8"))
    doc["shelter_mom"]["value"]["range"][1] += 0.2  # widen the upper bound
    reg.write_text(yaml.safe_dump(doc), encoding="utf-8")
    md, changed = compare(snapshot(ROOT), snapshot(work))
    assert changed
    assert "`shelter_mom`" in md
    assert "`supercore_mom`" not in md  # untouched nodes stay out of the table
