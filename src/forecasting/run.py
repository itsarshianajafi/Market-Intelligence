"""Validate, backtest, select on validation, and export a Q3-based Q4 projection."""
import argparse
import hashlib
import importlib.metadata
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .data import (COUNT, PRICE, KEYS, TARGETS, WARNINGS, build_panel, fingerprint,
                   load_inputs, quarter, validate_config)
from .evaluate import POLICY, evaluate
from .features import FEATURES, fallback_supported, make_features, origin_candidates, training_rows
from .models import NAIVE, SEASONAL, fit_ridge, predict_ridge

DEFAULT_CONFIG = Path(__file__).with_name('config.json')
SCHEMA_VERSION = '1.0'
OUTPUT_COLUMNS = ['schema_version', 'run_id', 'area', 'registration_type', 'property_scope',
    'origin_quarter', 'forecast_quarter', 'horizon_quarters', 'target', 'forecast_value', 'unit',
    'model_id', 'selection_basis', 'status', 'reason', 'data_cutoff_date', 'provisional_input',
    'history_quarters', 'last_actual', 'price_coverage']
OUTPUT_KEY = ['schema_version', 'run_id'] + KEYS + ['property_scope', 'origin_quarter', 'forecast_quarter', 'target']


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, default=str, allow_nan=False) + '\n')


def clean_json(data):
    """Convert pandas metadata to strict JSON, including unavailable numeric values."""
    if isinstance(data, dict):
        return {str(k): clean_json(v) for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        return [clean_json(v) for v in data]
    if isinstance(data, (np.integer, np.bool_)):
        return data.item()
    if isinstance(data, (float, np.floating)):
        return float(data) if np.isfinite(data) else None
    if isinstance(data, pd.Period):
        return str(data)
    return data


def deployment(feature_tables, selected, alphas, cfg, run_id, cutoff):
    output = []
    origin = quarter(cfg['origin_quarter'])
    for target, features in feature_tables.items():
        current = origin_candidates(features, origin, cfg)
        model = None
        if selected[target] and selected[target].startswith('ridge_'):
            model = fit_ridge(training_rows(features, origin, cfg), target, alphas[target])
        primary = current.origin_reason.eq('')
        fallback = fallback_supported(current, cfg)
        learned = pd.Series(np.nan, index=current.index)
        if model is not None and primary.any():
            learned.loc[primary] = predict_ridge(model, current.loc[primary], target)
        for idx, row in current.iterrows():
            method = selected[target]
            value, status, reason, actual_method = np.nan, 'insufficient_data', '', 'none'
            basis = 'validation_MAE_common_rows_2024'
            if primary.loc[idx] and method:
                if method == NAIVE:
                    value = row.naive
                elif method == SEASONAL:
                    value = row.seasonal_naive
                else:
                    value = learned.loc[idx]
                if np.isfinite(value):
                    status, actual_method = 'ok', method
            if status != 'ok':
                reason = row.origin_reason or ('no_valid_validation_cohort' if not method else 'selected_model_unavailable')
                if fallback.loc[idx]:
                    value, status, actual_method = row.naive, 'fallback', NAIVE
                    basis = 'predeclared_current_level_fallback'
                    reason = 'Fallback to supported current level: ' + reason
                else:
                    if row.month_coverage < 3 or (target == PRICE and (pd.isna(row.price_weight) or row.price_weight == 0)):
                        status = 'missing_input'
                        reason = 'Origin lacks three observed months or usable price input; ' + reason
                    elif target == PRICE and pd.isna(row.naive):
                        reason = 'Origin price fails sales, coverage or priced-month support; ' + reason
                    else:
                        reason = 'Not enough supported history for primary or fallback; ' + reason
            output.append(dict(schema_version=SCHEMA_VERSION, run_id=run_id,
                area=row.area, registration_type=row.registration_type, property_scope='Unit|Villa',
                origin_quarter=cfg['origin_quarter'], forecast_quarter=cfg['forecast_quarter'],
                horizon_quarters=1, target=target, forecast_value=value, unit=TARGETS[target],
                model_id=actual_method, selection_basis=basis, status=status, reason=reason,
                data_cutoff_date=cutoff, provisional_input=bool(row.provisional),
                history_quarters=int(row.history_quarters), last_actual=row.naive,
                price_coverage=row.price_coverage if target == PRICE else np.nan))
    return pd.DataFrame(output, columns=OUTPUT_COLUMNS).sort_values(KEYS + ['target']).reset_index(drop=True)


def validate_output(out, manifest):
    """Also used on read-back files. Null predictions must survive CSV round trips."""
    if list(out.columns) != OUTPUT_COLUMNS or out.empty or out.duplicated(OUTPUT_KEY).any():
        raise ValueError('Invalid output schema, empty output or duplicate forecast key')
    if not out.status.isin(['ok', 'fallback', 'insufficient_data', 'missing_input']).all():
        raise ValueError('Unknown output status')
    if not out.target.isin(TARGETS).all() or not out.unit.eq(out.target.map(TARGETS)).all():
        raise ValueError('Invalid target/unit')
    valid = out.status.isin(['ok', 'fallback'])
    if not np.isfinite(out.loc[valid, 'forecast_value']).all():
        raise ValueError('Available predictions must be finite')
    if not out.loc[~valid, 'forecast_value'].isna().all():
        raise ValueError('Unavailable predictions must be blank/null, never zero')
    if out.loc[~valid, 'reason'].fillna('').eq('').any() or out.loc[out.status.eq('fallback'), 'reason'].fillna('').eq('').any():
        raise ValueError('Unavailable and fallback rows need reasons')
    if out.loc[valid & out.target.eq(COUNT), 'forecast_value'].lt(0).any() or out.loc[valid & out.target.eq(PRICE), 'forecast_value'].le(0).any():
        raise ValueError('Forecast outside target domain')
    if not out.horizon_quarters.eq(1).all() or not out.property_scope.eq('Unit|Villa').all():
        raise ValueError('Invalid horizon or scope')
    if not out.provisional_input.map(lambda x: isinstance(x, (bool, np.bool_))).all():
        raise ValueError('provisional_input must be boolean')
    if not out.registration_type.isin(['Ready', 'Off-Plan']).all() or out.area.fillna('').eq('').any():
        raise ValueError('Invalid segment identity')
    if not out.history_quarters.ge(0).all() or not out.history_quarters.mod(1).eq(0).all():
        raise ValueError('Invalid history count')
    coverage = out.price_coverage.dropna()
    if not coverage.between(0, 1).all():
        raise ValueError('Invalid price coverage')
    for name in ['run_id', 'schema_version', 'origin_quarter', 'forecast_quarter', 'data_cutoff_date']:
        if not out[name].astype(str).eq(str(manifest[name])).all():
            raise ValueError(f'Manifest mismatch: {name}')
    if quarter(manifest['forecast_quarter']) != quarter(manifest['origin_quarter']) + 1:
        raise ValueError('Manifest horizon mismatch')
    if out.loc[valid, 'model_id'].eq('none').any():
        raise ValueError('Available rows must identify their model')
    if not out.groupby(KEYS, dropna=False).target.agg(set).map(lambda s: s == set(TARGETS)).all():
        raise ValueError('Each segment needs both targets')


def run(cfg):
    validate_config(cfg)
    generated = datetime.now(timezone.utc).isoformat()
    monthly, quality, profile = load_inputs(cfg)
    panel = build_panel(monthly, cfg)
    feature_tables = {target: make_features(panel, target, cfg) for target in TARGETS}
    versions = {}
    for package in ['pandas', 'numpy', 'scikit-learn', 'scipy', 'matplotlib', 'joblib', 'threadpoolctl',
                    'pillow', 'contourpy', 'cycler', 'fonttools', 'kiwisolver', 'pyparsing',
                    'python-dateutil', 'six', 'pytz', 'tzdata', 'narwhals', 'cloudpickle']:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = 'not_installed'
    versions['python'] = platform.python_version()
    config_hash = hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()
    code_hashes = {p.name: fingerprint(p) for p in sorted(Path(__file__).parent.glob('*.py'))}
    identity = dict(source_hashes=profile['source_hashes'], config_sha256=config_hash,
                    code_hashes=code_hashes, versions=versions)
    run_id = 'part3-' + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
    predictions, metric_table, evaluation = evaluate(feature_tables, cfg)
    out = deployment(feature_tables, evaluation['selected_methods'], evaluation['selected_ridge_alphas'],
                     cfg, run_id, quality['date_max'])
    profile.update(dict(segments=len(panel[KEYS].drop_duplicates()), panel_rows=len(panel),
        selected_sales=int(monthly.transaction_count.sum()),
        partial_segment_quarters=int(panel.month_coverage.between(1, 2).sum()),
        unknown_segment_quarters=int(panel.month_coverage.eq(0).sum()),
        supported_target_quarters={t: int(panel[t].notna().sum()) for t in TARGETS},
        output_status_counts=out.groupby('target').status.value_counts().unstack(fill_value=0).to_dict('index')))
    manifest = dict(schema_version=SCHEMA_VERSION, run_id=run_id, generated_at_utc=generated,
        origin_quarter=cfg['origin_quarter'], last_eligible_historical_quarter=cfg['origin_quarter'],
        forecast_quarter=cfg['forecast_quarter'], horizon_quarters=1, data_cutoff_date=quality['date_max'],
        historical_input_end_date=str(quarter(cfg['origin_quarter']).end_time.date()),
        publication_context='Q3-based projection generated during Q4; not published in September',
        **identity, selected_methods=evaluation['selected_methods'], selected_ridge_alphas=evaluation['selected_ridge_alphas'],
        selection_policy=POLICY, feature_columns=FEATURES,
        evaluation_periods={k: cfg[k] for k in ['train_start', 'validation_start', 'validation_end', 'test_start', 'test_end']},
        transformations={COUNT: 'log1p target and historical levels, expm1 inverse; clamp negative count predictions to zero',
                         PRICE: 'log target and historical levels, exp inverse; nonpositive/nonfinite predictions unavailable'},
        population={'property_scope': 'Unit|Villa', 'segment_keys': KEYS,
                    'universe': 'Every segment with a supplied scoped row between panel_start and origin, including unsupported segments',
                    'subtypes': 'Retained as source cells; blank subtype remains missing, distinct from literal labels'},
        eligibility={'count': 'All three segment months observed; sums exact for supplied rows. Zero requires numeric observed zero rows.',
                     'price': 'Count quarter supported, >=min_price_sales, all three months priced, >=min_price_coverage',
                     'history_quarters': 'Number of supported target quarters from panel_start through origin',
                     'last_actual': 'Supported origin-quarter target only; null if unsupported, never stale',
                     'price_coverage': 'Origin positive-median cell count weights / observed counts; blank for count and zero denominator',
                     'thresholds': {k: cfg[k] for k in ['min_training_pairs', 'min_fallback_quarters', 'min_price_sales', 'min_price_coverage']},
                     'provisional': f"Latest {cfg['provisional_quarters']} historical quarter(s); source corrections remain possible"},
        target_definitions={COUNT: 'Sum transaction_count for supplied Unit/Villa Sales cells in a supported area/registration quarter',
            PRICE: 'exp(sum(n_i * log(p_i)) / sum(n_i)) over positive monthly median_price_per_m2_aed, weighted by transaction_count'},
        units=TARGETS, status_definitions={'ok': 'Validation-selected method on primary supported cohort',
            'fallback': 'Predeclared supported-current-level naive fallback; outside common evaluation cohort',
            'insufficient_data': 'Inputs exist but history or price-support gates fail',
            'missing_input': 'Origin lacks three observed months or usable price inputs'},
        output_columns=OUTPUT_COLUMNS, output_key=OUTPUT_KEY,
        source_evidence=profile['source_evidence'],
        source_coverage_note=quality['coverage_note'], upstream_raw_provenance_unverified=quality['inputs'],
        warnings=WARNINGS, output_rows=len(out), status_counts=profile['output_status_counts'])
    fallback = evaluation['fallback_evaluation']
    manifest['fallback_evaluation'] = dict(report=str(Path(cfg['report_dir']) / 'evaluation.json'),
        section='fallback_evaluation', scope=fallback['scope'],
        runtime_failure_fallbacks=fallback['runtime_failure_fallbacks'],
        summaries=[s for s in fallback['summaries'] if s['forecast_quarter'] == 'all'],
        limitations=fallback['limitations'])
    validate_output(out, manifest)
    report_dir = Path(cfg['report_dir'])
    report_dir.mkdir(parents=True, exist_ok=True)
    for name in ['output', 'manifest']:
        Path(cfg[name]).parent.mkdir(parents=True, exist_ok=True)
    predictions['run_id'] = run_id
    metric_table['run_id'] = run_id
    predictions.to_csv(report_dir / 'predictions.csv', index=False)
    metric_table.to_csv(report_dir / 'metrics.csv', index=False)
    evaluation.update(dict(run_id=run_id, generated_at_utc=generated, warnings=WARNINGS,
        splits={k: cfg[k] for k in ['train_start', 'validation_start', 'validation_end', 'test_start', 'test_end']},
        metrics=metric_table.loc[metric_table.forecast_quarter.eq('all')].to_dict('records')))
    write_json(report_dir / 'evaluation.json', clean_json(evaluation))
    write_json(report_dir / 'run_config.json', dict(config=cfg, **identity))
    write_json(report_dir / 'data_profile.json', clean_json(profile))
    if cfg['figures']:
        from .figures import make_all
        make_all(predictions, metric_table, evaluation['selected_methods'], report_dir)
    out.to_csv(cfg['output'], index=False)
    manifest['output_sha256'] = fingerprint(cfg['output'])
    write_json(cfg['manifest'], clean_json(manifest))
    # Consumer-style read back, independent of any fitted model object.
    reread = pd.read_csv(cfg['output'], keep_default_na=False,
                         na_values={'forecast_value': [''], 'last_actual': [''], 'price_coverage': ['']},
                         dtype={'schema_version': str})
    validate_output(reread, json.loads(Path(cfg['manifest']).read_text()))
    if any(fingerprint(p) != expected for p, expected in profile['source_hashes'].items()):
        raise ValueError('Upstream input changed during execution; outputs are not a coherent snapshot')
    return out, clean_json(evaluation), clean_json(manifest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    try:
        out, evaluation, manifest = run(json.loads(args.config.read_text()))
    except (ValueError, KeyError, OSError, pd.errors.ParserError) as exc:
        parser.exit(1, f'Forecasting failed: {exc}\n')
    print(json.dumps(dict(run_id=manifest['run_id'], selected_methods=evaluation['selected_methods'],
        output_rows=len(out), status_counts=manifest['status_counts']), indent=2))


if __name__ == '__main__':
    main()
