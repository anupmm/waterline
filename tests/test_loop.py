import json
from datetime import date
from pathlib import Path

from waterline.loop import decide, rebuild_calibration


def make_repo(tmp_path: Path, frozen=(), resolved=()) -> Path:
    (tmp_path / "models/cpi").mkdir(parents=True)
    (tmp_path / "models/cpi/schedule.yaml").write_text(
        "releases:\n"
        "  - {period: 2026-06, date: 2026-07-14}\n"
        "  - {period: 2026-07, date: 2026-08-12}\n",
        encoding="utf-8",
    )
    for p in frozen:
        f = tmp_path / f"forecasts/cpi/{p}.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("{}", encoding="utf-8")
    for p in resolved:
        f = tmp_path / f"actuals/cpi/{p}.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("{}", encoding="utf-8")
    return tmp_path


def test_freeze_fires_only_inside_t_minus_3_window(tmp_path):
    root = make_repo(tmp_path)
    assert decide(root, date(2026, 7, 10)) == []                      # T-4: too early
    assert decide(root, date(2026, 7, 11)) == [("freeze", "2026-06")]  # T-3
    assert decide(root, date(2026, 7, 13)) == [("freeze", "2026-06")]  # T-1: catch-up
    assert decide(root, date(2026, 7, 14)) == []                      # release day, never frozen: too late


def test_resolve_fires_on_and_after_release_day_until_done(tmp_path):
    root = make_repo(tmp_path, frozen=["2026-06"])
    assert decide(root, date(2026, 7, 13)) == []
    assert decide(root, date(2026, 7, 14)) == [("resolve", "2026-06")]
    assert decide(root, date(2026, 7, 16)) == [("resolve", "2026-06")]  # print delayed: retry
    root = make_repo(tmp_path / "b", frozen=["2026-06"], resolved=["2026-06"])
    assert decide(root, date(2026, 7, 16)) == []                        # done: idempotent


def test_freeze_is_never_repeated(tmp_path):
    root = make_repo(tmp_path, frozen=["2026-06"])
    assert decide(root, date(2026, 7, 12)) == []


def test_rebuild_calibration_summary(tmp_path):
    root = tmp_path
    (root / "actuals/cpi").mkdir(parents=True)
    rows = [
        ("2026-04", 0.22, 0.376, False),
        ("2026-05", 0.227, 0.208, True),
    ]
    for period, p50, actual, hit in rows:
        (root / f"actuals/cpi/{period}.json").write_text(
            json.dumps({
                "period": period,
                "frozen": {"p10": p50 - 0.08, "p50": p50, "p90": p50 + 0.08},
                "actual": actual,
                "error_pp": actual - p50,
                "in_interval": hit,
            }),
            encoding="utf-8",
        )
    cal = rebuild_calibration(root)
    assert cal["summary"]["n_resolved"] == 2
    assert cal["summary"]["coverage_80"] == 0.5
    assert cal["summary"]["mae_pp"] > 0
    assert (root / "calibration/cpi.json").exists()
