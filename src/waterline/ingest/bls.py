"""BLS Public Data API v2 client.

Fetches index levels, caches raw responses to disk (committed, so backtests
are reproducible and re-runs don't burn the rate limit), and computes m/m
percent changes with gap handling — October 2025 was never published (shutdown),
so the Oct and Nov 2025 m/m values do not exist and must not be fabricated.

Unregistered tier: 25 queries/day, 25 series/query, 10 years/query.
With a key (BLS_API_KEY in .env): 500/day, 50 series, 20 years.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import requests

API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

# Series used by the CPI model. SA, US city average.
SERIES = {
    "core_cpi": "CUSR0000SA0L1E",       # all items less food and energy
    "shelter": "CUSR0000SAH1",
    "core_goods": "CUSR0000SACL1E",     # commodities less food & energy commodities [verify]
    "supercore": "CUSR0000SASL2RS",     # services less rent of shelter
}


def load_env_key(root: str | Path = ".") -> str | None:
    env = Path(root) / ".env"
    if not env.exists():
        return None
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("BLS_API_KEY=") and len(line) > len("BLS_API_KEY="):
            return line.split("=", 1)[1].strip()
    return None


def fetch_levels(
    series_ids: list[str],
    start_year: int,
    end_year: int,
    key: str | None = None,
    cache_dir: str | Path = "data/bls",
) -> dict[str, dict[str, float]]:
    """Return {series_id: {"YYYY-MM": index_level}}. Disk-cached by request."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    req_key = hashlib.sha256(
        json.dumps([sorted(series_ids), start_year, end_year]).encode()
    ).hexdigest()[:16]
    cache_file = cache_dir / f"levels_{start_year}_{end_year}_{req_key}.json"

    if cache_file.exists():
        raw = json.loads(cache_file.read_text(encoding="utf-8"))
    else:
        payload: dict = {
            "seriesid": series_ids,
            "startyear": str(start_year),
            "endyear": str(end_year),
        }
        if key:
            payload["registrationkey"] = key
        resp = requests.post(API_URL, json=payload, timeout=60)
        resp.raise_for_status()
        raw = resp.json()
        if raw.get("status") != "REQUEST_SUCCEEDED":
            raise RuntimeError(f"BLS API error: {raw.get('status')} {raw.get('message')}")
        raw["_retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        cache_file.write_text(json.dumps(raw, indent=1), encoding="utf-8")

    out: dict[str, dict[str, float]] = {}
    for s in raw["Results"]["series"]:
        levels: dict[str, float] = {}
        for point in s["data"]:
            period = point["period"]
            if not period.startswith("M") or period == "M13":  # skip annual averages
                continue
            try:
                value = float(point["value"])
            except ValueError:
                continue  # unpublished month (e.g. Oct 2025 shutdown) arrives as "-"
            levels[f"{point['year']}-{period[1:]}"] = value
        out[s["seriesID"]] = dict(sorted(levels.items()))
    missing = set(series_ids) - set(out)
    if missing:
        raise RuntimeError(f"BLS returned no data for series: {sorted(missing)}")
    return out


def mom(levels: dict[str, float]) -> dict[str, float]:
    """Month-over-month % change; a month only gets a value when the previous
    calendar month exists (no bridging across the Oct-2025 hole)."""
    out: dict[str, float] = {}
    for period, value in levels.items():
        year, month = int(period[:4]), int(period[5:])
        prev = f"{year - 1}-12" if month == 1 else f"{year}-{month - 1:02d}"
        if prev in levels:
            out[period] = 100.0 * (value / levels[prev] - 1.0)
    return out
