"""What agents in a segment are worth: a saturating response and forecast-error scenarios."""
import numpy as np


def captured_deals(agents, demand, cfg):
    """Deals won by `agents` in a segment with `demand` sales in the quarter.

    A few agents each close deals_per_agent; as they approach max_market_share of the segment
    each extra agent adds less. The curve is concave, so the model has diminishing returns.
    """
    ceiling = cfg['max_market_share'] * np.asarray(demand, dtype=float)
    agents = np.asarray(agents, dtype=float)
    with np.errstate(divide='ignore', invalid='ignore'):
        deals = ceiling * -np.expm1(-cfg['deals_per_agent'] * agents / ceiling)
    return np.where(ceiling > 0, deals, 0.0)


def deal_value(ticket, rate, cfg):
    return ticket * rate if cfg['objective'] == 'commission' else np.ones_like(ticket)


def value_table(demand, values, max_agents, cfg):
    """Mean value of 0..max_agents agents per segment. demand is (segments,) or (segments, scenarios)."""
    demand = np.asarray(demand, dtype=float)
    demand = demand[:, None] if demand.ndim == 1 else demand
    agents = np.arange(max_agents + 1, dtype=float)[None, None, :]
    deals = captured_deals(agents, demand[:, :, None], cfg).mean(axis=1)
    return deals * np.asarray(values, dtype=float)[:, None]


def scenarios(candidates, errors, cfg, rng, count=None):
    """Possible demands: forecast times resampled past errors, (segments, scenarios).

    Each scenario has a market-wide shock (a past quarter's mean error) plus a segment error from
    forecasts of similar size. Fallback forecasts get wider errors because Part 3 measured them
    as less accurate (test count WAPE 52.0% against 32.1%).
    """
    count = count or cfg['scenarios']
    demand = candidates.demand.to_numpy(dtype=float)
    if errors.empty:
        return demand[:, None]
    shocks = errors.groupby('forecast_quarter').log_error.mean()
    residual = (errors.log_error - errors.forecast_quarter.map(shocks)).to_numpy()
    edges = np.quantile(errors.prediction, [1 / 3, 2 / 3])
    past = np.searchsorted(edges, errors.prediction.to_numpy())
    now = np.searchsorted(edges, demand)
    pools = [residual[past == size] if np.any(past == size) else residual for size in range(3)]
    noise = np.column_stack([rng.choice(pools[size], size=count) for size in now])
    scale = np.where(candidates.status.eq('fallback'), cfg['fallback_error_scale'], 1.0)
    market = rng.choice(shocks.to_numpy(), size=count)[:, None]
    return (np.expm1(np.log1p(demand) + market + noise * scale)).clip(min=0).T
