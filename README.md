# Market-Intelligence
Private Project for University

## Member 1: Data Collection & Preparation

This Python pipeline prepares Dubai Land Department (DLD) transaction exports
for the group's analysis and forecasting work. It does not implement predictive
models, agent recommendations, or marketing allocation.

### Official data source

Use **DLD Transactions**, published by Dubai Land Department on the official
[Dubai Pulse catalogue](https://www.dubaipulse.gov.ae/data/dld-transactions/dld_transactions-open).
Search the portal for `dld_transactions-open` if the catalogue path changes.
Download the official CSV resource and retain its source and download date.
Do not use private listing websites. Check the portal's current license and
attribution requirements before redistributing exports.

During implementation, this cloud environment's proxy returned HTTP 403 for
the Dubai Pulse portal and API. Consequently, the current resource URL, API
authentication requirements, and real-data execution could not be verified.
No real records are bundled and no synthetic records replace official data.
The supported baseline is a manually downloaded official CSV. An optional
URL downloader works only with direct HTTPS CSV links on official Dubai Pulse
or DLD hosts; it does not discover resources or implement an authenticated API.
If a resource uses another host, download it manually after verifying its provenance.

### Install and run

Requires Python 3.11 or newer. From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
# Place the downloaded official export at data/raw/dld_transactions.csv
python -m src.dld_data.pipeline --input data/raw/dld_transactions.csv --output-dir data/processed/run1
python -m unittest discover -s tests -v
```

For a verified direct official CSV link, add `--url "$DLD_CSV_URL"` and use a
new `--input` destination. The URL must return a CSV, not a portal page. TLS
verification remains enabled. Downloads are limited to 1 GiB. This simple
pandas workflow reads the CSV into memory; use a manageable portal export or
a machine with enough RAM. It does not implement incremental ingestion.
Input and output files are never intentionally overwritten; use a new output
directory per run. Raw and prepared datasets are ignored by Git.

### Input contract and cleaning

The UTF-8 (or UTF-8 BOM), comma-delimited DLD export must include:
`transaction_id`, `instance_date`, `area_name_en`, `property_type_en`, and
`actual_worth`. Optional fields are `property_sub_type_en` and `trans_group_en`.
An incompatible schema fails clearly rather than guessing columns.

- Trim labels and collapse repeated whitespace. Preserve official area/type
  spelling rather than merging distinct labels heuristically.
- Accept explicit DD-MM-YYYY, DD/MM/YYYY, and YYYY-MM-DD dates; output ISO dates.
- Treat `actual_worth` as transaction consideration in AED. Accept positive
  numbers with optional correctly grouped thousands separators; reject missing,
  zero, negative, nonnumeric prices and impossible dates.
- Reject rows missing ID, area, or property type. Leave optional labels empty;
  do not estimate missing prices or locations.
- Remove exact normalized duplicates. Exclude every remaining row sharing a
  conflicting transaction ID so arbitrary records do not enter the dataset.

### Outputs for other members

`transactions_clean.csv` has one retained transaction per ID, ordered by date,
area, and ID. Columns are `transaction_id`, `transaction_date`, `area`,
`property_type`, `unit_type`, `transaction_group`, `price_aed`, `year`, `month`.
`month` uses YYYY-MM. Prices are whole-transaction amounts, not AED per square
metre; differences in property size affect comparisons. All transaction groups
are retained here, so analysis should select the relevant group explicitly.

`monthly_sales.csv` groups only records whose transaction group is `Sales`
(case insensitive) by area, property type, unit type, and month. It contains
`transaction_count`, `total_price_aed`, and `median_price_aed`. Missing months
are not fabricated as zeros. Missing transaction-group labels are excluded
from this summary; a missing group column yields an empty summary with headers.

`quality_report.json` records input, invalid, duplicate, conflicting-ID, and
output counts, sales coverage, source reference, input SHA-256, UTC preparation
time, and pandas version. The four disposition counts plus output reconcile
to input rows. Review exclusions before using results; no rejected records
are silently imputed. The manual-mode source URL is a catalogue reference,
not a claim that the input's origin has been independently authenticated.

### Files and functions

- `src/dld_data/pipeline.py`: `download_csv` retrieves an explicit official URL;
  `clean_transactions` validates and normalizes a pandas DataFrame; `prepare`
  reads a CSV and writes reusable data and audit outputs; `main` exposes the CLI.
- `requirements.txt`: pandas dependency; the remaining code uses Python's
  standard library.
- `tests/test_pipeline.py`: clearly artificial edge cases for validation,
  deduplication, dates, monthly sales aggregation, and input/output protection.
  These test records are never shipped as usable market datasets.
- `data/raw/` and `data/processed/`: local input and output locations, with
  placeholders tracked so team members share the same folder structure.

Real-export validation remains outstanding until the official CSV is available.
The tests validate the documented schema and preparation rules, not current
portal availability or the source's complete data quality.
