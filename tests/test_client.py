"""Client view: the facts it shows match the shared files, and the local server only serves what it should."""
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from src.client import basemap, view
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


    def test_charts_get_complete_series(self):
        market = view.market(self.bundle)
        months = [row['month'] for row in market['monthly']]
        self.assertEqual(months[0], '2020-01')
        self.assertEqual(months, sorted(set(months)))
        self.assertLess(months[-1], self.bundle['quality']['date_max'][:7])      # the half-covered last month is left out
        self.assertEqual(market['prices'][-1]['quarter'], market['quarter'])
        self.assertTrue(all(row['offplan'] > 0 and row['ready'] > 0 for row in market['prices']))
        last = market['direction_history'][-1]
        self.assertEqual({k: last[k] for k in ('steady', 'rising', 'falling')}, market['direction'])

    def test_every_area_on_the_map_is_a_forecast_area_with_a_place(self):
        points = view.area_points(self.bundle)
        places = view.base_map()['places']
        names = self.bundle['names']
        known = {names.get(area, area) for area in places}
        self.assertTrue(points)
        self.assertTrue(all(point['name'] in known for point in points))
        self.assertEqual(sum(point['agents'] for point in points), self.bundle['allocation_manifest']['agents'])
        self.assertTrue(all(24.7 < point['lat'] < 25.4 and 54.8 < point['lon'] < 55.7 for point in points))     # inside Dubai
        segments = view.segments(self.bundle['allocation'], names)
        self.assertEqual(sum(s['agents'] for s in segments), self.bundle['allocation_manifest']['agents'])


class BasemapTests(unittest.TestCase):
    def test_names_match_only_when_they_are_the_same_name(self):
        self.assertEqual(basemap.key('Al Barsha South Fourth'), basemap.key('Al Barsha South 4'))
        self.assertEqual(basemap.key("Me'Aisem First"), basemap.key('Me Aisem 1'))
        self.assertNotEqual(basemap.key('Al Barsha South Fourth'), basemap.key('Al Barsha South 5'))
        elements = [{'type': 'node', 'lat': 25.057, 'lon': 55.208, 'tags': {'place': 'suburb', 'name:en': 'Al Barsha South 4'}},
                    {'type': 'node', 'lat': 25.9, 'lon': 55.9, 'tags': {'place': 'neighbourhood', 'name': 'Al Barsha South 4'}},
                    {'type': 'way', 'center': {'lat': 25.079, 'lon': 55.135}, 'tags': {'place': 'suburb', 'name': 'Dubai Marina'}}]
        found = basemap.match_places(['Al Barsha South Fourth', 'Marsa Dubai', 'Al Barsha South Fifth'], elements,
                                     {'Marsa Dubai': 'Dubai Marina'})
        self.assertEqual(found['Al Barsha South Fourth'], {'lat': 25.057, 'lon': 55.208, 'osm_name': 'Al Barsha South 4', 'match': 'name'})
        self.assertEqual(found['Marsa Dubai']['match'], 'alias')
        self.assertNotIn('Al Barsha South Fifth', found)        # no similar-name guessing

    def test_simplify_keeps_corners_and_drops_points_on_a_line(self):
        straight = [(0, 0), (1, 0.00001), (2, 0), (3, 0)]
        self.assertEqual(basemap.simplify(straight, 0.001), [(0, 0), (3, 0)])
        corner = [(0, 0), (1, 0), (1, 1)]
        self.assertEqual(basemap.simplify(corner, 0.001), corner)


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
        self.assertEqual(self.fetch('/charts.js')[0], 200)
        status, body = self.fetch('/api/map')
        shape = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(shape['coast'] and shape['roads'] and 'OpenStreetMap' in shape['attribution'])
        self.assertNotIn('places', shape)

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
