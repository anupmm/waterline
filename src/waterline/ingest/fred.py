"""FRED keyless CSV ingestion.

fredgraph.csv requires no API key and serves official series mirrored by the
St. Louis Fed. Used for weekly initial jobless claims (ICSA, seasonally
adjusted, dated by week-ending Saturday). Truth per the resolution rule is
the DOL news release; FRED is the retrieval mechanism.
"""

from __future__ import annotations

import time
from pathlib import Path

import requests

CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
ICSA = "ICSA"


def fetch_series(
    series: str,
    cache_dir: str | Path = "data/fred",
    refresh: bool = False,
) -> dict[str, float]:
    """Return {date: value} (dates ISO, weekly series dated by week-ending
    Saturday... FRED dates ICSA by week-ending date). Disk-cached; refresh
    re-fetches and overwrites."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{series}.csv"

    if refresh or not cache_file.exists():
        resp = requests.get(
            CSV_URL.format(series=series),
            timeout=60,
            headers={"User-Agent": "waterline (github.com/anupmm/waterline)"},
        )
        resp.raise_for_status()
        text = resp.text
        if not text.startswith("observation_date") and series not in text.splitlines()[0]:
            raise RuntimeError(f"unexpected FRED CSV header: {text.splitlines()[0]!r}")
        stamped = f"# retrieved {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n{text}"
        cache_file.write_text(stamped, encoding="utf-8")

    out: dict[str, float] = {}
    for line in cache_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or line.startswith("observation_date") or "," not in line:
            continue
        date_s, val_s = line.split(",", 1)
        if val_s.strip() in (".", ""):
            continue  # FRED's missing-value marker
        out[date_s.strip()] = float(val_s)
    return dict(sorted(out.items()))
