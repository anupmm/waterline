## How this model was derived

**Two ways to size a market.** Top-down: find an industry report ("US jeans
market ≈ $15–20B") and trust someone else's homework. Bottom-up (used here):
build it from population × behavior × price, so every disagreement is visible
and arguable. The top-down number then becomes a *sanity check* rather than
the answer.

**The chain:**

    revenue = (population × buyers_fraction × pairs_per_buyer) × avg_price

**Where each number comes from:**

- `us_population` = 335M — Census resident population. Benchmarked; the one
  input nobody argues with.
- `buyers_fraction` [0.45, 0.8] — what share of people buy *at least one* pair
  in a year. Includes children and denim-avoiders at the low end. A guess, and
  flagged as one.
- `pairs_per_buyer_per_year` [0.7, 2.0] — among buyers. Fashion-heavy buyers
  pull the mean above 1; durable-wear buyers push it toward one pair every
  couple of years. The widest honest range in the model.
- `avg_price_usd` [30, 70] — blended mass-market ($20–40) and premium ($80+)
  price points, weighted toward mass market by volume. Benchmarked loosely to
  retail observation.

**Sanity check.** Point estimates: 335M × 0.6 × 1.2 × $48 ≈ $11.6B — the model's
band ($5.5B–$21B) comfortably brackets the commonly cited $15–20B industry
figures, leaning lower because bottom-up misses some channels (workwear,
institutional).

**Unlike the golf balls, this question has a referee in principle** — Census
retail categories or industry reports could settle it annually. If someone
writes a resolution rule naming a source, this model graduates from the Fermi
gallery to a scored annual metric. That is the intended path for gallery
models that deserve it.
