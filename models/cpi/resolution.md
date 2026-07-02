# Resolution rule — US core CPI, month-over-month

*Written at model creation, per keel-v2 §4/§7. This rule is fixed for the life of
the model; changing it requires a new PR and applies only to future periods.*

**Metric.** Seasonally adjusted month-over-month percent change of CPI-U, all items
less food and energy (BLS series `CUSR0000SA0L1E`), for the reference month.

**Resolving value.** Computed from the **first-published** SA index levels in the
BLS CPI news release for the reference month: `100 * (I_m / I_{m-1} - 1)`, carried
at three decimals for calibration math. The BLS-published one-decimal figure is
recorded alongside as the headline value quoted in readouts. Later revisions and
annual seasonal-factor updates do **not** change a resolved period.

**Source of truth.** The BLS API v2 response for `CUSR0000SA0L1E` retrieved on
release day (schedule: https://www.bls.gov/schedule/news_release/cpi.htm, 8:30 AM ET),
cross-checked against the news release text. If the API and the release text ever
disagree, the news release governs.

**Freeze.** The forecast for a reference month is frozen at **T−3 calendar days**
before the scheduled release, via a GitHub Release tagged `freeze/cpi-<period>`.
The scheduled date is re-verified against the BLS schedule page at T−7 and T−3
(2026 has already seen two slippages). If the release date moves after freezing,
the freeze stands — earlier information, honestly disadvantaged.

**Edge cases.**
- If BLS does not publish the reference month at all (as happened October 2025),
  the period resolves **void**: no calibration entry, noted in the readout.
- If BLS publishes a partial or imputation-flagged print, it still resolves
  normally — the referee is the official statistic, warts and all — but the
  readout must note the flag.
