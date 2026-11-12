"""The client view: three plain screens for an agency, served from this machine.

    python -m src.client            then open http://localhost:8600

It reads the same shared files as the analyst dashboard and reuses its checks and its custom
planner. Only the standard library is needed.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading

from src.dashboard.data import load_bundle, load_evidence
from src.dashboard.planning import generate_plan
from . import view

STATIC = Path(__file__).with_name('static')
FILES = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.css': ('app.css', 'text/css; charset=utf-8'),
         '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
         '/charts.js': ('charts.js', 'text/javascript; charset=utf-8')}
MAX_BODY = 10_000
PLANNING = threading.Lock()     # one custom plan at a time; each run takes a few seconds of CPU


def summary():
    """Everything the Market and Team plan screens need, checked the same way the dashboard checks it."""
    bundle = load_bundle()
    plan = view.plan(bundle['allocation'], bundle['allocation_manifest'], bundle['names'])
    plan['segments'] = view.segments(bundle['allocation'], bundle['names'])
    plan['team_curve'] = view.team_curve()
    return {'market': view.market(bundle), 'plan': plan, 'backtest': view.backtest(load_evidence())}


def custom_plan(settings):
    """A plan for the client's own numbers, with the difference from the saved plan."""
    numbers = {}
    for key in ['agents', 'deals_per_agent', 'ready_rate', 'offplan_rate', 'ready_change', 'offplan_change']:
        value = settings.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f'{key} must be a number.')
        numbers[key] = value
    bundle = load_bundle()
    share = bundle['allocation_manifest']['assumptions_not_from_data']['max_market_share']
    with PLANNING:
        table, manifest = generate_plan(numbers['agents'], numbers['deals_per_agent'], share, numbers['ready_rate'],
                                        numbers['offplan_rate'], 'commission', numbers['ready_change'],
                                        numbers['offplan_change'])
    return {'plan': view.plan(table, manifest, bundle['names']),
            'compare': view.compare(bundle['allocation'], table, bundle['names'])}


class Handler(BaseHTTPRequestHandler):
    def send(self, status, body, content_type):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status, data):
        self.send(status, json.dumps(data, allow_nan=False).encode(), 'application/json')

    def answer(self, make):
        """Run a data call; a problem the user can fix becomes a readable message, not a crash."""
        try:
            self.send_json(200, make())
        except (ValueError, KeyError, OSError) as exc:
            self.send_json(400, {'error': str(exc)})

    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/api/summary':
            self.answer(summary)
        elif path == '/api/map':
            self.answer(lambda: {k: v for k, v in view.base_map().items() if k != 'places'})
        elif path == '/favicon.ico':
            self.send(204, b'', 'image/x-icon')
        elif path in FILES:     # a fixed list, so a request can never reach other files
            name, content_type = FILES[path]
            self.send(200, (STATIC / name).read_bytes(), content_type)
        else:
            self.send_json(404, {'error': 'Not found'})

    def do_POST(self):
        if self.path != '/api/plan':
            return self.send_json(404, {'error': 'Not found'})
        try:
            length = int(self.headers.get('Content-Length', 0))
            if not 0 < length <= MAX_BODY:
                raise ValueError('Send the settings as a small JSON object.')
            settings = json.loads(self.rfile.read(length))
            if not isinstance(settings, dict):
                raise ValueError('Send the settings as a JSON object.')
        except ValueError as exc:
            return self.send_json(400, {'error': str(exc)})
        self.answer(lambda: custom_plan(settings))

    def log_message(self, *args):     # keep the terminal quiet during a demo
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--port', type=int, default=8600)
    args = parser.parse_args()
    try:
        summary()     # fail now, with a clear message, if the shared files are missing or inconsistent
    except (ValueError, KeyError, OSError) as exc:
        parser.exit(1, f'The shared results are missing or inconsistent: {exc}\nRerun the update command in the README.\n')
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)     # this machine only
    print(f'Client view: http://localhost:{args.port}  (Ctrl+C to stop)')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
