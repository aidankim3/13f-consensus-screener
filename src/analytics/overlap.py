"""Cross-manager overlap + portfolio-similarity analytics.

Pure pandas: DataFrame in, DataFrame out (or a float, for the single-pair
Jaccard score). No network, no knowledge of where the data came from.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

OVERLAP_COLUMNS = [
    "cusip",
    "name_of_issuer",
    "a_change_type",
    "b_change_type",
    "a_shares",
    "b_shares",
    "relationship",
    "opposite_trade",
]

_BUY_TYPES = {"new_buy", "add"}
_SELL_TYPES = {"trim", "sold_out"}


def pairwise_overlap(portfolio_a: pd.DataFrame, portfolio_b: pd.DataFrame) -> pd.DataFrame:
    """Compare two managers' full portfolios for the same quarter.

    portfolio_a/portfolio_b are each investor.investor_portfolio() output
    for a single manager (cusip, name_of_issuer, curr_shares, change_type
    at minimum, unchanged/sold_out rows included).

    One row per cusip appearing in either portfolio (a cusip neither
    currently holds -- both fully sold out -- is dropped, since there's
    nothing to compare). Columns:
        relationship     "common" (both hold now), "only_a", "only_b"
        opposite_trade    True when, this quarter, one manager was buying
                          (new_buy/add) while the other was selling
                          (trim/sold_out) on the SAME cusip -- independent
                          of `relationship`, since the seller may have
                          already fully exited (sold_out => not "holding
                          now", but still a sell for direction purposes)
    """
    a = portfolio_a[["cusip", "name_of_issuer", "curr_shares", "change_type"]].rename(
        columns={"curr_shares": "a_shares", "change_type": "a_change_type"}
    )
    b = portfolio_b[["cusip", "name_of_issuer", "curr_shares", "change_type"]].rename(
        columns={"curr_shares": "b_shares", "change_type": "b_change_type"}
    )

    merged = a.merge(b, on="cusip", how="outer", suffixes=("_a", "_b"))
    merged["name_of_issuer"] = merged["name_of_issuer_a"].fillna(merged["name_of_issuer_b"])
    merged = merged.drop(columns=["name_of_issuer_a", "name_of_issuer_b"])
    merged["a_shares"] = merged["a_shares"].fillna(0)
    merged["b_shares"] = merged["b_shares"].fillna(0)

    a_holds = merged["a_shares"] > 0
    b_holds = merged["b_shares"] > 0
    merged["relationship"] = np.select(
        [a_holds & b_holds, a_holds & ~b_holds, ~a_holds & b_holds],
        ["common", "only_a", "only_b"],
        default="neither",
    )

    a_buying = merged["a_change_type"].isin(_BUY_TYPES)
    a_selling = merged["a_change_type"].isin(_SELL_TYPES)
    b_buying = merged["b_change_type"].isin(_BUY_TYPES)
    b_selling = merged["b_change_type"].isin(_SELL_TYPES)
    merged["opposite_trade"] = (a_buying & b_selling) | (a_selling & b_buying)

    merged = merged[merged["relationship"] != "neither"]

    return (
        merged[OVERLAP_COLUMNS]
        .sort_values(["relationship", "cusip"])
        .reset_index(drop=True)
    )


def jaccard_similarity(current_holdings_a: pd.DataFrame, current_holdings_b: pd.DataFrame) -> float:
    """Jaccard index of two managers' currently-held cusip sets: |A∩B| / |A∪B|.

    Inputs are each manager's current-quarter holdings (any frame with a
    'cusip' column, e.g. holdings[holdings.cik == X]). Returns a 0..1
    score (not a percentage); 0.0 when both sets are empty.
    """
    set_a = set(current_holdings_a["cusip"].unique())
    set_b = set(current_holdings_b["cusip"].unique())
    if not set_a and not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def similarity_matrix(current_holdings: pd.DataFrame) -> pd.DataFrame:
    """N x N Jaccard similarity matrix (manager_name x manager_name), as
    percentages (0-100), from a single multi-manager current-quarter
    holdings frame (e.g. holdings[holdings.period_rank == 0], options
    excluded by the caller if desired). Diagonal is 100.
    """
    managers = (
        current_holdings[["cik", "manager_name"]].drop_duplicates().sort_values("manager_name")
    )
    cusip_sets = {
        cik: set(current_holdings.loc[current_holdings["cik"] == cik, "cusip"].unique())
        for cik in managers["cik"]
    }
    names = managers.set_index("cik")["manager_name"]

    matrix = pd.DataFrame(
        index=managers["manager_name"], columns=managers["manager_name"], dtype=float
    )
    for cik_i in managers["cik"]:
        for cik_j in managers["cik"]:
            set_i, set_j = cusip_sets[cik_i], cusip_sets[cik_j]
            union = set_i | set_j
            similarity = (len(set_i & set_j) / len(union) * 100) if union else 0.0
            matrix.loc[names[cik_i], names[cik_j]] = similarity

    matrix.index.name = None
    matrix.columns.name = None
    return matrix
