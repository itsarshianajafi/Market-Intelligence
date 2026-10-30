"""Read documented English DLD exports, including CSV parts inside ZIP files."""
import csv
import hashlib
import io
from pathlib import Path
from zipfile import ZipFile

import pandas as pd

DLD_CATALOGUE = 'https://dubailand.gov.ae/en/open-data/real-estate-data/'
PULSE_CATALOGUE = 'https://data.dubai/en/l/470061'
REQUIRED = {'transaction_id', 'instance_date', 'area_name_en',
            'property_type_en', 'actual_worth'}
CANONICAL = [*sorted(REQUIRED), 'property_sub_type_en', 'trans_group_en',
             'procedure_area', 'reg_type_en']
# Native CSV keys are supplied to DLD's export service by getExportHeader in
# https://dubailand.gov.ae/scripts/publicData.js. Display labels are taken from
# its English Transactions table. No private API or credentials are used.
SCHEMAS = {
    'dubai_pulse': {key: key for key in CANONICAL},
    'dld_native': {
        'transaction_id': 'transaction_number', 'instance_date': 'instance_date',
        'area_name_en': 'area_en', 'property_type_en': 'prop_type_en',
        'actual_worth': 'trans_value', 'property_sub_type_en': 'prop_sb_type_en',
        'trans_group_en': 'group_en',
        'procedure_area': 'procedure_area', 'reg_type_en': 'is_offplan_en',
    },
    # Header names for procedure_area and reg_type_en in dld_display are unconfirmed.
    'dld_display': {
        'transaction_id': 'transaction number', 'instance_date': 'transaction date',
        'area_name_en': 'area', 'property_type_en': 'property type',
        'actual_worth': 'amount', 'property_sub_type_en': 'property sub type',
        'trans_group_en': 'transaction type',
    },
}
MAX_ARCHIVE_BYTES = 2 * 1024 ** 3


def identify_schema(columns):
    """Return the explicit schema and source-to-canonical mapping; never guess."""
    names = pd.Index(columns).astype(str).str.strip().str.lower()
    if names.duplicated().any():
        raise ValueError('Duplicate column names after normalization')
    matches = [(name, mapping) for name, mapping in SCHEMAS.items()
               if {mapping[key] for key in REQUIRED}.issubset(names)]
    if len(matches) != 1:
        raise ValueError('Missing DLD columns or ambiguous schema. Expected English '
                         'Dubai Pulse fields, DLD native fields, or DLD display headers; '
                         'see README for the required columns.')
    name, mapping = matches[0]
    return name, {source: target for target, source in mapping.items() if source in names}


def normalize_schema(raw):
    """Map one recognized source to the internal Dubai Pulse column names."""
    name, mapping = identify_schema(raw.columns)
    raw = raw.copy()
    raw.columns = raw.columns.astype(str).str.strip().str.lower()
    return raw[list(mapping)].rename(columns=mapping), name


def read_table(binary_stream):
    """Check the original header and load only relevant fields into pandas."""
    with io.TextIOWrapper(binary_stream, encoding='utf-8-sig', newline='') as text:
        header = next(csv.reader(text), None)
        if not header:
            raise ValueError('Empty CSV file')
        schema, mapping = identify_schema(header)
        selected = [column for column in header if column.strip().lower() in mapping]
        text.seek(0)
        frame = pd.read_csv(text, dtype='string', keep_default_na=False, usecols=selected)
        frame.columns = frame.columns.str.strip().str.lower()
        return frame.rename(columns=mapping), schema


def load_inputs(paths):
    """Read every CSV part, without ZIP extraction, recording per-file provenance."""
    frames, manifests = [], []
    resolved = [Path(path).resolve() for path in paths]
    if len(resolved) != len(set(resolved)):
        raise ValueError('The same input path was supplied more than once')
    for path in resolved:
        with path.open('rb') as source:
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
        manifest = {'input_file': path.name, 'sha256': digest, 'tables': []}

        def add(stream, name):
            frame, schema = read_table(stream)
            frames.append(frame)
            manifest['tables'].append({
                'name': name, 'schema': schema, 'rows': len(frame),
                'catalogue_url': PULSE_CATALOGUE if schema == 'dubai_pulse' else DLD_CATALOGUE,
            })

        if path.suffix.lower() == '.zip':
            with ZipFile(path) as archive:
                members = [m for m in archive.infolist() if not m.is_dir() and m.filename.lower().endswith('.csv')]
                if not members:
                    raise ValueError(f'No CSV files in {path.name}')
                if sum(m.file_size for m in members) > MAX_ARCHIVE_BYTES:
                    raise ValueError('CSV contents of ZIP exceed the 2 GiB uncompressed limit')
                for member in members:
                    with archive.open(member) as stream:
                        add(stream, member.filename)
        elif path.suffix.lower() == '.csv':
            with path.open('rb') as stream:
                add(stream, path.name)
        else:
            raise ValueError('Inputs must be official .csv exports or .zip archives containing them')
        manifests.append(manifest)
    if not frames:
        raise ValueError('At least one input CSV or ZIP is required')
    return pd.concat(frames, ignore_index=True), manifests
