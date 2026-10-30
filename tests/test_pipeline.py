"""Artificial test cases only: these are not real property transactions."""
import tempfile
from datetime import date, timedelta
import io
from urllib.error import HTTPError
from pathlib import Path
import unittest
from unittest.mock import patch

import pandas as pd
from src.dld_data.pipeline import clean_transactions, prepare, download_csv


def row(**changes):
    data = dict(transaction_id='TEST-1', instance_date='31-01-2025',
                area_name_en=' Test   Area ', property_type_en='Unit',
                property_sub_type_en='Flat', actual_worth='1,200,000', trans_group_en='Sales')
    return {**data, **changes}


class PreparationTests(unittest.TestCase):
    def test_normalization_and_duplicates(self):
        df, report = clean_transactions(pd.DataFrame([row(), row()]))
        self.assertEqual(len(df), 1)
        self.assertEqual(report['duplicate_rows'], 1)
        self.assertEqual(df.iloc[0]['area'], 'Test Area')
        self.assertEqual(df.iloc[0]['transaction_date'], '2025-01-31')
        self.assertEqual(df.iloc[0]['price_aed'], 1200000)

    def test_reject_invalid_required_values(self):
        changes = [{'actual_worth': x} for x in ['0', '-5', 'NaN', 'inf', '12,34', '']]
        changes += [{'instance_date': '31/02/2025'}, {'area_name_en': ''}, {'transaction_id': ''}]
        df, report = clean_transactions(pd.DataFrame([row(**x) for x in changes]))
        self.assertTrue(df.empty)
        self.assertEqual(report['invalid_rows'], len(changes))

    def test_conflicting_ids_excluded(self):
        df, report = clean_transactions(pd.DataFrame([row(), row(actual_worth='100')]))
        self.assertTrue(df.empty)
        self.assertEqual(report['conflicting_id_rows'], 2)

    def test_missing_optional_and_iso_dates(self):
        data = row(instance_date='2025-02-01')
        del data['property_sub_type_en']
        df, _ = clean_transactions(pd.DataFrame([data]))
        self.assertTrue(pd.isna(df.iloc[0]['unit_type']))
        self.assertEqual(df.iloc[0]['month'], '2025-02')

    def test_schema_error(self):
        with self.assertRaisesRegex(ValueError, 'Missing DLD columns'):
            clean_transactions(pd.DataFrame({'price': [1]}))

    def test_full_csv_workflow_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pd.DataFrame([row(), row(transaction_id='TEST-2', actual_worth='800000'),
                          row(transaction_id='TEST-3', trans_group_en='Mortgages')]).to_csv(root / 'raw.csv', index=False)
            report = prepare(root / 'raw.csv', root / 'out')
            self.assertEqual(report['output_rows'], 3)
            monthly = pd.read_csv(root / 'out/monthly_sales.csv')
            self.assertEqual(monthly.iloc[0]['transaction_count'], 2)
            self.assertEqual(monthly.iloc[0]['median_price_aed'], 1000000)
            self.assertTrue((root / 'out/quality_report.json').exists())
            with self.assertRaisesRegex(ValueError, 'already exist'):
                prepare(root / 'raw.csv', root / 'out')

    def test_official_current_domain_download(self):
        with tempfile.TemporaryDirectory() as folder:
            response = io.BytesIO(b'transaction_id,actual_worth\nTEST-1,100\n')
            response.url = 'https://data.dubai/test.csv'
            response.headers = {'Content-Type': 'text/csv'}
            destination = Path(folder) / 'download.csv'
            with patch('src.dld_data.pipeline.urlopen', return_value=response):
                download_csv(response.url, destination)
            self.assertTrue(destination.read_bytes().startswith(b'transaction_id,'))

    def test_rejected_portal_html_is_not_saved(self):
        with tempfile.TemporaryDirectory() as folder:
            response = io.BytesIO(b'<html>Request Rejected</html>')
            response.url = 'https://data.dubai/en/l/470061'
            response.headers = {'Content-Type': 'text/html; charset=utf-8'}
            with patch('src.dld_data.pipeline.urlopen', return_value=response):
                with self.assertRaisesRegex(ValueError, 'HTML'):
                    download_csv(response.url, Path(folder) / 'data.csv')
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_api_access_denied_is_clear(self):
        with tempfile.TemporaryDirectory() as folder:
            url = 'https://api.dubaipulse.gov.ae/open/dld/dld_transactions-open-api'
            error = HTTPError(url, 401, 'Unauthorized', {}, None)
            self.addCleanup(error.close)
            with patch('src.dld_data.pipeline.urlopen', side_effect=error):
                with self.assertRaisesRegex(ValueError, 'registered API access'):
                    download_csv(url, Path(folder) / 'data.csv')
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_download_rejects_unofficial_source(self):
        with patch('src.dld_data.pipeline.urlopen') as request:
            with self.assertRaises(ValueError):
                download_csv('https://example.com/data.csv', 'unused.csv')
            request.assert_not_called()

    def test_impossible_hijri_year_is_rejected_not_fatal(self):
        valid = row()
        hijri = row(transaction_id='TEST-HIJRI', instance_date='1420-01-30', trans_group_en='Mortgages')
        df, report = clean_transactions(pd.DataFrame([valid, hijri]))
        self.assertEqual(len(df), 1)
        self.assertEqual(report['invalid_rows'], 1)
        self.assertEqual(report['implausible_year_rows'], 1)

    def test_low_price_sales_dropped_but_other_groups_kept(self):
        s1 = row(transaction_id='TEST-SALE-1', actual_worth='1,200,000', trans_group_en='Sales')
        s2 = row(transaction_id='TEST-SALE-2', actual_worth='100', trans_group_en='Sales')
        m1 = row(transaction_id='TEST-MORT-1', actual_worth='100', trans_group_en='Mortgages')
        df, report = clean_transactions(pd.DataFrame([s1, s2, m1]))
        self.assertEqual(report['low_price_sales_rows'], 1)
        self.assertEqual(set(df['transaction_id']), {'TEST-SALE-1', 'TEST-MORT-1'})
        self.assertEqual(report['input_rows'],
                         report['invalid_rows'] + report['duplicate_rows'] +
                         report['conflicting_id_rows'] + report['low_price_sales_rows'] +
                         report['output_rows'])
        df2, report2 = clean_transactions(pd.DataFrame([s1, s2, m1]), min_sale_price=50)
        self.assertEqual(report2['low_price_sales_rows'], 0)

    def test_area_price_per_m2_and_registration_type(self):
        r1 = row(transaction_id='TEST-1', actual_worth='1,200,000', procedure_area='100', reg_type_en='Existing Properties')
        r2 = row(transaction_id='TEST-2', actual_worth='1,200,000', procedure_area='50', reg_type_en='Off-Plan Properties')
        r3 = row(transaction_id='TEST-3', actual_worth='1,200,000', procedure_area='0', reg_type_en='')
        df, _ = clean_transactions(pd.DataFrame([r1, r2, r3]))
        row1 = df.loc[df.transaction_id == 'TEST-1'].iloc[0]
        row2 = df.loc[df.transaction_id == 'TEST-2'].iloc[0]
        row3 = df.loc[df.transaction_id == 'TEST-3'].iloc[0]
        self.assertEqual(row1['price_per_m2_aed'], 12000)
        self.assertEqual(row1['registration_type'], 'Ready')
        self.assertEqual(row2['price_per_m2_aed'], 24000)
        self.assertEqual(row2['registration_type'], 'Off-Plan')
        self.assertTrue(pd.isna(row3['area_m2']))
        self.assertTrue(pd.isna(row3['price_per_m2_aed']))
        self.assertTrue(pd.isna(row3['registration_type']))

    def test_monthly_sales_splits_offplan_and_ready(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            r1 = row(transaction_id='T-1', actual_worth='1,200,000', procedure_area='100', reg_type_en='Ready')
            r2 = row(transaction_id='T-2', actual_worth='1,000,000', procedure_area='50', reg_type_en='Off-Plan')
            r3 = row(transaction_id='T-3', actual_worth='1,400,000', procedure_area='50', reg_type_en='Off-Plan')
            pd.DataFrame([r1, r2, r3]).to_csv(root / 'raw.csv', index=False)
            prepare(root / 'raw.csv', root / 'out')
            monthly = pd.read_csv(root / 'out/monthly_sales.csv').set_index('registration_type')
            self.assertEqual(len(monthly), 2)
            self.assertEqual(monthly.loc['Ready', 'median_price_per_m2_aed'], 12000)
            self.assertEqual(monthly.loc['Off-Plan', 'transaction_count'], 2)
            self.assertEqual(monthly.loc['Off-Plan', 'median_price_per_m2_aed'], 24000)

    def test_future_dates_rejected(self):
        future = (date.today() + timedelta(days=2)).isoformat()
        df, report = clean_transactions(pd.DataFrame([row(), row(transaction_id='TEST-FUTURE', instance_date=future)]))
        self.assertEqual(list(df.transaction_id), ['TEST-1'])
        self.assertEqual(report['invalid_rows'], 1)
        self.assertEqual(report['future_date_rows'], 1)

    def test_small_area_keeps_row_but_no_price_per_m2(self):
        df, report = clean_transactions(pd.DataFrame([row(procedure_area='2')]))
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]['area_m2'], 2)
        self.assertTrue(pd.isna(df.iloc[0]['price_per_m2_aed']))
        self.assertEqual(report['small_area_rows'], 1)

    def test_procedure_name_is_kept(self):
        df, _ = clean_transactions(pd.DataFrame([row(procedure_name_en='Lease to Own Registration')]))
        self.assertEqual(df.iloc[0]['procedure'], 'Lease to Own Registration')


if __name__ == '__main__':
    unittest.main()
