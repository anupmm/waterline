## How this model was derived

**The question behind the question.** "How many golf balls fit in a 747" is really
"how big is a 747 inside, and how well do spheres pack." Two decompositions were
considered:

- *Seat-count approach* — balls per seat volume × number of seats. Rejected: it
  double-counts badly (aisles, galleys, cargo) and every term is a guess.
- *Volume approach* (used) — total interior volume, discounted for structure,
  discounted for sphere packing, divided by ball volume. Each factor is
  independently estimable and two of the four are benchmarkable.

**The chain:**

    golf_balls = (interior_volume × usable_fraction × packing_efficiency) / ball_volume

**Where each number comes from:**

- `interior_volume_m3` [700, 1100] — public 747-400 specs put the pressurized
  volume (passenger cabin + cargo holds) around 900–1000 m³; the range is wide
  because "interior" is ambiguous (strip the seats or not?). Benchmarked.
- `usable_fraction` [0.55, 0.85] — the honest guess in the model: how much of
  that volume isn't lost to seats, galleys, lavatories, crew rest, structure.
  Nobody has data; the tornado shows this guess dominates the answer, which is
  exactly what the red badge is for.
- `packing_efficiency` [0.58, 0.68] — benchmarked to physics: randomly poured
  equal spheres settle at ~0.64 (random close packing); a perfect lattice would
  reach 0.74 but nobody is hand-placing 10 million balls. The range brackets
  loose-to-settled pours.
- `ball_volume_m3` = 4.07e-5 — regulation golf ball diameter is 42.67 mm;
  volume = 4/3·π·r³. The one number in the model that is simply true.

**Sanity check.** Point estimates: 950 × 0.7 × 0.63 ≈ 419 m³ of ball volume,
÷ 4.07e-5 ≈ 10.3M — inside our 80% band and consistent with the commonly quoted
"about ten million" answer, which is reassuring but *not* a resolution: nobody
will ever count. That is why this model is unscored.

**If you fork this:** the highest-leverage disagreement is `usable_fraction` —
it carries most of the spread. An empty freighter variant would justify 0.85+;
a fully fitted passenger cabin argues for 0.5.
