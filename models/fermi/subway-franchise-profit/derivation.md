## How this model was derived

**Why this belongs in the Fermi gallery.** There is no public official number
that resolves "typical Subway franchise owner profit." Subway cautions against
future-profit projections, and the useful data lives in franchise disclosures,
private store P&Ls, and owner anecdotes. That makes this an inspectable
operating model, not a scored forecast.

**Sales engine.** The model starts from:

    annual sales = orders per day x average ticket x open days

StartupNation's June 18, 2025 article says a typical Subway store grosses about
$420,000 per year, and quotes an owner claiming the average US store was a
little under $8,000 per week in the older forum discussion. The traffic and
ticket ranges are calibrated so the model's middle case lands near that scale,
while still exposing the real driver: a low-traffic store and a good site are
different businesses.

**Cost structure.** The article gives two useful anchors:

- Subway royalty: 8% of gross sales.
- Advertising fee: 4.5% of gross sales.

It also quotes a three-store owner's P&L example:

| line item | cited level |
|---|---:|
| Food | 33% |
| Labor | 22% |
| Rent | 9% |
| Subway fees | 12.5% |
| Utilities / misc | 8.5% |
| Profit | 15% |

The model uses ranges around those line items rather than a single fixed
margin. Food and paper, labor, occupancy, and utilities all vary materially by
site, wage market, hours, spoilage, theft, local competition, and owner
discipline.

**Owner labor adjustment.** A store can show cash flow because the owner is
working unpaid shifts. That is real cash in the bank, but economically it is
not the same as passive business profit. The final output subtracts an
`owner_labor_value_usd` assumption so the model answers a stricter question:
what is left after giving the owner's time a value?

**What would improve this model.**

- A current Subway FDD, especially Item 7 and any Item 19 financial-performance
  representation.
- Actual P&Ls from several stores, separated by mall / strip center /
  non-traditional location.
- Local wage, rent, and delivery-app mix assumptions.
- A separate debt-service module for financed buildout or acquisition.

Source used: StartupNation, "What Is the Average Income of a Subway Restaurant
Franchise Owner?", updated June 18, 2025.
