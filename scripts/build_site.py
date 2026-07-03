"""Build the static site into site/ (deployed to GitHub Pages by CI).

One page, multi-metric: next-print cards, the CPI model with epistemic
colors and tornado, the resolution feed (all metrics, newest first),
simulated backfills, and per-metric calibration ledgers.
Standing constraint: no number without its epistemic color.

Run:  uv run python scripts/build_site.py
"""

from __future__ import annotations

import html
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import markdown

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from waterline.engine import run, sensitivity
from waterline.loop import METRICS, SEED, all_releases
from waterline.model import load_model

REPO = "https://github.com/anupmm/waterline"
BADGE = {
    "guess": ("guess", "#c0392b"),
    "benchmarked": ("benchmarked", "#b9770e"),
    "data_bound": ("data-bound", "#1e8449"),
}


def esc(s: object) -> str:
    return html.escape(str(s))


def badge(etype: str) -> str:
    label, color = BADGE[etype]
    return f'<span class="badge" style="background:{color}">{label}</span>'


def fmt(metric: str, v: float) -> str:
    return f"{v:+.3f}" if metric == "cpi" else f"{v:,.0f}"


def load_dir(d: Path) -> dict[str, dict]:
    if not d.exists():
        return {}
    return {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in sorted(d.glob("*.json"))}


def main() -> int:
    today = datetime.now(ZoneInfo("America/New_York")).date()

    forecasts = {m: load_dir(ROOT / f"forecasts/{m}") for m in METRICS}
    actuals = {m: load_dir(ROOT / f"actuals/{m}") for m in METRICS}

    # --- next print cards (nearest upcoming release per metric) ---
    seen = set()
    cards = ""
    for rel in sorted(all_releases(ROOT, today), key=lambda r: r.date):
        if rel.metric in seen or rel.period in actuals[rel.metric] or rel.date < today:
            continue
        seen.add(rel.metric)
        cfg = METRICS[rel.metric]
        days = (rel.date - today).days
        fz = forecasts[rel.metric].get(rel.period)
        if fz:
            fp = fz["percentiles"]
            status = (
                f'<strong>FROZEN</strong> {esc(fz["frozen_at"][:10])} at '
                f"p10 {fmt(rel.metric, fp['p10'])} / p50 {fmt(rel.metric, fp['p50'])} "
                f"/ p90 {fmt(rel.metric, fp['p90'])} {esc(cfg['unit'])} "
                f'(<a href="{REPO}/releases/tag/freeze/{rel.metric}-{esc(rel.period)}">verify timestamp</a>)'
            )
        else:
            status = f"freezes at T&minus;{cfg['freeze_days_before']}."
        cards += f"""<div class="card">
        <h2>Next print: {esc(cfg['title'])} {esc(rel.period)}</h2>
        <p>Scheduled release {esc(rel.date.isoformat())} (8:30 AM ET) &mdash; {days} day(s) away. {status}</p>
        </div>"""

    # --- CPI model section (committed model; claims is auto-authored at freeze) ---
    model = load_model(ROOT / "models/cpi/tree.yaml", ROOT / "registry/assumptions.yaml")
    res = run(model, seed=SEED)
    p = res.percentiles()
    tornado = sensitivity(model, seed=SEED)
    annualized = 100 * ((1 + p["p50"] / 100) ** 12 - 1)

    rows = ""
    for node in sorted(model.input_nodes, key=lambda n: n.name):
        q10, q50, q90 = (node.dist.quantile(q) for q in (0.10, 0.50, 0.90))
        rng = f"{q50:+.3f} (point)" if node.dist.is_point else f"{q10:+.3f} &hellip; {q90:+.3f}"
        rows += (
            f"<tr><td><code>{esc(node.name)}</code></td><td>{badge(node.epistemic_type)}</td>"
            f"<td class='num'>{rng}</td><td class='prov'>{esc(node.provenance or node.source or '')}</td></tr>"
        )
    max_spread = tornado[0].spread if tornado else 1.0
    bars = "".join(
        f"<div class='trow'><div class='tlabel'><code>{esc(t.node)}</code></div>"
        f"<div class='tbar'><div class='tfill' style='width:{100 * t.spread / max_spread:.0f}%'></div></div>"
        f"<div class='tval'>{t.spread:.3f}</div>{badge(t.epistemic_type)}</div>"
        for t in tornado
    )
    units_note = (
        '<p class="muted">CPI figures are the seasonally adjusted <strong>month-over-month</strong> '
        "% change in core CPI — the number the BLS release headline reports. A "
        f"+{p['p50']:.2f}% month compounds to &asymp;{annualized:.1f}% annualized; the "
        '"~3%" inflation figure in the news is the separate year-over-year measure. '
        "p10/p50/p90: 10% chance below p10, even odds around p50, 10% above p90 — "
        "p10&ndash;p90 is an 80% interval.</p>"
    )

    # --- resolution feed (all metrics, newest resolution first) ---
    resolved = []
    for m in METRICS:
        for period, a in actuals[m].items():
            resolved.append((a.get("resolved_at", ""), m, period))
    feed = ""
    for _, m, period in sorted(resolved, reverse=True):
        md = ROOT / f"readouts/{m}-{period}.md"
        if md.exists():
            body = markdown.markdown(md.read_text(encoding="utf-8"), extensions=["tables"])
            feed += f'<div class="card readout">{body}</div>'
    if not feed:
        feed = (
            "<p class='muted'>No resolved prints yet. The first live resolution lands with the "
            "initial-claims print; readouts appear here automatically.</p>"
        )

    # --- backfills + calibration ---
    def backtest_block(metric: str, path: Path, cols: tuple[str, str]) -> str:
        if not path.exists():
            return ""
        bt = json.loads(path.read_text(encoding="utf-8"))
        bs = bt["summary"]
        trs = "".join(
            f"<tr><td>{esc(r['period'])}</td><td class='num'>{fmt(metric, r['p10'])}</td>"
            f"<td class='num'>{fmt(metric, r['p50'])}</td><td class='num'>{fmt(metric, r['p90'])}</td>"
            f"<td class='num'>{fmt(metric, r['actual'])}</td>"
            f"<td>{'&#10003;' if r['hit'] else '&#10007;'}</td></tr>"
            for r in bt["rows"]
        )
        second = f" &middot; {cols[1]} {fmt(metric, bs[cols[0]])}" if cols[0] in bs else ""
        return f"""<h3>{esc(METRICS[metric]['title'])}</h3>
        <p>{bs['n']} prints &middot; model p50 MAE <strong>{fmt(metric, bs['mae_model'])}</strong>
        vs naive-last {fmt(metric, bs['mae_naive_last'])}{second}
        &middot; 80% coverage <strong>{bs['coverage_80']:.0%}</strong>
        &middot; <a href="{REPO}/blob/main/docs/backtest-{metric}.md">full report</a></p>
        <table><tr><th>period</th><th>p10</th><th>p50</th><th>p90</th><th>actual</th><th>hit</th></tr>{trs}</table>"""

    backtests = backtest_block("cpi", ROOT / "docs/backtest-cpi.json", ("mae_trailing6", "trailing-6m"))
    backtests += backtest_block("claims", ROOT / "docs/backtest-claims.json", ("mae_mean4", "4wk-mean"))

    cal_html = ""
    for m, cfg in METRICS.items():
        cal_file = ROOT / f"calibration/{m}.json"
        if not cal_file.exists():
            continue
        cal = json.loads(cal_file.read_text(encoding="utf-8"))
        s = cal["summary"]
        if not s["n_resolved"]:
            continue
        crows = "".join(
            f"<tr><td>{esc(r['period'])}</td><td class='num'>{fmt(m, r['p10'])}</td>"
            f"<td class='num'>{fmt(m, r['p50'])}</td><td class='num'>{fmt(m, r['p90'])}</td>"
            f"<td class='num'>{fmt(m, r['actual'])}</td><td class='num'>{fmt(m, r['error'])}</td>"
            f"<td>{'&#10003;' if r['in_interval'] else '&#10007;'}</td></tr>"
            for r in cal["rows"]
        )
        cal_html += f"""<h3>{esc(cfg['title'])}</h3>
        <p>{s['n_resolved']} resolved &middot; 80% coverage <strong>{s['coverage_80']:.0%}</strong>
        &middot; MAE <strong>{fmt(m, s['mae'])}</strong> &middot; bias {fmt(m, s['bias'])}</p>
        <table><tr><th>period</th><th>p10</th><th>p50</th><th>p90</th><th>actual</th><th>error</th><th>hit</th></tr>{crows}</table>"""
    if not cal_html:
        cal_html = "<p class='muted'>Empty until the first live frozen forecast resolves.</p>"

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Waterline — open calibrated driver models</title>
<link rel="stylesheet" href="style.css"></head><body>
<header><h1>Waterline</h1>
<p class="tag">Forecasts as versioned driver models: frozen before the print, resolved against official data,
error attributed to named assumptions, calibration public. <a href="{REPO}">Fork it on GitHub</a>.</p></header>

{cards}

<h2>The CPI model: US core CPI m/m</h2>
<p>Weighted decomposition (<a href="{REPO}/blob/main/models/cpi/tree.yaml">tree.yaml</a> &middot;
<a href="{REPO}/blob/main/models/cpi/resolution.md">resolution rule</a>).
Current output: <strong>p10 {p['p10']:+.3f} / p50 {p['p50']:+.3f} / p90 {p['p90']:+.3f}</strong> % m/m.</p>
{units_note}
<table><tr><th>assumption</th><th>epistemic status</th><th>q10 &hellip; q90</th><th>provenance</th></tr>{rows}</table>
<h3>Sensitivity (output p50 spread, one-at-a-time q10&rarr;q90)</h3>
<div class="tornado">{bars}</div>
<p class="muted">The claims model is simpler — trailing base &times; drift — and is auto-authored at each
freeze from the latest data (<a href="{REPO}/blob/main/models/claims/resolution.md">resolution rule</a>);
every frozen input is recorded in the forecast JSON.</p>
<p class="muted">Disagree with an assumption? Edit one YAML value and open a PR — CI comments your
exact forecast delta, and your track record accrues under your GitHub handle.</p>

<h2>Resolutions</h2>
{feed}

<h2>Simulated backfills (walk-forward backtests)</h2>
<p class="muted"><strong>Simulated, not frozen.</strong> Generated retroactively with as-of cutoffs
(same code path as live authoring, no lookahead) to show what the loop produces. No timestamp proof;
kept strictly separate from the live ledger below.</p>
{backtests}

<h2>Calibration ledger (live frozen forecasts only)</h2>
{cal_html}

<footer><p>Built {esc(today.isoformat())} by the loop. All data from primary public sources (BLS, DOL via FRED).
Nothing here is investment advice; Waterline forecasts official statistics and reported fundamentals, never prices.</p></footer>
</body></html>"""

    site = ROOT / "site"
    site.mkdir(exist_ok=True)
    (site / "index.html").write_text(page, encoding="utf-8")
    (site / "style.css").write_text(CSS, encoding="utf-8")
    print(f"wrote {site / 'index.html'}")
    return 0


CSS = """
:root { --fg:#1b2733; --muted:#6b7a8c; --line:#dfe6ee; --accent:#0b5394; }
* { box-sizing:border-box }
body { font:16px/1.55 -apple-system,'Segoe UI',Roboto,sans-serif; color:var(--fg);
  max-width:880px; margin:2rem auto; padding:0 1rem; }
h1 { margin-bottom:0 } .tag { color:var(--muted) }
h2 { border-bottom:1px solid var(--line); padding-bottom:.3rem; margin-top:2.2rem }
a { color:var(--accent) }
table { border-collapse:collapse; width:100%; font-size:.92rem }
th,td { text-align:left; padding:.35rem .6rem; border-bottom:1px solid var(--line); vertical-align:top }
td.num { font-variant-numeric:tabular-nums; white-space:nowrap }
td.prov { color:var(--muted); font-size:.8rem }
.badge { color:#fff; border-radius:3px; padding:.1rem .45rem; font-size:.75rem; white-space:nowrap }
.card { border:1px solid var(--line); border-radius:8px; padding:.2rem 1.2rem; margin:1.2rem 0;
  background:#f7fafc }
.readout table { margin:.5rem 0 }
.tornado { margin:.6rem 0 }
.trow { display:flex; align-items:center; gap:.6rem; margin:.25rem 0 }
.tlabel { width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap }
.tbar { flex:1; background:#eef2f7; border-radius:3px; height:14px }
.tfill { background:var(--accent); height:14px; border-radius:3px }
.tval { width:56px; text-align:right; font-variant-numeric:tabular-nums; font-size:.85rem }
.muted { color:var(--muted) }
footer { margin-top:3rem; border-top:1px solid var(--line); color:var(--muted); font-size:.85rem }
"""

if __name__ == "__main__":
    sys.exit(main())
