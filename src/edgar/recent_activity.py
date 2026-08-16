"""Cross-investor recent SEC filing activity (ANY form type) -- powers
the Home page's "Superinvestor Portfolio Updates" feed.

Deliberately separate from build.py's 13F-specific holdings pipeline:
this is about "what has each tracked investor filed with the SEC
lately" (13F-HR, SC 13D/13G, Form 3/4/5 if they're also an individual
filer, etc.), not about parsing 13F holdings data.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

from src.edgar.client import EdgarClient, list_recent_filings

logger = logging.getLogger(__name__)

RECENT_ACTIVITY_COLUMNS = ["manager_name", "cik", "form", "filing_date", "accession_number"]
RECENT_ACTIVITY_TABLE = "recent_activity"


def fetch_recent_activity(
    client: EdgarClient, investors: list[dict[str, Any]], per_investor_limit: int = 3
) -> list[dict[str, Any]]:
    """Each tracked investor's most recent `per_investor_limit` SEC
    filings (any form type), combined across all investors and sorted by
    filing date descending.

    One request per investor (get_submissions); a failure for one
    investor is logged and skipped rather than dropping everyone else's
    activity -- same isolation principle as build.py's per-investor loop.
    """
    rows: list[dict[str, Any]] = []
    for inv in investors:
        try:
            submissions = client.get_submissions(inv["cik"])
        except Exception as exc:
            logger.warning(
                "%s (CIK %s): failed to fetch submissions for recent activity: %s -- skipping",
                inv["name"], inv["cik"], exc,
            )
            continue
        for filing in list_recent_filings(submissions, limit=per_investor_limit):
            rows.append(
                {
                    "manager_name": inv["name"],
                    "cik": inv["cik"],
                    "form": filing["form"],
                    "filing_date": filing["filingDate"],
                    "accession_number": filing["accessionNumber"],
                }
            )

    return sorted(rows, key=lambda r: r["filing_date"], reverse=True)


def save_recent_activity_table(activity: pd.DataFrame, db_path: Path) -> None:
    """Replace the recent-activity table with the given DataFrame. Full
    replace, not append -- scripts/build_recent_activity.py always
    re-fetches each investor's latest filings fresh.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        activity.to_sql(RECENT_ACTIVITY_TABLE, conn, if_exists="replace", index=False)


def load_recent_activity_table(db_path: Path) -> pd.DataFrame:
    """Empty (correctly-columned) frame if the db/table doesn't exist yet
    -- lets the UI render a normal empty state instead of crashing on a
    fresh checkout before build_recent_activity.py has ever run.
    """
    if not db_path.exists():
        return pd.DataFrame(columns=RECENT_ACTIVITY_COLUMNS)
    with sqlite3.connect(db_path) as conn:
        try:
            return pd.read_sql(f"SELECT * FROM {RECENT_ACTIVITY_TABLE}", conn)
        except pd.errors.DatabaseError:
            return pd.DataFrame(columns=RECENT_ACTIVITY_COLUMNS)
