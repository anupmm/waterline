"""Daily loop entry point (run by GitHub Actions; runnable locally).

    uv run python scripts/loop.py                     # decide + act for today (ET)
    uv run python scripts/loop.py --today 2026-08-09  # pretend it's another day
    uv run python scripts/loop.py --simulate 2026-05  # acceptance dry-run:
        author the model as-of the month before, freeze, resolve against the
        real print, write everything to .simulate/<period>/ (gitignored)

Emits `frozen=` / `resolved=` lines to $GITHUB_OUTPUT when set, so the
workflow can cut freeze releases and skip empty commits.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from waterline.cpi_author import author_assumptions, fit_weights, write_model_files
from waterline.ingest.bls import SERIES, fetch_levels, load_env_key, mom
from waterline.loop import decide, freeze_cpi, resolve_cpi


def gh_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")


def prev_period(p: str) -> str:
    y, m = int(p[:4]), int(p[5:])
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def simulate(period: str) -> int:
    """Freeze->resolve on a historical month, end to end, no lookahead."""
    scratch = ROOT / ".simulate" / period
    scratch.mkdir(parents=True, exist_ok=True)

    key = load_env_key(ROOT)
    levels = fetch_levels(list(SERIES.values()), 2018, 2026, key=key, cache_dir=ROOT / "data/bls")
    moms = {name: mom(levels[sid]) for name, sid in SERIES.items()}

    as_of = prev_period(period)
    fit = fit_weights(moms, as_of=as_of)
    assumptions = author_assumptions(moms, as_of=as_of)
    write_model_files(scratch, fit, assumptions, SERIES, f"simulated-as-of-{as_of}")

    y, m = int(period[:4]), int(period[5:])
    fake_release = (date(y, m, 1) + timedelta(days=42)).replace(day=12)  # ~mid next month
    forecast = freeze_cpi(
        ROOT, period, out_root=scratch, model_root=scratch, release_date=fake_release
    )
    print(f"frozen {period}: {forecast['percentiles']}")

    result = resolve_cpi(ROOT, period, out_root=scratch, refresh=False)
    if result is None:
        print(f"ERROR: {period} has no published print to resolve against")
        return 1
    print(f"resolved {period}: actual {result['actual']:+.3f}, error {result['error_pp']:+.3f}pp")
    print(f"\n--- readout ---\n")
    print((scratch / f"readouts/cpi-{period}.md").read_text(encoding="utf-8"))
    print(f"artifacts in {scratch}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--today", default=None, help="override today's date (YYYY-MM-DD)")
    parser.add_argument("--simulate", default=None, metavar="PERIOD", help="dry-run a historical month")
    args = parser.parse_args()

    if args.simulate:
        return simulate(args.simulate)

    if args.today:
        today = date.fromisoformat(args.today)
    else:
        today = datetime.now(ZoneInfo("America/New_York")).date()
    actions = decide(ROOT, today)
    if not actions:
        print(f"{today}: nothing to do")
        return 0

    frozen, resolved = [], []
    for action, period in actions:
        if action == "freeze":
            f = freeze_cpi(ROOT, period)
            frozen.append(period)
            print(f"froze {period}: {f['percentiles']} (release {f['release_date']})")
        elif action == "resolve":
            r = resolve_cpi(ROOT, period)
            if r is None:
                print(f"{period}: print not available yet, will retry")
            else:
                resolved.append(period)
                print(f"resolved {period}: actual {r['actual']:+.3f}, error {r['error_pp']:+.3f}pp")

    if frozen:
        gh_output("frozen", ",".join(frozen))
    if resolved:
        gh_output("resolved", ",".join(resolved))
    return 0


if __name__ == "__main__":
    sys.exit(main())
