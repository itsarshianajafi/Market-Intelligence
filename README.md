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

No real transactions or prepared market datasets are bundled. The importer is
tested against fields confirmed in DLD's public export JavaScript, not a retrieved
DLD export. **Real-export validation remains outstanding.** Tests use artificial
records explicitly labelled as test data, never substituted for market records.

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
CSV members must total at most 2 GiB per archive. Only the seven relevant fields
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

Native keys are confirmed by DLD's `getExportHeader` and Transactions grid in
its public `scripts/publicData.js`. The display headers are from its English
Transactions table. Actual exported CSV encoding, delimiters and values remain
to be checked on a real export. An unrecognized, ambiguous, duplicate-header or
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
- Normalize each source, combine all supplied parts, remove exact normalized
  duplicates, then exclude all remaining records with conflicting transaction IDs.
  This avoids choosing a conflicting row arbitrarily. Review these exclusions:
  the pipeline assumes one reusable record per ID, which needs real-source validation.

### Outputs for teammates

`transactions_clean.csv` contains `transaction_id`, `transaction_date`, `area`,
`property_type`, `unit_type`, `transaction_group`, `price_aed`, `year`, `month`.
Rows are sorted by date, area and ID. Dates use YYYY-MM-DD and months YYYY-MM.
All transaction groups are retained. Select the relevant group before modelling;
prices are whole-transaction amounts, not AED per square metre. Property size
and ready/off-plan distinctions are not retained by this basic shared dataset.

`monthly_sales.csv` groups only `Sales` records (case insensitive) by area,
property type, unit type and month. It contains `transaction_count`,
`total_price_aed`, and `median_price_aed`. It does not invent zero-activity
months. Missing group labels are excluded; no group column yields an empty
summary with headers. This summary is descriptive preparation, not forecasting.

`quality_report.json` records mutually exclusive invalid, duplicate, conflicting-ID
and retained row counts that reconcile to input rows. It also contains sales
coverage, observed date bounds, per-input SHA-256 hashes, each CSV member's schema,
row count and catalogue reference, preparation time, and pandas version. Catalogue
references are based on the detected schema, not authenticated proof of input
origin. Observed date bounds do not establish coverage completeness. Download URL
queries are omitted from the report to avoid storing signed URL credentials.

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

Tests demonstrate preparation behaviour on artificial inputs. They do not verify
portal availability, the complete market history, or actual export compatibility.


## Validation (real-data test)

Tested on 28 Oct 2026 against a real Data Dubai export
(https://data.dubai/en/l/470061, two CSV parts in one ZIP).

Command:
    python -m src.dld_data.pipeline --input data/raw/<export>.zip --output-dir data/processed/full-run

Results (pandas 2.3.3): 1,808,832 rows in, 4 invalid rows rejected
(impossible dates, years 1416-1422), 0 duplicates, 0 conflicting IDs,
1,808,828 rows out, 1,383,411 sales transactions, 51,446 monthly sales rows.
All 19 unit tests pass.

Notes:
- Keep pandas below 3.0. Pandas 3.0 crashes on the 4 invalid dates.
- Data before ~2019 is sparse. Model from 2019/2020 onwards.
- 2026 volumes look lower than 2025; completeness of the 2026 export is being confirmed.

## How to update the data

The pipeline is semi-automated. Downloading is manual (the DLD portal needs a
CAPTCHA); cleaning, validation and organisation are automated.

1. Download a new export from DLD or Data Dubai.
2. Put the file(s) in data/raw/.
3. Run the pipeline command above with a NEW --output-dir name (e.g. run-2026-11).
4. Copy the new monthly_sales.csv and quality_report.json to data/shared/ and push.

Overlapping exports are fine, duplicates across files are removed.