"""Periodic job: snapshot every tracked investor's most recent SEC
filings (any form type -- 13F, 13D/13G, Form 3/4/5, etc.) into
data/recent_activity.db.

Home's "Superinvestor Portfolio Updates" feed reads this pre-built
snapshot instead of hitting SEC live on every page load. Run on a
schedule (see .github/workflows/refresh_data.yml) rather than in-app.

Usage:
    ..\\.venv\\Scripts\\python.exe scripts\\build_recent_activity.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.edgar.build import load_investors
from src.edgar.client import EdgarClient
from src.edgar.recent_activity import (
    RECENT_ACTIVITY_COLUMNS,
    fetch_recent_activity,
    save_recent_activity_table,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
RECENT_ACTIVITY_DB_PATH = ROOT / "data" / "recent_activity.db"
USER_AGENT = "Aidan Kim aidankim3@gmail.com"

PER_INVESTOR_LIMIT = 3


def main() -> None:
    investors = load_investors()
    logger.info("fetching latest %d filings (any form type) for %d investors", PER_INVESTOR_LIMIT, len(investors))

    client = EdgarClient(user_agent=USER_AGENT)
    rows = fetch_recent_activity(client, investors, per_investor_limit=PER_INVESTOR_LIMIT)

    activity = pd.DataFrame(rows, columns=RECENT_ACTIVITY_COLUMNS)
    save_recent_activity_table(activity, RECENT_ACTIVITY_DB_PATH)
    logger.info("saved %d recent filing row(s) to %s", len(activity), RECENT_ACTIVITY_DB_PATH)


if __name__ == "__main__":
    main()
