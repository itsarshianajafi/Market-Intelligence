"""Read a coherent set of shared outputs without changing source files."""
import json
from pathlib import Path

import pandas as pd

from src.forecasting.data import fingerprint
from src.forecasting.run import validate_output

ROOT = Path(__file__).resolve().parents[2]
SHARED = ROOT / 'data/shared'
FILES = ['monthly_sales.csv', 'quality_report.json', 'market_trends.csv',
         'forecasts.csv', 'forecast_manifest.json', 'allocation.csv', 'allocation_manifest.json']


def source_signature():
    """Invalidate the UI cache and custom plans whenever an upstream file changes."""
    paths = [SHARED / name for name in FILES] + [ROOT / 'reports/part3/predictions.csv']
    return tuple((str(path), path.stat().st_mtime_ns, path.stat().st_size) for path in paths)


def load_bundle():
    """Validate source fingerprints before exposing forecasts or recommendations."""
    before = source_signature()
    quality = json.loads((SHARED / 'quality_report.json').read_text())
    forecast_manifest = json.loads((SHARED / 'forecast_manifest.json').read_text())
    allocation_manifest = json.loads((SHARED / 'allocation_manifest.json').read_text())
    for manifest in [forecast_manifest, allocation_manifest]:
        for name, expected in manifest['source_hashes'].items():
            path = ROOT / name
            if fingerprint(path) != expected:
                raise ValueError(f'{Path(name).name} differs from the saved analysis. Refresh Parts 2–4 together.')
    for name, manifest in [('forecasts.csv', forecast_manifest), ('allocation.csv', allocation_manifest)]:
        if fingerprint(SHARED / name) != manifest['output_sha256']:
            raise ValueError(f'{name} does not match its manifest. Regenerate its outputs.')
    if allocation_manifest['forecast_run_id'] != forecast_manifest['run_id']:
        raise ValueError('The allocation and forecasts belong to different runs.')
    monthly = pd.read_csv(SHARED / 'monthly_sales.csv')
    if len(monthly) != quality['monthly_sales_rows'] or int(monthly.transaction_count.sum()) != quality['sales_transactions']:
        raise ValueError('Monthly sales do not reconcile with the quality report.')
    forecasts = pd.read_csv(SHARED / 'forecasts.csv', dtype={'schema_version': str})
    validate_output(forecasts, forecast_manifest)
    monthly['date'] = pd.to_datetime(monthly.month + '-01')
    trends = pd.read_csv(SHARED / 'market_trends.csv')
    allocation = pd.read_csv(SHARED / 'allocation.csv', dtype={'schema_version': str})
    if before != source_signature():
        raise ValueError('Source files changed while reading. Wait for the update to finish and refresh.')
    return dict(monthly=monthly, quality=quality, forecasts=forecasts,
                forecast_manifest=forecast_manifest, allocation_manifest=allocation_manifest,
                trends=trends, allocation=allocation)


def filter_rows(frame, area='All areas', registration='Both'):
    """Apply the same segment identity to each view; empty results remain empty."""
    selected = frame
    if area != 'All areas':
        selected = selected[selected.area.eq(area)]
    if registration != 'Both':
        selected = selected[selected.registration_type.eq(registration)]
    return selected.copy()


def monthly_summary(frame):
    """Sum counts and consideration; do not present averages of medians as medians."""
    return frame.groupby('date')[['transaction_count', 'total_price_aed']].sum().rename(
        columns={'transaction_count': 'Sales', 'total_price_aed': 'Transaction value (AED)'})
