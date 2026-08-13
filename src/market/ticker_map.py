"""CUSIP -> ticker resolution.

Not SEC-EDGAR-specific (OpenFIGI + SEC's public company_tickers.json used
only as a name-based fallback), so this lives outside src/edgar. Pure
data-layer code: no Streamlit dependency. Side-effecting (network + disk
cache) like src/edgar/fetch.py.

Method, cheapest-first:
1. OpenFIGI's free mapping API (no API key needed, rate-limited) resolves
   CUSIP -> ticker directly and precisely, including share class (e.g.
   distinguishes GOOGL/Alphabet Class A from GOOG/Class C).
2. For anything OpenFIGI doesn't resolve, fall back to exact-match on a
   normalized company name against SEC's own company_tickers.json (every
   SEC registrant's primary ticker). Coarser -- can't distinguish share
   classes -- but free and needs no extra registration.
All results (including "not found") are cached in SQLite so a CUSIP is
only ever looked up once.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

# OpenFIGI's unauthenticated limits: max 10 jobs/request, ~25 requests/min.
_OPENFIGI_BATCH_SIZE = 10
_OPENFIGI_MIN_SECONDS_BETWEEN_BATCHES = 2.6  # ~23 req/min, under the cap
_PREFERRED_EXCH_CODE = "US"  # composite US listing, when present

TICKER_MAP_TABLE = "cusip_ticker_map"

_NAME_SUFFIXES = {
    "INC", "INCORPORATED", "CORP", "CORPORATION", "CO", "COMPANY", "LTD",
    "LIMITED", "LLC", "LP", "LLP", "PLC", "HOLDINGS", "HLDGS", "GROUP",
    "GRP", "SA", "NV", "AG", "THE", "NEW",
}


def _normalize_name(name: str) -> str:
    """Normalize an issuer/company name for exact-match comparison."""
    name = name.upper()
    name = re.sub(r"\bCLASS\s+[A-Z]\b", " ", name)
    name = re.sub(r"\bCL\s+[A-Z]\b", " ", name)
    name = re.sub(r"[^A-Z0-9\s]", " ", name)
    tokens = [t for t in name.split() if t not in _NAME_SUFFIXES]
    return " ".join(tokens)


def _init_cache(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TICKER_MAP_TABLE} (
            cusip TEXT PRIMARY KEY,
            ticker TEXT,
            source TEXT,
            resolved_at TEXT
        )
        """
    )
    conn.commit()


def _load_cache(conn: sqlite3.Connection) -> dict[str, Optional[str]]:
    rows = conn.execute(f"SELECT cusip, ticker FROM {TICKER_MAP_TABLE}").fetchall()
    return {cusip: ticker for cusip, ticker in rows}


def _save_to_cache(conn: sqlite3.Connection, resolved: dict[str, Optional[str]], source: str) -> None:
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    conn.executemany(
        f"INSERT OR REPLACE INTO {TICKER_MAP_TABLE} (cusip, ticker, source, resolved_at) "
        f"VALUES (?, ?, ?, ?)",
        [(cusip, ticker, source, now) for cusip, ticker in resolved.items()],
    )
    conn.commit()


def _resolve_via_openfigi(cusips: list[str]) -> dict[str, Optional[str]]:
    """Resolve CUSIPs to tickers via OpenFIGI. Missing/failed lookups map
    to None rather than raising -- callers must not crash on a
    third-party API hiccup."""
    resolved: dict[str, Optional[str]] = {}
    for i in range(0, len(cusips), _OPENFIGI_BATCH_SIZE):
        batch = cusips[i : i + _OPENFIGI_BATCH_SIZE]
        body = [{"idType": "ID_CUSIP", "idValue": c} for c in batch]
        try:
            response = requests.post(
                OPENFIGI_URL, json=body, headers={"Content-Type": "application/json"}, timeout=30
            )
            response.raise_for_status()
            results = response.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning("OpenFIGI batch lookup failed (%s), leaving as unresolved: %s", exc, batch)
            results = [{} for _ in batch]

        for cusip, result in zip(batch, results):
            data = result.get("data") if isinstance(result, dict) else None
            if not data:
                resolved[cusip] = None
                continue
            preferred = [d for d in data if d.get("exchCode") == _PREFERRED_EXCH_CODE]
            pick = preferred[0] if preferred else data[0]
            resolved[cusip] = pick.get("ticker")

        if i + _OPENFIGI_BATCH_SIZE < len(cusips):
            time.sleep(_OPENFIGI_MIN_SECONDS_BETWEEN_BATCHES)

    return resolved


def _fetch_sec_name_index(user_agent: str) -> dict[str, str]:
    """Normalized company name -> ticker, from SEC's own registrant list."""
    try:
        response = requests.get(
            SEC_COMPANY_TICKERS_URL, headers={"User-Agent": user_agent}, timeout=30
        )
        response.raise_for_status()
        entries = response.json().values()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Could not fetch SEC company_tickers.json (%s); name fallback disabled", exc)
        return {}
    return {_normalize_name(e["title"]): e["ticker"] for e in entries if e.get("title") and e.get("ticker")}


def _resolve_via_sec_name(
    cusips_with_names: dict[str, str], user_agent: str
) -> dict[str, Optional[str]]:
    name_index = _fetch_sec_name_index(user_agent)
    resolved = {}
    for cusip, issuer_name in cusips_with_names.items():
        ticker = name_index.get(_normalize_name(issuer_name))
        resolved[cusip] = ticker
        if ticker:
            logger.info("resolved %s -> %s via SEC name fallback (%r)", cusip, ticker, issuer_name)
    return resolved


def resolve_tickers(
    cusips_with_names: dict[str, str],
    db_path: Path,
    user_agent: str,
) -> dict[str, Optional[str]]:
    """Resolve {cusip: name_of_issuer} to {cusip: ticker or None}.

    Cached in db_path (SQLite) -- a CUSIP already seen (resolved or not)
    is never looked up again. Tries OpenFIGI first, then an SEC-registrant
    name-match fallback for anything OpenFIGI missed.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        _init_cache(conn)
        cache = _load_cache(conn)

        to_resolve = [c for c in cusips_with_names if c not in cache]
        if to_resolve:
            logger.info("resolving %d new CUSIP(s) via OpenFIGI", len(to_resolve))
            openfigi_result = _resolve_via_openfigi(to_resolve)
            _save_to_cache(conn, openfigi_result, source="openfigi")
            cache.update(openfigi_result)

            still_missing = {c: cusips_with_names[c] for c, t in openfigi_result.items() if t is None}
            if still_missing:
                logger.info("falling back to SEC name match for %d CUSIP(s)", len(still_missing))
                name_result = _resolve_via_sec_name(still_missing, user_agent)
                _save_to_cache(conn, name_result, source="sec_name")
                cache.update(name_result)

    return {c: cache.get(c) for c in cusips_with_names}
