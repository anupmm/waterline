# Resolution rule — US weekly initial jobless claims (SA)

*Fixed at model creation; changes apply only to future periods.*

**Metric.** Seasonally adjusted initial claims for unemployment insurance for a
reference week (ending Saturday), as published in the Department of Labor's
weekly UI claims news release (typically the following Thursday, 8:30 AM ET).

**Period id.** The week-ending Saturday date, ISO format (e.g. `2026-07-04`).

**Resolving value.** The **first-published** SA initial-claims figure for the
reference week. Truth is the DOL news release; the retrieval mechanism is the
FRED `ICSA` series (a St. Louis Fed mirror of the DOL figure), fetched on or
after release day. Later revisions — which happen nearly every week — do not
change a resolved period. If FRED and the DOL release text ever disagree, the
DOL release governs.

**Freeze.** T−1 day before the nominal release (Wednesday), via a GitHub
Release tagged `freeze/claims-<period>`. The model is auto-authored at freeze
from the latest published data (trailing base + drift distribution); the
frozen JSON records every input. Holiday-shifted releases resolve whenever the
figure appears — the loop retries daily.

**Void.** If DOL never publishes a reference week, the period resolves void:
no calibration entry, noted in the readout.
