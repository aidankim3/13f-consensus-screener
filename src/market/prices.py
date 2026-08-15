"""Quarterly average "entry price" estimate + current price, via yfinance.

Not SEC-EDGAR-specific; lives outside src/edgar. No Streamlit dependency.
Side-effecting (network + disk cache) like src/edgar/fetch.py.

13F doesn't disclose trade dates or prices within a quarter -- only the
quarter-end position. The "entry price" here is therefore a rough proxy:
the average of that quarter's first trading day Open and last trading day
Close, for whichever ticker the holding was reported under. It is NOT an
actual transaction price. This approximation is surfaced to the user in
the UI, not just in code comments.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

QUARTERLY_PRICE_TABLE = "quarterly_price_cache"
CURRENT_PRICE_TABLE = "current_price_cache"
DAILY_PRICE_TABLE = "daily_price_cache"

# A past quarter's average price never changes, so it's cached forever.
# "Current" price does change, so it's re-fetched periodically.
CURRENT_PRICE_TTL_SECONDS = 3600


def _quarter_start(period_date: str) -> str:
    """First calendar day of the quarter that period_date (a quarter-end
    date, e.g. '2026-03-31') falls in."""
    d = datetime.strptime(period_date, "%Y-%m-%d").date()
    start_month = (d.month - 1) // 3 * 3 + 1
    return date(d.year, start_month, 1).isoformat()


def _day_after(period_date: str) -> str:
    d = datetime.strptime(period_date, "%Y-%m-%d").date()
    return (d + timedelta(days=1)).isoformat()


def _init_cache(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {QUARTERLY_PRICE_TABLE} (
            ticker TEXT, period_date TEXT, avg_price REAL, fetched_at TEXT,
            PRIMARY KEY (ticker, period_date)
        )
        """
    )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {CURRENT_PRICE_TABLE} (
            ticker TEXT PRIMARY KEY, price REAL, fetched_at TEXT
        )
        """
    )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {DAILY_PRICE_TABLE} (
            ticker TEXT, date TEXT, close REAL,
            PRIMARY KEY (ticker, date)
        )
        """
    )
    conn.commit()


def _fetch_quarterly_avg_price(ticker: str, period_date: str) -> Optional[float]:
    start = _quarter_start(period_date)
    end = _day_after(period_date)  # yfinance's `end` is exclusive
    try:
        hist = yf.Ticker(ticker).history(start=start, end=end)
    except Exception as exc:  # yfinance raises a variety of exception types
        logger.warning("quarterly price history fetch failed for %s: %s", ticker, exc)
        return None
    if hist.empty:
        logger.warning("no price history for %s in %s..%s", ticker, start, period_date)
        return None
    open_price = float(hist["Open"].iloc[0])
    close_price = float(hist["Close"].iloc[-1])
    return (open_price + close_price) / 2


def _fetch_current_price(ticker: str) -> Optional[float]:
    try:
        hist = yf.Ticker(ticker).history(period="5d")
    except Exception as exc:
        logger.warning("current price fetch failed for %s: %s", ticker, exc)
        return None
    if hist.empty:
        return None
    return float(hist["Close"].iloc[-1])


def get_quarterly_avg_prices(
    tickers_with_periods: list[tuple[str, str]], db_path: Path
) -> dict[tuple[str, str], Optional[float]]:
    """Resolve [(ticker, period_date), ...] to {(ticker, period_date): avg_price or None}.

    Cached indefinitely in db_path -- a past quarter's average price is
    immutable once computed.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        _init_cache(conn)
        cached = {
            (t, p): price
            for t, p, price in conn.execute(
                f"SELECT ticker, period_date, avg_price FROM {QUARTERLY_PRICE_TABLE}"
            ).fetchall()
        }

        to_fetch = [key for key in tickers_with_periods if key not in cached]
        if to_fetch:
            logger.info("fetching %d quarterly avg price(s) via yfinance", len(to_fetch))
            now = time.strftime("%Y-%m-%dT%H:%M:%S")
            rows = []
            for ticker, period_date in to_fetch:
                price = _fetch_quarterly_avg_price(ticker, period_date)
                cached[(ticker, period_date)] = price
                rows.append((ticker, period_date, price, now))
            conn.executemany(
                f"INSERT OR REPLACE INTO {QUARTERLY_PRICE_TABLE} "
                f"(ticker, period_date, avg_price, fetched_at) VALUES (?, ?, ?, ?)",
                rows,
            )
            conn.commit()

    return {key: cached.get(key) for key in tickers_with_periods}


def get_current_prices(tickers: list[str], db_path: Path) -> dict[str, Optional[float]]:
    """Resolve tickers to {ticker: latest close price or None}.

    Cached in db_path for CURRENT_PRICE_TTL_SECONDS; a fresh Streamlit
    session reuses a recent price instead of re-hitting yfinance for
    every rerun.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        _init_cache(conn)
        now_ts = time.time()
        rows = conn.execute(f"SELECT ticker, price, fetched_at FROM {CURRENT_PRICE_TABLE}").fetchall()
        cached: dict[str, Optional[float]] = {}
        stale: set[str] = set(tickers)
        for ticker, price, fetched_at in rows:
            fetched_ts = time.mktime(time.strptime(fetched_at, "%Y-%m-%dT%H:%M:%S"))
            if ticker in stale and (now_ts - fetched_ts) < CURRENT_PRICE_TTL_SECONDS:
                cached[ticker] = price
                stale.discard(ticker)

        if stale:
            logger.info("fetching %d current price(s) via yfinance", len(stale))
            now = time.strftime("%Y-%m-%dT%H:%M:%S")
            rows_to_write = []
            for ticker in stale:
                price = _fetch_current_price(ticker)
                cached[ticker] = price
                rows_to_write.append((ticker, price, now))
            conn.executemany(
                f"INSERT OR REPLACE INTO {CURRENT_PRICE_TABLE} (ticker, price, fetched_at) "
                f"VALUES (?, ?, ?)",
                rows_to_write,
            )
            conn.commit()

    return {t: cached.get(t) for t in tickers}


def _fetch_daily_history(ticker: str, start: str, end: str) -> Optional[pd.DataFrame]:
    try:
        hist = yf.Ticker(ticker).history(start=start, end=_day_after(end))
    except Exception as exc:
        logger.warning("daily price history fetch failed for %s: %s", ticker, exc)
        return None
    return hist if not hist.empty else None


def get_price_history(ticker: str, start: str, end: str, db_path: Path) -> pd.Series:
    """Daily close price series for `ticker` from `start` to `end`
    (inclusive), indexed by date (a pandas Series, name=ticker).

    Cached per-ticker in db_path. If the cached rows already cover most
    (>=90%) of the requested range's weekdays, the cache is trusted as-is
    (holidays mean 100% coverage is never expected); otherwise the full
    range is re-fetched from yfinance and merged in. Returns an empty
    Series (never raises) if the ticker can't be resolved or has no data.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        _init_cache(conn)

        def _read_cached() -> pd.DataFrame:
            return pd.read_sql(
                f"SELECT date, close FROM {DAILY_PRICE_TABLE} "
                f"WHERE ticker = ? AND date >= ? AND date <= ?",
                conn,
                params=(ticker, start, end),
            )

        cached = _read_cached()
        expected_weekdays = max(len(pd.bdate_range(start, end)), 1)
        coverage = len(cached) / expected_weekdays

        if coverage < 0.9:
            hist = _fetch_daily_history(ticker, start, end)
            if hist is not None:
                logger.info("fetched daily price history for %s (%s..%s)", ticker, start, end)
                rows = [
                    (ticker, idx.strftime("%Y-%m-%d"), float(row["Close"]))
                    for idx, row in hist.iterrows()
                ]
                conn.executemany(
                    f"INSERT OR REPLACE INTO {DAILY_PRICE_TABLE} (ticker, date, close) "
                    f"VALUES (?, ?, ?)",
                    rows,
                )
                conn.commit()
                cached = _read_cached()

    if cached.empty:
        return pd.Series(dtype="float64", name=ticker)
    cached["date"] = pd.to_datetime(cached["date"])
    return cached.set_index("date")["close"].sort_index().rename(ticker)


def get_52week_range(tickers: list[str], db_path: Path) -> dict[str, tuple[Optional[float], Optional[float]]]:
    """Resolve tickers to {ticker: (52w_low, 52w_high)} in daily closes.

    Built on get_price_history() (same DAILY_PRICE_TABLE cache, no new
    table) rather than a separate yfinance call, so a ticker already
    warmed by a price-history/backtest fetch costs nothing extra here.
    (None, None) for a ticker with no price history at all.
    """
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=365)).isoformat()
    result: dict[str, tuple[Optional[float], Optional[float]]] = {}
    for ticker in tickers:
        series = get_price_history(ticker, start, end, db_path)
        result[ticker] = (float(series.min()), float(series.max())) if not series.empty else (None, None)
    return result
