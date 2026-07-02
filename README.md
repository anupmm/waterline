# Waterline

**An open, calibrated driver-model ledger.** Forecasts as versioned, inspectable
driver trees: assumptions typed by epistemic status (guess / benchmarked /
data-bound), frozen before the print via GitHub Releases, resolved against
official data, with error attributed to specific assumptions and calibration
accumulating publicly. First metric: US core CPI m/m.

See `keel-v2.md` (vision brief) in the parent planning folder; this repo is its
implementation. Not investment advice; no price or return forecasts — official
statistics and reported fundamentals only.

## Layout

```
src/waterline/     the runtime: YAML driver tree -> seeded Monte Carlo -> p10/p50/p90 + tornado
models/cpi/        the CPI model (tree.yaml, resolution.md)
registry/          shared assumption registry
forecasts/         frozen forecasts (written by CI at freeze)
actuals/           resolved actuals + attribution (written by CI on print day)
readouts/          auto-drafted resolution narratives
docs/              verify-pass reports and design notes
```

## Develop

```sh
uv sync
uv run pytest
```

Copy `.env.example` to `.env` and add your BLS API key (free registration:
https://data.bls.gov/registrationEngine/). Never commit `.env`.

## Runtime in 10 lines

```python
from waterline import load_model, run, sensitivity

m = load_model("models/cpi/tree.yaml", "registry/assumptions.yaml")
res = run(m, n_draws=10_000, seed=42)
print(res.percentiles())        # {'p10': ..., 'p50': ..., 'p90': ...}
for row in sensitivity(m):      # tornado, widest spread first
    print(row.node, row.spread)
```

Determinism contract: same model + same seed is bit-identical; each input node
has its own RNG stream keyed by node name, so unrelated edits never reshuffle
another node's draws.
