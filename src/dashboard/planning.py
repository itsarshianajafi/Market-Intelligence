"""Run the existing allocation model with isolated, disposable output files."""
import json
from pathlib import Path
import tempfile

from src.allocation.run import run
from .data import ROOT, load_bundle, source_signature


def generate_plan(agents, deals_per_agent, market_share, ready_rate, offplan_rate, objective,
                  ready_change=0.0, offplan_change=0.0):
    """Return a custom plan without writing to shared datasets or project reports."""
    cfg = json.loads((ROOT / 'src/allocation/config.json').read_text())
    if not 5 <= agents <= 60 or int(agents) != agents:
        raise ValueError('Choose a whole team size from 5 to 60.')
    if not 0 < deals_per_agent <= 20 or not 0 < market_share <= 1:
        raise ValueError('Deal rate and market share must be positive and within their ranges.')
    if not all(0 < rate <= 1 for rate in [ready_rate, offplan_rate]):
        raise ValueError('Commission rates must be positive and no more than 100%.')
    if not all(-0.9 <= change <= 1 for change in [ready_change, offplan_change]):
        raise ValueError('A what-if sales change must be between -90% and +100%.')
    if objective not in ('commission', 'deals'):
        raise ValueError('Unknown planning objective.')
    before = source_signature()
    load_bundle()
    for key in ['forecasts', 'forecast_manifest', 'market_trends', 'monthly_sales', 'predictions']:
        cfg[key] = str(ROOT / cfg[key])
    cfg.update(agents=int(agents), deals_per_agent=float(deals_per_agent),
               max_market_share=float(market_share),
               commission_rate={'Ready': float(ready_rate), 'Off-Plan': float(offplan_rate)},
               objective=objective, figures=False, team_sizes=[int(agents)],
               demand_change={'Ready': float(ready_change), 'Off-Plan': float(offplan_change)})
    with tempfile.TemporaryDirectory(prefix='dubai-plan-') as folder:
        cfg.update(output=str(Path(folder) / 'allocation.csv'),
                   manifest=str(Path(folder) / 'allocation_manifest.json'), report_dir=folder)
        table, manifest, _ = run(cfg, evaluation=False)
    if before != source_signature():
        raise ValueError('Source files changed during planning. Refresh and generate a new plan.')
    return table, manifest
