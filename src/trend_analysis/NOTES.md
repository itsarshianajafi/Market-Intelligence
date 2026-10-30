# Part 2 notes (Mahan)

Why Part 2 is built the way it is, written so I can explain it in the viva. Numbers come from
the 28 Oct 2026 export with the default `config.json`.

## The question

For each area of Dubai, is the market going up, staying flat or going down right now? Imza
wants to know where prices are moving, and Shahul's forecasting (Part 3) and Saba's part can
use the labels as an input.

There are no "true" labels for this. Nobody publishes an official list of rising areas, so this
is not a supervised learning problem. That's the main reason I picked fuzzy logic instead of
training a classifier.

## What a row is

One **segment** (area + off-plan or ready) in one **calendar quarter**.

- Off-plan and ready are kept apart because they are priced very differently (median around
  18k AED/m2 for off-plan vs 11k for ready since 2020). An area with a lot of new launches would
  look like it's rising just because the mix moved towards off-plan.
- Quarters, not months. Most areas have too few sales in a month to say anything.
- Year on year (this quarter vs the same quarter last year), so seasonality (Ramadan, summer)
  cancels out.
- From 2020Q1. Earlier data is sparse (Albaraa noted this too) and the year-on-year change needs
  2019 anyway.
- Units and villas only. Land and whole buildings are priced per plot and are a different market.
- Only complete quarters. The export ends on 27 Oct 2026, so 2026Q4 is left out and 2026Q3 is the
  last one. It is marked `provisional` because DLD keeps correcting a few records each month
  (we saw 1 to 30 a month when comparing two exports).

## The three inputs

**Price change (P).** Year-on-year change in price per m2, as a log change. Log because +50% and
-33% are the same size move in log terms (log 1.5 = -log 0.667), so up and down are treated
the same.

It is **mix-adjusted**. Inside a segment I compare each property kind with itself (flats with
flats, villas with villas, offices with offices) and then average those changes, weighted by
min(sales now, sales a year ago). Without this, an area where buyers switch from flats to
cheaper villas would look like it's falling even if no price changed. There's a test for
exactly that case (`test_mix_shift_is_not_a_price_change`).

Prices come from Part 1's monthly medians. A quarter's price for a cell is the sales-weighted
mean of the monthly log medians. This is an approximation of the true quarterly median, but it
means Part 2 runs on the shared `monthly_sales.csv` that everyone has, not the 220 MB file.

**Volume change (V).** Log of (sales this quarter / sales same quarter last year). It's a demand
signal: prices react slowly, the number of buyers reacts faster.

**Volatility (S).** Standard deviation of the last 4 quarter-on-quarter price changes. It measures
how jumpy the area is, so we know how much to trust a big move.

**Enough data.** A segment quarter is only labelled if it has at least 30 sales now and 30 a year
ago, and at least half its sales are in property kinds that existed in both years. Everything
else is `Insufficient data` (2,394 of 4,123 rows, but they are only 11% of the sales). 30 is a
judgement call. The sensitivity test shows 10 or 50 changes almost nothing (98-99% same labels).

## Membership functions

Each input gets fuzzy sets. For P and V: Falling, Flat, Rising. For S: Low, High. Picture:
`reports/part2/membership_functions.png`.

The breakpoints come from the data, not from me guessing:

| Input | a (fully flat inside +-a) | b (fully rising/falling beyond +-b) |
|---|---|---|
| P | 0.061 (about 6%) | 0.201 (about 22%) |
| V | 0.187 (about 20%) | 0.793 (about 2.2x) |

a and b are the 25th and 75th percentiles of the *size* of the change (|P|, |V|). So "flat" means
"a smaller move than three quarters of what we see in Dubai", which adjusts itself to how much
this market normally moves. I used the size (absolute value) so the sets stay centred on zero.
If I'd used plain percentiles of P, then in 2023 when nearly everything went up, a quarter of
areas would be "falling" even though their prices went up.

Falling, Flat and Rising always add up to 1 at any point (trapezoids with linear overlaps), which
makes them easy to read: a log change of 0.11 (about +12%) is 0.35 Rising and 0.65 Flat.

Volatility High goes from 0 at the median (0.063) to 1 at the 90th percentile (0.172).
Low = 1 - High.

## Rules

AND = min, NOT x = 1 - x, rule weights multiply the firing strength, and each class takes the
max over its rules (standard Mamdani, same as Lab 4).

| # | IF | THEN | weight | Why |
|---|---|---|---|---|
| 1 | P Rising AND V not Falling | Rising | 1.0 | prices up and buyers aren't leaving |
| 2 | P Falling AND V not Rising | Declining | 1.0 | prices down and no buying rush |
| 3 | P Flat | Stable | 1.0 | |
| 4 | P Rising AND V Falling | Stable | 0.7 | mixed signals, prices up but demand drying up |
| 5 | P Falling AND V Rising | Stable | 0.7 | mixed signals |
| 6 | P Flat AND V Rising | Rising | 0.5 | demand often moves before prices |
| 7 | P Flat AND V Falling | Declining | 0.5 | same, the other way |
| 8 | S High | Stable | 0.5 | a big move in a jumpy area is less trustworthy |

Price leads and volume adjusts. I didn't let volume alone decide the label because new project
launches make volume jump around (Jabal Ali Industrial Second off-plan went from 171 to 2,535
sales in a year).

Weights 0.7 and 0.5 are my judgement, not fitted. Changing them is a limitation I'd mention.

## Output

- **Label** = the class with the highest strength (ties go to Stable).
- **Degrees** = the three strengths (`rising_degree` etc.), so Shahul can see "0.54 Declining, 0.46
  Stable" instead of just "Declining".
- **Trend score** = centroid defuzzification. The output sets are triangles on -1..1 (Declining
  peak at -1, Stable at 0, Rising at +1). Clip each at its strength, take the max, and the
  centre of mass is the score. It is useful for sorting areas.

## Worked examples (2026Q3)

**Al Barshaa South Second, Ready.** 36 sales (91 a year ago). P = -0.137, V = -0.927, S = 0.05.
- P is 0.54 Falling, 0.46 Flat. V is fully Falling. S is not High.
- Rule 2: min(0.54, 1 - 0) = 0.54 Declining. Rule 3: 0.46 Stable. Rule 7: 0.5 x min(0.46, 1) = 0.23
  Declining (lower than 0.54, so the max stays 0.54).
- Result: **Declining** (0.54), score -0.144. Crisp and k-means also say Declining.

**Al Hebiah First, Off-Plan.** 658 sales (1,499 a year ago). P = -0.05 (inside the flat band),
V = -0.82.
- Rule 3: Stable 1.0. Rule 7: 0.5 x min(1, 1) = 0.5 Declining.
- Result: **Stable**, but leaning down (score -0.095). This is what fuzzy gives that crisp doesn't:
  crisp just says Stable. Several areas in 2026Q3 sit at exactly -0.095 for the same reason
  (prices flat, sales down a lot), which is the 2026 slowdown showing up.

**Jabal Ali Industrial Second, Off-Plan.** P = +0.169, V = +2.7, S = 0.093 (0.28 High).
- Rule 1: 0.77 Rising. Rule 3: 0.23 Stable. Rule 8: 0.5 x 0.28 = 0.14 Stable.
- Result: **Rising** (0.77), score 0.321. k-means called it Stable, because of the huge volume number.

## Baselines

- **Crisp rules:** Rising if P > (a + b) / 2, Declining if P < -(a + b) / 2, else Stable. That is
  exactly where fuzzy Rising crosses 0.5, so the comparison is fair: the only difference is the
  fuzzy reasoning (graded degrees, plus volume and volatility).
- **k-means** (k = 3) on standardised P, V, S. Clusters are named by their average P. This is the
  "let the data decide" option.

## Results and what they mean

Files: `reports/part2/evaluation.json`, `forward_check.csv`, `sensitivity.csv` and the figures.

- Fuzzy vs crisp: 95% the same (kappa 0.91). Expected, since both lean on price. The 5% that differ
  are the mixed-signal cases, which is where the rules matter.
- Fuzzy vs k-means: 33% (kappa -0.07, about chance). k-means splits mostly on volume, not
  direction. It's also unstable: different seeds agree only 72% +- 29% (20 runs). So unsupervised
  clustering doesn't find "trend" by itself. This is a good argument for a rule-based method with
  domain knowledge.
- Bootstrap: I resampled the data 200 times (seed 42), refit the breakpoints and relabelled.
  98.8% +- 0.8% of labels stayed the same. The percentile-based sets are stable.
- Sensitivity: changing one setting at a time (min sales 10/50, percentiles 20-70 or 30-80,
  volatility percentiles, min cell sales) keeps 92-99% of labels.
- Over time: Rising share peaked near 60% in early 2024, was 37% in 2026Q1 and 8% in 2026Q3. That
  matches the slowdown we found in the raw data.

**Forward check (the honest bit).** Does a Rising area keep rising next year? I compared each
label with the price change from q+1 to q+5, minus that quarter's market median (otherwise the
whole-market boom makes everything look right).
- Answer: no. Spearman correlation of trend score with next year's change is -0.01. Areas
  labelled Declining actually did about 2 points *better* than the market the next year (slight
  rebound).
- First I used q to q+4, which shares quarter q with the label's own change (q-4 to q). Then any
  noise in quarter q pushes the two changes in opposite directions and looks like mean reversion.
  Skipping a quarter fixes that.
- So the labels describe the market now. They are not a forecast, and we shouldn't sell them to
  Imza as one. Forecasting is Part 3.

## Limitations

- No ground truth, so "accuracy" can't be measured. Only agreement, stability and the forward check.
- Monthly medians, not transactions: quarterly prices are approximate.
- Rule weights and the 30-sales minimum are judgement calls.
- Breakpoints are fitted on all quarters, including later ones. For a live system they'd be refit
  each quarter on data up to that point. The bootstrap suggests this barely changes labels.
- DLD area names are official land names, not the community names buyers use (for example JVC
  sits inside an Al Barsha South area [check which one]). Imza would want a mapping.
- 2026Q3 is provisional, and 2026Q4 isn't in yet.

## Log

- 29 Oct 2026: cloned the repo, reviewed Part 1, downloaded a fresh Data Dubai export and confirmed
  the 2026 slowdown is real (not a bad download).
- 30 Oct 2026: Part 1 fixes (off-plan/ready split, procedure column, date and area checks), PR #2,
  merged. Built Part 2: features, fuzzy classifier, crisp and k-means baselines, evaluation,
  figures, `market_trends.csv`, README section, tests (14 for Part 2, 41 total).
