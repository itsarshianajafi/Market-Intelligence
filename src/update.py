"""Refresh everything from a new DLD export: clean it, then rerun Parts 2, 3 and 4.

    python -m src.update --input data/raw/export_1.csv data/raw/export_2.csv

Downloading stays manual (the DLD portal has a CAPTCHA). Every model is refitted from scratch.
If any step fails, the shared files, reports and configs are put back as they were.
"""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import re
import shutil
import tempfile

import pandas as pd

from .allocation import run as allocation
from .dashboard.data import load_bundle
from .dld_data.pipeline import prepare
from .forecasting import run as forecasting
from .forecasting.data import last_calendar_complete_quarter
from .trend_analysis import run as trends

SHARED, REPORTS = Path('data/shared'), Path('reports')
PART1_FILES = ['monthly_sales.csv', 'quality_report.json']


def advance_quarters(config_text, date_max):
    """Part 3's config with its quarters moved to the newest complete quarter in the data.

    Only the three values change, so the file keeps its layout and the diff stays small.
    """
    latest = last_calendar_complete_quarter(date_max)
    values = {'origin_quarter': latest, 'test_end': latest, 'forecast_quarter': latest + 1}
    for key, quarter in values.items():
        config_text, count = re.subn(rf'("{key}":\s*)"\d{{4}}Q[1-4]"', rf'\g<1>"{quarter}"', config_text)
        if count != 1:
            raise ValueError(f'Could not find {key} in the Part 3 config')
    return config_text


@contextmanager
def restored_on_failure(paths):
    """Keep a copy of files and folders; if the block fails, put them back exactly."""
    with tempfile.TemporaryDirectory(prefix='update-backup-') as folder:
        copies = {}
        for index, path in enumerate(map(Path, paths)):
            if path.exists():
                copies[path] = Path(folder) / str(index)
                (shutil.copytree if path.is_dir() else shutil.copy2)(path, copies[path])
        try:
            yield
        except BaseException:
            for path in map(Path, paths):
                if path.is_dir():
                    shutil.rmtree(path)
                elif path.exists():
                    path.unlink()
                if path in copies:
                    (shutil.copytree if copies[path].is_dir() else shutil.copy2)(copies[path], path)
            raise


def update(inputs, output_dir):
    """Returns a short summary of the refreshed snapshot."""
    part1 = prepare(inputs, output_dir)     # refuses an output folder that already has results
    with restored_on_failure([SHARED, REPORTS, forecasting.DEFAULT_CONFIG]):
        for name in PART1_FILES:
            shutil.copy2(Path(output_dir) / name, SHARED / name)
        config = forecasting.DEFAULT_CONFIG
        config.write_text(advance_quarters(config.read_text(), part1['date_max']))
        trends.run(json.loads(trends.DEFAULT_CONFIG.read_text()))
        forecasting.run(json.loads(config.read_text()))
        allocation.run(json.loads(allocation.DEFAULT_CONFIG.read_text()))
        bundle = load_bundle()      # the same consistency checks the dashboard makes
    manifest = bundle['forecast_manifest']
    return {'records': f"{part1['date_min']} to {part1['date_max']}", 'sales': part1['sales_transactions'],
            'last_complete_quarter': manifest['origin_quarter'], 'forecast_quarter': manifest['forecast_quarter'],
            'agents_placed': int(bundle['allocation'].agents.sum()), 'cleaned_export': str(output_dir)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--input', type=Path, nargs='+', required=True,
                        help='Official CSV/ZIP export files; give all parts of one export together')
    parser.add_argument('--output-dir', type=Path,
                        help='Where the cleaned export goes (default: data/processed/update-<date-time>)')
    args = parser.parse_args()
    output_dir = args.output_dir or Path('data/processed') / f'update-{pd.Timestamp.now():%Y-%m-%d-%H%M}'
    try:
        summary = update(args.input, output_dir)
    except (ValueError, KeyError, OSError, pd.errors.ParserError) as exc:
        parser.exit(1, f'Update failed. Shared files, reports and configs are as they were: {exc}\n')
    print(json.dumps(summary, indent=2))
    print('Updated. Run the tests, look at the dashboard, then commit data/shared, reports and the Part 3 config.')


if __name__ == '__main__':
    main()
