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
- Normalize each source, combine all supplied parts, remove exact normalized
  duplicates, then exclude all remaining records with conflicting transaction IDs.
  This avoids choosing a conflicting row arbitrarily. Review these exclusions:
  the pipeline assumes one reusable record per ID, which needs real-source validation.
- Sales below 10,000 AED are dropped (--min-sale-price changes it; mortgages and gifts not filtered; applied last).
- Area must be positive and finite, price per m2 = price_aed / area_m2 (equals the export's meter_sale_price on every sales row).

### Outputs for teammates

`transactions_clean.csv` contains `transaction_id`, `transaction_date`, `area`,
`property_type`, `unit_type`, `transaction_group`, `price_aed`, `year`, `month`,
`area_m2`, `price_per_m2_aed`, `registration_type` (Off-Plan/Ready).
Rows are sorted by date, area and ID. Dates use YYYY-MM-DD and months YYYY-MM.
All transaction groups are retained. Select the relevant group before modelling;
prices are whole-transaction amounts, not AED per square metre.

`monthly_sales.csv` groups only `Sales` records (case insensitive) by area,
property type, unit type and month. It contains `transaction_count`,
`total_price_aed`, `median_price_aed`, `median_area_m2`, `median_price_per_m2_aed`,
`offplan_transactions`, and `ready_transactions`. It does not invent zero-activity
months. Missing group labels are excluded; no group column yields an empty
summary with headers. This summary is descriptive preparation, not forecasting.

`quality_report.json` records mutually exclusive invalid, duplicate, conflicting-ID
and retained row counts that reconcile to input rows. It also contains sales
coverage, observed date bounds, per-input SHA-256 hashes, each CSV member's schema,
row count and catalogue reference, preparation time, and pandas version. It also
includes `implausible_year_rows` (subset of `invalid_rows`), `low_price_sales_rows`,
and `min_sale_price_aed`. Catalogue references are based on the detected schema,
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
- `requirements.txt`: pandas dependency; other code uses Python's standard library.
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

Tested against a full real Data Dubai export (https://data.dubai/en/l/470061, two CSV parts in one ZIP) and on a DLD native export.

Command:
```bash
python -m src.dld_data.pipeline --input data/raw/transactions_2026-10-27_19-03-09_0001_0002.zip --output-dir data/processed/full-run-v2
```

Results:
- `input_rows`: 1,808,832
- `invalid_rows`: 4 (impossible dates, years 1416-1422)
- `implausible_year_rows`: 4 (subset of invalid rows)
- `duplicate_rows`: 0
- `conflicting_id_rows`: 0
- `low_price_sales_rows`: 417
- `output_rows`: 1,808,411
- `sales_transactions`: 1,382,994
- `monthly_sales_rows`: 51,439
- All 24 unit tests pass.

Notes:
- The 2026 slowdown is real: existing/ready sales fell from ~6.5k to under 4k a month since March 2026, and off-plan fell from ~13k to ~7.5-8.5k (an independent second export matched).
- Data before ~2019 is sparse; model from 2019/2020 onwards.
- October 2026 is partial (ends 26 Oct 2026).
- `transactions_clean.csv` (~190 MB) is shared outside GitHub.

## How to update the data

The pipeline is semi-automated. Downloading is manual (the DLD portal needs a
CAPTCHA); cleaning, validation and organisation are automated.

1. Download a new export from DLD or Data Dubai.
2. Put the file(s) in data/raw/.
3. Run the pipeline command above with a NEW --output-dir name (e.g. run-2026-11).
4. Copy the new monthly_sales.csv and quality_report.json to data/shared/ and push.

Overlapping exports are fine, duplicates across files are removed.
