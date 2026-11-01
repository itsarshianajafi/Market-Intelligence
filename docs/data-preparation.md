# Part 1 data preparation: reference

Detail moved from the README: where the data comes from, the input formats the pipeline accepts,
every cleaning rule and the full contents of the outputs. The README has the summary and commands.

## Official sources and scope

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

## Direct download and input limits

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

## Accepted input schemas

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

## Cleaning rules

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

## Outputs

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

## Files and functions

- `src/dld_data/sources.py`: `identify_schema` validates documented headers;
  `normalize_schema` maps a DataFrame; `read_table` loads relevant fields;
  `load_inputs` combines CSV/ZIP parts and records provenance.
- `src/dld_data/pipeline.py`: `download_csv` retrieves a supplied public official
  URL; `clean_transactions` validates and normalizes records; `prepare` combines
  inputs and writes datasets/audit information; `main` exposes the CLI.
- `requirements.txt`: pandas (Part 1) plus numpy, scikit-learn and matplotlib (Part 2) and scipy (Part 4);
  `requirements-lock.txt` pins the exact versions the results were produced with.
- `tests/test_pipeline.py` and `tests/test_sources.py`: artificial validation cases,
  source schemas, cross-part conflicts/duplicates, ZIP handling and CLI integration.
- `docs/official-sources.md`: source research, access evidence and remaining limits.
- `data/raw/` and `data/processed/`: Git-ignored original exports and generated outputs.
