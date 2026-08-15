"""Cross-manager consensus + quarter-over-quarter change analytics.

Pure pandas: DataFrame in, DataFrame out. No knowledge of where the data
came from or how it's displayed — callers decide which snapshot(s) to
pass in (e.g. options excluded, a single quarter's period_rank==0 rows).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

CONSENSUS_COLUMNS = [
    "cusip",
    "name_of_issuer",
    "holder_count",
    "total_value_usd",
    "avg_weight_pct",
    "equal_weight_score",
    "value_weight_score",
]

CHANGE_COLUMNS = [
    "cik",
    "manager_name",
    "cusip",
    "name_of_issuer",
    "prev_shares",
    "curr_shares",
    "shares_delta",
    "prev_value_usd",
    "curr_value_usd",
    "value_delta_usd",
    "prev_weight_pct",
    "curr_weight_pct",
    "weight_delta_pct",
    "change_type",
]

TOP_BUYS_COLUMNS = [
    "cusip",
    "name_of_issuer",
    "n_new_buyers",
    "total_value_added_usd",
    "avg_weight_change_pct",
]

TOP_SELLS_COLUMNS = [
    "cusip",
    "name_of_issuer",
    "n_sold_out",
    "total_value_reduced_usd",
]

HOLDERS_COLUMNS = ["manager_name", "shares", "value_usd", "weight_pct"]


def _weight_pct_within_manager(holdings: pd.DataFrame) -> pd.Series:
    """value_usd as a percentage of each row's own manager's (cik) total
    value_usd within the given frame."""
    manager_total = holdings.groupby("cik")["value_usd"].transform("sum")
    return np.where(manager_total > 0, holdings["value_usd"] / manager_total * 100, 0.0)


def _consolidate_by_manager(holdings: pd.DataFrame) -> pd.DataFrame:
    """Collapse multiple rows for the same (cik, cusip) into one.

    A single 13F can report one issuer across several line items when a
    manager splits investment discretion across sub-accounts (e.g. real
    Berkshire Hathaway filings report American Express across 3 separate
    rows, same cusip, for its different insurance subsidiaries). Every
    per-(cik, cusip) computation downstream needs each manager's TOTAL
    position, not its internal bookkeeping split — otherwise a manager
    with 3 line items for one stock silently counts 3x in an average, and
    an outer merge across two quarters explodes into a spurious cartesian
    product (3 prev rows x 3 curr rows = 9 "changes" instead of 1).
    """
    if holdings.empty:
        return holdings
    return (
        holdings.groupby(["cik", "cusip"])
        .agg(
            manager_name=("manager_name", "first"),
            name_of_issuer=("name_of_issuer", "first"),
            value_usd=("value_usd", "sum"),
            shares=("shares", "sum"),
        )
        .reset_index()
    )


def consensus_holdings(holdings: pd.DataFrame) -> pd.DataFrame:
    """One row per cusip: cross-manager consensus metrics for the given
    holdings snapshot.

    The caller decides scope by what it passes in — typically a single
    quarter (period_rank == 0) with options already excluded.

    Columns:
        holder_count        distinct managers (cik) holding this cusip
        total_value_usd     summed value_usd across those managers
        avg_weight_pct      mean of each holder's own-portfolio weight (%)
        equal_weight_score  holder_count as a % of all managers in the
                             input frame (headcount-based conviction)
        value_weight_score  total_value_usd as a % of the input frame's
                             grand total value_usd (dollar-based conviction)
    """
    if holdings.empty:
        return pd.DataFrame(columns=CONSENSUS_COLUMNS)

    df = _consolidate_by_manager(holdings)
    df["weight_pct"] = _weight_pct_within_manager(df)

    n_managers = df["cik"].nunique()
    grand_total_value = df["value_usd"].sum()

    grouped = (
        df.groupby("cusip")
        .agg(
            name_of_issuer=("name_of_issuer", "first"),
            holder_count=("cik", "nunique"),
            total_value_usd=("value_usd", "sum"),
            avg_weight_pct=("weight_pct", "mean"),
        )
        .reset_index()
    )

    grouped["equal_weight_score"] = (
        grouped["holder_count"] / n_managers * 100 if n_managers else 0.0
    )
    grouped["value_weight_score"] = (
        grouped["total_value_usd"] / grand_total_value * 100 if grand_total_value else 0.0
    )

    return (
        grouped[CONSENSUS_COLUMNS]
        .sort_values(["holder_count", "total_value_usd"], ascending=False)
        .reset_index(drop=True)
    )


CONSENSUS_TREND_COLUMNS = ["period_date", "holder_count", "total_value_usd", "avg_weight_pct"]


def consensus_trend(holdings: pd.DataFrame, cusip: str) -> pd.DataFrame:
    """Per period_date: consensus_holdings() metrics for one cusip, across
    every period_date present in `holdings` -- the quarter-over-quarter
    history behind a "how has conviction in this stock changed" chart.

    `holdings` should span multiple quarters (any number of managers),
    options already included/excluded as the caller wants. A quarter
    where no tracked manager held the cusip gets an explicit
    holder_count=0 row rather than being skipped, so a line chart shows a
    real drop to zero instead of a gap.
    """
    if holdings.empty:
        return pd.DataFrame(columns=CONSENSUS_TREND_COLUMNS)

    rows = []
    for period, group in holdings.groupby("period_date"):
        match = consensus_holdings(group)
        match = match[match["cusip"] == cusip]
        if match.empty:
            rows.append(
                {"period_date": period, "holder_count": 0, "total_value_usd": 0.0, "avg_weight_pct": 0.0}
            )
        else:
            r = match.iloc[0]
            rows.append(
                {
                    "period_date": period,
                    "holder_count": r["holder_count"],
                    "total_value_usd": r["total_value_usd"],
                    "avg_weight_pct": r["avg_weight_pct"],
                }
            )
    return pd.DataFrame(rows, columns=CONSENSUS_TREND_COLUMNS).sort_values("period_date").reset_index(drop=True)


def holders_of_cusip(holdings: pd.DataFrame, cusip: str) -> pd.DataFrame:
    """Drill-down for consensus_holdings(): which managers hold `cusip` in
    the given snapshot, with each holder's shares/value and that
    position's weight within their OWN portfolio (not the cross-manager
    consensus weight).

    `holdings` should be a single quarter's rows (options already
    included/excluded as the caller wants), same scope as whatever was
    passed to consensus_holdings() to produce the holder_count being
    drilled into.
    """
    if holdings.empty:
        return pd.DataFrame(columns=HOLDERS_COLUMNS)

    df = _consolidate_by_manager(holdings)
    df["weight_pct"] = _weight_pct_within_manager(df)
    scoped = df[df["cusip"] == cusip]

    return (
        scoped[HOLDERS_COLUMNS]
        .sort_values("value_usd", ascending=False)
        .reset_index(drop=True)
    )


def _manager_lookup(*frames: pd.DataFrame) -> pd.Series:
    combined = pd.concat([f[["cik", "manager_name"]] for f in frames if not f.empty])
    return combined.drop_duplicates("cik").set_index("cik")["manager_name"]


def _issuer_lookup(*frames: pd.DataFrame) -> pd.Series:
    combined = pd.concat([f[["cusip", "name_of_issuer"]] for f in frames if not f.empty])
    return combined.drop_duplicates("cusip").set_index("cusip")["name_of_issuer"]


def _build_change_table(previous_holdings: pd.DataFrame, current_holdings: pd.DataFrame) -> pd.DataFrame:
    """Shared merge+classify step behind quarter_changes() and
    investor.investor_portfolio(). Unlike quarter_changes(), this KEEPS
    'unchanged' rows — callers filter as needed. Returns CHANGE_COLUMNS
    plus 'change_type' (already included in CHANGE_COLUMNS).

    Classification is based on SHARE COUNT, not value, so a pure price
    move (no change in position size) is never mistaken for a buy/sell:
        new_buy    held now, not held previously
        add        held both quarters, shares increased
        trim       held both quarters, shares decreased
        sold_out   held previously, not held now
        unchanged  held both quarters, same share count

    previous_holdings/current_holdings should each be a single quarter's
    rows (e.g. period_rank == 1 and period_rank == 0 respectively),
    options already excluded by the caller if desired. Matching is scoped
    per manager via `cik`, so one manager's previous holdings are never
    compared against another manager's current holdings.
    """
    prev = _consolidate_by_manager(previous_holdings)
    curr = _consolidate_by_manager(current_holdings)
    prev["weight_pct"] = _weight_pct_within_manager(prev) if not prev.empty else []
    curr["weight_pct"] = _weight_pct_within_manager(curr) if not curr.empty else []

    prev_slim = prev[["cik", "cusip", "shares", "value_usd", "weight_pct"]].rename(
        columns={"shares": "prev_shares", "value_usd": "prev_value_usd", "weight_pct": "prev_weight_pct"}
    )
    curr_slim = curr[["cik", "cusip", "shares", "value_usd", "weight_pct"]].rename(
        columns={"shares": "curr_shares", "value_usd": "curr_value_usd", "weight_pct": "curr_weight_pct"}
    )

    merged = prev_slim.merge(curr_slim, on=["cik", "cusip"], how="outer")
    for col in [
        "prev_shares", "prev_value_usd", "prev_weight_pct",
        "curr_shares", "curr_value_usd", "curr_weight_pct",
    ]:
        merged[col] = merged[col].fillna(0)

    manager_names = _manager_lookup(prev, curr)
    issuer_names = _issuer_lookup(prev, curr)
    merged["manager_name"] = merged["cik"].map(manager_names)
    merged["name_of_issuer"] = merged["cusip"].map(issuer_names)

    had_prev = merged["prev_shares"] > 0
    has_curr = merged["curr_shares"] > 0

    conditions = [
        ~had_prev & has_curr,
        had_prev & ~has_curr,
        had_prev & has_curr & (merged["curr_shares"] > merged["prev_shares"]),
        had_prev & has_curr & (merged["curr_shares"] < merged["prev_shares"]),
    ]
    choices = ["new_buy", "sold_out", "add", "trim"]
    merged["change_type"] = np.select(conditions, choices, default="unchanged")

    merged["shares_delta"] = merged["curr_shares"] - merged["prev_shares"]
    merged["value_delta_usd"] = merged["curr_value_usd"] - merged["prev_value_usd"]
    merged["weight_delta_pct"] = merged["curr_weight_pct"] - merged["prev_weight_pct"]

    return merged[CHANGE_COLUMNS]


def quarter_changes(previous_holdings: pd.DataFrame, current_holdings: pd.DataFrame) -> pd.DataFrame:
    """Per (manager, cusip): classify the change between two quarterly
    snapshots of the same manager's holdings into new_buy/add/trim/
    sold_out. Rows with unchanged share counts are dropped (not a
    "change") — see _build_change_table for the classification rules.
    """
    if previous_holdings.empty and current_holdings.empty:
        return pd.DataFrame(columns=CHANGE_COLUMNS)

    merged = _build_change_table(previous_holdings, current_holdings)
    merged = merged[merged["change_type"] != "unchanged"]
    return merged.sort_values("value_delta_usd", ascending=False).reset_index(drop=True)


def top_buys(changes: pd.DataFrame) -> pd.DataFrame:
    """Rank cusips by buying activity (new_buy + add) across managers.

    n_new_buyers counts only new_buy rows (brand-new positions);
    total_value_added_usd and avg_weight_change_pct pool both new_buy and
    add rows, since both represent money moving into the position.
    """
    buys = changes[changes["change_type"].isin(["new_buy", "add"])]
    if buys.empty:
        return pd.DataFrame(columns=TOP_BUYS_COLUMNS)

    new_buy_counts = (
        changes[changes["change_type"] == "new_buy"].groupby("cusip").size().rename("n_new_buyers")
    )
    grouped = (
        buys.groupby("cusip")
        .agg(
            name_of_issuer=("name_of_issuer", "first"),
            total_value_added_usd=("value_delta_usd", "sum"),
            avg_weight_change_pct=("weight_delta_pct", "mean"),
        )
        .reset_index()
        .merge(new_buy_counts, on="cusip", how="left")
    )
    grouped["n_new_buyers"] = grouped["n_new_buyers"].fillna(0).astype(int)

    return (
        grouped[TOP_BUYS_COLUMNS]
        .sort_values(["n_new_buyers", "total_value_added_usd"], ascending=False)
        .reset_index(drop=True)
    )


ACTIVITY_COLUMNS = ["cusip", "n_new_buy", "n_add", "n_trim", "n_sold_out"]


def activity_summary(changes: pd.DataFrame) -> pd.DataFrame:
    """Per cusip: how many managers each change_type applied to this
    quarter -- the compact "+2 new / +1 add / -1 trim / -1 sold" signal
    meant to sit inline in the consensus table, instead of requiring a
    separate 최다매수/최다매도 tab visit to see any activity at all.

    `changes` is quarter_changes()'s output (already excludes 'unchanged'
    rows). A cusip with no activity this quarter simply isn't a row here
    -- callers should left-join and fill zeros.
    """
    if changes.empty:
        return pd.DataFrame(columns=ACTIVITY_COLUMNS)

    pivot = changes.groupby(["cusip", "change_type"]).size().unstack(fill_value=0)
    for col in ("new_buy", "add", "trim", "sold_out"):
        if col not in pivot.columns:
            pivot[col] = 0
    pivot = pivot.rename(
        columns={"new_buy": "n_new_buy", "add": "n_add", "trim": "n_trim", "sold_out": "n_sold_out"}
    ).reset_index()

    return pivot[ACTIVITY_COLUMNS]


def top_sells(changes: pd.DataFrame) -> pd.DataFrame:
    """Rank cusips by selling activity (trim + sold_out) across managers.

    n_sold_out counts only sold_out rows (fully exited positions);
    total_value_reduced_usd pools both trim and sold_out (as a positive
    magnitude, i.e. how much value was pulled out).
    """
    sells = changes[changes["change_type"].isin(["trim", "sold_out"])]
    if sells.empty:
        return pd.DataFrame(columns=TOP_SELLS_COLUMNS)

    sold_out_counts = (
        changes[changes["change_type"] == "sold_out"].groupby("cusip").size().rename("n_sold_out")
    )
    grouped = (
        sells.groupby("cusip")
        .agg(
            name_of_issuer=("name_of_issuer", "first"),
            total_value_reduced_usd=("value_delta_usd", "sum"),
        )
        .reset_index()
        .merge(sold_out_counts, on="cusip", how="left")
    )
    grouped["n_sold_out"] = grouped["n_sold_out"].fillna(0).astype(int)
    grouped["total_value_reduced_usd"] = grouped["total_value_reduced_usd"].abs()

    return (
        grouped[TOP_SELLS_COLUMNS]
        .sort_values(["n_sold_out", "total_value_reduced_usd"], ascending=False)
        .reset_index(drop=True)
    )
