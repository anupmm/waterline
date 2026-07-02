"""The loop: freeze -> resolve -> readout -> calibration (keel-v2 §7).

Freeze (T-3 before each scheduled print): run the committed model, write an
immutable forecasts/cpi/<period>.json. The CI workflow then cuts a GitHub
Release tagged freeze/cpi-<period> — the server-side timestamp is the public
proof the forecast predates the print.

Resolve (print day): re-fetch BLS, compute the first-published m/m, write
actuals/cpi/<period>.json with per-component attribution, draft the readout,
rebuild calibration/cpi.json from scratch (idempotent, no incremental state).

All date logic runs in America/New_York, because BLS does.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import yaml

from .cpi_author import COMPONENTS
from .engine import run, sensitivity
from .ingest.bls import SERIES, fetch_levels, load_env_key, mom
from .model import load_model

SEED = 20260702
N_DRAWS = 10_000
FREEZE_DAYS_BEFORE = 3


@dataclass(frozen=True)
class Release:
    period: str  # reference month "YYYY-MM"
    date: date   # scheduled release date


def load_schedule(root: Path) -> list[Release]:
    doc = yaml.safe_load((root / "models/cpi/schedule.yaml").read_text(encoding="utf-8"))
    out = []
    for r in doc["releases"]:
        d = r["date"] if isinstance(r["date"], date) else date.fromisoformat(str(r["date"]))
        out.append(Release(period=str(r["period"]), date=d))
    return sorted(out, key=lambda r: r.date)


def decide(root: Path, today: date) -> list[tuple[str, str]]:
    """Return [(action, period)] where action is 'freeze' or 'resolve'."""
    actions = []
    for rel in load_schedule(root):
        frozen = (root / f"forecasts/cpi/{rel.period}.json").exists()
        resolved = (root / f"actuals/cpi/{rel.period}.json").exists()
        days_out = (rel.date - today).days
        if not frozen and 0 < days_out <= FREEZE_DAYS_BEFORE:
            actions.append(("freeze", rel.period))
        if frozen and not resolved and days_out <= 0:
            actions.append(("resolve", rel.period))
    return actions


def git_head(root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:
        return "unknown"


def freeze_cpi(
    root: Path,
    period: str,
    out_root: Path | None = None,
    model_root: Path | None = None,
    release_date: date | None = None,
) -> dict:
    """Snapshot the committed model as the frozen forecast for `period`.
    `model_root` and `release_date` exist for the simulate path (as-of model
    in a scratch dir, historical period not in the live schedule)."""
    out_root = out_root or root
    model_root = model_root or root
    if release_date is None:
        release_date = next(r for r in load_schedule(root) if r.period == period).date
    model_path = model_root / "models/cpi/tree.yaml"
    registry_path = model_root / "registry/assumptions.yaml"
    model = load_model(model_path, registry_path)

    res = run(model, n_draws=N_DRAWS, seed=SEED)
    tornado = sensitivity(model, seed=SEED)

    weights = dict(
        zip(model.nodes[model.output].inputs, model.nodes[model.output].params["_weights"])
    )
    inputs = {}
    for node in model.input_nodes:
        inputs[node.name] = {
            "spec": {"kind": node.dist.kind, "params": list(node.dist.params)},
            "q10": node.dist.quantile(0.10),
            "q50": node.dist.quantile(0.50),
            "q90": node.dist.quantile(0.90),
            "epistemic_type": node.epistemic_type,
            "provenance": node.provenance,
            "weight": weights.get(node.name),
        }

    forecast = {
        "metric": "cpi",
        "period": period,
        "release_date": release_date.isoformat(),
        "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model_file": "models/cpi/tree.yaml",
        "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        "git_commit": git_head(root),
        "seed": SEED,
        "n_draws": N_DRAWS,
        "percentiles": res.percentiles(),
        "inputs": inputs,
        "tornado": [
            {"node": t.node, "spread": t.spread, "epistemic_type": t.epistemic_type}
            for t in tornado
        ],
    }
    out = out_root / f"forecasts/cpi/{period}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(forecast, indent=1), encoding="utf-8")
    return forecast


def resolve_cpi(
    root: Path, period: str, out_root: Path | None = None, refresh: bool = True
) -> dict | None:
    """Resolve a frozen forecast against the (just-)published print.
    Returns None if BLS has not published the period yet (retry next run)."""
    out_root = out_root or root
    forecast = json.loads(
        (out_root / f"forecasts/cpi/{period}.json").read_text(encoding="utf-8")
    )
    key = load_env_key(root)
    levels = fetch_levels(
        list(SERIES.values()), 2018, 2026, key=key, cache_dir=root / "data/bls", refresh=refresh
    )
    moms = {name: mom(levels[sid]) for name, sid in SERIES.items()}
    if period not in moms["core_cpi"]:
        return None  # not printed yet (or void month) — loop retries tomorrow

    actual = moms["core_cpi"][period]
    p = forecast["percentiles"]

    components = {}
    explained = 0.0
    for c in COMPONENTS:
        node = forecast["inputs"].get(f"{c}_mom")
        realized = moms[c].get(period)
        if node is None or realized is None or node.get("weight") is None:
            continue
        contribution = node["weight"] * (realized - node["q50"])
        explained += contribution
        components[c] = {
            "frozen_q50": node["q50"],
            "realized": realized,
            "weight": node["weight"],
            "contribution_pp": contribution,
        }
    error = actual - p["p50"]

    result = {
        "metric": "cpi",
        "period": period,
        "resolved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": f"BLS API {SERIES['core_cpi']}, first-published levels",
        "actual": actual,
        "published_1dp": round(actual, 1),
        "frozen": {**p, "frozen_at": forecast["frozen_at"]},
        "error_pp": error,
        "in_interval": p["p10"] <= actual <= p["p90"],
        "attribution": {
            "components": components,
            "unexplained_pp": error - explained,
        },
    }
    out = out_root / f"actuals/cpi/{period}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1), encoding="utf-8")

    rebuild_calibration(out_root)
    write_readout(out_root, result)
    return result


def rebuild_calibration(root: Path) -> dict:
    rows = []
    for f in sorted((root / "actuals/cpi").glob("*.json")):
        a = json.loads(f.read_text(encoding="utf-8"))
        rows.append(
            {
                "period": a["period"],
                "p10": a["frozen"]["p10"],
                "p50": a["frozen"]["p50"],
                "p90": a["frozen"]["p90"],
                "actual": a["actual"],
                "error_pp": a["error_pp"],
                "in_interval": a["in_interval"],
            }
        )
    n = len(rows)
    summary = {
        "n_resolved": n,
        "coverage_80": (sum(r["in_interval"] for r in rows) / n) if n else None,
        "mae_pp": (sum(abs(r["error_pp"]) for r in rows) / n) if n else None,
        "bias_pp": (sum(r["error_pp"] for r in rows) / n) if n else None,
    }
    cal = {"metric": "cpi", "summary": summary, "rows": rows}
    out = root / "calibration/cpi.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(cal, indent=1), encoding="utf-8")
    return cal


def write_readout(root: Path, r: dict) -> Path:
    cal = json.loads((root / "calibration/cpi.json").read_text(encoding="utf-8"))
    s = cal["summary"]
    comp_rows = "\n".join(
        f"| {c} | {v['frozen_q50']:+.3f} | {v['realized']:+.3f} | {v['weight']:.3f} "
        f"| {v['contribution_pp']:+.3f} |"
        for c, v in r["attribution"]["components"].items()
    )
    hit = "inside" if r["in_interval"] else "OUTSIDE"
    text = f"""# Core CPI {r['period']}: {r['actual']:+.3f}% vs frozen p50 {r['frozen']['p50']:+.3f}%

The forecast was frozen {r['frozen']['frozen_at'][:10]} (release `freeze/cpi-{r['period']}`),
{abs((date.fromisoformat(r['resolved_at'][:10]) - date.fromisoformat(r['frozen']['frozen_at'][:10])).days)} days before the print.
The print landed **{hit}** the 80% interval [{r['frozen']['p10']:+.3f}, {r['frozen']['p90']:+.3f}].
Miss: **{r['error_pp']:+.3f}pp**.

## Which assumptions ate the error

| component | frozen p50 | realized | weight | contribution (pp) |
|---|---|---|---|---|
{comp_rows}
| unexplained (decomposition residual) | | | | {r['attribution']['unexplained_pp']:+.3f} |

Contributions are weight x (realized minus frozen median); they sum with the
residual to the total miss. Every frozen assumption, its provenance, and the
full model are in `forecasts/cpi/{r['period']}.json` and the tagged release.

## Calibration to date

{s['n_resolved']} resolved print(s); 80% interval coverage {s['coverage_80']:.0%};
MAE {s['mae_pp']:.3f}pp; bias {s['bias_pp']:+.3f}pp.

*Generated by the loop. Not investment advice.*
"""
    out = root / f"readouts/cpi-{r['period']}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return out
