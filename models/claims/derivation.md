## How this model was derived

**Why the model is deliberately humble.** Weekly initial claims is a
mean-reverting series with no free intra-week drivers — the state-level and
seasonal-factor information that would genuinely improve on persistence is
either lagged or licensed. Pretending structure that isn't there would be
model theater. So:

    claims = base_4wk × drift

- `base_4wk` — median of the last four published weeks. Data-bound; moves
  every week, which is why this model is re-authored at each freeze rather
  than committed long-lived (the frozen JSON records the exact inputs used).
- `drift` — the trailing year's empirical distribution of how far a week
  lands from its own trailing base (actual ÷ base ratios, p10/p90). It
  absorbs both genuine labor-market movement and seasonal-adjustment noise
  without claiming to distinguish them.

**What the backtest says, unspun.** Over 26 weeks, the model's MAE (~9.9k)
LOSES to naive-last (~7.9k), and interval coverage runs under nominal (69%
vs 80%). Both numbers are published. This metric exists in the ledger for
loop cadence — a live resolution every Thursday — not for alpha.

**Why the baselines are shown as competing models.** naive-last and the
4-week mean are frozen alongside the driver model on identical terms and
scored at every resolution. A platform whose point is honest scoring does
not hide a rival that beats it; it puts the rival on the leaderboard and
invites someone to beat both. That is also the template for how contributor
models will appear on any question: named forecasters, same freeze, same
referee.
