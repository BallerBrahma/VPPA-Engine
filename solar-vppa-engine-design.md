# Solar VPPA Settlement & Basis Engine — Design

A library that settles virtual power purchase agreements for utility-scale solar
and quantifies the basis and shape risk buried in them.

**Thesis to prove:** solar generates when solar suppresses prices, so a project's
realized revenue per MWh falls faster than average market prices do. A VPPA
priced against average forwards can be structurally underwater once settled
against the hours the asset actually produces.

---

## 1. Architecture

Five layers, each independently testable. Data flows one direction only.

```
┌─────────────────────────────────────────────────────────┐
│ ingest/     Pull raw data from external sources          │
│             gridstatus (prices) · PySAM (generation)     │
│             EIA (nearby capacity)                        │
└────────────────────────┬────────────────────────────────┘
                         │  writes immutable Parquet
┌────────────────────────▼────────────────────────────────┐
│ store/      Local Parquet cache, partitioned by          │
│             source / iso / year. Never mutated.          │
└────────────────────────┬────────────────────────────────┘
                         │  loads + aligns to one UTC index
┌────────────────────────▼────────────────────────────────┐
│ model/      Typed domain objects                         │
│             Contract · GenerationProfile · PriceSeries   │
│             Validation lives here, not in the engine.    │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│ engine/     Pure functions. No I/O, no network.          │
│             settle() · capture_rate() · basis()          │
│             breakeven_strike() · scenarios()             │
└────────────────────────┬────────────────────────────────┘
                         │  returns DataFrames
┌────────────────────────▼────────────────────────────────┐
│ report/     Monthly statements, charts, CLI, Streamlit   │
└─────────────────────────────────────────────────────────┘
```

**Why this shape.** The engine layer is where the intellectual content lives, and
keeping it free of I/O means it is fast, deterministic, and trivially unit
testable. Every number the tool reports should be reproducible from a small
in-memory fixture with no network access. Reviewers notice this.

### Repo layout

```
solar-vppa/
├── README.md                    # the finding, not the code
├── pyproject.toml
├── contracts/
│   └── example_ercot_west.yaml  # contract definitions as config
├── data/                        # gitignored Parquet cache
│   ├── prices/
│   └── generation/
├── src/vppa/
│   ├── ingest/
│   │   ├── prices.py            # gridstatus wrappers + caching
│   │   ├── generation.py        # PySAM PVWatts runner
│   │   └── penetration.py       # EIA-860 nearby solar capacity
│   ├── store.py                 # read/write Parquet, cache keys
│   ├── model.py                 # pydantic models
│   ├── engine/
│   │   ├── settlement.py
│   │   ├── metrics.py           # capture rate, basis, breakeven
│   │   └── scenarios.py
│   ├── report/
│   │   ├── statement.py         # monthly settlement statement
│   │   └── charts.py
│   └── cli.py
├── notebooks/                   # exploration only, not the product
└── tests/
    └── fixtures/                # tiny hand-built price/gen series
```

### The contract as config

Contracts are data, not code. One YAML file per deal keeps the engine generic
and makes scenario runs cheap.

```yaml
name: ercot_west_solar_150mw
counterparty_view: buyer          # buyer | seller
strike_usd_mwh: 34.50
contract_mw: 150
term: {start: 2023-01-01, end: 2025-12-31}
settlement_index: hub             # hub | node
hub: ERCOT_HB_WEST
node: WESTSOLAR_ALL               # settlement point where output is sold
negative_price_floor: 0.0         # null = no floor
escalation_pct_yr: 0.0
project:
  lat: 31.85
  lon: -102.37
  dc_capacity_mw: 195             # ILR 1.30
  tilt_deg: 25
  azimuth_deg: 180
  losses_pct: 14
```

### Core settlement contract (the one function that matters)

```python
def settle(
    generation_mwh: pd.Series,    # UTC-indexed, hourly
    index_price: pd.Series,       # UTC-indexed, hourly, same index
    strike: float,
    floor: float | None = None,
) -> pd.DataFrame:
    """Returns hourly frame: index_price, generation, unit_diff, cash_to_buyer."""
```

Everything else — capture rate, basis, breakeven, scenarios — is a
transformation of that frame or of its inputs. Resist adding a second settlement
path; one function, exercised many ways.

---

## 2. Data sources

### Prices — `gridstatus`

Open-source Python library, no account needed, pulls directly from CAISO, ERCOT,
PJM, MISO, SPP, NYISO, ISO-NE, IESO, AESO and the EIA. Covers day-ahead and
real-time LMPs, load, fuel mix, ancillary prices, and interconnection queues.

```python
from gridstatus import Ercot
ercot = Ercot()
da = ercot.get_lmp_by_settlement_point("2024-06-01")
```

There is also `gridstatusio`, a client for their hosted API, which returns
normalized data across ISOs but requires a key. Start with the open-source
library; move to hosted only if raw ISO quirks eat too much time.

**What to pull:** day-ahead hourly LMP at both the project settlement point and
the zonal hub, for at least three consecutive years. Real-time only if you later
model a project that settles RT.

### Generation — NREL PySAM (PVWatts)

`pip install nrel-pysam`. The PVWatts module takes lat/long, DC capacity, tilt,
azimuth, array type, and losses, and returns 8,760 hourly AC output.

Set the **inverter loading ratio** deliberately (1.25–1.35 is typical for
utility-scale). It clips midday peaks and flattens the shoulders, which changes
capture rate by a meaningful margin. Document the value you chose.

### Weather — NREL NSRDB

PySAM defaults to a TMY (typical meteorological year) file. **This is the single
biggest correctness trap in the project:** TMY is a synthetic average year, so
pairing it with actual 2024 prices means your cloudy hours and your price spikes
are uncorrelated. Two acceptable resolutions, and you must state which you used:

1. Accept it, and treat results as "typical production against actual prices."
   Fine for basis and shape analysis, wrong for a specific year's P&L.
2. Pull actual-year NSRDB data (free API key from NREL's developer portal) and
   run PVWatts against real weather for each contract year. More work, much
   stronger claim.

Do (1) for phase 1, (2) before you call it finished.

### Solar penetration — EIA API v2 / Form EIA-860

Free API key. Gives operating solar capacity by plant with location and
commercial operation date. Aggregate capacity within a radius of your project
(or within the ISO zone) by year to build the penetration series that explains
your capture rate decay chart.

### Benchmarks — LBNL "Utility-Scale Solar" annual report

Published capture-rate and PPA-price series to sanity-check your outputs
against. If your capture rate is 40% or 110%, this is where you find out you
have a bug.

### Cost assumptions (only if you add a pro forma later) — NREL ATB

---

## 3. Tech stack

| Layer | Choice | Why |
|---|---|---|
| Python | 3.11+ | PySAM and gridstatus both current |
| Env / deps | `uv` | fast, lockfile, one tool |
| Dataframes | pandas | ecosystem fit; dataset is small enough |
| Storage | Parquet via pyarrow | columnar, compressed, cached locally |
| Ad hoc queries | DuckDB | SQL directly over Parquet, no server |
| Validation | pydantic v2 | contract YAML → typed objects, fails loud |
| Prices | gridstatus | see above |
| Generation | nrel-pysam | see above |
| Charts | matplotlib (static) + plotly (interactive) | matplotlib for README figures |
| CLI | typer | `vppa settle contracts/x.yaml --year 2024` |
| API | FastAPI | reuses the pydantic contract models directly |
| UI (phase 3) | Next.js + TypeScript | replaced Streamlit, which was too rigid |
| Tests | pytest | fixtures with hand-computed expected values |
| Lint / format | ruff | one tool, zero config |

**Deliberately not included:** Airflow, Postgres, Docker, Kubernetes, dbt, a
message queue. This is a batch analytical library over a few hundred megabytes
of Parquet. Adding orchestration would signal that you reach for infrastructure
before you need it, which is the opposite of the signal you want.

---

## 4. Known traps

**Timezones.** Store everything in UTC internally, convert only at display.
ERCOT reports in Central, PJM in Eastern Prevailing Time. DST creates a
duplicated hour in fall and a missing hour in spring; a naive join silently
drops or doubles those hours and quietly corrupts annual totals.

**Interval conventions.** Some ISO feeds are interval-beginning, some
interval-ending. Off-by-one-hour alignment between generation and price is the
most common bug in this class of tool, and it does not throw an error — it just
makes your capture rate wrong by a few percent.

**Settlement granularity.** ERCOT real-time settles in 15-minute intervals while
day-ahead is hourly. If you use RT, aggregate explicitly and say how.

**Units.** MW is power, MWh is energy. PVWatts returns kW by default. Pick MWh
everywhere internally and convert once, at ingest.

**Leap years.** 8,784 hours, not 8,760. Never hardcode.

**Negative prices.** Do not clip them. They are a central result, not bad data.

---

## 5. Build phases

**Phase 1 — hub settlement, one project, one year.**
Ingest, generation profile, `settle()`, monthly statement, capture rate,
breakeven strike. Ship this. It is complete and defensible on its own.

**Phase 2 — node settlement and basis.**
Add the node price series, compute node-minus-hub basis, negative-basis hours,
cost of basis in $/MWh. Extend to three projects in different zones and three
years. Produce the capture-rate-decay-vs-penetration chart. This is where the
findings are.

**Phase 3 — scenarios and interface.**
P90 production, bad basis year, price collapse. Streamlit front end.

**Phase 4 — storage overlay.**
Reuse the battery dispatch LP: shift output out of the saturated midday into the
evening peak, and report the capture rate uplift and the settlement impact. This
closes the arc — problem, cost, fix.

---

## 6. README structure (write this first, fill it in last)

1. The question, in two sentences.
2. Headline finding with the one best chart.
3. How settlement works, briefly, for readers who don't know VPPAs.
4. Assumptions, stated plainly (TMY vs actual weather, ILR, settlement point).
5. Limitations, stated more plainly than you want to.
6. How to reproduce.

Reviewers read this far more carefully than they read the code.
