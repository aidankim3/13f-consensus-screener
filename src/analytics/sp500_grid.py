"""S&P 500 ownership screen: which S&P 500 constituents the tracked
managers hold, and how much conviction (holder count, avg weight) they
show in each -- Dataroma's "S&P 500 Grid" reinterpreted as a sector-aware
screener over consensus_holdings() rather than a literal 500xN checkbox
matrix (which would be mostly empty cells and less useful to scan).

Pure pandas: DataFrame in, DataFrame out. Reuses consensus_holdings() so
the weighting/consolidation rules never drift from the main consensus view.
"""
from __future__ import annotations

import pandas as pd

from src.analytics.consensus import consensus_holdings

GRID_COLUMNS = ["ticker", "name", "sector", "cusip", "holder_count", "avg_weight_pct", "total_value_usd"]


def sp500_ownership_summary(
    holdings: pd.DataFrame, sp500: pd.DataFrame, ticker_by_cusip: dict[str, str]
) -> pd.DataFrame:
    """Per S&P 500 ticker actually held by >=1 tracked manager this
    quarter: holder count, average portfolio weight among those holders,
    and sector -- sorted by holder count (highest-conviction names first).

    `holdings` is a single quarter's rows (options already included/
    excluded, any number of managers). `sp500` is load_sp500()'s output.
    `ticker_by_cusip` maps cusip -> resolved ticker (see
    src.market.ticker_map); cusips with no resolved ticker are simply
    unmatchable against the S&P 500 list and excluded. A ticker with zero
    tracked holders is absent from the result (a mostly-empty 500-row
    table isn't useful to scan) -- callers wanting the "not held" set can
    diff against sp500['ticker'].
    """
    if holdings.empty or sp500.empty:
        return pd.DataFrame(columns=GRID_COLUMNS)

    consensus = consensus_holdings(holdings)
    consensus["ticker"] = consensus["cusip"].map(ticker_by_cusip)

    matched = consensus.merge(sp500, on="ticker", how="inner")
    if matched.empty:
        return pd.DataFrame(columns=GRID_COLUMNS)

    return (
        matched[GRID_COLUMNS]
        .sort_values(["holder_count", "avg_weight_pct"], ascending=False)
        .reset_index(drop=True)
    )
