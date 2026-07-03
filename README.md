# Waterline

**An open, calibrated driver-model ledger.** Forecasts as versioned, inspectable
driver trees: assumptions typed by epistemic status (guess / benchmarked /
data-bound), frozen before each official release via server-timestamped GitHub
Releases, resolved against primary public data, with error attributed to named
assumptions and calibration accumulating publicly.

**Live site:** https://anupmm.github.io/waterline/

Not investment advice. Waterline forecasts official statistics and reported
fundamentals — never prices or returns.

## What's on the ledger

| Question | Cadence | Referee | Status |
|---|---|---|---|
| US core CPI, m/m | monthly | BLS release (API) | committed model; freezes T−3 |
| US initial jobless claims, weekly | weekly | DOL release via FRED | auto-authored at freeze (T−1); frozen alongside two named baseline models, all scored on the same terms |
| Fermi gallery (golf balls in a 747; US jeans spend) | — | none | **unscored** — computable, not observable; exists to be inspected and forked |

The loop runs daily in CI: freeze inside each metric's window → resolve on
print day → write the attribution readout → rebuild calibration → redeploy the
site. It is designed to run unattended.

## The model contract

Every model is a directory:

- **`tree.yaml`** — the machine-checked model: a YAML driver DAG that compiles
  and runs (Monte Carlo, 10k seeded draws → p10/p50/p90 + tornado).
- **`derivation.md`** — the author's reasoning: why this decomposition, where
  each number comes from, what was considered and rejected, sanity checks.
- **`resolution.md`** (scored metrics only) — the rule fixed at creation for
  which published number settles the forecast.

PRs that change one should update the others. The site renders the tree
diagram directly from the DAG on every build, so the picture can never drift
from the model.

## Contributing a disagreement

Edit one value in a `tree.yaml` or `registry/assumptions.yaml` and open a PR.
CI comments your exact forecast delta (seeded per-node RNG streams make the
delta attributable to your edit alone), and your track record accrues under
your GitHub handle. Broken model edits fail CI.

## Layout

```
src/waterline/     runtime (distributions, DAG, Monte Carlo, sensitivity, delta),
                   ingestion (BLS, FRED), authoring, the loop
models/            one directory per model (tree.yaml + derivation.md [+ resolution.md])
registry/          shared assumption registry (CPI)
forecasts/         frozen forecast JSON, written by CI at freeze
actuals/           resolved actuals + per-assumption attribution
readouts/          auto-drafted resolution narratives
calibration/       per-metric ledgers, rebuilt idempotently
docs/              verify-pass reports and walk-forward backtests (honest: the
                   claims model currently loses to naive-last, and says so)
scripts/           loop, authoring, backtests, site generator, PR delta
.github/workflows  loop (daily 14:10 UTC), site (Pages), pr (tests + delta comment)
```

## Develop

```sh
uv sync
uv run pytest
uv run waterline run models/cpi/tree.yaml --registry registry/assumptions.yaml
uv run python scripts/loop.py --today 2026-07-08   # dry-drive the loop
uv run python scripts/build_site.py                # render site/ locally
```

Copy `.env.example` to `.env` for a BLS API key (free; optional — unregistered
tier suffices for development). CI uses repo secrets.

Determinism contract: same model + same seed is bit-identical; each input node
has its own RNG stream keyed by node name, so unrelated edits never reshuffle
another node's draws.

## Operational notes

- If a Pages deploy fails with "try again later", re-dispatch the site
  workflow; never re-run the failed job (duplicate-artifact trap). The
  workflow retries once in-run, and the daily loop self-heals the site.
- BLS release dates slip (twice in 2026); the CPI schedule file is provisional
  and re-checked near each freeze. October 2025 CPI was never published — void
  periods resolve as absent, never bridged.

## Vision

This repo is the implementation of a larger brief — a versioned ledger for an
organization's bets ("git for an organization's bets, worn like a shared
document, kept true by an AI staff"). The public instance exercises the loop
on free public referees; the object model is built to point at planning
decisions, where the stakes are native. See `keel.md` / `keel-v2.md` in the
owner's planning folder.
