"""Ticker -> sector/industry classification, via yfinance.

Not SEC-EDGAR-specific; lives outside src/edgar. No Streamlit dependency.
Side-effecting (network + disk cache) like ticker_map.py / prices.py.

Unlike OpenFIGI (ticker_map.py), yfinance's per-ticker `.info` lookup has
no bulk/batch endpoint and is noticeably slower and less reliable at
scale. Callers should scope this to small ticker sets (e.g. one manager's
~50-150 holdings) rather than the full multi-thousand-ticker universe.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from typing import Optional

import yfinance as yf

logger = logging.getLogger(__name__)

SECTOR_TABLE = "ticker_sector_map"


def _init_cache(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SECTOR_TABLE} (
            ticker TEXT PRIMARY KEY, sector TEXT, industry TEXT, fetched_at TEXT
        )
        """
    )
    conn.commit()


def _fetch_sector(ticker: str) -> tuple[Optional[str], Optional[str]]:
    try:
        info = yf.Ticker(ticker).info
    except Exception as exc:  # yfinance raises a variety of exception types
        logger.warning("sector lookup failed for %s: %s", ticker, exc)
        return None, None
    return info.get("sector"), info.get("industry")


def resolve_sectors(tickers: list[str], db_path: Path) -> dict[str, tuple[Optional[str], Optional[str]]]:
    """Resolve tickers to {ticker: (sector, industry)}.

    Cached indefinitely in db_path -- a company's sector classification
    changes rarely enough that re-checking isn't worth the cost. Missing/
    failed lookups are cached as (None, None) too, so a bad ticker is
    never retried every rerun.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        _init_cache(conn)
        cached: dict[str, tuple[Optional[str], Optional[str]]] = {
            t: (sector, industry)
            for t, sector, industry in conn.execute(f"SELECT ticker, sector, industry FROM {SECTOR_TABLE}")
        }

        to_fetch = [t for t in tickers if t not in cached]
        if to_fetch:
            logger.info("resolving %d new ticker sector(s) via yfinance", len(to_fetch))
            now = time.strftime("%Y-%m-%dT%H:%M:%S")
            rows = []
            for ticker in to_fetch:
                sector, industry = _fetch_sector(ticker)
                cached[ticker] = (sector, industry)
                rows.append((ticker, sector, industry, now))
            conn.executemany(
                f"INSERT OR REPLACE INTO {SECTOR_TABLE} (ticker, sector, industry, fetched_at) "
                f"VALUES (?, ?, ?, ?)",
                rows,
            )
            conn.commit()

    return {t: cached.get(t, (None, None)) for t in tickers}
