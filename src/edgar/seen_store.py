"""Tracks which filings have already been seen/alerted on, across runs.

Used by src/jobs/refresh.py to detect genuinely NEW filings. Side-effecting
(disk cache), no Streamlit dependency.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

SEEN_FILINGS_TABLE = "seen_filings"


def _init(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SEEN_FILINGS_TABLE} (
            tracking_key TEXT,
            accession_number TEXT,
            form TEXT,
            filing_date TEXT,
            first_seen_at TEXT,
            PRIMARY KEY (tracking_key, accession_number)
        )
        """
    )
    conn.commit()


def filter_new_filings(
    tracking_key: str, filings: list[dict[str, Any]], db_path: Path
) -> tuple[list[dict[str, Any]], bool]:
    """Return (new_filings, is_first_run) for one tracked feed.

    `tracking_key` scopes the seen-set (e.g. "{cik}:13F" vs "{cik}:13D-G"
    so a manager's two feeds are tracked independently). Every filing
    passed in is recorded as seen regardless of outcome, so the next call
    only reports what's genuinely new since this run.

    On the very first call for a tracking_key (no prior history at all),
    nothing is reported as "new" -- that would just dump the manager's
    entire filing history as if it all happened today. Instead this
    silently establishes a baseline (is_first_run=True) so only real
    future changes get surfaced.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        _init(conn)
        seen = {
            row[0]
            for row in conn.execute(
                f"SELECT accession_number FROM {SEEN_FILINGS_TABLE} WHERE tracking_key = ?",
                (tracking_key,),
            ).fetchall()
        }
        is_first_run = len(seen) == 0
        new_filings = [] if is_first_run else [f for f in filings if f["accessionNumber"] not in seen]

        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        conn.executemany(
            f"INSERT OR IGNORE INTO {SEEN_FILINGS_TABLE} "
            f"(tracking_key, accession_number, form, filing_date, first_seen_at) "
            f"VALUES (?, ?, ?, ?, ?)",
            [
                (tracking_key, f["accessionNumber"], f["form"], f["filingDate"], now)
                for f in filings
            ],
        )
        conn.commit()

    return new_filings, is_first_run
