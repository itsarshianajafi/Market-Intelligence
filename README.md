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
