"""Dashboard contracts and optional Streamlit browser-free interaction checks."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from src.dashboard.data import ROOT, filter_rows, load_bundle, monthly_summary, source_signature
from src.dashboard.planning import generate_plan
from src.forecasting.data import fingerprint

try:
    from streamlit.testing.v1 import AppTest
except ImportError:
    AppTest = None


class DashboardDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = load_bundle()

    def test_shared_bundle_reconciles(self):
        self.assertEqual(int(self.bundle['monthly'].transaction_count.sum()),
                         self.bundle['quality']['sales_transactions'])
        self.assertTrue(len(source_signature()) >= 7)

    def test_filters_keep_empty_selection_empty(self):
        self.assertTrue(filter_rows(self.bundle['monthly'], 'Not a real area').empty)
        frame = filter_rows(self.bundle['monthly'], 'Business Bay', 'Ready')
        self.assertTrue(frame.area.eq('Business Bay').all())
        self.assertTrue(frame.registration_type.eq('Ready').all())

    def test_summary_preserves_counts_and_value(self):
        frame = filter_rows(self.bundle['monthly'], 'Business Bay')
        summary = monthly_summary(frame)
        self.assertEqual(int(summary.Sales.sum()), int(frame.transaction_count.sum()))
        self.assertAlmostEqual(summary['Transaction value (AED)'].sum(), frame.total_price_aed.sum(), delta=1)

    def test_mixed_snapshot_is_rejected(self):
        with patch('src.dashboard.data.fingerprint', return_value='different-source-hash'):
            with self.assertRaisesRegex(ValueError, 'differs from the saved analysis'):
                load_bundle()

    def test_custom_planner_rejects_bad_assumptions(self):
        for changes in [(0, 2, .05, .02, .04, 'commission'),
                        (20, 2, 0, .02, .04, 'commission'),
                        (20, 2, .05, .02, .04, 'unknown')]:
            with self.assertRaises(ValueError):
                generate_plan(*changes)

    def test_real_custom_plan_does_not_modify_shared_artifacts(self):
        paths = list((ROOT / 'data/shared').glob('*')) + list((ROOT / 'reports').rglob('*.*'))
        before = {str(p): fingerprint(p) for p in paths if p.is_file()}
        frame, manifest = generate_plan(20, 2, .05, .02, .04, 'commission')
        self.assertEqual(int(frame.agents.sum()), 20)
        self.assertTrue(manifest['feasible'])
        self.assertEqual(before, {p: fingerprint(p) for p in before})


@unittest.skipUnless(AppTest, 'Install requirements-dashboard.txt for Streamlit interaction tests')
class DashboardUITests(unittest.TestCase):
    def app(self):
        return AppTest.from_file(str(ROOT / 'app.py'), default_timeout=30).run()

    def test_all_pages_render(self):
        app = self.app()
        for page in ['Overview', 'Data Explorer', 'Market Trends', 'Forecasts', 'Agent Allocation']:
            app.sidebar.radio[0].set_value(page).run()
            self.assertEqual(len(app.exception), 0, str(app.exception))
        self.assertTrue(any('assumptions' in w.value.lower() for w in app.warning))

    def test_empty_explorer_filter_does_not_crash(self):
        app = self.app()
        app.sidebar.radio[0].set_value('Data Explorer').run()
        app.multiselect[0].set_value([]).run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any('No records match' in item.value for item in app.info))

    def test_forecast_segment_filter(self):
        app = self.app()
        app.sidebar.radio[0].set_value('Forecasts').run()
        app.sidebar.selectbox[0].set_value('Business Bay').run()
        app.sidebar.selectbox[1].set_value('Ready').run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any('projection' in m.label for m in app.metric))

    def test_form_generation_is_explicit_and_retained(self):
        app = self.app()
        app.sidebar.radio[0].set_value('Agent Allocation').run()
        frame = load_bundle()['allocation']
        manifest = json.loads((ROOT / 'data/shared/allocation_manifest.json').read_text())
        with patch('src.dashboard.planning.generate_plan', return_value=(frame, manifest)) as generator:
            app.button[0].click().run()
            self.assertEqual(generator.call_count, 1)
            self.assertEqual(len(app.exception), 0)
            app.sidebar.radio[0].set_value('Overview').run()
            app.sidebar.radio[0].set_value('Agent Allocation').run()
            self.assertEqual(generator.call_count, 1)
            self.assertTrue(any(h.value == 'Custom plan' for h in app.subheader))
