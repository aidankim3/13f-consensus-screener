"""Aggregate insider (Form 4) open-market purchase activity into
per-stock summaries -- the data behind Dataroma-style "Insider Buys"
screens ("Superinvestor Stocks With Most Insider Buys").

Pure pandas: DataFrame in, DataFrame out. No network, no SEC knowledge --
that lives in src/edgar/form4.py, which this only consumes.
"""
from __future__ import annotations

import pandas as pd

INSIDER_SUMMARY_COLUMNS = ["ticker", "issuer_name", "n_buys", "total_value_usd"]


def insider_buy_summary(transactions: pd.DataFrame, min_value_usd: float = 0.0) -> pd.DataFrame:
    """Per ticker: count of insider open-market purchase transactions and
    their combined dollar value, sorted by count then value (both
    descending) -- "who's buying the most, and the most of".

    `transactions` should already be scoped to whatever lookback window
    and transaction-code filter the caller wants (see
    fetch_insider_buys_for_issuer, which already restricts to code=='P').
    Rows below min_value_usd are dropped before aggregating -- Dataroma's
    own "$50k+" significance filter.
    """
    if transactions.empty:
        return pd.DataFrame(columns=INSIDER_SUMMARY_COLUMNS)

    scoped = transactions[transactions["value_usd"] >= min_value_usd]
    if scoped.empty:
        return pd.DataFrame(columns=INSIDER_SUMMARY_COLUMNS)

    grouped = (
        scoped.groupby("ticker")
        .agg(
            issuer_name=("issuer_name", "first"),
            n_buys=("value_usd", "size"),
            total_value_usd=("value_usd", "sum"),
        )
        .reset_index()
    )
    return (
        grouped[INSIDER_SUMMARY_COLUMNS]
        .sort_values(["n_buys", "total_value_usd"], ascending=False)
        .reset_index(drop=True)
    )
