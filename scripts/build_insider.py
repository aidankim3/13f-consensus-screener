"""One-off/periodic job: fetch recent Form 4 open-market insider-purchase
activity for every stock currently held by >=2 tracked investors, and
save it to data/insider.db.

Scoped to the "2+ holder" consensus universe (not every stock any single
manager has ever held) to keep SEC request volume bounded -- each stock
needs one browse-edgar call to list its Form 4 filings, plus one more
per filing found in the lookback window.

Usage:
    ..\\.venv\\Scripts\\python.exe scripts\\build_insider.py
"""
from __future__ import annotations

import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.analytics.consensus import consensus_holdings
from src.edgar.client import EdgarClient
from src.edgar.form4 import fetch_insider_buys_for_issuer
from src.edgar.insider_storage import save_insider_table
from src.edgar.storage import load_holdings_table
from src.market.issuer_cik import resolve_issuer_ciks
from src.market.ticker_map import resolve_tickers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
HOLDINGS_DB_PATH = ROOT / "data" / "holdings.db"
TICKER_DB_PATH = ROOT / "data" / "tickers.db"
ISSUER_CIK_DB_PATH = ROOT / "data" / "issuer_ciks.db"
INSIDER_DB_PATH = ROOT / "data" / "insider.db"
FORM4_CACHE_DIR = ROOT / "data" / "raw_form4"
USER_AGENT = "Aidan Kim aidankim3@gmail.com"

# Dataroma's own "Insider Buys" window is 3 months; padded a little so a
# quarter-boundary run doesn't just barely miss something.
LOOKBACK_DAYS = 100

FAILED_TICKERS_LOG_PATH = ROOT / "data" / "insider_build_failed_tickers.txt"
MAX_ATTEMPTS = 3


def _fetch_with_retries(client, cik, ticker, since_date, cache_dir):
    """Retry a ticker up to MAX_ATTEMPTS times before giving up -- a
    single transient network blip (read timeout, connection reset)
    shouldn't permanently drop a ticker from the snapshot. Cheap to retry:
    fetch_insider_buys_for_issuer disk-caches each filing's XML as soon as
    it succeeds, so a retry only re-does whatever didn't finish last time.
    """
    last_exc: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return fetch_insider_buys_for_issuer(client, cik, ticker, since_date, cache_dir)
        except Exception as exc:
            last_exc = exc
            if attempt < MAX_ATTEMPTS:
                logger.warning(
                    "%s (issuer CIK %s): attempt %d/%d failed (%s) -- retrying",
                    ticker, cik, attempt, MAX_ATTEMPTS, exc,
                )
                time.sleep(2 * attempt)
    logger.error(
        "%s (issuer CIK %s): failed after %d attempts: %s -- skipping",
        ticker, cik, MAX_ATTEMPTS, last_exc,
    )
    return None


def main() -> None:
    holdings = load_holdings_table(HOLDINGS_DB_PATH)
    holdings["period_date"] = pd.to_datetime(holdings["period_date"])
    holdings["is_option"] = holdings["is_option"].astype(bool)
    latest = holdings[holdings["period_rank"] == 0]
    latest_stock_only = latest[~latest["is_option"]]
    consensus = consensus_holdings(latest_stock_only)
    universe = consensus[consensus["holder_count"] >= 2]
    logger.info("%d consensus stocks (2+ holders) in scope", len(universe))

    tickers = resolve_tickers(
        dict(zip(universe["cusip"], universe["name_of_issuer"])), TICKER_DB_PATH, USER_AGENT
    )
    resolved_tickers = sorted({t for t in tickers.values() if t})
    logger.info("%d/%d resolved to a ticker", len(resolved_tickers), len(universe))

    issuer_ciks = resolve_issuer_ciks(resolved_tickers, ISSUER_CIK_DB_PATH, USER_AGENT)
    resolved_ciks = {t: c for t, c in issuer_ciks.items() if c}
    logger.info("%d/%d tickers resolved to an issuer CIK", len(resolved_ciks), len(resolved_tickers))

    client = EdgarClient(user_agent=USER_AGENT)
    since_date = (date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    logger.info("fetching Form 4 purchases filed on/after %s", since_date)

    frames = []
    failed_tickers: list[str] = []
    items = list(resolved_ciks.items())
    for i, (ticker, cik) in enumerate(items):
        df = _fetch_with_retries(client, cik, ticker, since_date, FORM4_CACHE_DIR)
        if df is None:
            failed_tickers.append(ticker)
        elif not df.empty:
            logger.info("%s: %d purchase transaction(s)", ticker, len(df))
            frames.append(df)
        if (i + 1) % 20 == 0:
            logger.info("progress: %d/%d tickers processed (%d failed so far)", i + 1, len(items), len(failed_tickers))

    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    save_insider_table(combined, INSIDER_DB_PATH)
    logger.info(
        "saved %d insider purchase transaction(s) across %d tickers to %s",
        len(combined), len(frames), INSIDER_DB_PATH,
    )

    if failed_tickers:
        FAILED_TICKERS_LOG_PATH.write_text("\n".join(failed_tickers), encoding="utf-8")
        logger.warning(
            "%d ticker(s) failed after %d attempts each -- listed in %s (re-run this script to retry; "
            "already-succeeded tickers' filings stay cached and fly through instantly)",
            len(failed_tickers), MAX_ATTEMPTS, FAILED_TICKERS_LOG_PATH,
        )
    elif FAILED_TICKERS_LOG_PATH.exists():
        FAILED_TICKERS_LOG_PATH.unlink()


if __name__ == "__main__":
    main()
