# Solar VPPA Settlement & Basis Engine

[![CI](https://github.com/BallerBrahma/VPPA-Engine/actions/workflows/ci.yml/badge.svg)](https://github.com/BallerBrahma/VPPA-Engine/actions/workflows/ci.yml)

A library that settles virtual power purchase agreements for utility-scale solar
and quantifies the basis and shape risk buried in them.

## The question

A VPPA is priced against average forward power prices, but it settles against the
hours a solar project actually produces. Solar generates when solar suppresses
prices — so does a deal struck at a "fair" average price end up structurally
underwater once you settle it hour by hour?

In ERCOT West, yes, and by a widening margin.

## The finding

Holding the generation profile constant and varying only the year's prices, a
West Texas solar project's **capture rate fell from 160% in 2019 to 63% in 2025**
as ERCOT's installed solar grew from 2.6 GW to 29.9 GW. The correlation between
penetration and capture rate is **−0.911**.

![Capture rate vs ERCOT solar build-out](docs/capture_rate_decay.png)

In 2019 solar was scarce and midday *was* the system peak, so the asset earned a
60% premium over the average market price. By 2025 it captured barely three-fifths
of that average. Negative-price hours at HB_WEST rose from 33 to 341 a year.

**The 2019 endpoint is inflated, and the honest version of this chart says so.**
That 160% is mostly one event: August and September 2019 cleared at 196% and 198%
capture during ERCOT's record-low reserve margin, with 35 hours above $1,000/MWh
and 27.8% of the year's revenue arriving in 20 hours. Solar happened to be
generating through a scarcity crisis. Every other month that year sat near 100%.
So the 160% → 63% span mixes a real penetration effect with a rare scarcity
windfall at the start. The penetration effect survives on its own: from 2023 to
2025, with no comparable scarcity event, capture still fell 92.6% → 62.6%.

Settling the example contract against real 2024 prices:

| Metric | Value |
|---|---|
| Annual capture rate | 65.5% |
| Breakeven strike | **$19.20/MWh** |
| Contract strike | $34.50/MWh |

The project would need a strike of $19.20 to break even on its actual production
shape. At $34.50 the buyer is underwater by roughly $15/MWh — not because the
strike was above the average market price, but because it was above the price the
asset *captures*.

### Is the typical-year shortcut distorting this?

No, and it is worth checking rather than asserting. Re-running the example
contract against each year's *actual* NSRDB weather:

| Year | Capture (TMY) | Capture (actual) | Difference |
|---|---|---|---|
| 2023 | 92.6% | 92.3% | −0.33 pp |
| 2024 | 65.5% | 65.2% | −0.26 pp |
| 2025 | 62.6% | 61.2% | −1.48 pp |

TMY tracks actual weather to within 1.5 points and is consistently a little
optimistic. Note 2025 delivered 4.1% *more* generation than a typical year yet
captured a *lower* share of the average price — the extra sunlight arrived in
hours that were worth less, which is the thesis restated from the weather side.

## Basis: the risk a hub-settled deal leaves on the table

A hub-settled VPPA pays out against the hub, but the project sells at its own
node. That gap — basis — is unhedged. Three real ERCOT assets, three years,
settled against their own nodes:

| Project | Zone | Year | Capture (hub) | Capture (node) | Mean basis | **Cost of basis** | Neg-basis hrs |
|---|---|---|---|---|---|---|---|
| Lamesa (Dawson Co.) | West | 2023 | 94.2% | 94.1% | −$0.05 | −$0.07 | 29% |
| | | 2024 | 65.8% | 63.5% | +$1.52 | +$0.29 | 35% |
| | | 2025 | 63.0% | 47.6% | +$16.78 | +$2.78 | 7% |
| Noble (Denton Co.) | North | 2023 | 93.8% | 94.1% | −$0.62 | −$0.40 | 76% |
| | | 2024 | 74.9% | 75.9% | +$0.14 | +$0.37 | 61% |
| | | 2025 | 70.3% | 70.3% | −$2.46 | −$1.73 | 62% |
| Sun Valley (Hill Co.) | Central | 2023 | 94.2% | 94.2% | +$0.09 | +$0.07 | 23% |
| | | 2024 | 76.7% | 74.1% | −$0.46 | −$1.06 | 38% |
| | | 2025 | 70.8% | **34.4%** | −$5.22 | **−$13.79** | 57% |

Three things fall out of this:

**The decay is not local to one site.** Capture rate fell in every project and
every zone, 2023 → 2025: 94% → 63% (West), 94% → 70% (North), 94% → 71%
(Central). This is a market-wide repricing of solar hours, not an artifact of one
node.

**Generation-weighting usually moves basis against the project.** In 6 of 9
project-years, the generation-weighted cost of basis is worse than the simple
hourly mean — congestion bites hardest in the hours the plant is running. Lamesa
2025 is the cleanest illustration: its node averaged **+$16.78/MWh above** the hub
across all hours, but only **+$2.78/MWh** in the hours it actually generated. The
good basis accrues overnight, when the panels are dark. Noble is the exception,
running slightly *better* when generating.

**Basis risk is project-specific and can arrive suddenly.** Two of the three
projects carried negligible basis for three years. Sun Valley then lost
**$13.79/MWh** in 2025 — its node captured 34% of the average price while its hub
captured 71%. A separate cross-section of all 88 ERCOT solar nodes over a recent
31-day window found generation-weighted basis ranging from roughly zero to
**−$21.52/MWh**. Nothing about a hub-settled deal protects against that, and it
cannot be estimated from hub data alone.

## Scenarios

Stresses are applied to `settle()`'s *inputs*, never to its results, so a
scenario can never drift from what the engine would actually compute. Sun Valley
2025, settled at its node against a $32.00 strike:

| Scenario | Generation (MWh) | Capture rate | Breakeven | Cash to buyer |
|---|---|---|---|---|
| base | 496,969 | 34.4% | $15.61 | −$8.15M |
| P90 production | 452,384 | 34.4% | $15.61 | **−$7.42M** |
| price collapse (−30%) | 496,969 | 34.4% | $10.93 | −$10.47M |
| bad basis year (−$10/MWh) | 496,969 | −2.6% | $8.66 | −$11.60M |
| combined stress | 452,384 | −35.3% | $4.35 | −$12.51M |

Note the P90 row: a **worse** production year leaves the buyer **better off**.
The contract is underwater in every lit hour, so less production means less
volume to pay out on. P90 is a downside case for the *seller*, which is why
these are read per counterparty rather than collapsed into one "bad case"
number. Under a bad-basis year the capture rate goes negative outright — the
generation-weighted price the asset earns falls below zero while the market
average stays positive.

## Storage: what it would take to fix it

Pair each project with a 4-hour battery at roughly 25% of AC capacity, charging
only from its own output, and dispatch it optimally against 2025 nodal prices:

| Project | Capture rate | With storage | Uplift | Revenue uplift |
|---|---|---|---|---|
| Lamesa (West) | 47.6% | 71.8% | +24.3 pp | +$2.64M ($11.32/MWh) |
| Noble (North) | 70.3% | 97.9% | +27.7 pp | +$4.18M ($7.56/MWh) |
| Sun Valley (Central) | 34.4% | 72.6% | **+38.2 pp** | +$4.93M ($9.92/MWh) |

The fix is largest where the problem is worst: Sun Valley, the project with the
$13.79/MWh basis blowout, gains the most. That is the arc the whole exercise was
built to trace — the shape problem, its cost, and what undoing it is worth.

**Two caveats make these upper bounds, not forecasts:**

- **The dispatch has perfect foresight.** The LP optimises against the whole
  year's realised prices at once. A real operator dispatches against a forecast
  and will capture materially less. This is the single biggest reason to read
  these numbers as a ceiling.
- **No degradation, no cycling cost, no capex.** The optimiser cycles ~390–450
  times a year, above the ~365 many warranties assume, because nothing in the
  objective penalises a cycle. And this is *gross revenue uplift* — it says
  nothing about whether the battery pays for itself. A 62 MW / 248 MWh system is
  a nine-figure capital decision that this model does not attempt.

Round-trip losses are real in the figures: delivered volume is strictly below
generation (16,627 MWh lost for Sun Valley), so every dollar of uplift comes
from better price capture rather than from more energy.

## Architecture

Five layers, one direction of flow, with two thin front ends on top:

```
ingest/   pull prices (gridstatus), generation (PySAM), capacity (EIA)
store/    immutable Parquet cache, partitioned by source / key / year
model/    typed domain objects; all validation lives here
engine/   pure functions: settle, capture_rate, basis, scenarios, dispatch
report/   monthly statements and charts
          |
          +-- cli.py       `vppa settle ...`
          +-- api/         FastAPI, consumed by the Next.js app in web/
```

The engine layer holds every number the project reports and does no I/O, so it
is testable from small in-memory fixtures with no network. Both front ends are
deliberately thin: they fetch, align and display, but compute nothing, so the
web UI cannot drift away from what the CLI prints. The API reuses the same
pydantic `Contract` the CLI loads, so an uploaded or edited deal is validated
by exactly the same rules.

## Contract terms that actually bind

Every field in a contract YAML changes a number somewhere; none are decorative:

- **`escalation_pct_yr`** compounds the strike annually from the first year of
  the term, so a 2.5% escalator on a $32.00 strike settles 2024 at $32.80 and
  2025 at $33.62.
- **`counterparty_view`** flips the reported sign. `settle()` always returns
  `cash_to_buyer` as the single canonical convention; a seller-view contract
  reports the negation rather than quietly showing the buyer's P&L.
- **`term`** is checked against the settled year. Settling outside it is allowed,
  because "what would this deal have done in 2019?" is a fair question, but the
  CLI says out loud that it is a counterfactual.
- **`negative_price_floor`** caps how far a negative index price can push the
  settlement, while the raw price is preserved unclipped for analysis.
- **`storage`** is optional; when present the CLI and UI report the overlay.

## How VPPA settlement works

A VPPA is a financial swap layered on top of physical market sales. The generator
sells its output into the market at the local price. Separately, buyer and seller
exchange the difference between that price and a fixed strike:

    cash_to_buyer = (index_price − strike) × generation_mwh

When the market clears above the strike the buyer receives the difference; below
it, the buyer pays. The volume is whatever the sun delivers that hour, never a
flat block — which is precisely why the shape matters and why an average price is
the wrong thing to price against.

## Assumptions

These are choices, not facts, and they move the numbers:

- **Typical weather by default, actual weather available.** Generation defaults
  to a TMY (typical meteorological year) file, which is deliberate for the decay
  analysis: holding weather fixed means a change in capture rate can only come
  from prices. Pass `--weather actual` (or `weather="actual"`) to use that year's
  real NSRDB weather instead, which is what a specific year's P&L needs. The two
  are cached separately and never substituted for one another.
- **Inverter loading ratio 1.30**, set explicitly. PVWatts otherwise defaults to
  1.2 regardless of the project, and the ratio changes capture rate materially by
  clipping midday peaks.
- **Fixed-tilt, open rack.** Many real ERCOT solar plants use single-axis
  tracking, which shifts output toward the evening and would raise capture rate.
- **Prevailing-time alignment.** NSRDB reports weather in fixed standard time;
  ERCOT settles on prevailing local time with DST. Generation is mapped onto the
  region's real DST-observing zone so hours line up with market hours year-round.
- **Calendar reconciliation.** A TMY year has no Feb 29 and cannot represent DST's
  doubled fall-back hour, so price hours without a generation counterpart are
  dropped explicitly (25 hours in a leap year) rather than silently misaligned.
- **Strikes are illustrative.** The contracts in `contracts/` are written on real
  assets with real locations and capacities from EIA-860, but the strike prices
  are made up. They are not real deals.

## Limitations

- The TMY default is an approximation, but a measured one. Re-running the example
  contract on actual NSRDB weather moves capture rate by 0.33 pp (2023), 0.26 pp
  (2024) and 1.48 pp (2025), always slightly *lower* than TMY suggests. The decay
  finding is not a TMY artifact, but per-year figures on the default basis are
  optimistic by up to about 1.5 points.
- 2021 breaks the decay trend (97.6%, rebounding to 108% in 2022). That is Winter
  Storm Uri: the year's average price was $142.66/MWh, distorted by a handful of
  hours at the $9,000 cap. The denominator is doing that, not the thesis.
- Capture rate is computed against day-ahead hub prices. A project settling
  real-time, or at its own node, faces a different number.
- No curtailment modelling. Real projects are curtailed during the same
  oversupplied hours this analysis prices at or below zero, so realized volumes
  would be lower than modelled. The storage overlay is therefore credited with
  absorbing energy that a real plant might simply have curtailed more cheaply.
- The battery LP assumes perfect price foresight and charges only from the
  project's own output. It carries no degradation, cycling cost or capex, so
  its uplift is an upper bound on what a real asset would earn.
- Nodal price history comes from a commercial API (gridstatus.io); ERCOT's free
  archive covers only hubs and load zones, plus a ~31-day rolling window of nodal
  prices.
- The 2019 capture rate (160%) is a scarcity artifact as much as a penetration
  one — see the note under the headline. Read the 2023–2025 decline as the
  cleaner measure of the shape effect.
- Capture rate is sensitive to a handful of extreme hours in any scarcity year,
  so single-year comparisons across ERCOT's price spikes should be treated with
  care. Nothing here winsorises or caps prices.
- One ISO. Everything here is ERCOT.

## Reproducing

```bash
uv sync --extra dev
cp .env.example .env        # then add your NREL, gridstatus.io and EIA keys
uv run pytest               # 84 tests, no network required
uv run vppa settle contracts/example_ercot_west.yaml --year 2024
uv run vppa settle contracts/lamesa_west.yaml --year 2025 --weather actual
```

For the web interface, run the API and the front end together:

```bash
uv run uvicorn vppa.api:app --reload --port 8000    # http://localhost:8000/docs
cd web && npm install && npm run dev                # http://localhost:3000
```

The test suite is deliberately offline and deterministic: every number it checks
comes from a small hand-built fixture. Network-backed behaviour is verified by
one-off runs against the real APIs, not in CI.

## Design

See [solar-vppa-engine-design.md](solar-vppa-engine-design.md) for the full
architecture, data sources, known traps, and build phases.
