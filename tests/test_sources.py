"""Schema and multipart integration tests using artificial records, not market data."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile

import pandas as pd
from src.dld_data.pipeline import clean_transactions, prepare
from src.dld_data.sources import load_inputs


def native_row(**changes):
    return dict(TRANSACTION_NUMBER='ARTIFICIAL-1', INSTANCE_DATE='2026-01-31T00:00:00',
                AREA_EN='Test Area', PROP_TYPE_EN='Unit', TRANS_VALUE='1000',
                PROP_SB_TYPE_EN='Flat', GROUP_EN='Sales', **changes)


class SourceTests(unittest.TestCase):
    def test_native_source_mapping_and_timestamp(self):
        clean, _ = clean_transactions(pd.DataFrame([native_row()]))
        self.assertEqual(clean.iloc[0]['transaction_id'], 'ARTIFICIAL-1')
        self.assertEqual(clean.iloc[0]['price_aed'], 1000)
        self.assertEqual(clean.iloc[0]['transaction_date'], '2026-01-31')

    def test_display_header_mapping(self):
        frame = pd.DataFrame([{
            'Transaction Number': 'ARTIFICIAL-1', 'Transaction Date': '31/01/2026',
            'Area': 'Test Area', 'Property Type': 'Unit', 'Amount': '1,000',
            'Property Sub Type': 'Flat', 'Transaction Type': 'Sales',
        }])
        clean, report = clean_transactions(frame)
        self.assertEqual(report['output_rows'], 1)
        self.assertEqual(clean.iloc[0]['transaction_group'], 'Sales')

    def test_ambiguous_schema_rejected(self):
        frame = pd.DataFrame([{**native_row(), 'transaction_id': 'ARTIFICIAL-2',
                               'area_name_en': 'Test Area', 'property_type_en': 'Unit',
                               'actual_worth': '1000'}])
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            clean_transactions(frame)

    def test_zip_and_csv_parts_are_deduplicated_globally(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = native_row()
            second = {**first, 'TRANSACTION_NUMBER': 'ARTIFICIAL-2'}
            conflicting = {**first, 'TRANSACTION_NUMBER': 'ARTIFICIAL-3'}
            with ZipFile(root / 'parts.zip', 'w') as archive:
                # Paths stay inside the archive, never extracted onto disk.
                archive.writestr('../part1.csv', pd.DataFrame([first, conflicting]).to_csv(index=False))
                archive.writestr('part2.csv', pd.DataFrame([first, second]).to_csv(index=False))
            pd.DataFrame([{**conflicting, 'TRANS_VALUE': '2000'}]).to_csv(root / 'part3.csv', index=False)
            report = prepare([root / 'parts.zip', root / 'part3.csv'], root / 'out')
            self.assertEqual(report['input_rows'], 5)
            self.assertEqual(report['duplicate_rows'], 1)
            self.assertEqual(report['conflicting_id_rows'], 2)
            self.assertEqual(report['output_rows'], 2)
            self.assertEqual(len(report['inputs']), 2)
            self.assertEqual(len(report['inputs'][0]['tables']), 2)
            self.assertEqual(report['inputs'][0]['tables'][0]['schema'], 'dld_native')
            self.assertEqual(len(report['inputs'][0]['sha256']), 64)
            self.assertFalse((root.parent / 'part1.csv').exists())

    def test_duplicate_original_csv_header_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bad.csv'
            path.write_text('transaction_id,transaction_id,instance_date,area_name_en,property_type_en,actual_worth\n')
            with self.assertRaisesRegex(ValueError, 'Duplicate column'):
                load_inputs([path])

    def test_empty_zip_and_repeated_input_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'empty.zip'
            with ZipFile(path, 'w'):
                pass
            with self.assertRaisesRegex(ValueError, 'No CSV'):
                load_inputs([path])
            with self.assertRaisesRegex(ValueError, 'more than once'):
                load_inputs([path, path])

    def test_null_required_label_rejected(self):
        frame = pd.DataFrame([{**native_row(), 'AREA_EN': 'NULL'}])
        clean, report = clean_transactions(frame)
        self.assertTrue(clean.empty)
        self.assertEqual(report['invalid_rows'], 1)

    def test_missing_group_produces_empty_summary_with_headers(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            record = native_row()
            del record['GROUP_EN']
            pd.DataFrame([record]).to_csv(root / 'data.csv', index=False)
            report = prepare(root / 'data.csv', root / 'out')
            self.assertEqual(report['missing_transaction_group_rows'], 1)
            self.assertEqual(report['sales_transactions'], 0)
            summary = pd.read_csv(root / 'out/monthly_sales.csv')
            self.assertTrue(summary.empty)
            self.assertIn('transaction_count', summary.columns)

    def test_cli_zip_import_and_all_invalid_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'official-export-shape.zip'
            with ZipFile(path, 'w') as archive:
                archive.writestr('part.csv', pd.DataFrame([native_row()]).to_csv(index=False))
            result = subprocess.run([sys.executable, '-m', 'src.dld_data.pipeline',
                                     '--input', str(path), '--output-dir', str(root / 'out')],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['output_rows'], 1)
            pd.DataFrame([{**native_row(), 'TRANS_VALUE': '0'}]).to_csv(root / 'bad.csv', index=False)
            result = subprocess.run([sys.executable, '-m', 'src.dld_data.pipeline',
                                     '--input', str(root / 'bad.csv'), '--output-dir', str(root / 'bad-out')],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('No valid transactions', result.stderr)
            self.assertFalse((root / 'bad-out').exists())


if __name__ == '__main__':
    unittest.main()
