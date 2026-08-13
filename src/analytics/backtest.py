"""Honest backtest: "hold the top-N consensus stocks, equal-weighted."

Pure pandas: DataFrame in, DataFrame out. Price data must already be
fetched by the caller (src/market/prices.py) — this module only knows
how to rank consensus history and simulate a portfolio against prices
it's given.

The one rule that makes this honest rather than optimistic: a quarter's
consensus is only tradeable from the date it was FULLY knowable, not from
the quarter-end date. See consensus_asof_schedule.
"""
from __future__ import annotations

import pandas as pd

from src.analytics.consensus import consensus_holdings

SCHEDULE_COLUMNS = ["period_date", "entry_date", "days_after_period_end", "cusips"]

# SEC's Form 13F deadline: due within 45 days of quarter-end. Used only to
# flag anomalies (e.g. very late amendments), not to clip/adjust dates.
FILING_DEADLINE_DAYS = 45


def consensus_asof_schedule(holdings: pd.DataFrame, top_n: int) -> pd.DataFrame:
    """For each distinct quarter (period_date) in `holdings`, the top-N
    consensus cusips and the earliest date that full picture could
    actually have been known.

    `holdings` should already be scoped to whatever universe the caller
    wants (e.g. options excluded) — one manager's rows per quarter, many
    quarters, many managers.

    entry_date for a quarter = max(filing_date) across every row
    contributing to that quarter's snapshot: the date the LAST tracked
    manager filed for that period. The consensus signal isn't complete
    until every filer's card is on the table, so this — not the
    quarter-end date — is the first date a top-N strategy could have
    traded on it. This is the look-ahead-bias guard: no period's entry
    ever uses a price from before its consensus was actually public.

    Returns one row per quarter (period_date, entry_date,
    days_after_period_end, cusips: list[str]), sorted by entry_date
    ascending. days_after_period_end over FILING_DEADLINE_DAYS (45) would
    indicate a data anomaly -- worth a caller-side warning, not fatal.
    """
    if holdings.empty:
        return pd.DataFrame(columns=SCHEDULE_COLUMNS)

    rows = []
    for period_date, group in holdings.groupby("period_date"):
        consensus = consensus_holdings(group)
        top = consensus.head(top_n)
        entry_date = group["filing_date"].max()
        days_after = (pd.Timestamp(entry_date) - pd.Timestamp(period_date)).days
        rows.append(
            {
                "period_date": period_date,
                "entry_date": entry_date,
                "days_after_period_end": days_after,
                "cusips": list(top["cusip"]),
            }
        )

    return pd.DataFrame(rows, columns=SCHEDULE_COLUMNS).sort_values("entry_date").reset_index(drop=True)


def _turnover_pct(prev_tickers: set[str], curr_tickers: set[str]) -> float:
    """% of the combined name-list that changed between two baskets:
    (# removed + # added) / (# prev + # curr) * 100. Same "name-swap
    ratio" definition used in analytics.investor.portfolio_summary, for
    consistency across the app.
    """
    denom = len(prev_tickers) + len(curr_tickers)
    if denom == 0:
        return 0.0
    removed = len(prev_tickers - curr_tickers)
    added = len(curr_tickers - prev_tickers)
    return (removed + added) / denom * 100


def simulate_portfolio(
    price_history: pd.DataFrame,
    rebalances: list[dict],
    cost_bps: float = 10.0,
) -> pd.DataFrame:
    """Simulate an equal-weighted portfolio rebalanced at each entry_date.

    price_history: DataFrame indexed by date, one column per ticker
        (close prices), e.g. concat of several market.prices.get_price_history()
        series.
    rebalances: [{"entry_date": ..., "tickers": [...]}, ...] — need not be
        pre-sorted. Each period runs from its entry_date up to (but not
        including) the next rebalance's entry_date; the last period runs
        to the end of price_history. Within a period, the basket is
        bought equal-weighted at entry and held (no daily rebalancing).
    cost_bps: one-time cost applied at each rebalance AFTER the first,
        proportional to turnover_pct (e.g. 10 bps * 100% turnover = 0.10%
        value haircut). The first entry has no prior basket to transition
        from, so no cost.

    Returns a DataFrame indexed by date with columns:
        value         portfolio value, rebased to 100 at the first entry_date
        turnover_pct  set only on rebalance dates (else NaN)
    Tickers absent from price_history, or without a price on/after their
    rebalance's entry_date, are dropped from that period's basket (the
    remaining tickers still split it equally) rather than failing the run.
    """
    if not rebalances:
        return pd.DataFrame(columns=["value", "turnover_pct"])

    rebalances = sorted(rebalances, key=lambda r: r["entry_date"])
    price_history = price_history.sort_index()

    segments = []
    portfolio_value = 100.0
    prev_tickers: set[str] = set()

    for i, reb in enumerate(rebalances):
        entry_date = pd.Timestamp(reb["entry_date"])
        candidate_tickers = [t for t in reb["tickers"] if t in price_history.columns]
        next_entry = pd.Timestamp(rebalances[i + 1]["entry_date"]) if i + 1 < len(rebalances) else None

        period_prices = price_history.loc[entry_date:, candidate_tickers]
        if next_entry is not None:
            period_prices = period_prices[period_prices.index < next_entry]
        if period_prices.empty:
            continue

        entry_prices = period_prices.iloc[0]
        usable = entry_prices.dropna().index.tolist()
        if not usable:
            continue
        period_prices = period_prices[usable]

        normalized = period_prices / period_prices.iloc[0]
        basket_index = normalized.mean(axis=1)  # equal-weight, NaN-tolerant

        turnover = _turnover_pct(prev_tickers, set(usable)) if i > 0 else None
        if turnover is not None:
            portfolio_value *= 1 - (cost_bps / 10000) * (turnover / 100)

        segment_value = portfolio_value * basket_index
        segment = pd.DataFrame({"value": segment_value})
        segment["turnover_pct"] = pd.NA
        segment.iloc[0, segment.columns.get_loc("turnover_pct")] = turnover
        segments.append(segment)

        portfolio_value = segment_value.iloc[-1]
        prev_tickers = set(usable)

    if not segments:
        return pd.DataFrame(columns=["value", "turnover_pct"])
    return pd.concat(segments).sort_index()
