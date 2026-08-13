"""Per-manager holding summaries. Pure pandas: DataFrame in, DataFrame out."""
from __future__ import annotations

import pandas as pd


def summarize_by_manager(holdings: pd.DataFrame) -> pd.DataFrame:
    """One row per (cik, manager_name, period_date) with stock holding
    count, summed long-stock value, and option position count.

    Options are excluded from n_holdings/sum_value_usd — 13F option rows
    (PUT/CALL) aren't long stock exposure and shouldn't be counted as
    "holdings" in the default view, but their count is still surfaced.
    """
    stocks = holdings.loc[~holdings["is_option"]]
    options = holdings.loc[holdings["is_option"]]

    summary = (
        stocks.groupby(["cik", "manager_name", "period_date"])
        .agg(n_holdings=("cusip", "nunique"), sum_value_usd=("value_usd", "sum"))
        .reset_index()
    )

    option_counts = (
        options.groupby(["cik", "manager_name", "period_date"])
        .size()
        .rename("n_option_positions")
        .reset_index()
    )

    summary = summary.merge(
        option_counts, on=["cik", "manager_name", "period_date"], how="left"
    )
    summary["n_option_positions"] = summary["n_option_positions"].fillna(0).astype(int)

    return summary.sort_values("sum_value_usd", ascending=False).reset_index(drop=True)
