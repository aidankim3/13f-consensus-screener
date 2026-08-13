"""Estimated entry price vs. current price comparison.

Pure pandas: DataFrame in, DataFrame out. No network here -- src/market/*
resolves tickers and fetches prices; this module only combines
already-fetched price data with a single-manager portfolio table.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ENTRY_PRICE_COLUMNS = [
    "cusip",
    "name_of_issuer",
    "ticker",
    "change_type",
    "curr_shares",
    "curr_value_usd",
    "curr_weight_pct",
    "entry_price",
    "current_price",
    "price_diff_pct",
]


def with_entry_price_comparison(portfolio: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """Attach estimated entry price / current price / % difference to a
    single-manager portfolio table (investor.investor_portfolio() output).

    `prices` must have columns: cusip, ticker, entry_price, current_price.
    Any of ticker/entry_price/current_price may be missing (NaN/None) for
    a row when the CUSIP couldn't be mapped to a ticker or the price
    fetch failed -- such rows are kept (not dropped), just with a NaN
    price_diff_pct, so the table stays a complete portfolio view.

    price_diff_pct = (current_price - entry_price) / entry_price * 100.
    Positive means the stock costs MORE today than the investor's
    estimated entry price -- buying now would be pricier than they got.

    entry_price itself is only an approximation (see src/market/prices.py:
    average of the reporting quarter's first Open and last Close), not an
    actual transaction price -- 13F doesn't disclose trade dates/prices.
    """
    if portfolio.empty:
        return pd.DataFrame(columns=ENTRY_PRICE_COLUMNS)

    merged = portfolio.merge(prices, on="cusip", how="left")
    # Coerce to numeric explicitly: an all-missing price column merged in
    # (e.g. every ticker unresolved) comes through as object dtype full of
    # None, not float64 NaN, which breaks arithmetic below.
    merged["entry_price"] = pd.to_numeric(merged["entry_price"], errors="coerce")
    merged["current_price"] = pd.to_numeric(merged["current_price"], errors="coerce")

    has_prices = (
        merged["entry_price"].notna()
        & merged["current_price"].notna()
        & (merged["entry_price"] != 0)
    )
    merged["price_diff_pct"] = np.where(
        has_prices,
        (merged["current_price"] - merged["entry_price"]) / merged["entry_price"] * 100,
        np.nan,
    )

    return merged[ENTRY_PRICE_COLUMNS]
