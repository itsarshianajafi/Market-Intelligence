# Part 3 notes: forecasting

Detail moved from the README: what exactly is forecast, the method, and the full evaluation.
The README has the summary, results table, output format and run command.

## Scope

Forecasts the next quarter's recorded sales activity and a property-price proxy by
exact DLD `area` and separate `registration_type` values, Ready and Off-Plan.
The declared property scope is `Unit|Villa`, including source subtypes and missing
subtypes. This population is not guaranteed to be residential only.

Input is Part 1's `data/shared/monthly_sales.csv` and `quality_report.json`.
`market_trends.csv` is optional descriptive context and is fingerprinted when
present. Part 2's full-history fitted fuzzy scores are not predictive features.
Quarters align with Part 2 and provide more support than sparse monthly cells.
Part 4 consumes the two forecast files directly without importing or training Part 3.

## Targets and observation rules

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

## Methods and evaluation

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

## Results in detail

Validation selected Ridge alpha 10 for activity and Ridge alpha 1 for price.
These results come from the current supplied snapshot, using the default config.

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

## Reproducibility

The shared outputs were regenerated on 1 Nov 2026 with the versions in `requirements-lock.txt`
(Python 3.14.8, pandas 3.1.0, numpy 2.5.4, scikit-learn 1.9.1, scipy 1.18.1). The first run on
Python 3.12.14 and pandas 2.2.3 gave the same forecasts to floating-point precision. Exact Part 3 package versions,
source/code hashes and configuration identity are recorded in its manifest and
`reports/part3/run_config.json`.

The command validates inputs, evaluates models, selects using validation, refits
through Q3, exports forecasts, creates figures and reads back the consumer files.
Reruns replace Part 3 outputs. They do not modify the shared input files or Parts
1 and 2. Numeric outputs and run identity are deterministic for unchanged sources,
configuration, code and runtime versions. Generation timestamps change on reruns.
