"""SQLite persistence for the normalized holdings table."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

HOLDINGS_TABLE = "holdings"


def save_holdings_table(holdings: pd.DataFrame, db_path: Path) -> None:
    """Replace the holdings table with the given DataFrame.

    Full replace, not append/upsert — build.py always fetches each
    manager's single latest filing, so there is nothing to merge yet.
    Historical accumulation across runs is a later step.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        holdings.to_sql(HOLDINGS_TABLE, conn, if_exists="replace", index=False)


def load_holdings_table(db_path: Path) -> pd.DataFrame:
    with sqlite3.connect(db_path) as conn:
        return pd.read_sql(f"SELECT * FROM {HOLDINGS_TABLE}", conn)
