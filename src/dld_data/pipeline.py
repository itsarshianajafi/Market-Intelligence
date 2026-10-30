"""Prepare official DLD CSV exports without estimating missing transactions."""
import argparse
import json
import os
from pathlib import Path
import tempfile
from zipfile import BadZipFile
from urllib.parse import urlsplit
from urllib.request import urlopen
from urllib.error import HTTPError

import pandas as pd

from .sources import load_inputs, normalize_schema

COLUMNS = ["transaction_id", "transaction_date", "area", "property_type", "unit_type",
           "transaction_group", "price_aed", "year", "month",
           "area_m2", "price_per_m2_aed", "registration_type", "procedure"]

# Some old mortgage rows carry Hijri years 1416-1422.
MIN_YEAR, MAX_YEAR = 1900, 2100
MIN_SALE_PRICE_AED = 10_000
# Below this size price per m2 is unreliable (1,789 sales since 2020, some above 1M AED/m2).
MIN_AREA_M2 = 10


def download_csv(url, destination):
    """Download an explicitly supplied official CSV atomically, with TLS checks."""
    def official(value):
        parsed = urlsplit(value)
        return (parsed.scheme == "https" and parsed.hostname in {
            "data.dubai", "www.dubaipulse.gov.ae", "dubaipulse.gov.ae", "api.dubaipulse.gov.ae",
            "dubailand.gov.ae", "www.dubailand.gov.ae"}
            and not parsed.username and not parsed.password and parsed.port in (None, 443))
    if not official(url):
        raise ValueError("Use an HTTPS CSV URL hosted by Dubai Pulse or Dubai Land Department")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ValueError("Download destination already exists; choose another path")
    temp = None
    try:
        with urlopen(url, timeout=60) as response:
            if not official(response.url):
                raise ValueError("Download redirected outside supported official hosts")
            if 'html' in response.headers.get('Content-Type', '').lower():
                raise ValueError("Server returned HTML, not a CSV export")
            with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as output:
                temp = Path(output.name)
                total = 0
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > 1024 ** 3:
                        raise ValueError("Download exceeds 1 GiB; download manually")
                    output.write(chunk)
        os.replace(temp, destination)
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise ValueError(
                f"Official source denied access (HTTP {exc.code}). "
                "The provider may require registered API access; a portal or blob URL "
                "is not a public CSV download. No transaction data was downloaded."
            ) from exc
        raise
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def clean_transactions(raw, min_sale_price=MIN_SALE_PRICE_AED):
    """Normalize DLD fields and return valid records plus mutually exclusive counts.

    Invalid required values are rejected; missing optional labels stay empty.
    Exact duplicate normalized rows and conflicting repeated IDs are removed.
    All rows of a conflicting ID are excluded instead of choosing arbitrarily.
    Sales below min_sale_price are dropped as data errors after conflict removal.
    implausible_year_rows is an informational subset of invalid_rows.
    """
    raw, _ = normalize_schema(raw)
    df = pd.DataFrame(index=raw.index)
    for source, target in [('transaction_id', 'transaction_id'),
                           ('area_name_en', 'area'), ('property_type_en', 'property_type'),
                           ('property_sub_type_en', 'unit_type'),
                           ('trans_group_en', 'transaction_group'),
                           ('procedure_name_en', 'procedure')]:
        values = raw[source] if source in raw else pd.Series(pd.NA, index=raw.index, dtype='string')
        normalized = values.astype('string').str.strip().str.replace(r'\s+', ' ', regex=True)
        df[target] = normalized.mask(normalized.str.casefold().isin(['', 'null', 'none', 'n/a', 'nan']))
    area = (raw['procedure_area'] if 'procedure_area' in raw else pd.Series(pd.NA, index=raw.index, dtype='string'))
    area = pd.to_numeric(area.astype('string').str.strip().str.replace(',', '', regex=False), errors='coerce').astype('float64')
    df['area_m2'] = area.where(area.gt(0) & area.lt(float('inf')))
    reg = (raw['reg_type_en'] if 'reg_type_en' in raw else pd.Series(pd.NA, index=raw.index, dtype='string'))
    reg = reg.astype('string').str.casefold()
    df['registration_type'] = (pd.Series(pd.NA, index=raw.index, dtype='string')
        .mask(reg.str.contains('ready|existing', na=False), 'Ready')
        .mask(reg.str.contains('off', na=False), 'Off-Plan'))
    # DLD exports use day-first dates; ISO YYYY-MM-DD is also accepted explicitly.
    dates = raw['instance_date'].astype('string').str.strip()
    year = pd.to_numeric(dates.str.extract(r'(\d{4})')[0], errors='coerce')
    implausible = year.notna() & ~year.between(MIN_YEAR, MAX_YEAR)
    dates = dates.mask(implausible)
    parsed = pd.Series(pd.NaT, index=raw.index, dtype='datetime64[ns]')
    for fmt in ('%d-%m-%Y', '%d/%m/%Y', '%Y-%m-%d',
                '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M:%S.%f',
                '%Y-%m-%d %H:%M:%S'):
        parsed = parsed.fillna(pd.to_datetime(dates, format=fmt, errors='coerce'))
    future = parsed.gt(pd.Timestamp.now(tz='Asia/Dubai').tz_localize(None).normalize())
    df['transaction_date'] = parsed.mask(future)
    prices = raw['actual_worth'].astype('string').str.strip()
    # Only accept plain numbers or correctly grouped thousands, optionally decimal.
    valid_number = prices.str.fullmatch(r'[+]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?', na=False)
    df['price_aed'] = pd.to_numeric(prices.where(valid_number).str.replace(',', '', regex=False), errors='coerce')
    invalid = (df[['transaction_id', 'area', 'property_type']].isna().any(axis=1)
               | df.transaction_date.isna() | df.price_aed.isna()
               | (df.price_aed <= 0) | ~df.price_aed.lt(float('inf')))
    stats = {'input_rows': len(df), 'invalid_rows': int(invalid.sum()), 'implausible_year_rows': int(implausible.sum()),
             'future_date_rows': int(future.sum())}
    df = df.loc[~invalid].copy()
    duplicates = df.duplicated()
    stats['duplicate_rows'] = int(duplicates.sum())
    df = df.loc[~duplicates].copy()
    conflicts = df.transaction_id.duplicated(keep=False)
    stats['conflicting_id_rows'] = int(conflicts.sum())
    df = df.loc[~conflicts].copy()
    is_sale = df.transaction_group.str.casefold().eq('sales').fillna(False).astype(bool)
    low_price = is_sale & df.price_aed.lt(min_sale_price)
    stats['low_price_sales_rows'] = int(low_price.sum())
    df = df.loc[~low_price].copy()
    small_area = df.area_m2.lt(MIN_AREA_M2)
    stats['small_area_rows'] = int(small_area.sum())
    df['price_per_m2_aed'] = (df.price_aed / df.area_m2).round(2).mask(small_area)
    df['year'] = df.transaction_date.dt.year
    df['month'] = df.transaction_date.dt.strftime('%Y-%m')
    df['transaction_date'] = df.transaction_date.dt.strftime('%Y-%m-%d')
    df = df[COLUMNS].sort_values(['transaction_date', 'area', 'transaction_id']).reset_index(drop=True)
    stats['output_rows'] = len(df)
    return df, stats


def prepare(input_path, output_dir, source_url=None, min_sale_price=MIN_SALE_PRICE_AED):
    """Write reusable transactions, monthly sales aggregates, and audit metadata."""
    paths = [input_path] if isinstance(input_path, (str, Path)) else list(input_path)
    output_dir = Path(output_dir)
    targets = ['transactions_clean.csv', 'monthly_sales.csv', 'quality_report.json']
    if any((output_dir / name).exists() for name in targets):
        raise ValueError("Output files already exist; choose a new output directory")
    raw, manifests = load_inputs(paths)
    clean, stats = clean_transactions(raw, min_sale_price=min_sale_price)
    if clean.empty:
        raise ValueError(f"No valid transactions; nothing written. Counts: {stats}")
    output_dir.mkdir(parents=True, exist_ok=True)
    # Sales only: mortgages and gifts are not comparable market sale prices.
    sales = clean.loc[clean.transaction_group.str.casefold().eq('sales').fillna(False)]
    # Off-plan and ready sales are priced differently, so they are never mixed in one median.
    monthly = (sales.groupby(['area', 'property_type', 'unit_type', 'registration_type', 'month'],
                             dropna=False).agg(
        transaction_count=('transaction_id', 'size'),
        total_price_aed=('price_aed', 'sum'),
        median_price_aed=('price_aed', 'median'),
        median_area_m2=('area_m2', 'median'),
        median_price_per_m2_aed=('price_per_m2_aed', 'median')).reset_index())
    clean.to_csv(output_dir / targets[0], index=False)
    monthly.to_csv(output_dir / targets[1], index=False)
    report = {**stats, 'monthly_sales_rows': len(monthly), 'sales_transactions': len(sales),
              'min_sale_price_aed': min_sale_price, 'min_area_m2': MIN_AREA_M2,
              'inputs': manifests,
              'date_min': clean.transaction_date.min(), 'date_max': clean.transaction_date.max(),
              'missing_transaction_group_rows': int(clean.transaction_group.isna().sum()),
              'coverage_note': 'Only supplied records; completeness is not established.',
              'prepared_at_utc': pd.Timestamp.now(tz='UTC').isoformat(),
              'pandas_version': pd.__version__}
    if source_url:
        # A signed URL may contain credentials in its query; never persist them.
        parsed = urlsplit(source_url)
        report['download_source'] = parsed._replace(query='', fragment='').geturl()
    (output_dir / targets[2]).write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    """Run manual CSV preparation or download an explicitly supplied official CSV."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, nargs='+', required=True,
                        help='Official CSV/ZIP paths; supply all export parts together')
    parser.add_argument('--url', help='Optional verified official HTTPS CSV URL; not the catalogue page')
    parser.add_argument('--output-dir', type=Path, default=Path('data/processed'))
    parser.add_argument('--min-sale-price', type=float, default=MIN_SALE_PRICE_AED,
                        help='Drop Sales below this AED value as data errors (default 10000)')
    args = parser.parse_args()
    try:
        if args.url:
            if len(args.input) != 1 or args.input[0].suffix.lower() != '.csv':
                raise ValueError('--url requires exactly one .csv input destination')
            download_csv(args.url, args.input[0])
        report = prepare(args.input, args.output_dir, args.url, min_sale_price=args.min_sale_price)
    except (ValueError, OSError, BadZipFile, pd.errors.ParserError) as exc:
        parser.exit(1, f"Pipeline failed: {exc}\n")
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
