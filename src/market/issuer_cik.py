"""Ticker -> issuer CIK, via SEC's company_tickers.json.

Not SEC-EDGAR-specific to 13F, but the SEC IS the source, so this
mirrors ticker_map.py's shape rather than living under src/edgar --
needed to look up Form 4 (insider trading) filings for a given ticker,
since those are cross-referenced on EDGAR by the ISSUER's CIK via the
classic browse-edgar endpoint (see src/edgar/form4.py), not by ticker.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

ISSUER_CIK_TABLE = "ticker_issuer_cik_map"
SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


def _init_cache(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {ISSUER_CIK_TABLE} (
            ticker TEXT PRIMARY KEY, cik TEXT, fetched_at TEXT
        )
        """
    )
    conn.commit()


def resolve_issuer_ciks(tickers: list[str], db_path: Path, user_agent: str) -> dict[str, Optional[str]]:
    """Resolve tickers to {ticker: issuer CIK or None}.

    Cached indefinitely in db_path -- a ticker's issuer CIK never
    changes. The whole SEC company_tickers.json index (all ~10k US
    listed tickers) is fetched in ONE request on a cache miss and used
    to resolve every missing ticker at once, rather than one request per
    ticker.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        _init_cache(conn)
        cached: dict[str, Optional[str]] = {
            t: c for t, c in conn.execute(f"SELECT ticker, cik FROM {ISSUER_CIK_TABLE}")
        }

        missing = [t for t in tickers if t not in cached]
        if missing:
            logger.info("resolving %d ticker(s) to issuer CIK via SEC company_tickers.json", len(missing))
            try:
                response = requests.get(
                    SEC_COMPANY_TICKERS_URL, headers={"User-Agent": user_agent}, timeout=30
                )
                response.raise_for_status()
                data = response.json()
            except (requests.RequestException, ValueError) as exc:
                logger.warning("could not fetch SEC company_tickers.json (%s); leaving unresolved", exc)
                data = {}

            index = {entry["ticker"]: str(entry["cik_str"]).zfill(10) for entry in data.values()}
            now = time.strftime("%Y-%m-%dT%H:%M:%S")
            rows = [(t, index.get(t), now) for t in missing]
            conn.executemany(
                f"INSERT OR REPLACE INTO {ISSUER_CIK_TABLE} (ticker, cik, fetched_at) VALUES (?, ?, ?)",
                rows,
            )
            conn.commit()
            cached.update({t: index.get(t) for t in missing})

    return {t: cached.get(t) for t in tickers}
