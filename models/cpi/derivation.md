## How this model was derived

**Why three components.** Core CPI is an index over hundreds of items, but its
monthly movement decomposes well into shelter (the heavyweight), core services
excluding shelter ("supercore"), and core goods. BLS publishes all three as
seasonally adjusted series, so each driver is *observable* — meaning at
resolution we can say which one missed, not just that the total did.

**Why the weights are fitted, not copied.** BLS publishes official relative-
importance weights, but the page blocks automated retrieval and the weights
drift monthly. Instead the weights come from least-squares reconstruction of
core CPI m/m from the three component series over the trailing 48 months —
with fit quality (R², residual) committed alongside. If the decomposition ever
stops reconstructing core CPI honestly (residual > 0.05pp), authoring fails
loudly rather than shipping a dishonest tree. Current fit: R² ≈ 0.87.
The fitted shelter weight (~0.52) runs above the official relative importance
(~0.45) — collinearity between components moves credit around; the provenance
records this openly.

**The residual node.** The first backtest covered only 58% at a nominal 80%
interval — the tree was overconfident because summing three sampled components
ignored the ~0.045pp the reconstruction cannot explain. That measured residual
is now an explicit input node. This was a correction of a dishonest omission,
not a tuning pass: coverage moved to 83% with the point forecast unchanged.
The tornado ranks this node first — the model's largest admitted uncertainty
is what its own structure can't see.

**The assumptions are deliberately naive.** Each component's range is the
trailing-12-month empirical p10/p90 — pure history, no judgment. The
walk-forward backtest (12 prints) shows this already beats naive-last and
trailing-6m baselines on MAE. The intended upgrade path is not a cleverer
formula; it is the news-analyst bot (and human contributors) proposing
informed assumption updates via PR, each scored at the next print.

**Known data caveats** (docs/verify-cpi.md): October 2025 was never published
(shutdown) — a permanent hole handled as void; shelter carries imputation
artifacts from Oct 2025–Apr 2026, and the April 2026 backtest miss lands
exactly on that flagged window.
