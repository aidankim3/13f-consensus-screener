"""Single-manager portfolio detail analytics.

Pure pandas: DataFrame in, DataFrame out. Reuses the merge/classify core
from src.analytics.consensus (same package) so the single-manager and
cross-manager views can never drift out of sync on classification rules.
"""
from __future__ import annotations

import pandas as pd

from src.analytics.consensus import (
    CHANGE_COLUMNS,
    _build_change_table,
    _consolidate_by_manager,
    _weight_pct_within_manager,
)

PORTFOLIO_COLUMNS = CHANGE_COLUMNS

SUMMARY_COLUMNS = [
    "n_holdings",
    "top10_concentration_pct",
    "turnover_pct",
    "option_weight_pct",
]


def _require_single_manager(frame: pd.DataFrame, label: str) -> None:
    if not frame.empty and frame["cik"].nunique() > 1:
        raise ValueError(f"investor_portfolio expects a single manager (one cik) in {label}")


def investor_portfolio(previous_holdings: pd.DataFrame, current_holdings: pd.DataFrame) -> pd.DataFrame:
    """Full single-manager portfolio table: every cusip held now, or held
    previously but fully exited this quarter — each row classified vs.
    the prior quarter (new_buy/add/trim/sold_out/unchanged).

    Unlike consensus.quarter_changes(), 'unchanged' rows are KEPT here
    since this is a full portfolio view, not a changes-only view. A
    'sold_out' row (curr_value_usd/curr_shares == 0) stays visible so a
    recently-exited name doesn't just silently disappear from the table.

    previous_holdings/current_holdings must both already be scoped to a
    single manager (one cik) — e.g. holdings[holdings.cik == X] — and to
    whichever option-inclusion the caller wants reflected in the table.
    """
    _require_single_manager(previous_holdings, "previous_holdings")
    _require_single_manager(current_holdings, "current_holdings")

    if previous_holdings.empty and current_holdings.empty:
        return pd.DataFrame(columns=PORTFOLIO_COLUMNS)

    merged = _build_change_table(previous_holdings, current_holdings)
    return merged.sort_values("curr_value_usd", ascending=False).reset_index(drop=True)


def portfolio_summary(
    portfolio: pd.DataFrame, current_holdings_with_options: pd.DataFrame
) -> pd.DataFrame:
    """One-row summary of a manager's current portfolio.

    `portfolio` is investor_portfolio()'s output for this manager.
    `current_holdings_with_options` is this manager's RAW current-quarter
    holdings, INCLUDING option rows, used only to compute
    option_weight_pct — kept independent of whatever option-inclusion
    filter was applied to build `portfolio`, so this metric stays
    meaningful even when the caller excludes options from the table.

    Columns:
        n_holdings                distinct cusips actually held now
                                   (excludes rows classified sold_out)
        top10_concentration_pct   share of current portfolio value held
                                   in the 10 largest positions
        turnover_pct              (# new_buy + # sold_out) / (# held
                                   previously + # held now) * 100 — a
                                   rough "how much of the name list
                                   churned" proxy, NOT a dollar-turnover
                                   ratio. NaN if there's no prior-quarter
                                   data to compare against.
        option_weight_pct         option rows' value_usd as a % of this
                                   manager's TOTAL value_usd (stock+option)
    """
    if portfolio.empty:
        n_holdings = 0
        top10_concentration_pct = 0.0
        turnover_pct = float("nan")
    else:
        current_only = portfolio[portfolio["change_type"] != "sold_out"]
        n_holdings = current_only["cusip"].nunique()

        total_value = current_only["curr_value_usd"].sum()
        top10_value = current_only.nlargest(10, "curr_value_usd")["curr_value_usd"].sum()
        top10_concentration_pct = (top10_value / total_value * 100) if total_value else 0.0

        n_prev = (portfolio["change_type"] != "new_buy").sum()
        n_curr = (portfolio["change_type"] != "sold_out").sum()
        n_new_buy = (portfolio["change_type"] == "new_buy").sum()
        n_sold_out = (portfolio["change_type"] == "sold_out").sum()
        turnover_pct = (
            (n_new_buy + n_sold_out) / (n_prev + n_curr) * 100 if n_prev > 0 else float("nan")
        )

    if current_holdings_with_options.empty:
        option_weight_pct = 0.0
    else:
        is_option = current_holdings_with_options["is_option"]
        stock_value = current_holdings_with_options.loc[~is_option, "value_usd"].sum()
        option_value = current_holdings_with_options.loc[is_option, "value_usd"].sum()
        grand_total = stock_value + option_value
        option_weight_pct = (option_value / grand_total * 100) if grand_total else 0.0

    return pd.DataFrame(
        [
            {
                "n_holdings": n_holdings,
                "top10_concentration_pct": top10_concentration_pct,
                "turnover_pct": turnover_pct,
                "option_weight_pct": option_weight_pct,
            }
        ]
    )[SUMMARY_COLUMNS]


TREND_COLUMNS = ["period_date"] + SUMMARY_COLUMNS


def investor_trend(holdings_filtered: pd.DataFrame, holdings_raw: pd.DataFrame) -> pd.DataFrame:
    """Per period_date: portfolio_summary() metrics for one manager, across
    every period_date present in `holdings_filtered` -- the quarter-over-
    quarter history behind a "how has this investor's portfolio changed"
    chart.

    Both frames must already be scoped to a SINGLE manager (one cik) and
    span multiple quarters. `holdings_filtered` reflects the caller's
    option-inclusion choice (drives n_holdings/top10_concentration_pct/
    turnover_pct); `holdings_raw` is this manager's unfiltered holdings,
    used only for option_weight_pct so it reflects the manager's TRUE mix
    regardless of the toggle -- same split the single-quarter view uses.
    Each period's turnover_pct is computed against its own immediately
    preceding period in `holdings_filtered` (NaN for the first one, same
    as portfolio_summary's "no prior quarter" case).
    """
    if holdings_filtered.empty:
        return pd.DataFrame(columns=TREND_COLUMNS)

    periods = sorted(holdings_filtered["period_date"].dropna().unique())
    rows = []
    for i, period in enumerate(periods):
        curr = holdings_filtered[holdings_filtered["period_date"] == period]
        prev = (
            holdings_filtered[holdings_filtered["period_date"] == periods[i - 1]]
            if i > 0
            else holdings_filtered.iloc[0:0]
        )
        raw_curr = holdings_raw[holdings_raw["period_date"] == period]
        portfolio = investor_portfolio(prev, curr)
        summary = portfolio_summary(portfolio, raw_curr).iloc[0]
        rows.append({"period_date": period, **summary.to_dict()})

    return pd.DataFrame(rows, columns=TREND_COLUMNS)


POSITION_TREND_COLUMNS = ["period_date", "shares", "value_usd", "weight_pct"]


def position_trend(holdings: pd.DataFrame, cusip: str) -> pd.DataFrame:
    """Per period_date: this manager's shares/value/weight_pct in ONE
    cusip, across every period_date present in `holdings` -- "how has
    this investor's position in this specific stock changed" (e.g.
    Berkshire's AAPL holding across 5 years).

    `holdings` must already be scoped to a SINGLE manager (one cik) and
    span multiple quarters. A quarter where the manager didn't hold the
    cusip at all gets an explicit zero row (not skipped), so a line chart
    shows a real drop to zero instead of a gap.
    """
    if holdings.empty:
        return pd.DataFrame(columns=POSITION_TREND_COLUMNS)

    rows = []
    for period, group in holdings.groupby("period_date"):
        consolidated = _consolidate_by_manager(group)
        consolidated["weight_pct"] = _weight_pct_within_manager(consolidated)
        match = consolidated[consolidated["cusip"] == cusip]
        if match.empty:
            rows.append({"period_date": period, "shares": 0, "value_usd": 0.0, "weight_pct": 0.0})
        else:
            r = match.iloc[0]
            rows.append(
                {
                    "period_date": period,
                    "shares": r["shares"],
                    "value_usd": r["value_usd"],
                    "weight_pct": r["weight_pct"],
                }
            )
    return pd.DataFrame(rows, columns=POSITION_TREND_COLUMNS).sort_values("period_date").reset_index(drop=True)
