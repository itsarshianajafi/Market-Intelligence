"""Client view: the facts it shows match the shared files, and the local server only serves what it should."""
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from src.client import view
from src.client.server import Handler, summary
from src.dashboard.data import load_bundle, load_evidence


class ViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = load_bundle()

    def test_market_matches_the_monthly_sales(self):
        market = view.market(self.bundle)
        monthly = self.bundle['monthly']
        latest = self.bundle['forecast_manifest']['origin_quarter']
        months = monthly[monthly.date.dt.to_period('Q').astype(str).eq(latest)]
        self.assertEqual(market['total']['sales'], int(months.transaction_count.sum()))
        self.assertEqual(market['total']['sales'], market['offplan']['sales'] + market['ready']['sales'])
        self.assertEqual(len(market['history']), 8)
        last = market['history'][-1]
        self.assertEqual(last['offplan'] + last['ready'], market['total']['sales'])
        forecasts = [area['forecast'] for area in market['busiest']]
        self.assertEqual(forecasts, sorted(forecasts, reverse=True))

    def test_plan_cards_add_up_to_the_saved_plan(self):
        table, manifest = self.bundle['allocation'], self.bundle['allocation_manifest']
        plan = view.plan(table, manifest, self.bundle['names'])
        self.assertEqual(plan['agents'], manifest['agents'])
        self.assertEqual(sum(card['agents'] for card in plan['cards']), plan['agents'])
        self.assertEqual(plan['offplan_agents'] + plan['ready_agents'], plan['agents'])
        self.assertAlmostEqual(sum(card['commission'] for card in plan['cards']), plan['commission'], delta=1)
        self.assertEqual(len(plan['cards']), plan['areas'])
        scores = view.backtest(load_evidence())
        self.assertGreater(scores['optimiser'], scores['rule'])

    def test_compare_counts_agents_in_a_new_place(self):
        saved = self.bundle['allocation']
        same = view.compare(saved, saved, self.bundle['names'])
        self.assertEqual((same['moved'], same['commission_change']), (0, 0.0))
        chosen = saved[saved.agents.gt(0)]
        moved = saved.copy()
        moved.loc[chosen.index[0], 'agents'] -= 1       # one agent leaves the biggest team
        moved.loc[chosen.index[-1], 'agents'] += 1      # and joins the last one
        self.assertEqual(view.compare(saved, moved, self.bundle['names'])['moved'], 1)


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f'http://127.0.0.1:{cls.server.server_address[1]}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def fetch(self, path, body=None):
        request = Request(self.base + path, data=None if body is None else body.encode(),
                          headers={'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=60) as response:
                return response.status, response.read()
        except HTTPError as error:
            return error.code, error.read()

    def test_pages_and_summary(self):
        status, page = self.fetch('/')
        self.assertEqual(status, 200)
        self.assertIn(b'Market Intelligence', page)
        status, body = self.fetch('/api/summary')
        self.assertEqual((status, json.loads(body)), (200, summary()))

    def test_only_listed_files_are_served(self):
        for path in ['/../README.md', '/server.py', '/static/app.js', '/api/unknown']:
            self.assertEqual(self.fetch(path)[0], 404, path)

    def test_bad_settings_get_a_message_not_a_crash(self):
        good = dict(agents=20, deals_per_agent=2, ready_rate=.02, offplan_rate=.04, ready_change=0, offplan_change=0)
        for body in ['not json', '[1, 2]', json.dumps({**good, 'agents': 'many'}), json.dumps({**good, 'agents': 500}),
                     json.dumps({**good, 'offplan_change': -2}), json.dumps({k: v for k, v in good.items() if k != 'agents'})]:
            status, answer = self.fetch('/api/plan', body)
            self.assertEqual(status, 400, body)
            self.assertIn('error', json.loads(answer))

    def test_custom_plan_end_to_end(self):
        settings = dict(agents=20, deals_per_agent=2, ready_rate=.02, offplan_rate=.04, ready_change=0, offplan_change=-0.3)
        status, body = self.fetch('/api/plan', json.dumps(settings))
        result = json.loads(body)
        self.assertEqual(status, 200, result)
        self.assertEqual(result['plan']['agents'], 20)
        self.assertLess(result['compare']['commission_change'], 0)     # a smaller market cannot earn more
        self.assertEqual(sum(row['after'] for row in result['compare']['rows']), 20)


if __name__ == '__main__':
    unittest.main()
