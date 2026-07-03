"""The loop: freeze -> resolve -> readout -> calibration (keel-v2 §7).

Multi-metric. Each metric defines: how its release schedule is known, how far
before the print it freezes, how its forecast is produced, and how it
resolves. Two styles exist so far:

  cpi     committed long-lived model (models/cpi/tree.yaml + registry),
          schedule from models/cpi/schedule.yaml, freeze at T-3,
          resolved from the BLS API with per-component attribution.
  claims  auto-authored at freeze from the latest FRED data (trailing
          windows move weekly; the frozen JSON records the exact inputs),
          schedule computed (week ends Saturday, prints Thursday +5),
          freeze at T-1, resolved from FRED (truth: the DOL release).

Freeze artifacts are immutable forecasts/<metric>/<period>.json; the CI
workflow cuts a GitHub Release freeze/<metric>-<period> whose server-side
timestamp is the public proof the forecast predates the print. Resolutions
write actuals + readout and rebuild calibration/<metric>.json idempotently.
All date logic runs in America/New_York.
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

from .claims_author import author_claims_doc
from .cpi_author import COMPONENTS
from .engine import run, sensitivity
from .ingest.bls import SERIES, fetch_levels, load_env_key, mom
from .ingest.fred import ICSA, fetch_series
from .model import build_model, load_model

SEED = 20260702
N_DRAWS = 10_000

METRICS = {
    "cpi": {"title": "Core CPI", "freeze_days_before": 3, "unit": "% m/m"},
    "claims": {"title": "Initial claims", "freeze_days_before": 1, "unit": "persons"},
}


@dataclass(frozen=True)
class Release:
    metric: str
    period: str
    date: date  # scheduled release date


# --- schedules ---------------------------------------------------------------

def load_schedule(root: Path) -> list[Release]:
    """CPI schedule from file (dates slip; owner-verified)."""
    doc = yaml.safe_load((root / "models/cpi/schedule.yaml").read_text(encoding="utf-8"))
    out = []
    for r in doc["releases"]:
        d = r["date"] if isinstance(r["date"], date) else date.fromisoformat(str(r["date"]))
        out.append(Release("cpi", str(r["period"]), d))
    return sorted(out, key=lambda r: r.date)


def claims_schedule(today: date, weeks_ahead: int = 4) -> list[Release]:
    """Computed: reference week ends Saturday, prints the following Thursday.
    Holiday shifts are absorbed by the resolve-retry behavior."""
    out = []
    days_to_sat = (5 - today.weekday()) % 7  # Monday=0 ... Saturday=5
    next_sat = today + timedelta(days=days_to_sat)
    for i in range(-2, weeks_ahead):  # a couple past weeks so resolve can catch up
        week_end = next_sat + timedelta(weeks=i)
        out.append(Release("claims", week_end.isoformat(), week_end + timedelta(days=5)))
    return out


def all_releases(root: Path, today: date) -> list[Release]:
    return load_schedule(root) + claims_schedule(today)


def decide(root: Path, today: date) -> list[tuple[str, str, str]]:
    """[(action, metric, period)] — freeze inside the metric's window,
    resolve on/after release day until an actual exists."""
    actions = []
    for rel in all_releases(root, today):
        frozen = (root / f"forecasts/{rel.metric}/{rel.period}.json").exists()
        resolved = (root / f"actuals/{rel.metric}/{rel.period}.json").exists()
        days_out = (rel.date - today).days
        window = METRICS[rel.metric]["freeze_days_before"]
        if not frozen and 0 < days_out <= window:
            actions.append(("freeze", rel.metric, rel.period))
        if frozen and not resolved and days_out <= 0:
            actions.append(("resolve", rel.metric, rel.period))
    return actions


# --- shared helpers ----------------------------------------------------------

def git_head(root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:
        return "unknown"


def _forecast_payload(model, metric: str, period: str, release_date: date, extra: dict) -> dict:
    res = run(model, n_draws=N_DRAWS, seed=SEED)
    tornado = sensitivity(model, seed=SEED)
    inputs = {}
    for node in model.input_nodes:
        inputs[node.name] = {
            "spec": {"kind": node.dist.kind, "params": list(node.dist.params)},
            "q10": node.dist.quantile(0.10),
            "q50": node.dist.quantile(0.50),
            "q90": node.dist.quantile(0.90),
            "epistemic_type": node.epistemic_type,
            "provenance": node.provenance,
        }
    return {
        "metric": metric,
        "period": period,
        "release_date": release_date.isoformat(),
        "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seed": SEED,
        "n_draws": N_DRAWS,
        "percentiles": res.percentiles(),
        "inputs": inputs,
        "tornado": [
            {"node": t.node, "spread": t.spread, "epistemic_type": t.epistemic_type}
            for t in tornado
        ],
        **extra,
    }


def _write_forecast(out_root: Path, payload: dict) -> None:
    out = out_root / f"forecasts/{payload['metric']}/{payload['period']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1), encoding="utf-8")


def _write_actual(out_root: Path, metric: str, result: dict) -> None:
    out = out_root / f"actuals/{metric}/{result['period']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    rebuild_calibration(out_root, metric)
    write_readout(out_root, metric, result)


# --- cpi ---------------------------------------------------------------------

def freeze_cpi(
    root: Path,
    period: str,
    out_root: Path | None = None,
    model_root: Path | None = None,
    release_date: date | None = None,
) -> dict:
    out_root = out_root or root
    model_root = model_root or root
    if release_date is None:
        release_date = next(
            r for r in load_schedule(root) if r.period == period
        ).date
    model_path = model_root / "models/cpi/tree.yaml"
    model = load_model(model_path, model_root / "registry/assumptions.yaml")
    weights = dict(
        zip(model.nodes[model.output].inputs, model.nodes[model.output].params["_weights"])
    )
    payload = _forecast_payload(
        model, "cpi", period, release_date,
        {
            "model_file": "models/cpi/tree.yaml",
            "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
            "git_commit": git_head(root),
            "weights": weights,
        },
    )
    for name, w in weights.items():
        if name in payload["inputs"]:
            payload["inputs"][name]["weight"] = w
    _write_forecast(out_root, payload)
    return payload


def resolve_cpi(
    root: Path, period: str, out_root: Path | None = None, refresh: bool = True
) -> dict | None:
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
        return None

    actual = moms["core_cpi"][period]
    p = forecast["percentiles"]
    components, explained = {}, 0.0
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
        "error": error,
        "in_interval": p["p10"] <= actual <= p["p90"],
        "attribution": {"components": components, "unexplained": error - explained},
    }
    result["error_pp"] = error  # back-compat for earlier artifacts/site
    _write_actual(out_root, "cpi", result)
    return result


# --- claims ------------------------------------------------------------------

def freeze_claims(
    root: Path,
    period: str,
    out_root: Path | None = None,
    release_date: date | None = None,
    refresh: bool = True,
    as_of: str | None = None,
) -> dict:
    out_root = out_root or root
    if release_date is None:
        release_date = date.fromisoformat(period) + timedelta(days=5)
    values = fetch_series(ICSA, cache_dir=root / "data/fred", refresh=refresh)
    doc, meta = author_claims_doc(values, as_of=as_of)
    payload = _forecast_payload(
        build_model(doc), "claims", period, release_date,
        {"authored_doc": doc, "git_commit": git_head(root)},
    )
    _write_forecast(out_root, payload)
    return payload


def resolve_claims(
    root: Path, period: str, out_root: Path | None = None, refresh: bool = True
) -> dict | None:
    out_root = out_root or root
    forecast = json.loads(
        (out_root / f"forecasts/claims/{period}.json").read_text(encoding="utf-8")
    )
    values = fetch_series(ICSA, cache_dir=root / "data/fred", refresh=refresh)
    if period not in values:
        return None

    actual = values[period]
    p = forecast["percentiles"]
    base = forecast["inputs"]["base_4wk"]["q50"]
    drift_q50 = forecast["inputs"]["drift"]["q50"]
    result = {
        "metric": "claims",
        "period": period,
        "resolved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "DOL weekly UI claims release (SA initial claims), retrieved via FRED ICSA",
        "actual": actual,
        "frozen": {**p, "frozen_at": forecast["frozen_at"]},
        "error": actual - p["p50"],
        "in_interval": p["p10"] <= actual <= p["p90"],
        "attribution": {
            "components": {
                "drift": {
                    "frozen_q50": drift_q50,
                    "realized": actual / base,
                    "note": "realized week-over-base ratio vs assumed",
                }
            },
            "unexplained": 0.0,
        },
    }
    _write_actual(out_root, "claims", result)
    return result


FREEZERS = {"cpi": freeze_cpi, "claims": freeze_claims}
RESOLVERS = {"cpi": resolve_cpi, "claims": resolve_claims}


# --- calibration + readouts --------------------------------------------------

def rebuild_calibration(root: Path, metric: str) -> dict:
    rows = []
    actuals_dir = root / f"actuals/{metric}"
    for f in sorted(actuals_dir.glob("*.json")) if actuals_dir.exists() else []:
        a = json.loads(f.read_text(encoding="utf-8"))
        rows.append(
            {
                "period": a["period"],
                "p10": a["frozen"]["p10"],
                "p50": a["frozen"]["p50"],
                "p90": a["frozen"]["p90"],
                "actual": a["actual"],
                "error": a.get("error", a.get("error_pp")),
                "in_interval": a["in_interval"],
            }
        )
    n = len(rows)
    summary = {
        "n_resolved": n,
        "coverage_80": (sum(r["in_interval"] for r in rows) / n) if n else None,
        "mae": (sum(abs(r["error"]) for r in rows) / n) if n else None,
        "bias": (sum(r["error"] for r in rows) / n) if n else None,
    }
    cal = {"metric": metric, "summary": summary, "rows": rows}
    out = root / f"calibration/{metric}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(cal, indent=1), encoding="utf-8")
    return cal


def _fmt(metric: str, v: float) -> str:
    return f"{v:+.3f}%" if metric == "cpi" else f"{v:,.0f}"


def write_readout(root: Path, metric: str, r: dict) -> Path:
    cal = json.loads((root / f"calibration/{metric}.json").read_text(encoding="utf-8"))
    s = cal["summary"]
    title = METRICS[metric]["title"]
    f = lambda v: _fmt(metric, v)  # noqa: E731
    hit = "inside" if r["in_interval"] else "OUTSIDE"

    comp_rows = ""
    for c, v in r["attribution"]["components"].items():
        realized = v.get("realized")
        contribution = v.get("contribution_pp")
        comp_rows += (
            f"| {c} | {v['frozen_q50']:+.3f} | {realized:+.3f} "
            f"| {'' if contribution is None else f'{contribution:+.3f}'} |\n"
        )
    unexplained = r["attribution"].get("unexplained", 0.0)

    text = f"""# {title} {r['period']}: {f(r['actual'])} vs frozen p50 {f(r['frozen']['p50'])}

Frozen {r['frozen']['frozen_at'][:10]} (release `freeze/{metric}-{r['period']}`).
The print landed **{hit}** the 80% interval [{f(r['frozen']['p10'])}, {f(r['frozen']['p90'])}].
Miss: **{f(r['error'])}**.

## Attribution

| component | frozen p50 | realized | contribution |
|---|---|---|---|
{comp_rows}| unexplained | | | {unexplained:+.3f} |

Every frozen assumption and its provenance: `forecasts/{metric}/{r['period']}.json`
and the tagged release.

## Calibration to date ({title})

{s['n_resolved']} resolved; 80% interval coverage {s['coverage_80']:.0%};
MAE {(f"{s['mae']:.3f}" if metric == "cpi" else f"{s['mae']:,.0f}")}; bias {f(s['bias'])}.

*Generated by the loop. Not investment advice.*
"""
    out = root / f"readouts/{metric}-{r['period']}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return out
