"""Build the static site into site/ (deployed to GitHub Pages by CI).

Layout is prediction-first: one section per metric, each led by the question
being predicted, the current answer (frozen or preview), and the resolution
date. Model internals, track record, and methodology sit below the fold in
<details> blocks. Standing constraint: no number without its epistemic color.

Run:  uv run python scripts/build_site.py
"""

from __future__ import annotations

import html
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import markdown
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from waterline.claims_author import author_claims_doc
from waterline.engine import run, sensitivity
from waterline.ingest.fred import ICSA, fetch_series
from waterline.loop import METRICS, SEED, all_releases
from waterline.model import InputNode, TransformNode, build_model, load_model

REPO = "https://github.com/anupmm/waterline"
BADGE = {
    "guess": ("guess", "#c0392b"),
    "benchmarked": ("benchmarked", "#b9770e"),
    "data_bound": ("data-bound", "#1e8449"),
}

DISPLAY = {
    "cpi": {
        "topic": "Inflation",
        "question": lambda per: f"How much will US core consumer prices rise in {month_name(per)}?",
        "value": lambda v: f"{v:+.2f}%",
        "value_note": "seasonally adjusted month-over-month change in core CPI",
        "period_phrase": lambda per: month_name(per),
    },
    "claims": {
        "topic": "Labor market",
        "question": lambda per: f"How many Americans will file new unemployment claims in the week ending {day_name(per)}?",
        "value": lambda v: f"{v:,.0f}",
        "value_note": "seasonally adjusted initial jobless claims",
        "period_phrase": lambda per: f"week ending {day_name(per)}",
    },
}

MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]


def month_name(period: str) -> str:
    return f"{MONTHS[int(period[5:7]) - 1]} {period[:4]}"


def day_name(period: str) -> str:
    d = date.fromisoformat(period)
    return f"{MONTHS[d.month - 1]} {d.day}, {d.year}"


def esc(s: object) -> str:
    return html.escape(str(s))


def badge(etype: str) -> str:
    label, color = BADGE[etype]
    return f'<span class="badge" style="background:{color}">{label}</span>'


def fmt(metric: str, v: float) -> str:
    return f"{v:+.3f}" if metric == "cpi" else f"{v:,.0f}"


def humanize(v: float, kind: str) -> str:
    prefix = "$" if kind == "usd" else ""
    a = abs(v)
    if a >= 1e9:
        s = f"{v / 1e9:.1f} billion"
    elif a >= 1e6:
        s = f"{v / 1e6:.1f} million"
    elif a >= 1e3:
        s = f"{v / 1e3:.0f} thousand"
    else:
        s = f"{v:,.0f}"
    return prefix + s


def load_dir(d: Path) -> dict[str, dict]:
    if not d.exists():
        return {}
    return {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in sorted(d.glob("*.json"))}


FN_LABEL = {"weighted_sum": "weighted sum of", "sum": "sum of", "product": "product of",
            "ratio": "ratio of", "linear": "linear in"}


def tree_html(model) -> str:
    """Auto-rendered driver tree from the DAG — a rendering of tree.yaml,
    regenerated on every build so it can never drift from the model."""

    def render(name: str, weight: float | None = None) -> str:
        node = model.nodes[name]
        wtag = f"<span class='muted'> ×{weight:.3g}</span>" if weight is not None else ""
        if isinstance(node, InputNode):
            q10, q90 = node.dist.quantile(0.10), node.dist.quantile(0.90)
            rng = (
                f"{node.dist.quantile(0.5):,.3g}"
                if node.dist.is_point
                else f"{q10:,.3g} … {q90:,.3g}"
            )
            return (
                f"<li><code>{esc(name)}</code>{wtag} {badge(node.epistemic_type)} "
                f"<span class='num muted'>{rng}</span></li>"
            )
        assert isinstance(node, TransformNode)
        weights = node.params.get("_weights")
        children = "".join(
            render(i, w)
            for i, w in zip(node.inputs, weights or [None] * len(node.inputs))
        )
        label = FN_LABEL.get(node.fn, node.fn)
        return (
            f"<li><code>{esc(name)}</code>{wtag} <span class='muted'>= {esc(label)}</span>"
            f"<ul>{children}</ul></li>"
        )

    return f"<ul class='dtree'>{render(model.output)}</ul>"


def derivation_html(model_dir: Path) -> str:
    md = model_dir / "derivation.md"
    if not md.exists():
        return ""
    return (
        "<div class='derivation'>"
        + markdown.markdown(md.read_text(encoding="utf-8"), extensions=["tables"])
        + f"<p class='muted'>Convention: <code>tree.yaml</code> is the machine-checked model; "
        f"<code>derivation.md</code> is the author's reasoning. PRs that change one should "
        f"update the other.</p></div>"
    )


def model_details_html(model, valfmt) -> str:
    rows = ""
    for node in sorted(model.input_nodes, key=lambda n: n.name):
        q10, q50, q90 = (node.dist.quantile(q) for q in (0.10, 0.50, 0.90))
        # per-node values may live on a different scale than the output
        # (fractions, unit volumes), so format compactly and scale-agnostically
        nf = lambda v: f"{v:,.3g}"  # noqa: E731
        rng = f"{nf(q50)} (point)" if node.dist.is_point else f"{nf(q10)} &hellip; {nf(q90)}"
        rows += (
            f"<tr><td><code>{esc(node.name)}</code></td><td>{badge(node.epistemic_type)}</td>"
            f"<td class='num'>{rng}</td><td class='prov'>{esc(node.provenance or node.source or '')}</td></tr>"
        )
    tornado = sensitivity(model, seed=SEED)
    max_spread = tornado[0].spread if tornado else 1.0
    bars = "".join(
        f"<div class='trow'><div class='tlabel'><code>{esc(t.node)}</code></div>"
        f"<div class='tbar'><div class='tfill' style='width:{100 * t.spread / max_spread:.0f}%'></div></div>"
        f"<div class='tval'>{valfmt(t.spread).lstrip('+$')}</div>{badge(t.epistemic_type)}</div>"
        for t in tornado
    )
    return f"""
    <table><tr><th>assumption</th><th>status</th><th>q10 &hellip; q90</th><th>where it comes from</th></tr>{rows}</table>
    <p class="muted" style="margin-top:.8rem">Sensitivity — how much the answer moves if one assumption
    slides from its own q10 to q90:</p>
    <div class="tornado">{bars}</div>"""


def track_record_html(metric: str) -> str:
    out = ""
    cal_file = ROOT / f"calibration/{metric}.json"
    if cal_file.exists():
        cal = json.loads(cal_file.read_text(encoding="utf-8"))
        s = cal["summary"]
        if s["n_resolved"]:
            crows = "".join(
                f"<tr><td>{esc(r['period'])}</td><td class='num'>{fmt(metric, r['p10'])}</td>"
                f"<td class='num'>{fmt(metric, r['p50'])}</td><td class='num'>{fmt(metric, r['p90'])}</td>"
                f"<td class='num'>{fmt(metric, r['actual'])}</td><td class='num'>{fmt(metric, r['error'])}</td>"
                f"<td>{'&#10003;' if r['in_interval'] else '&#10007;'}</td></tr>"
                for r in cal["rows"]
            )
            out += f"""<h4>Live frozen forecasts</h4>
            <p>{s['n_resolved']} resolved &middot; 80% coverage <strong>{s['coverage_80']:.0%}</strong>
            &middot; MAE <strong>{fmt(metric, s['mae']).lstrip('+')}</strong></p>
            <table><tr><th>period</th><th>p10</th><th>p50</th><th>p90</th><th>actual</th><th>error</th><th>hit</th></tr>{crows}</table>"""
    if not out:
        out = "<p class='muted'>No live resolutions yet — the ledger starts with the first frozen print.</p>"

    bt_file = ROOT / f"docs/backtest-{metric}.json"
    if bt_file.exists():
        bt = json.loads(bt_file.read_text(encoding="utf-8"))
        bs = bt["summary"]
        out += f"""<h4>Simulated backfill (not frozen)</h4>
        <p class="muted">Walk-forward backtest with as-of cutoffs — same code as live authoring, no
        lookahead, but no timestamp proof either; kept separate from the live ledger.</p>
        <p>{bs['n']} prints &middot; model p50 MAE <strong>{fmt(metric, bs['mae_model']).lstrip('+')}</strong>
        vs naive-last {fmt(metric, bs['mae_naive_last']).lstrip('+')}
        &middot; 80% coverage <strong>{bs['coverage_80']:.0%}</strong>
        &middot; <a href="{REPO}/blob/main/docs/backtest-{metric}.md">full table</a></p>"""
    return out


def main() -> int:
    today = datetime.now(ZoneInfo("America/New_York")).date()
    forecasts = {m: load_dir(ROOT / f"forecasts/{m}") for m in METRICS}
    actuals = {m: load_dir(ROOT / f"actuals/{m}") for m in METRICS}

    # nearest actionable release per metric: unresolved, and either already
    # frozen (awaiting the print) or still freezable (release in the future)
    nxt: dict[str, object] = {}
    for rel in sorted(all_releases(ROOT, today), key=lambda r: r.date):
        if rel.metric in nxt or rel.period in actuals[rel.metric]:
            continue
        frozen = rel.period in forecasts[rel.metric]
        if frozen or rel.date > today:
            nxt[rel.metric] = rel

    # current answer per metric: frozen if frozen, else live preview
    sections = ""
    for m, cfg in METRICS.items():
        disp = DISPLAY[m]
        rel = nxt.get(m)
        if rel is None:
            continue
        if m == "cpi":
            model = load_model(ROOT / "models/cpi/tree.yaml", ROOT / "registry/assumptions.yaml")
        else:
            doc, _ = author_claims_doc(fetch_series(ICSA, cache_dir=ROOT / "data/fred"))
            model = build_model(doc)

        fz = forecasts[m].get(rel.period)
        if fz:
            p = fz["percentiles"]
            chip = (
                f'<span class="chip frozen">frozen {esc(fz["frozen_at"][:10])} &middot; '
                f'<a href="{REPO}/releases/tag/freeze/{m}-{esc(rel.period)}">proof</a></span>'
            )
        else:
            p = run(model, seed=SEED).percentiles()
            freeze_day = rel.date - timedelta(days=cfg["freeze_days_before"])
            chip = f'<span class="chip">preview &middot; freezes {esc(freeze_day.isoformat())}</span>'

        days = (rel.date - today).days
        question = disp["question"](rel.period)

        competing = ""
        if m == "claims":
            values = fetch_series(ICSA, cache_dir=ROOT / "data/fred")
            hist = [values[k] for k in sorted(values)]
            base_src = fz.get("baselines") if fz else None
            baselines = base_src or {
                "naive_last": hist[-1],
                "mean_4wk": float(sum(hist[-4:]) / 4),
            }
            competing = (
                "<p class='competing'>Competing models on this question, frozen on the same terms: "
                + " &middot; ".join(
                    f"<strong>{esc(name.replace('_', '-'))}</strong> {disp['value'](v)}"
                    for name, v in baselines.items()
                )
                + " <span class='muted'>(on the backtest, naive-last currently beats the driver "
                "model — each resolution scores them all)</span></p>"
            )

        sections += f"""
<section class="metric">
<p class="topic">{esc(disp['topic'])}</p>
<h2>{esc(question)}</h2>
<div class="answer">
  <span class="big">{disp['value'](p['p50'])}</span>
  <span class="band">80% band: {disp['value'](p['p10'])} to {disp['value'](p['p90'])}</span>
  {chip}
</div>
<p class="when">{esc(disp['value_note'])} &middot; official answer
{esc(rel.date.isoformat())} (8:30 AM ET), {days} day(s) from now.</p>
{competing}
<details><summary>The model — the driver tree, every assumption colored by how much to trust it</summary>
{tree_html(model)}
{model_details_html(model, disp['value'])}
{derivation_html(ROOT / "models" / m)}
<p class="muted">Resolution rule: <a href="{REPO}/blob/main/models/{m}/resolution.md">what officially settles this number</a>.
Disagree with an assumption? <a href="{REPO}">Edit one YAML value and open a PR</a> — CI comments your
exact forecast delta, and your track record accrues under your GitHub handle.</p>
</details>

<details><summary>Track record — how past forecasts scored</summary>
{track_record_html(m)}
</details>
</section>"""

    # --- fermi gallery: decompositions without a referee, never scored ---
    fermi_cards = ""
    for tree in sorted((ROOT / "models/fermi").glob("*/tree.yaml")):
        doc = yaml.safe_load(tree.read_text(encoding="utf-8"))
        model = build_model(doc)
        p = run(model, seed=SEED).percentiles()
        kind = doc.get("format", "count")
        vf = lambda v, k=kind: humanize(v, k)  # noqa: E731
        fermi_cards += f"""
<section class="metric fermi">
<p class="topic">Fermi gallery</p>
<h2>{esc(doc.get('question', doc['name']))}</h2>
<div class="answer">
  <span class="big">{vf(p['p50'])}</span>
  <span class="band">80% band: {vf(p['p10'])} to {vf(p['p90'])}</span>
  <span class="chip">unscored &mdash; no referee</span>
</div>
<p class="when">Computable, not observable: no official number will ever settle this, so it is
never frozen or scored. It exists to be inspected and forked.</p>
<details><summary>The decomposition — driver tree and how it was derived</summary>
{tree_html(model)}
{model_details_html(model, vf)}
{derivation_html(tree.parent)}
<p class="muted"><a href="{REPO}/blob/main/models/fermi/{esc(tree.parent.name)}/tree.yaml">tree.yaml</a>
&mdash; disagree with a guess? Fork it.</p>
</details>
</section>"""

    # resolution feed (all metrics, newest first)
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
    feed_section = (
        f"<h2 class='feedhead'>Resolved: what we said vs. what happened</h2>{feed}" if feed else ""
    )

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Waterline — open calibrated forecasts</title>
<link rel="stylesheet" href="style.css"></head><body>
<header><h1>Waterline</h1>
<p class="tag">Public forecasts of official numbers, frozen before each release and scored after.
Every forecast is an open model you can inspect and fork — not a black box.
<a href="{REPO}">GitHub</a>.</p></header>

{sections}

{feed_section}

{fermi_cards}

<footer>
<p><strong>How this works.</strong> Each forecast is a driver model in a public git repo. Days before
the official release the forecast is frozen (a server-timestamped GitHub Release — the proof it predates
the print). When the official number lands, the forecast is scored, the miss is attributed to specific
assumptions, and the calibration ledger grows. Everything is automated; the models are deliberately
transparent about what is a guess (red), what is benchmarked to history (amber), and what is bound to
data (green).</p>
<p>Built {esc(today.isoformat())} by the loop. Primary public sources only (BLS; DOL via FRED).
Not investment advice; Waterline forecasts official statistics, never prices.</p>
</footer>
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
  max-width:820px; margin:2rem auto; padding:0 1rem; }
h1 { margin-bottom:0 } .tag { color:var(--muted) }
a { color:var(--accent) }
section.metric { border:1px solid var(--line); border-radius:10px; padding:1.2rem 1.5rem; margin:1.6rem 0 }
.topic { text-transform:uppercase; letter-spacing:.08em; font-size:.75rem; color:var(--muted); margin:0 }
section.metric h2 { margin:.2rem 0 .8rem; font-size:1.25rem }
.answer { display:flex; align-items:baseline; gap:1rem; flex-wrap:wrap }
.big { font-size:2.4rem; font-weight:700; font-variant-numeric:tabular-nums }
.band { color:var(--muted); font-variant-numeric:tabular-nums }
.chip { font-size:.78rem; border:1px solid var(--line); border-radius:999px; padding:.15rem .7rem;
  color:var(--muted); background:#f7fafc }
.chip.frozen { border-color:#1e8449; color:#1e8449 }
.when { color:var(--muted); font-size:.9rem }
.competing { font-size:.9rem }
section.fermi { background:#fbfaf7 }
.dtree, .dtree ul { list-style:none; margin:.2rem 0; padding-left:0 }
.dtree ul { border-left:1px solid var(--line); margin-left:.45rem; padding-left:1.1rem }
.dtree li { margin:.3rem 0 }
.derivation { border-top:1px dashed var(--line); margin-top:1rem; padding-top:.4rem; font-size:.93rem }
.derivation h2 { border:none; font-size:1.05rem; margin-top:.6rem }
details { margin:.8rem 0; border-top:1px solid var(--line); padding-top:.6rem }
summary { cursor:pointer; color:var(--accent); font-size:.95rem }
details[open] summary { margin-bottom:.6rem }
h4 { margin:1rem 0 .3rem }
.feedhead { border-bottom:1px solid var(--line); padding-bottom:.3rem; margin-top:2.4rem }
table { border-collapse:collapse; width:100%; font-size:.9rem }
th,td { text-align:left; padding:.32rem .55rem; border-bottom:1px solid var(--line); vertical-align:top }
td.num { font-variant-numeric:tabular-nums; white-space:nowrap }
td.prov { color:var(--muted); font-size:.78rem }
.badge { color:#fff; border-radius:3px; padding:.1rem .45rem; font-size:.72rem; white-space:nowrap }
.card { border:1px solid var(--line); border-radius:8px; padding:.2rem 1.2rem; margin:1.2rem 0; background:#f7fafc }
.readout table { margin:.5rem 0 }
.tornado { margin:.6rem 0 }
.trow { display:flex; align-items:center; gap:.6rem; margin:.25rem 0 }
.tlabel { width:190px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap }
.tbar { flex:1; background:#eef2f7; border-radius:3px; height:14px }
.tfill { background:var(--accent); height:14px; border-radius:3px }
.tval { width:72px; text-align:right; font-variant-numeric:tabular-nums; font-size:.85rem }
.muted { color:var(--muted) }
footer { margin-top:3rem; border-top:1px solid var(--line); color:var(--muted); font-size:.88rem }
"""

if __name__ == "__main__":
    sys.exit(main())
