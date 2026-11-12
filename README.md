# Market-Intelligence

A market intelligence tool for Dubai real estate, built with Imza Premium Properties. It turns
the Dubai Land Department's public sales records into four things an agency can use:

| Part | Question it answers | Output in `data/shared/` |
|---|---|---|
| 1. Data preparation | What sold, where, for how much? (cleaned and checked) | `monthly_sales.csv`, `quality_report.json` |
| 2. Trend analysis | Is each area's market rising, stable or declining right now? | `market_trends.csv` |
| 3. Forecasting | How many sales and what price per m2 next quarter? | `forecasts.csv`, `forecast_manifest.json` |
| 4. Agent allocation | Where should the agents work next quarter? | `allocation.csv`, `allocation_manifest.json` |

Each part reads the files of the parts before it. Areas are DLD's official area names, and
off-plan and ready sales are always kept apart.

## Interactive dashboard

The Streamlit interface provides Overview, Data Explorer, Market Trends, Forecasts,
Agent Allocation and Evidence pages. Market Trends replays the fuzzy rules for any segment
(inputs, membership degrees, rules fired), and Evidence shows each part's test results
against its baselines, read from `reports/`. Quarters are shown as months (Oct–Dec 2026), and areas
also carry the name people use (Marsa Dubai is shown as Dubai Marina). When the
forecast quarter has already started, Forecasts shows the sales recorded so far beside each forecast. It reads the existing shared outputs; an official
portal connection is not needed to browse the supplied analysis.

```bash
python -m pip install -r requirements-dashboard.txt
python -m streamlit run app.py
```

For the recorded core dependency versions, install `requirements-lock.txt` before
`requirements-dashboard.txt`. On Windows, use `.venv\Scripts\python.exe` instead
of `python` after creating the virtual environment described below.

Filter areas, registration type, property types and months, download the current
selection, inspect held-out forecasts, or click **Generate custom plan** to adjust
team size, deal rate, market share, commission rates and planning objective. The same form has a
what-if: change off-plan or ready sales by a percentage to test a shock the forecast cannot see.
Custom plans run only on submission, persist in the current browser session, and
can be downloaded with their assumptions. They use disposable temporary output
folders and never replace `data/shared/` or the committed reports. This is the
existing allocation model, including its whole-agent constraint rounding; the UI
shows effective limits for the selected team size.

The interface displays the source cutoff, unsupported forecasts, provisional
inputs and placeholder business assumptions. It verifies input/output manifest
hashes and refuses an inconsistent snapshot. After updating the underlying data,
rerun Parts 2–4 together before refreshing the app. The dashboard does not download
new official exports, retrain forecasts on page load, or allocate marketing budgets.

Dashboard implementation: `app.py` contains the views; `src/dashboard/data.py`
loads and verifies shared results; `src/dashboard/planning.py` isolates custom
allocation runs. `tests/test_dashboard.py` covers filters, source consistency,
shared-file preservation, navigation and form submission. Install the dashboard
requirements to run its Streamlit interaction tests; core-only installations skip
those UI checks. No hosted deployment or user authentication is configured.

Run everything (Python 3.11 or newer, see Install below):

```bash
python -m pip install -r requirements.txt
python -m src.trend_analysis.run                            # Part 2, seconds
python -m src.forecasting.run --config src/forecasting/config.json   # Part 3, seconds
python -m src.allocation.run                                # Part 4, about 2 minutes
python -m unittest discover -s tests                        # all tests
```

Things to know before using the results:

- The data is the Data Dubai export of 28 Oct 2026. The latest full quarter is 2026Q3, and it is
  provisional because DLD still corrects recent records.
- Trend labels (Part 2) describe the market now. They do not predict next year's prices.
- Forecasts (Part 3) beat simply repeating last quarter by only a small margin. Use them as a guide.
- Part 4's team size, commission rates, deals per agent and market share are placeholders. Replace
  them with Imza's own numbers before using the plan.
- To refresh the data, follow "How to update the data" below.

Each part's section below explains its method, results and limits.

## Member 1: Data Collection & Preparation

Cleans official Dubai Land Department (DLD) transaction exports into the files the other parts use.
Downloading is manual: the [DLD portal](https://dubailand.gov.ae/en/open-data/real-estate-data/) needs a
CAPTCHA and older years come from [Data Dubai](https://data.dubai/en/l/470061). Raw exports and the
large transaction-level file are kept out of Git. Full detail on sources, accepted formats, cleaning
rules and outputs is in [docs/data-preparation.md](docs/data-preparation.md), and the source
investigation is in [docs/official-sources.md](docs/official-sources.md).

### Install

Requires Python 3.11 or newer. Run from this repository's root:

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows, instead of activating, use the virtual environment interpreter directly:

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

To get the exact versions the shared outputs were made with, install `requirements-lock.txt` instead.

### Prepare official data

Keep original downloads in `data/raw/` (ZIP files work directly). Supply all parts of an export
in one run, so duplicates across parts are removed:

```bash
python -m src.dld_data.pipeline --input data/raw/part1.csv data/raw/part2.csv --output-dir data/processed/run1
```

On Windows replace `python` with `.venv\Scripts\python.exe`. Inputs are never modified, and a
folder that already has these output files is refused. An optional `--url` downloads a known official CSV link
(see the docs).

### Cleaning in short

- Accepts the Data Dubai, DLD native and DLD display column layouts and maps them to one format.
- Rejects rows with a missing ID, area or property type, an impossible or future date, a year outside
  1900-2100 (this catches old mortgage rows with Hijri years, 1416-1422), or a missing, zero,
  negative or malformed price.
- Removes exact duplicates, then drops every row whose transaction ID appears with different values.
- Drops sales under 10,000 AED (`--min-sale-price` changes this).
- Keeps rows under 10 m2 but leaves their price per m2 empty (tiny areas give absurd values).
- Never estimates missing prices or locations. Every removal is counted in `quality_report.json`.

### Outputs for teammates

- `transactions_clean.csv`: one row per transaction, all transaction groups, with area, property and
  unit type, price, size, price per m2, off-plan/ready and DLD procedure. Not in Git (~220 MB).
- `monthly_sales.csv` (in `data/shared/`): sales only, grouped by area, property type, unit type,
  off-plan/ready and month, with count, total and median price, median size and median price per m2.
  Off-plan and ready are never mixed in one median, and months with no sales are not invented.
- `quality_report.json` (in `data/shared/`): row counts for every rule above, input file hashes,
  date range and pandas version. The date range does not prove the export covers the whole market.

### Validation

```bash
python -m unittest discover -s tests -v
```

Part 1's tests use artificial records. Real-export results are below.

## Real-data validation

Tested against full real Data Dubai exports (https://data.dubai/en/l/470061) and on a DLD native export.
The shared files in `data/shared/` come from the export downloaded on 28 Oct 2026 (two CSV parts,
`transactions_2026-10-28_19-12-20_0001.csv` and `_0002.csv`; SHA-256 in `quality_report.json`).

Command:
```bash
python -m src.dld_data.pipeline --input data/raw/transactions_2026-10-28_19-12-20_0001.csv data/raw/transactions_2026-10-28_19-12-20_0002.csv --output-dir data/processed/run-2026-10-28
```

Results:
- `input_rows`: 1,809,472
- `invalid_rows`: 4 (impossible dates, years 1416-1422)
- `implausible_year_rows`: 4, `future_date_rows`: 0 (subsets of invalid rows)
- `duplicate_rows`: 0
- `conflicting_id_rows`: 0
- `low_price_sales_rows`: 417
- `small_area_rows`: 2,788 (kept, no price per m2)
- `output_rows`: 1,809,051
- `sales_transactions`: 1,383,409
- `monthly_sales_rows`: 59,008
- Part 1's 27 unit tests pass on pandas 2.3.3 and 3.1.0.
- The earlier 27 Oct export (1,808,832 rows) gave the same monthly counts and medians for 99.96% of groups
  up to Sep 2026; DLD corrects a few older records between exports (1-30 a month).

Notes:
- The 2026 slowdown is real: existing/ready sales fell from ~6.5k to under 4k a month since March 2026, and off-plan fell from ~13k to ~7.5-8.5k (an independent second export matched).
- Data before ~2019 is sparse; model from 2019/2020 onwards.
- October 2026 is partial (ends 27 Oct 2026).

## Area names people use

DLD's areas are land names: Marsa Dubai is Dubai Marina and Al Barsha South Fourth is Jumeirah
Village Circle. `data/shared/area_names.csv` gives each area the master project that holds most of
its sales since 2020, taken from the export's own `master_project_en` column, so nothing is guessed:

```bash
python -m src.dld_data.area_names --input data/raw/export_1.csv data/raw/export_2.csv
```

`common_name` is the top master project when it has at least half of the area's unit and villa
sales, or the projects with at least a fifth each when together they reach half. Otherwise it is
blank and the dashboard shows the DLD name alone. Of 65 areas with a master project, 58 get a name.
The analysis itself still uses DLD's names; the common name is only shown beside them.

Some official names are not the ones agents say (Al Thanyah Fifth comes out as "DMCC Master
Community", which people call JLT). Put corrections in `data/area_name_overrides.csv`
(`area,common_name`); they win over the data the next time the command or the update runs.

## How to update the data

Downloading is manual, because the DLD portal needs a CAPTCHA. Everything after that is one command:

1. Download a new export from DLD or Data Dubai and put the file(s) in `data/raw/`.
2. Run the update with all parts of the export:

```bash
python -m src.update --input data/raw/export_1.csv data/raw/export_2.csv
```

It cleans the export (Part 1), copies the new monthly sales and quality report to `data/shared/`,
refreshes the area names,
moves Part 3's forecast to the newest complete quarter, reruns Parts 2, 3 and 4 and checks that the
results belong together. Every model is refitted from scratch; nothing is carried over from the last
run. It takes about 5 minutes. If any step fails, the shared files, reports and configs are put back
as they were.

3. Run the tests, look at the dashboard, then commit `data/shared/`, `reports/` and
   `src/forecasting/config.json`.

Overlapping exports are fine, duplicates across files are removed. The dashboard's sidebar shows how
old the data is and warns once the forecast quarter is over. The parts can still be run one by one
with the commands at the top.

## Member 2: Market Trend Analysis

Labels every area's market as **Rising**, **Stable** or **Declining** each quarter, using a
fuzzy logic classifier. Input is `data/shared/monthly_sales.csv` from Part 1; output is
`data/shared/market_trends.csv` for Parts 3 and 4.

```bash
python -m src.trend_analysis.run                      # default settings
python -m src.trend_analysis.run --config my.json     # same keys as src/trend_analysis/config.json
```

It takes a few seconds and also writes the evaluation and figures to `reports/part2/`.
Design decisions and limitations are explained in `src/trend_analysis/NOTES.md`.

### Method

- **Segment** = area + off-plan/ready, per calendar quarter, from 2020Q1. Units and villas only
  (land and whole-building sales are a different market). Only complete quarters are used
  (the end date comes from `quality_report.json`); the latest one is marked provisional.
- **Inputs** (year on year): price change per m2, sales volume change, and volatility (spread of
  the last four quarter-on-quarter price changes). Price change is mix-adjusted: each property
  and unit type is compared with itself a year earlier, so a shift from flats to villas is not a
  price change.
- **Enough data:** at least 30 sales in the quarter and in the same quarter last year, and at least
  50% of sales in property types that can be compared. Otherwise `Insufficient data`.
- **Fuzzy classifier** (own numpy code, `fuzzy.py`): membership functions set from percentiles of the
  data, 8 weighted Mamdani rules, centroid defuzzification to a trend score from -1 to 1.
- **Baselines:** crisp price-only thresholds at the same crossover point, and k-means (k = 3).

### market_trends.csv

One row per segment and quarter that had sales in that quarter or the same quarter last year.
Percentages are fractions (0.05 = 5%).

| Column | Meaning |
|---|---|
| `area`, `registration_type`, `quarter` | Segment and quarter (`2026Q3`) |
| `sales_count`, `sales_count_prev_year` | Unit/villa sales this quarter and the same quarter last year |
| `price_change_yoy` | Mix-adjusted change in price per m2 vs the same quarter last year |
| `volume_change_yoy` | Change in number of sales vs the same quarter last year |
| `volatility` | Std of the last 4 quarter-on-quarter log price changes |
| `price_coverage` | Share of sales in property types compared with last year |
| `status` | `ok` or `insufficient_data` |
| `provisional` | True for the latest quarter (DLD may still correct records) |
| `trend_label` | Fuzzy label: Rising, Stable, Declining or Insufficient data |
| `trend_score` | -1 (declining) to 1 (rising) |
| `rising_degree`, `stable_degree`, `declining_degree` | Fuzzy membership of each label, 0 to 1 |
| `baseline_label`, `kmeans_label` | Labels from the comparison methods |

### Results (28 Oct 2026 export)

- 4,123 segment quarters, 1,729 with enough data, covering 89% of unit and villa sales.
- Fuzzy labels: 1,010 Stable, 646 Rising, 73 Declining. The share of Rising segments
  peaked near 60% in early 2024, was 37% in 2026Q1 and fell to 8% in 2026Q3 (the 2026 slowdown).
- Agreement with crisp rules 95% (Cohen's kappa 0.91); with k-means 33% (kappa -0.07): k-means
  groups segments by volume rather than direction, and changes a lot between seeds (72% +- 29%).
- Bootstrap (200 seeded refits of the membership functions): 98.8% +- 0.8% of labels unchanged.
- Sensitivity (one setting changed at a time): 92-99% of labels unchanged.
- **Forward check:** labels describe the current market; they do **not** predict next year.
  Correlation of trend score with the next year's price change is -0.01. Use them for "what is
  happening now", not as a forecast.

## Member 3: AI Forecasting

For every area (off-plan and ready separately), Part 3 forecasts next quarter's number of sales and a
price per m2. It compares three methods: repeating last quarter, repeating the same quarter last year,
and a Ridge regression trained on past quarters. The method for each target is picked on 2024 and then
tested on 2025Q1 to 2026Q3. Input is Part 1's `monthly_sales.csv` and `quality_report.json`; units and
villas only. The current output forecasts 2026Q4 from data up to 2026Q3.

Detailed rules, the method and the full evaluation (including the fallback check) are in
[src/forecasting/NOTES.md](src/forecasting/NOTES.md).

```bash
python -m src.forecasting.run --config src/forecasting/config.json
```

It takes a few seconds and also writes the evaluation and figures to `reports/part3/`. After a data
update, see step 6 of "How to update the data".

### Results (28 Oct 2026 export)

| Target | Method | Validation MAE | Test MAE | Test RMSE | Test count WAPE | Test rows |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Activity | Naive | 129.01 | 136.11 | 284.81 | 32.78% | 570 |
| Activity | Seasonal naive | 195.05 | 207.02 | 442.58 | 49.86% | 570 |
| Activity | Ridge alpha 10 | 124.42 | 133.25 | 283.89 | 32.09% | 570 |
| Price proxy | Naive | 1,247.24 | 1,091.72 | 1,721.24 | n/a | 436 |
| Price proxy | Seasonal naive | 2,549.55 | 2,226.87 | 3,227.98 | n/a | 436 |
| Price proxy | Ridge alpha 1 | 1,208.71 | 1,160.74 | 1,731.09 | n/a | 436 |

Activity errors are sales per quarter and price errors are AED per m2.
WAPE is `sum(abs(prediction - actual)) / sum(actual)` and is undefined when the
denominator is zero. It is an error measure, not an accuracy percentage.

- Ridge was picked for both targets on 2024. For sales it is slightly better than repeating last quarter
  on the test years (32.1% against 32.8% error). For price, repeating last quarter did a little better
  on the test, but Ridge stays because the choice was fixed before testing.
- Segments with too little history for the model but at least 4 supported quarters, including the
  current one, get a `fallback` (last quarter's value). Others are `insufficient_data` with blank values.
  Fallback was tested on a different set of segments (52% sales error), so it is not directly
  comparable with the 32% above. See [the Part 3 notes](src/forecasting/NOTES.md).
- Each forecast has a rough range (`range_low`, `range_high`) taken from past forecast errors pooled over
  all segments: −44% to +45% around a sales forecast, −10% to +9% around a price. It is meant to hold
  80% of the time; on the test, 74% of sales and 78% of prices landed inside. It is not a model-based
  prediction interval, and it is the same relative width for every segment.
- Big misses happen around project launches (Madinat Al Mataar Off-Plan, 2026Q2: 5,101 actual sales
  against 2,249 forecast).

### forecasts.csv

`data/shared/forecasts.csv` contains 396 long-form rows, two targets for each of
198 segments observed within the configured history. `forecast_manifest.json` in
the same directory records the source hashes, actual timestamp, cutoff, units,
selection policy, model settings, eligibility rules and limitations. Its CSV hash
allows consumers to check that the files belong together. The output schema is `1.0`.

| Field or status | Meaning |
| --- | --- |
| `area`, `registration_type`, `property_scope` | Exact DLD area, Ready or Off-Plan, and `Unit\|Villa` |
| `origin_quarter`, `forecast_quarter`, `horizon_quarters` | `2026Q3`, `2026Q4`, and 1 |
| `target`, `forecast_value`, `unit` | Target identifier, nullable numeric prediction, and its native unit |
| `model_id`, `selection_basis` | Actual method used and validation or fallback policy |
| `ok` | Validation-selected method with primary input/history support |
| `fallback` | Supported current-level naive forecast with at least four valid historical quarters |
| `insufficient_data` | Existing inputs fail history or price-support requirements |
| `missing_input` | Origin lacks three observed months or usable price inputs |
| `reason` | Explanation for an unavailable prediction or fallback |
| `history_quarters`, `last_actual` | Supported quarters since 2020 and supported origin actual, never a stale carried value |
| `price_coverage`, `provisional_input` | Origin price-support weight fraction, blank for activity, and boolean provisional flag |
| `range_low`, `range_high` | Rough 80% range from past errors; blank when the forecast is unavailable |
| `schema_version`, `run_id`, `data_cutoff_date` | Contract version, linked run identity and source cutoff |

The unique key is schema version, run ID, area, registration, property scope,
origin quarter, forecast quarter and target. Read schema version as a string.
Unavailable predictions have blank numeric values, never zero. Accept `ok` and
`fallback` numeric values while retaining the status. Do not replace blanks with
zero. Activity remains usable when price is unavailable for the same segment.
For this run, activity has 92 `ok`, 30 `fallback`, 4 `insufficient_data` and 72
`missing_input` rows. Price has 68 `ok`, 25 `fallback`, 33 `insufficient_data` and
72 `missing_input` rows. Historical fallback results are in [the Part 3 notes](src/forecasting/NOTES.md). They
remain sample-limited and do not guarantee performance for a particular segment.

### Files and checks

- `src/forecasting/`: source validation, quarterly panel, features, models,
  chronological evaluation, export CLI, figures and configuration.
- `tests/test_forecasting.py`: synthetic schema, calendar, leakage, train-only
  preprocessing, evaluation, missing-value, reproducibility and consumer checks.
- `reports/part3/predictions.csv` and `metrics.csv`: actuals, predictions, exclusion
  reasons, model comparisons and per-quarter errors.
- `reports/part3/evaluation.json`, `run_config.json` and `data_profile.json`:
  model selection, failures, coverage, source fingerprints and run settings.
- `reports/part3/actual_vs_forecast.png` and `baseline_comparison.png`: held-out
  evidence for both targets, including median-error and worst-error segments.

## Member 4: Intelligent Agent Allocation

Recommends how many of Imza's agents should work in each area and segment next quarter.
Input is Part 3's `forecasts.csv` and `forecast_manifest.json`, Part 2's `market_trends.csv`, Part 1's
`monthly_sales.csv` and Part 3's `reports/part3/predictions.csv`. Output is `data/shared/allocation.csv`.
Design decisions and limitations are explained in `src/allocation/NOTES.md`.

```bash
python -m src.allocation.run                                # plan, backtest and sensitivity, about 2 minutes
python -m src.allocation.run --skip-evaluation --agents 30 --output-dir plans/30-agents   # a few seconds
python -m src.allocation.run --skip-evaluation --current today.csv --max-moves 4 --output-dir plans/today
```

The default run writes the shared `data/shared/allocation.csv`. Any run whose settings differ from
`src/allocation/config.json` (flags such as `--agents`, `--current`, `--max-moves`, or another `--config`)
must name an `--output-dir`, so the shared file always holds the default plan.
`today.csv` has the columns `area`, `registration_type`, `agents`. Anything else is in
`src/allocation/config.json`. A Git checkout on Windows may convert line endings, so hashes here ignore them.

**The team size, deal rate, market share and commission rates in the config are placeholders, not
Imza's numbers.** Replace them before using the plan. Whether Imza wants commission or deal count
(`objective`) changes the plan most: only 1 of 20 agents stays in place.

### Method

- **Candidates:** segments with an `ok` or `fallback` activity forecast of at least 30 sales: 95 of 198.
  Blank forecasts are never treated as zero.
- **Value of x agents:** `deals(x) = ceiling * (1 - exp(-deals_per_agent * x / ceiling))`, with
  `ceiling = max_market_share * forecast sales`, times the typical deal value and commission rate.
  This gives diminishing returns.
- **Constraints:** every agent placed, at least 2 agents in an area in use, no area over 25% of the team,
  at most 8 areas, Off-Plan 30-70% of the team, optional limit on agents moved from today's plan.
- **Search:** simulated annealing with a final hill climb (own code, `search.py`). A mixed-integer
  program (scipy HiGHS) checks it independently, and the run keeps the better plan.
- **Evaluation:** walk-forward on real 2024-2026 sales. Choices frozen on 2024, reported on 2025Q1
  to 2026Q3. Forecast-error scenarios and trend weights did not win on 2024, so the plain forecast
  is used and trend labels are context only.

### Results (28 Oct 2026 export, 20 agents)

Share of the hindsight-best plan, mean of seven test quarters. Sales and prices are real, but the
response curve is assumed in both planning and scoring, so these are **not** measured commissions.

| Method | Share of best plan | Worst quarter | Meets constraints |
| --- | ---: | ---: | ---: |
| Optimiser with move limit of 4 (not selected) | 89.9% | 75.6% | 7 of 7 |
| Optimiser with Part 3 forecast (selected) | 86.8% | 75.7% | 7 of 7 |
| Optimiser with last quarter as forecast | 83.9% | 66.7% | 7 of 7 |
| Share of forecast value | 51.8% | 41.7% | 0 of 7 |
| Even split over biggest segments | 37.0% | 32.7% | 0 of 7 |
| Share of forecast sales | 36.1% | 32.5% | 0 of 7 |
| Share of last quarter sales | 36.0% | 31.5% | 0 of 7 |

- The optimiser beat the best rule in all seven test quarters (paired difference 35.0 +- 5.2 points,
  Wilcoxon p = 0.016). Most of that comes from valuing deals and modelling saturation: Part 3's
  forecast adds 2.9 +- 3.2 points over using last quarter.
- Over 10 seeds the selected method scores 86.6%, std 1.0 points between seeds and 8.8 between quarters.
- The move limit's higher score is not established (4 wins, 2 losses, 1 tie, p = 0.16).
- Annealing with hill climb is 0.28% +- 0.50% below the exact optimum (worst 2.30%, 10 seeds on 11
  quarters), and 0 on the 2026Q4 plan. It takes 0.38 s; the exact solver takes 0.02 s.
- With `objective = deals` the advantage disappears (99.4% against 99.2%).

Plan for 2026Q4: Business Bay Off-Plan 5, Marsa Dubai Off-Plan 3, Palm Jumeirah Off-Plan 2 and Ready 2,
Al Thanayah Fourth Ready 2, Wadi Al Safa 6 Ready 2, Al Yufrah 1 Off-Plan 2, Al Khairan First Off-Plan 2.
The first four stay chosen in 97-100% of replans under forecast error. The last four only in 37-67%,
so treat them as close calls.

### allocation.csv

One row per Part 3 segment, largest allocation first. `allocation_manifest.json` records the source
hashes, placeholder assumptions, policy and solver check.

| Column | Meaning |
| --- | --- |
| `area`, `registration_type`, `forecast_quarter` | Segment and quarter |
| `agents` | Recommended agents; 0 if not selected |
| `forecast_sales`, `forecast_status`, `price_status` | Part 3 forecast and its status; blank stays blank |
| `ticket_aed` | Typical deal value used for planning |
| `expected_deals`, `expected_commission_aed` | Expected result under the assumed response, not a promise |
| `next_agent_value_aed` | What one more agent would add |
| `selection_rate` | Share of replans under forecast error that still gave this segment an agent |
| `trend_label`, `trend_score` | Part 2 context for the origin quarter; not used in the decision |
| `note` | Allocated, not selected, or why the segment was not a candidate |

### Files and checks

- `src/allocation/`: `data.py` inputs, `model.py` value and scenarios, `search.py` constraints and solvers,
  `evaluate.py` backtest and sensitivity, `figures.py`, `run.py`, `config.json`, `NOTES.md`.
- `tests/test_allocation.py`: response, leakage, constraints, solvers against brute force, output contract.
- `reports/part4/`: `backtest.csv`, `backtest_summary.csv`, `evaluation.json`, `sensitivity.csv`,
  `repeated_runs.csv`, `convergence.csv`, `team_size.csv`, `allocation.png`, `backtest.png`,
  `convergence.png`, `team_size.png`.
