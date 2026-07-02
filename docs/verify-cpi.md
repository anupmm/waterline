# CPI data-source verify pass

*Researched 2026-07-02 by the research agent (web search only; bls.gov and
clevelandfed.org block automated fetches with 403, so several items are
cross-checked via FRED/secondary sources and flagged for human re-verification).*

## 1. BLS Public Data API v2

- **Endpoint:** `POST https://api.bls.gov/publicAPI/v2/timeseries/data/` with JSON body:
  `{"seriesid": [...], "startyear": "2020", "endyear": "2026", "registrationkey": "...", "calculations": true}`
- **Rate limits:** unregistered 25 queries/day, 25 series/query, 10 yrs; registered key
  (free, https://data.bls.gov/registrationEngine/) 500 queries/day, 50 series/query, 20 yrs.
- **The API returns index levels.** With `"calculations": true` it adds `pct_changes`
  (1/3/6/12-month). Decision: **compute m/m % ourselves from first-published SA levels**
  to control rounding; keep the API's calculated field as a cross-check.
- **Series IDs (SA, US city average):**

  | Node | Series |
  |---|---|
  | All items | `CUSR0000SA0` |
  | Core (ex food & energy) | `CUSR0000SA0L1E` |
  | Shelter | `CUSR0000SAH1` |
  | Rent of primary residence | `CUSR0000SEHA` |
  | Owners' equivalent rent | `CUSR0000SEHC` |
  | Energy | `CUSR0000SA0E` |
  | Gasoline (all types) | `CUSR0000SETB01` |
  | Food | `CUSR0000SAF1` ⚠ |
  | Used cars and trucks | `CUSR0000SETA02` ⚠ |
  | Services less rent of shelter ("supercore") | `CUSR0000SASL2RS` |
  | All items less shelter (sanity series) | `CUSR0000SA0L2` |

  ⚠ = confirm suffix against `https://download.bls.gov/pub/time.series/cu/cu.series`
  from a browser before the ingestion code hardcodes it. (FRED mirrors matched all
  IDs the agent could cross-check.)

## 2. Release calendar

- Official: https://www.bls.gov/schedule/news_release/cpi.htm — 8:30 AM ET.
- Remaining 2026 (provisional): Jul 14, Aug 12, Sep 11, Oct 14, Nov 10, Dec 10.
- **Dates have slipped twice in 2026 already** (shutdowns). Freeze logic must re-check
  the schedule page at T−7 and T−3 rather than trusting the annual calendar.

## 3. Component weights (relative importance)

- https://www.bls.gov/cpi/tables/relative-importance/ — updated annually from December
  expenditure data. Monthly drift trackable via news-release Table 1
  (https://www.bls.gov/news.release/cpi.t01.htm).

## 4. Cleveland Fed inflation nowcast (benchmark #1)

- https://www.clevelandfed.org/indicators-and-data/inflation-nowcasting — daily
  (~10 AM ET) CPI + core CPI m/m and y/y nowcasts. Methodology apparently unchanged.
- ⚠ **Archived nowcast history download not confirmed** (403 on direct fetch). Human
  action: visit the page, look for the chart's data-download link. Fallback mirror:
  MacroMicro republishes the series.

## 5. Kalshi CPI markets (benchmark #2)

- Active 2026 series: `KXCPI` (headline m/m thresholds), `KXCPICORE`, `KXCPIYOY`,
  `KXCPICOREYOY`. Tickers have been renamed before — resolve the live ticker per
  event, don't hardcode.
- **Public read API, no auth:** `https://external-api.kalshi.com/trade-api/v2`
  (`/markets`, `/events/{ticker}`, `/series/{ticker}`). Docs: docs.kalshi.com.
- ⚠ Check ToS on republishing market data before quoting prices on the site.

## 6. Surprises vs. an early-2026 baseline (all load-bearing for us)

1. **October 2025 CPI was never published** (government shutdown; collection suspended).
   There is a permanent hole: no valid Oct→Nov 2025 m/m. Backtests must special-case
   this window; naive level-diff code will produce garbage there.
2. **2026 releases have slipped twice** (Jan print moved Feb 11→13; further disruption
   Feb–Apr). Hence the T−7/T−3 schedule re-check above.
3. **Shelter/OER quality artifacts Oct 2025–Apr 2026** from carry-forward imputation of
   the missing housing panel (April 2026 rent m/m computed off an atypical panel
   rotation). Widen error bands / flag this window in the shelter node's backtest.
4. **Collection footprint reduced** (Lincoln NE, Provo UT, Buffalo NY suspended 2025).
   BLS says <0.01pp national impact; matters only if we ever use regional detail.
5. BLS API v2 itself: no evidence of endpoint/auth/limit changes through mid-2026.

## Open items for the owner (5 minutes in a browser)

- [ ] Confirm `CUSR0000SAF1` (food) and `CUSR0000SETA02` (used cars) in the cu.series file.
- [ ] Find the Cleveland Fed nowcast history download (CSV?) for backtesting.
- [ ] Skim Kalshi data ToS re: quoting prices in readouts.
