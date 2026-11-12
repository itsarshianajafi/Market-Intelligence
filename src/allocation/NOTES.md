# Part 4 notes (Saba)

Why Part 4 is built the way it is, written so I can explain it in the viva. Numbers come from the
28 Oct 2026 export with the default `config.json`.

## The question

Imza has a fixed number of agents. In which areas should they work next quarter, and how many in
each? Part 3 says where sales will happen and Part 2 says what the market is doing now. Neither
says how many agents to send, because recorded sales are not the same thing as agent demand.

There is no "correct" allocation to train on, so this is not a supervised learning problem. It is
a decision under constraints, which is what search and constraint satisfaction are for (weeks 2
and 3 of the course).

## What a decision looks like

- **Variables:** one per agent. **Domain:** the candidate segments (area + Off-Plan or Ready).
- **Candidates:** segments with an `ok` or `fallback` activity forecast of at least 30 sales. That
  leaves 95 of 198 segments, in 57 areas. 30 is the same minimum Parts 2 and 3 use. Blank forecasts
  stay out and are never treated as zero (Shahul's rule). There is a test for this.
- **Constraints (all hard):**
  - every agent is placed
  - an area in use has at least 2 agents, so nobody works alone
  - no area has more than 25% of the team
  - at most 8 areas, so the team can be managed
  - Off-Plan gets 30-70% of the team, so we are not betting on one side of the market
  - optional: at most M agents change segment compared with today

## What an agent is worth

For one segment with forecast demand D:

```
ceiling = max_market_share * D
deals(x) = ceiling * (1 - exp(-deals_per_agent * x / ceiling))
value(x) = deals(x) * ticket * commission_rate
```

With a few agents each one closes `deals_per_agent`. As they approach the share of the segment
Imza could realistically win, each extra agent adds less. That is diminishing returns, and it is
why the plan spreads out instead of putting everyone in the best area.

**Ticket** is a typical sale value: the count-weighted mean of monthly median prices over the last
four quarters, scaled by Part 3's price forecast divided by the current price. If there is no price
forecast the scale is 1.

My first version used the mean sale value (`total_price / count`). That put 3 agents on Jumeirah
Second Off-Plan, a segment with 27 forecast sales, because a couple of huge deals made the "average"
ticket AED 49M. Typical value plus the 30-sales minimum fixed it.

## The search

**Simulated annealing** (`search.py`). Start from a greedy plan, propose a move, accept it if better,
and sometimes accept it if worse, less often as the temperature falls. Moves are one agent to
another segment, or a whole area's team to one segment. Each restart reheats from the best plan so
far, and a hill climb finishes the job.

Breaking a constraint costs a penalty in the energy rather than being forbidden, because opening a
new area has to pass through a lone agent, which is infeasible. Only feasible plans can become the
answer. The penalty matters a lot: 2.0 left the plans 2.2% below the optimum on average, 0.2 got
that to 0.6% in the same time.

The search space is large: 95 segments and 20 agents give about 9.6 x 10^21 possible allocations
before constraints, so trying them all is impossible. Each annealing move costs constant time
because value and violations are updated incrementally. The cost grows with iterations, not with
the size of that space.

**Exact check.** The same problem is written as a mixed-integer program (`exact` in `search.py`, using
scipy's HiGHS). Values are concave, so one binary per segment and agent fills in order. This is an
independent check of the annealer. It agreed with brute force on small cases (test).

**Honest point for the viva:** the exact solver takes about 0.02 s against about 0.38 s for
annealing, and it is optimal. For this exact problem annealing is not needed. Annealing is the
course method and it would still work if we add constraints that are not linear, but on today's
problem the exact solver is the better tool. So the run takes the better of the two plans and says
which one in the manifest.

Solver variants, 10 seeds on each of the 11 quarters (`reports/part4/repeated_runs.csv`):

| Variant | Gap to optimum: mean +- std | Worst | Time | Feasible |
|---|---:|---:|---:|---:|
| Greedy only | 0.5% (it breaks constraints, so this is not a fair gap) | | instant | 1 of 11 quarters |
| Annealing | 0.36% +- 0.61% | 2.75% | 0.36 s | all |
| Annealing + hill climb | 0.28% +- 0.50% | 2.30% | 0.38 s | all |
| Exact (HiGHS) | 0 | 0 | 0.02 s | all |

The gap on the 2026Q4 plan was 0. Annealing gets within about 1% of the optimum by 30,000 iterations
and the restarts take it further (`reports/part4/convergence.png`). For team size, annealing time
grows slowly (0.34 s at 5 agents, 0.57 s at 50) and the exact solver grows faster (0.01 s to 0.21 s),
with a gap of 0.31% at 50 agents (`team_size.csv`). So doubling the team costs annealing little,
and the exact solver remains fast at this size.

## Evaluation

Walk-forward. For each quarter from 2024Q1 to 2026Q3 I use Part 3's prediction made the quarter
before, plan, and score the plan on the sales and prices that really happened, through the same
value model. "Oracle" is the exact best plan with hindsight, under the same constraints. Scores
are a share of the oracle. It is the same discipline as Part 3: **choices are made on 2024, then
frozen, then reported on 2025Q1 to 2026Q3.**

Six variants competed on 2024: with or without forecast-error scenarios, and with the trend score
weighted 0, 0.25 or 0.5. A more complicated variant had to win by 0.1 points. **Plain forecast, no
trend weight won.**

- Scenarios (resampling Part 3's past errors, with fallback errors 1.6x wider) did not help on 2024.
  They are still used for the robustness check below.
- Trend at 0.25 tied and at 0.5 was worse. That fits Mahan's forward check, which found the score
  has no correlation with next year's price change. Labels are reported as context only.

Test results (`reports/part4/backtest_summary.csv`, 20 agents):

| Method | Share of oracle | Worst quarter | Feasible quarters |
|---|---:|---:|---:|
| Optimiser with a move limit of 4 | 89.9% | 75.6% | 7 of 7 |
| **Optimiser, Part 3 forecast (selected)** | **86.8%** | 75.7% | 7 of 7 |
| Optimiser, last quarter as the forecast | 83.9% | 66.7% | 7 of 7 |
| Rule: share of forecast value | 51.8% | 41.7% | 0 of 7 |
| Rule: even split over biggest segments | 37.0% | 32.7% | 0 of 7 |
| Rule: share of forecast sales | 36.1% | 32.5% | 0 of 7 |
| Rule: share of last quarter sales | 36.0% | 31.5% | 0 of 7 |

The rules are not constrained, so they break the team rules every quarter, and they still lose.

What this does and does not show:

- **The optimiser beat the best rule in all 7 test quarters**, and in 7 of 7 under nine of the ten
  changed assumptions. Paired difference 35.0 +- 5.2 points, Wilcoxon p = 0.016, which is the smallest
  p seven quarters can give.
- **Repeated runs:** over 10 seeds the selected method scores 86.6%, with std 1.0 points between seeds
  and 8.8 points between quarters. The market changes the result far more than solver randomness.
- **It is mostly the value model doing the work, not the forecast.** Better than the value rule by
  35 points, but Part 3's forecast only adds 2.9 +- 3.2 points over using last quarter (ahead in 6
  of 7 quarters, tied in the other, p = 0.031). That matches Part 3, where Ridge only just beats naive.
- **This is not proof of real commission.** Sales and prices are real, but the response curve is
  assumed in both the plan and the score, so the backtest shares the optimiser's assumptions. It
  shows the plan fits the model on real demand. It cannot show that agents behave like the model.
- **My first version of this table flattered the method.** Rules that ignore price scored 36%, but
  with `objective = deals` the gap nearly closed (99.4% against 99.2%). So I added the value rule,
  which is the fair comparison.

Findings I noticed on the test, so they are not tuned or selected:

- The **move limit** scored higher than free replanning (89.9% against 86.8%) with 3.5 moves a
  quarter instead of 5.4, but the difference is not established: it won 4, lost 2, tied 1, p = 0.16.
  So I can say it costs nothing measurable and moves fewer agents, not that it is better.
- Trend weight 0.5 scored 88.7% on the test, against 86.8%. It lost on 2024, so it stays out.
  Picking it now would be choosing on the test.

## The 2026Q4 plan (20 agents)

| Area | Segment | Agents | Forecast sales | Typical deal (AED) | Kept in replans |
|---|---|---:|---:|---:|---:|
| Business Bay | Off-Plan | 5 | 594 | 3.6M | 100% |
| Marsa Dubai | Off-Plan | 3 | 133 | 6.5M | 100% |
| Palm Jumeirah | Off-Plan | 2 | 67 | 10.6M | 100% |
| Palm Jumeirah | Ready | 2 | 156 | 9.3M | 97% |
| Al Thanayah Fourth | Ready | 2 | 99 | 6.7M | 67% |
| Wadi Al Safa 6 | Ready | 2 | 60 | 8.5M | 63% |
| Al Yufrah 1 | Off-Plan | 2 | 415 | 3.0M | 40% |
| Al Khairan First | Off-Plan | 2 | 526 | 2.9M | 37% |

"Kept in replans" is the share of 30 replans, each on one random draw of forecast error, in which
the segment still got an agent. The first four are solid. **The last four are close calls** and
could swap with similar areas. Expected value is about AED 5.4M a quarter and 30 deals, but only
under the assumed numbers. 14 of 20 agents are Off-Plan, the top of the 30-70% limit, because of the
assumed 4% commission against 2%.

The huge segments such as Madinat Al Mataar Off-Plan (3,683 forecast sales) are not picked, because
their typical deals are much cheaper. If Imza cares about deal count, they would be.

## Assumptions, and what happens if they are wrong

**These are my placeholders, not Imza's data.** I could not find them anywhere, and Imza should
replace them: team size 20, 2 deals per agent per quarter, 5% maximum share of a segment,
commission of 2% on Ready and 4% on Off-Plan, and the constraint limits.

`reports/part4/sensitivity.csv` changes one at a time and recomputes the backtest and the plan:

- Team size, deal rate, market share, equal commission and area limits: 12 to 18 of the 20 agents
  stay put (at 10 or 40 agents, 10 and 16 are in the default plan), and the optimiser stays ahead.
- **`objective = deals` is the one that changes everything:** only 1 of 20 agents stays, and the
  optimiser's edge goes (99.4% against 99.2%). So Imza's goal, commission or number of deals, is the
  most important input of all, and Imza has to decide it.

**What if the market moves?** The forecast only knows past sales, so it cannot see a conflict or
a rate change. The optional config key `demand_change`, for example `{"Off-Plan": -0.3}`, scales
the forecast by registration type before planning; the dashboard's form sets it. On the 2026Q4
plan, off-plan sales 30% lower costs about 7% of the estimated commission and moves 2 of the 20
agents; off-plan 50% and ready 20% lower costs about 16% and moves 3. The plan changes little
because an agent's deals level off with market share, so the same areas stay the best ones.

`reports/part4/team_size.csv` shows how value grows with team size (exact solver, 5 to 50 agents).
An added agent is worth about AED 233k a quarter around 10 agents and about AED 134k around 50.

Threats to validity: quarters are not independent, so the p-values are a guide rather than proof;
the response curve is shared by planning and scoring; 2024 and later use revised data, not what was
known at the time; and the candidate list changes each quarter.

## Limitations

- Agent response is assumed, not measured. Imza's own deal history would let us fit it.
- All agents are treated the same: no language, experience, or current territory.
- Off-Plan volume is often developer launches, which a broker may not be able to win.
- Past ticket and price uncertainty is not simulated, only sales demand.
- Backtest candidates exclude fallback segments, because `predictions.csv` has only the primary
  cohort. The live plan includes them. No fallback segment was picked for 2026Q4.
- Part 3's limits carry over: one quarter ahead, rough empirical ranges only, and 2026Q3 is provisional.
- DLD area names are land names, not the community names buyers use. Mahan flagged this too. Imza
  will want a mapping before seeing the plan. What I could find for the plan's areas, none of it from
  DLD's own boundary data, so check with Imza:

  | DLD name | Community name | Evidence |
  |---|---|---|
  | Business Bay, Palm Jumeirah | Same name | Common knowledge |
  | Marsa Dubai | Dubai Marina | Widely used; the sources I found do not state it outright |
  | Al Thanyah Fourth | Formerly Emirates Hills Third | Gulf News table of the 2024 renames |
  | Wadi Al Safa 6 | Arabian Ranches | Community code listing and property sites |
  | Al Khairan First | Dubai Creek Harbour | Zone name on property listings |
  | Al Yufrah 1 | Includes Sobha Sanctuary | Thin: project listing sites only |
- 2024 validation picks among close variants and 7 test quarters is a small sample.

## Log

- 1 Nov 2026: cloned the repo, reviewed Parts 1-3. Built Part 4: data layer, response model,
  annealer, exact check, backtest, sensitivity, figures, tests, README section.
  Then checked against the project brief and added 10-seed repeated runs, paired tests, solver
  variants, runtime and convergence. Fixed on the way: Windows CRLF breaking Part 3's hash check, mean tickets driven by outlier
  deals, the annealing penalty, and baselines that flattered the method.
