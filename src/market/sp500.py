"""Static S&P 500 constituent list (ticker, name, GICS sector).

Not fetched live -- backed by data/sp500.csv, a one-time snapshot pulled
from Wikipedia's "List of S&P 500 companies" page. Index membership
changes only a handful of times a year, so re-fetching on every app run
isn't worth taking on a network dependency (and a Wikipedia-scrape
failure) for something this static. Re-run the fetch (see README) to
refresh the snapshot occasionally.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

SP500_COLUMNS = ["ticker", "name", "sector"]


def load_sp500(csv_path: Path) -> pd.DataFrame:
    return pd.read_csv(csv_path)[SP500_COLUMNS]
