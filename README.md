# Market-Intelligence
Private Project for University

## Member 1: Data Collection & Preparation

Prepare official Dubai Land Department (DLD) transaction exports for teammates'
forecasting and market analysis. This component does not implement prediction,
agent recommendations, or marketing allocation.

### Official sources and scope

The primary manual source is [DLD Real Estate Data](https://dubailand.gov.ae/en/open-data/real-estate-data/).
Its **Transactions** tab offers a CSV export. Select English, the required date
range and filters, complete the site's CAPTCHA, search, then use **Download as CSV**.
The current interface restricts dates to the current year and directs previous-year
requests to [Data Dubai's transaction catalogue](https://data.dubai/en/l/470061).
Check the portal's current license and attribution terms before redistribution.
Record the date range and filters you selected; no pipeline can infer missing
export parts or whether an export covers the whole market.

Automatic cleaning and preparation are implemented. **Unattended discovery and
collection from the current portal are not implemented.** DLD's CAPTCHA requires
a browser interaction. Data Dubai returns a Request Rejected page to this cloud
workspace; its legacy API denies unauthenticated requests. No security controls
are bypassed. An optional downloader accepts an already known public official
HTTPS CSV URL; a catalogue page or browser-local `blob:` URL is not such a URL.
See [source investigation](docs/official-sources.md) for observed access results.

Real-export validation is done (see Real-data validation below): the pipeline was run on a full Data Dubai export (1.8M transactions) and on a DLD native export. Raw exports and the large transaction-level file are not stored in Git; only the prepared monthly sales summary and quality report are shared, in data/shared/. Unit tests use artificial records labelled as test data.

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

### Prepare official data

Keep original official downloads in `data/raw/`. ZIP inputs are supported directly;
there is no need to extract them, cut sample rows, or upload data into chat.

```bash
python -m src.dld_data.pipeline --input data/raw/dld_export.csv --output-dir data/processed/run1
# Or a ZIP containing one or more official CSV parts:
python -m src.dld_data.pipeline --input data/raw/dld_export.zip --output-dir data/processed/run2
# Supply ALL relevant parts in the same invocation for cross-part deduplication:
python -m src.dld_data.pipeline --input data/raw/part1.csv data/raw/part2.csv --output-dir data/processed/run3
```

On Windows replace `python` with `.venv\Scripts\python.exe` in these commands.
Files must already be available on the machine running the command. If a portal
export contains two parts, supplying only part 2 produces a partial dataset.

For an independently verified, publicly accessible direct official CSV URL:

```bash
python -m src.dld_data.pipeline --url "$DLD_CSV_URL" --input data/raw/download.csv --output-dir data/processed/download-run
```

`--url` requires exactly one new `.csv` destination. TLS verification remains
enabled, downloads are limited to 1 GiB, and access errors/HTML responses fail
clearly. This is not a registered API client and does not handle CAPTCHA.

Inputs are never modified. Existing output filenames are refused; choose a new
output directory for each run. ZIP files are read without extracting paths;
CSV members must total at most 2 GiB per archive. Only the nine relevant fields
are loaded, reducing memory for wide exports. All selected records are still
combined in RAM for global deduplication: this is not an out-of-core pipeline,
and full 550 MB exports have not been benchmarked. Datasets are ignored by Git.

### Accepted input schemas

Inputs are UTF-8 (including BOM), comma-separated English CSVs. Headers are
case insensitive with surrounding whitespace ignored. These explicit schemas
map into a single internal representation:

| Meaning | Data Dubai / Dubai Pulse | DLD native export keys | DLD English display headers |
| --- | --- | --- | --- |
| Transaction ID (required) | transaction_id | TRANSACTION_NUMBER | Transaction Number |
| Transaction date (required) | instance_date | INSTANCE_DATE | Transaction Date |
| Area (required) | area_name_en | AREA_EN | Area |
| Property type (required) | property_type_en | PROP_TYPE_EN | Property Type |
| Consideration in AED (required) | actual_worth | TRANS_VALUE | Amount |
| Unit/subtype (optional) | property_sub_type_en | PROP_SB_TYPE_EN | Property Sub Type |
| Transaction group (optional) | trans_group_en | GROUP_EN | Transaction Type |
| Area in m2 (optional) | procedure_area | PROCEDURE_AREA | not confirmed |
| Off-plan / ready (optional) | reg_type_en | IS_OFFPLAN_EN | not confirmed |
| Procedure (optional) | procedure_name_en | PROCEDURE_EN | not confirmed |

Native keys are confirmed by DLD's `getExportHeader` and Transactions grid in
its public `scripts/publicData.js`. The display headers are from its English
Transactions table. The Data Dubai and DLD native schemas were checked against real exports; the display-header schema was not. An unrecognized, ambiguous, duplicate-header or
Arabic-only schema fails with an error rather than guessing columns. Different
recognized schemas can be supplied as separate files in the same run.

### Cleaning rules

- Trim labels, collapse repeated whitespace, and recognize blank/null/none/N/A/NaN
  markers as missing (case insensitive). Preserve official area/type spelling.
- Accept DD-MM-YYYY, DD/MM/YYYY and YYYY-MM-DD dates. Also accept ISO-like
  YYYY-MM-DDTHH:MM:SS (optional fractional seconds) and YYYY-MM-DD HH:MM:SS;
  retain the calendar date. Timezones and other date conventions are not inferred.
- Accept positive, finite numeric prices with optional correctly grouped thousands
  separators. Reject missing, zero, negative, malformed and nonnumeric prices.
- Reject impossible dates or missing required ID, area or property type values.
  Leave optional labels empty; never estimate prices or locations.
- Years outside 1900-2100 are rejected before parsing (old mortgage rows carry Hijri years 1416-1422; counted in invalid_rows and implausible_year_rows).
- Dates after today (Dubai time) are rejected (counted in invalid_rows and future_date_rows).
- Normalize each source, combine all supplied parts, remove exact normalized
  duplicates, then exclude all remaining records with conflicting transaction IDs.
  This avoids choosing a conflicting row arbitrarily. Review these exclusions:
  the pipeline assumes one reusable record per ID, which needs real-source validation.
- Sales below 10,000 AED are dropped (--min-sale-price changes it; mortgages and gifts not filtered; applied last).
- Area must be positive and finite, price per m2 = price_aed / area_m2 (equals the export's meter_sale_price on every sales row).
- Below 10 m2 the row is kept but price_per_m2_aed is left empty (tiny areas give values up to 81M AED/m2; counted in small_area_rows).

### Outputs for teammates

`transactions_clean.csv` contains `transaction_id`, `transaction_date`, `area`,
`property_type`, `unit_type`, `transaction_group`, `price_aed`, `year`, `month`,
`area_m2`, `price_per_m2_aed`, `registration_type` (Off-Plan/Ready), `procedure`
(DLD procedure name, e.g. Sell, Sell - Pre registration, Lease to Own Registration).
Rows are sorted by date, area and ID. Dates use YYYY-MM-DD and months YYYY-MM.
All transaction groups are retained. Select the relevant group before modelling;
prices are whole-transaction amounts, not AED per square metre.

`monthly_sales.csv` groups only `Sales` records (case insensitive) by area,
property type, unit type, registration type (Off-Plan/Ready) and month. Off-plan and
ready sales are priced differently, so they are never mixed in one median. It contains
`transaction_count`, `total_price_aed`, `median_price_aed`, `median_area_m2` and
`median_price_per_m2_aed`. It does not invent zero-activity
months. Missing group labels are excluded; no group column yields an empty
summary with headers. This summary is descriptive preparation, not forecasting.

`quality_report.json` records mutually exclusive invalid, duplicate, conflicting-ID
and retained row counts that reconcile to input rows. It also contains sales
coverage, observed date bounds, per-input SHA-256 hashes, each CSV member's schema,
row count and catalogue reference, preparation time, and pandas version. It also
includes `implausible_year_rows` and `future_date_rows` (subsets of `invalid_rows`),
`low_price_sales_rows`, `small_area_rows`, `min_sale_price_aed` and `min_area_m2`. Catalogue references are based on the detected schema,
not authenticated proof of input origin. Observed date bounds do not establish
coverage completeness. Download URL queries are omitted from the report to avoid
storing signed URL credentials.

### Files and functions

- `src/dld_data/sources.py`: `identify_schema` validates documented headers;
  `normalize_schema` maps a DataFrame; `read_table` loads relevant fields;
  `load_inputs` combines CSV/ZIP parts and records provenance.
- `src/dld_data/pipeline.py`: `download_csv` retrieves a supplied public official
  URL; `clean_transactions` validates and normalizes records; `prepare` combines
  inputs and writes datasets/audit information; `main` exposes the CLI.
- `requirements.txt`: pandas (Part 1) plus numpy, scikit-learn and matplotlib (Part 2);
  `requirements-lock.txt` pins the exact versions the results were produced with.
- `tests/test_pipeline.py` and `tests/test_sources.py`: artificial validation cases,
  source schemas, cross-part conflicts/duplicates, ZIP handling and CLI integration.
- `docs/official-sources.md`: source research, access evidence and remaining limits.
- `data/raw/` and `data/processed/`: Git-ignored original exports and generated outputs.

### Validation

```bash
python -m unittest discover -s tests -v
```

Tests demonstrate preparation behaviour on artificial inputs. Real-export compatibility and end-to-end data validation are verified in the Real-data validation section below.


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
- All 27 unit tests pass on pandas 2.3.3 and 3.1.0.
- The earlier 27 Oct export (1,808,832 rows) gave the same monthly counts and medians for 99.96% of groups
  up to Sep 2026; DLD corrects a few older records between exports (1-30 a month).

Notes:
- The 2026 slowdown is real: existing/ready sales fell from ~6.5k to under 4k a month since March 2026, and off-plan fell from ~13k to ~7.5-8.5k (an independent second export matched).
- Data before ~2019 is sparse; model from 2019/2020 onwards.
- October 2026 is partial (ends 27 Oct 2026).
- `transactions_clean.csv` (~220 MB) is shared outside GitHub.

## How to update the data

The pipeline is semi-automated. Downloading is manual (the DLD portal needs a
CAPTCHA); cleaning, validation and organisation are automated.

1. Download a new export from DLD or Data Dubai.
2. Put the file(s) in data/raw/.
3. Run the pipeline command above with a NEW --output-dir name (e.g. run-2026-11).
4. Copy the new monthly_sales.csv and quality_report.json to data/shared/.
5. Rerun Part 2 (`python -m src.trend_analysis.run`) so market_trends.csv matches, then push.

Overlapping exports are fine, duplicates across files are removed.

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

Forecasts the next quarter's recorded sales activity and a property-price proxy by
exact DLD `area` and separate `registration_type` values, Ready and Off-Plan.
The declared property scope is `Unit|Villa`, including source subtypes and missing
subtypes. This population is not guaranteed to be residential only.

Input is Part 1's `data/shared/monthly_sales.csv` and `quality_report.json`.
`market_trends.csv` is optional descriptive context and is fingerprinted when
present. Part 2's full-history fitted fuzzy scores are not predictive features.
Quarters align with Part 2 and provide more support than sparse monthly cells.
Part 4 consumes the two forecast files directly without importing or training Part 3.

### Targets and observation rules

- `sales_count`, in `sales_per_quarter`, is the sum of recorded `transaction_count`
  across the supplied Unit/Villa Sales cells within an area/registration quarter.
- `weighted_geomean_monthly_median_aed_m2`, in `AED_per_m2`, is
  `exp(sum(n_i * log(p_i)) / sum(n_i))`. Here `n_i` is a monthly cell's transaction
  count and `p_i` is its available positive `median_price_per_m2_aed`. This is a
  transaction-count-weighted geometric mean of monthly medians, not a pooled
  transaction-level quarterly median, mix-adjusted index or individual valuation.

An activity target needs supplied records in all three segment months. Partial
quarter sums are retained for profiling but not treated as fully observed targets.
Absent rows remain unknown. Zero is retained only when explicitly observed as
numeric zero, and no outcomes are interpolated. Three observed months establish
support for the supplied records, not complete market or property/subtype coverage.
Price also needs at least 30 quarterly sales, positive price observations in all
three months and count-weight coverage of at least 0.5. Coverage is the count
weight of cells with positive medians divided by all observed counts. It is not
the exact proportion of transaction-level valid prices. These gates are configurable
engineering choices in `src/forecasting/config.json`.

The first output projects `2026Q4` from `2026Q3`. The source cutoff is
`2026-10-27`, but modelling stops at `2026-09-30` and excludes October records.
This is a Q3-based projection generated during Q4, not a forecast published in
September. `2026Q3` is provisional. The actual generation timestamp is in the manifest.

The full monthly source has 59,008 cells and sums to 1,383,409 recorded sales,
matching the quality report. Its observed sales months span `1975-01` to partial
`2026-10`. The report's `1966-01-18` to `2026-10-27` bounds describe cleaned
records across transaction groups, not the export query period. The aggregate
was prepared on 30 October 2026 at 09:37 UTC. Source filenames, raw-file hashes
and catalogue references are upstream provenance records, not independent
authentication of raw files by Part 3.

Part 1 reports four invalid records and 417 low-price sales removed. It retains
2,788 small-area records without per-m2 prices. Monthly aggregation omits IDs,
procedure categories and the exact transaction-level valid-price denominator.
Complete-market coverage would require recorded export dates and filters, a
verified list of all parts or pages, and reconciliation to authoritative totals
for the same population after documented exclusions. Missing-month semantics
and historical release vintages also need upstream evidence. Internal count
reconciliation and three observed segment months do not supply that proof.

### Methods and evaluation

Naive repeats the supported current quarter. Seasonal naive uses the same target
quarter last year, which is `t-3` when the origin is `t` and the target is `t+1`.
Neither baseline carries a stale observation across a missing current quarter.
Pooled Ridge fits separate activity and price regressions. It uses current,
previous-quarter, seasonal and trailing historical levels, available-history
counts, target-quarter seasonality, area and registration identity.

Numeric features use train-only median imputation, missingness indicators and
scaling. Categorical features use train-only one-hot encoding. Activity uses
`log1p` and price uses `log`. Inverse transforms return native units, with negative
activity predictions clamped to zero. These log predictions are not automatically
unbiased arithmetic means. Fractional activity values are continuous numerical
forecasts of activity, not literal fractional transactions. CSV precision is retained.

The calendar panel begins at `2020Q1`. Initial training targets are `2021Q1` to
`2023Q4`, validation targets are `2024Q1` to `2024Q4`, and held-out test targets are
`2025Q1` to `2026Q3`. Each one-step origin refits on labels known by that origin.
Eligibility needs at least 12 supported training pairs, a supported current level
and matching seasonal history. It is recomputed using past information only,
without requiring survival through the future test period. Historical training
segments need 12 known pairs at the fitting origin.

Ridge alpha is selected from 0.1, 1, 10 and 100 using pooled validation MAE in
native units. Ties prefer smaller alpha. The method is then selected by validation
MAE, with ties preferring naive, seasonal naive, then Ridge. Choices and support
rules are frozen before the test. Later test actuals enter subsequent fits only
after becoming available. All compared methods share the same scored rows per
target and origin. Excluded rows and reasons remain in `predictions.csv`.

### Results (28 Oct 2026 export)

Validation selected Ridge alpha 10 for activity and Ridge alpha 1 for price.
These results come from the current supplied snapshot, using the default config.

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
Validation has 244 activity rows and 190 price rows. The test scores 92 distinct
activity segments and 70 price segments across seven origins. There are 761
excluded activity segment-origin cases and 895 excluded price cases, counted once
per target rather than once per model. Sample counts and exclusions for each
quarter are in `evaluation.json`. Coverage changes by origin.

Ridge's activity improvement is small. Naive beats the validation-selected Ridge
price model on the held-out test. The operational price method remains Ridge
because the selection policy was frozen. Large failures include Madinat Al Mataar
Off-Plan activity in `2026Q2`, with 5,101 actual sales versus 2,249.49 predicted,
and Palm Jumeirah Off-Plan price in `2026Q1`, with 64,715.16 actual versus 57,047.25
predicted AED per m2. Fallback forecasts are outside these common-cohort metrics.

The fallback policy was also replayed at each historical origin. A case qualifies
when the primary history or seasonal-input gate fails, the current target is
supported and at least four supported historical quarters are available. Those
quarters need not be consecutive. The next actual is checked only after choosing
the cohort. This experiment does not select segments from the final deployment
list or use the eventual validation winner to choose earlier fallback cases.

| Period | Target | Eligible | Scored | Scored segments | MAE | RMSE | Count WAPE |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Validation | Activity | 163 | 146 | 56 | 99.58 | 225.87 | 58.56% |
| Validation | Price proxy | 123 | 118 | 39 | 1,265.29 | 1,835.75 | n/a |
| Test | Activity | 254 | 219 | 58 | 141.59 | 336.00 | 52.02% |
| Test | Price proxy | 192 | 175 | 43 | 1,413.24 | 2,347.17 | n/a |

Validation covers four forecast quarters and the test covers seven. Missing or
unsupported next actuals exclude 17 validation activity cases, 5 validation price
cases, 35 test activity cases and 17 test price cases. These metrics describe a
different cohort from the primary comparison. Individual test quarters have
26 to 36 scored activity cases and 20 to 30 price cases. The report retains
per-quarter counts, unavailable-input counts, unscorable predictions and reasons
under `fallback_evaluation` in `reports/part3/evaluation.json`. The manifest links
to that section and includes its overall summaries. The primary `metrics.csv`
and `predictions.csv` retain their existing schemas and cohort.

Fallback errors can be large. Al Yelayiss 1 Off-Plan activity in `2026Q2` was
428 sales against a fallback of 2,744. Al Safouh First Off-Plan price in `2026Q3`
was 33,785.16 against 46,966.26 AED per m2. This is historical evidence for the
support policy, not an accuracy guarantee for each segment or `2026Q4`. Fallbacks
caused by numerical model failures are outside this experiment. Fallback scores
are not used for model selection or eligibility tuning.

These are pseudo-real-time tests using today's revised data, not archived data
vintages. Temporal origins and neighbouring areas are dependent. Sparse segments,
launches, changing property mix and the observed 2026 activity changes limit
generalisation. The supplied export does not prove complete market coverage.
There are no prediction intervals or guaranteed future prices. Recorded activity
does not directly establish buyer enquiries, agent demand, staffing or profit.
Allocation rules remain Part 4's responsibility.

### Install and run

Use Python 3.11 or newer and the virtual environment described under Member 1.
The existing `requirements.txt` already includes all four direct dependencies.
The verified run used Python 3.12.14, pandas 2.2.3, numpy 2.3.5, scikit-learn 1.9.1,
scipy 1.18.1 and matplotlib 3.11.2. The original `requirements-lock.txt` describes
the earlier component environment and is preserved. Exact Part 3 package versions,
source/code hashes and configuration identity are recorded in its manifest and
`reports/part3/run_config.json`.

```bash
python -m pip install -r requirements.txt
python -m src.forecasting.run --config src/forecasting/config.json
python -m unittest discover -s tests -v
```

To match the principal package versions used for these results:

```bash
python -m pip install pandas==2.2.3 numpy==2.3.5 scikit-learn==1.9.1 scipy==1.18.1 matplotlib==3.11.2 joblib==1.6.0 threadpoolctl==3.7.0
```

The command validates inputs, evaluates models, selects using validation, refits
through Q3, exports forecasts, creates figures and reads back the consumer files.
Reruns replace Part 3 outputs. They do not modify the shared input files or Parts
1 and 2. Numeric outputs and run identity are deterministic for unchanged sources,
configuration, code and runtime versions. Generation timestamps change on reruns.

### Forecast files for Parts 4 and the interface

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
| `schema_version`, `run_id`, `data_cutoff_date` | Contract version, linked run identity and source cutoff |

The unique key is schema version, run ID, area, registration, property scope,
origin quarter, forecast quarter and target. Read schema version as a string.
Unavailable predictions have blank numeric values, never zero. Accept `ok` and
`fallback` numeric values while retaining the status. Do not replace blanks with
zero. Activity remains usable when price is unavailable for the same segment.
For this run, activity has 92 `ok`, 30 `fallback`, 4 `insufficient_data` and 72
`missing_input` rows. Price has 68 `ok`, 25 `fallback`, 33 `insufficient_data` and
72 `missing_input` rows. Historical fallback results are reported above. They
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
