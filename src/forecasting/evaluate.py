"""Expanding one-step evaluation. Selection sees validation predictions only."""
import numpy as np
import pandas as pd

from .data import COUNT, KEYS, TARGETS
from .features import fallback_supported, origin_candidates, training_rows
from .models import NAIVE, SEASONAL, predictions_for, ridge_id

POLICY = {
    'primary_metric': 'pooled native-unit MAE on common eligible rows',
    'alpha_selection': '2024 validation only; minimum MAE, then smaller alpha',
    'method_selection': '2024 validation only; minimum MAE, ties naive then seasonal then Ridge',
    'test_policy': 'Freeze alpha, method and gates before test. Expand fits using labels known at each origin.',
    'cohort': 'Dynamic origin-only eligibility; at least configured min_training_pairs known supported training pairs. No future survival gate.',
    'scoring': 'All compared methods use the same rows. Next actual must satisfy the declared target support rule.',
    'fallback': 'Current supported level and >=min_fallback_quarters valid quarters; no stale-level carry forward. Never used in fair-cohort metrics.'
}


def metrics(actual, predicted, count=False):
    actual, predicted = np.asarray(actual, dtype=float), np.asarray(predicted, dtype=float)
    if actual.shape != predicted.shape or not (np.isfinite(actual).all() and np.isfinite(predicted).all()):
        raise ValueError('Metrics require aligned finite actuals and predictions')
    if not len(actual):
        return dict(n=0, mae=None, rmse=None, wape=None)
    error = predicted - actual
    denominator = float(np.abs(actual).sum())
    return dict(n=len(actual), mae=float(np.mean(np.abs(error))),
                rmse=float(np.sqrt(np.mean(error ** 2))),
                wape=float(np.abs(error).sum() / denominator) if count and denominator > 0 else None)


def walk_forward(feature_tables, start, end, split, cfg, alphas):
    records, coverage = [], []
    for forecast_quarter in pd.period_range(start, end, freq='Q'):
        origin = forecast_quarter - 1
        for target, features in feature_tables.items():
            candidates = origin_candidates(features, origin, cfg)
            train = training_rows(features, origin, cfg)
            eligible = candidates.origin_reason.eq('')
            to_predict = candidates.loc[eligible].copy()
            methods = [NAIVE, SEASONAL] + [ridge_id(a) for a in alphas]
            predicted = predictions_for(train, to_predict, target, alphas) if len(to_predict) else {}
            matrix = pd.DataFrame(predicted, index=to_predict.index).reindex(candidates.index, columns=methods)
            reason = candidates.origin_reason.copy()
            reason = reason.mask(eligible & candidates.actual.isna(), 'next_actual_unsupported')
            reason = reason.mask(eligible & candidates.actual.notna() & matrix.isna().any(axis=1), 'model_prediction_unavailable')
            common = reason.eq('')
            coverage.append(dict(split=split, target=target, origin_quarter=str(origin),
                forecast_quarter=str(forecast_quarter), known_segments=len(candidates),
                origin_eligible_segments=int(eligible.sum()), scored_segments=int(common.sum()),
                excluded_segments=int((~common).sum()), training_rows=len(train),
                exclusions=reason[~common].value_counts().to_dict()))
            for model in methods:
                part = candidates[KEYS].copy()
                part['split'], part['target'], part['unit'] = split, target, TARGETS[target]
                part['origin_quarter'], part['forecast_quarter'] = str(origin), str(forecast_quarter)
                part['train_max_target_quarter'] = str(train.target_quarter.max()) if len(train) else ''
                part['model_id'] = model
                part['actual'], part['prediction'] = candidates.actual, matrix[model]
                part['scored'], part['exclusion_reason'] = common, reason
                part['error'] = (matrix[model] - candidates.actual).where(common)
                records.append(part)
    return pd.concat(records, ignore_index=True), coverage


def summarize(predictions):
    result = []
    for (split, target, model), group in predictions.groupby(['split', 'target', 'model_id'], sort=True):
        scored = group.loc[group.scored]
        for period, subset in [('all', scored)] + list(scored.groupby('forecast_quarter')):
            result.append(dict(split=split, target=target, unit=TARGETS[target], model_id=model,
                forecast_quarter=period, **metrics(subset.actual, subset.prediction, target == COUNT)))
    return pd.DataFrame(result)


def select_validation(validation, cfg):
    if not validation.split.eq('validation').all():
        raise ValueError('Model selection accepts validation rows only')
    summary = summarize(validation)
    selected, best_alphas = {}, {}
    for target in TARGETS:
        scores = summary.loc[summary.target.eq(target) & summary.forecast_quarter.eq('all')].set_index('model_id')
        grid = [(a, scores.loc[ridge_id(a), 'mae']) for a in cfg['ridge_alphas']]
        valid = [(a, error) for a, error in grid if pd.notna(error)]
        if not valid:
            selected[target], best_alphas[target] = None, None
            continue
        alpha = min(valid, key=lambda pair: (pair[1], pair[0]))[0]
        methods = [NAIVE, SEASONAL, ridge_id(alpha)]
        winner = min(methods, key=lambda m: (scores.loc[m, 'mae'], methods.index(m)))
        best_alphas[target] = alpha
        selected[target] = winner
    return selected, best_alphas


def evaluate_fallbacks(feature_tables, cfg):
    """Score input/history-driven fallbacks on their own origin-selected cohort.

    Primary support gates are shared by every model. No validation winner or
    next-quarter actual is used to choose these fallback rows. Numerical model
    failures are a different fallback path and are outside this experiment.
    """
    records, coverage = [], []
    periods = [('validation', cfg['validation_start'], cfg['validation_end']),
               ('test', cfg['test_start'], cfg['test_end'])]
    for split, start, end in periods:
        for forecast_quarter in pd.period_range(start, end, freq='Q'):
            origin = forecast_quarter - 1
            for target, features in feature_tables.items():
                candidates = origin_candidates(features, origin, cfg)
                primary = candidates.origin_reason.eq('')
                fallback = ~primary & fallback_supported(candidates, cfg)
                unavailable = ~primary & ~fallback
                reasons = np.where(candidates.naive.isna(), 'origin_target_unsupported',
                                   'fewer_than_min_fallback_quarters')
                rows = candidates.loc[fallback]
                scored = rows.actual.notna()
                coverage.append(dict(split=split, target=target, origin_quarter=str(origin),
                    forecast_quarter=str(forecast_quarter), known_segments=len(candidates),
                    primary_supported_segments=int(primary.sum()),
                    eligible_fallbacks=len(rows), scored_fallbacks=int(scored.sum()),
                    unscorable_fallbacks=int((~scored).sum()),
                    unavailable_segments=int(unavailable.sum()),
                    unavailable_reasons=pd.Series(reasons[unavailable.to_numpy()]).value_counts().to_dict()))
                for _, row in rows.iterrows():
                    can_score = pd.notna(row.actual)
                    records.append(dict(split=split, target=target, unit=TARGETS[target],
                        area=row.area, registration_type=row.registration_type,
                        origin_quarter=str(origin), forecast_quarter=str(forecast_quarter),
                        model_id=NAIVE, cohort='fallback', prediction=row.naive,
                        actual=row.actual, scored=can_score,
                        exclusion_reason='' if can_score else 'next_actual_unsupported',
                        primary_exclusion_reason=row.origin_reason,
                        history_quarters=int(row.history_quarters),
                        error=row.naive - row.actual if can_score else np.nan))
    columns = ['split', 'target', 'unit'] + KEYS + ['origin_quarter', 'forecast_quarter',
               'model_id', 'cohort', 'prediction', 'actual', 'scored', 'exclusion_reason',
               'primary_exclusion_reason', 'history_quarters', 'error']
    predictions = pd.DataFrame(records, columns=columns)
    summaries, failures = [], []
    for split, start, end in periods:
        for target in feature_tables:
            group = predictions.loc[predictions.split.eq(split) & predictions.target.eq(target)]
            for period in ['all'] + list(pd.period_range(start, end, freq='Q').astype(str)):
                rows = group if period == 'all' else group.loc[group.forecast_quarter.eq(period)]
                scored = rows.loc[rows.scored.astype(bool)]
                summaries.append(dict(split=split, target=target, unit=TARGETS[target],
                    model_id=NAIVE, cohort='fallback', forecast_quarter=period,
                    eligible_predictions=len(rows), excluded_predictions=len(rows) - len(scored),
                    eligible_segments=len(rows[KEYS].drop_duplicates()),
                    scored_segments=len(scored[KEYS].drop_duplicates()),
                    eligible_quarters=rows.forecast_quarter.nunique(),
                    scored_quarters=scored.forecast_quarter.nunique(),
                    **metrics(scored.actual, scored.prediction, target == COUNT)))
            scored = group.loc[group.scored.astype(bool)].copy()
            if not scored.empty:
                scored['absolute_error'] = scored.error.abs()
                failures += scored.nlargest(3, 'absolute_error').to_dict('records')
    return dict(
        scope='Input/history-driven fallback policy, evaluated separately from the primary common-row cohort',
        eligibility='Primary support gate fails; current target supported; at least min_fallback_quarters supported historical quarters',
        selection='Eligibility uses origin history only; next-quarter support is checked afterwards for scoring. No final-deployment segment list or validation winner selects the cohort.',
        runtime_failure_fallbacks='Not evaluated here; numerical model failures are outside this support-policy experiment',
        limitations=[
            'Historical, sample-limited evidence; no guarantee for an individual segment or the operational quarter.',
            'Validation and test cohorts vary by origin and differ from the final operational fallback list.',
            'Revised source snapshot rather than historical vintages; completeness remains unverified.',
            'Origin and segment observations are dependent; price scores exclude unsupported next-quarter prices.'
        ], summaries=summaries, per_origin=coverage,
        predictions=predictions.to_dict('records'), high_error_examples=failures)


def evaluate(feature_tables, cfg):
    validation, validation_coverage = walk_forward(feature_tables, cfg['validation_start'],
        cfg['validation_end'], 'validation', cfg, cfg['ridge_alphas'])
    selected, alphas = select_validation(validation, cfg)
    # Test is evaluated only after choices above have been frozen. Each target
    # gets its own chosen alpha, while baselines remain in the comparison.
    tests, coverage = [], []
    for target, table in feature_tables.items():
        grid = [] if alphas[target] is None else [alphas[target]]
        pred, cov = walk_forward({target: table}, cfg['test_start'], cfg['test_end'], 'test', cfg, grid)
        tests.append(pred)
        coverage += cov
    predictions = pd.concat([validation] + tests, ignore_index=True)
    table = summarize(predictions)
    failures, segments = [], []
    for target, method in selected.items():
        subset = predictions.loc[predictions.split.eq('test') & predictions.scored
            & predictions.target.eq(target) & predictions.model_id.eq(method)].copy()
        subset['absolute_error'] = subset.error.abs()
        failures += subset.nlargest(5, 'absolute_error').to_dict('records')
        for keys, group in subset.groupby(KEYS):
            segments.append(dict(zip(KEYS, keys), target=target, model_id=method,
                                 **metrics(group.actual, group.prediction, target == COUNT)))
    return predictions, table, dict(selection_policy=POLICY, selected_methods=selected,
        selected_ridge_alphas=alphas, per_origin=validation_coverage + coverage,
        selected_model_failure_examples=failures, selected_model_segment_metrics=segments,
        fallback_evaluation=evaluate_fallbacks(feature_tables, cfg))
