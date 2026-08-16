"""SQLite persistence for the Form 4 insider-purchase transaction table.

Mirrors storage.py's holdings persistence exactly, kept as its own small
module (its own db file, data/insider.db) rather than folded into
storage.py, so it can be rebuilt/refreshed independently of the 13F
holdings snapshot.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from src.edgar.form4 import TRANSACTION_COLUMNS

INSIDER_TABLE = "insider_transactions"


def save_insider_table(transactions: pd.DataFrame, db_path: Path) -> None:
    """Replace the insider transactions table with the given DataFrame.
    Full replace, not append -- build_insider.py always re-fetches the
    whole lookback window fresh.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        transactions.to_sql(INSIDER_TABLE, conn, if_exists="replace", index=False)


def load_insider_table(db_path: Path) -> pd.DataFrame:
    """Empty (correctly-columned) frame if the db/table doesn't exist yet
    -- lets the UI render a normal empty state instead of crashing on a
    fresh checkout before build_insider.py has ever run.
    """
    if not db_path.exists():
        return pd.DataFrame(columns=TRANSACTION_COLUMNS)
    with sqlite3.connect(db_path) as conn:
        try:
            return pd.read_sql(f"SELECT * FROM {INSIDER_TABLE}", conn)
        except pd.errors.DatabaseError:
            return pd.DataFrame(columns=TRANSACTION_COLUMNS)
