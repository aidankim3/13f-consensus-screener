"""CLI entry point: fetch each configured investor's latest N quarterly
13F filings and store them in SQLite.

Multiple quarters (not just the latest) are kept so (a) quarter-over-
quarter change analysis (src/analytics/consensus.py: quarter_changes) has
something to compare against, (b) the backtest
(src/analytics/backtest.py) has enough historical rebalance points to be
meaningful, and (c) the UI's as-of period screener
(src/app/main.py) has ~5 years of quarters to pick from
(QUARTERS_TO_FETCH=20 -> up to 19 rebalances / ~5 years). Rows
are tagged with period_rank: 0 = each manager's most recent filed period,
1 = their next-most-recent, etc. Because managers can lag each other
(e.g. one filer's "most recent" period might be a quarter behind
another's), period_rank is a per-manager relative ordering, not a shared
calendar date — see period_date for the actual quarter.

Usage:
    .venv\\Scripts\\python.exe -m src.edgar.build
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import yaml

from src.analytics.summary import summarize_by_manager
from src.edgar.client import EdgarClient, list_13f_filings
from src.edgar.fetch import fetch_filing_documents, find_original_filing, resolve_latest_filings
from src.edgar.parse import (
    build_holdings_frame,
    build_holdings_frame_from_raw,
    combine_raw_tables,
    is_partial_amendment,
    parse_information_table,
)
from src.edgar.storage import save_holdings_table

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

USER_AGENT = "Aidan Kim aidankim3@gmail.com"

ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = ROOT / "config" / "investors.yaml"
CACHE_DIR = ROOT / "data" / "raw"
DB_PATH = ROOT / "data" / "holdings.db"

QUARTERS_TO_FETCH = 20


def load_investors(config_path: Path = CONFIG_PATH) -> list[dict]:
    return yaml.safe_load(config_path.read_text(encoding="utf-8"))["investors"]


def _process_one_filing(
    client: EdgarClient,
    inv: dict,
    filing: dict,
    all_filings: list[dict],
    cache_dir: Path,
) -> pd.DataFrame:
    """Fetch + parse a single resolved filing into a holdings frame
    (without period_rank attached -- the caller adds that)."""
    docs = fetch_filing_documents(
        client, inv["cik"], filing["accessionNumber"], filing["primaryDocument"], cache_dir
    )

    if not is_partial_amendment(docs.cover_page_xml):
        return build_holdings_frame(
            information_table_xml=docs.information_table_xml,
            cover_page_xml=docs.cover_page_xml,
            cik=inv["cik"],
            manager_name=inv["name"],
            period_date=filing["reportDate"],
            filing_date=filing["filingDate"],
        )

    # A "NEW HOLDINGS" amendment only adds previously-confidential
    # positions -- it is NOT a full restatement. Using it alone would
    # silently undercount the quarter (seen for real: Berkshire's
    # 2025-03-31 13F-HR/A had 4 rows vs ~114 in the original). Merge with
    # the original 13F-HR for the same period instead.
    original = find_original_filing(all_filings, filing["reportDate"])
    if not original or original["accessionNumber"] == filing["accessionNumber"]:
        logger.warning(
            "%s: %s (period %s) looks like a partial NEW-HOLDINGS amendment but no "
            "original 13F-HR was found -- using it as-is (may undercount)",
            inv["name"], filing["accessionNumber"], filing["reportDate"],
        )
        return build_holdings_frame(
            information_table_xml=docs.information_table_xml,
            cover_page_xml=docs.cover_page_xml,
            cik=inv["cik"],
            manager_name=inv["name"],
            period_date=filing["reportDate"],
            filing_date=filing["filingDate"],
        )

    logger.warning(
        "%s: %s (period %s) is a NEW-HOLDINGS amendment -- merging with original 13F-HR "
        "(accession %s) to avoid undercounting",
        inv["name"], filing["accessionNumber"], filing["reportDate"], original["accessionNumber"],
    )
    original_docs = fetch_filing_documents(
        client, inv["cik"], original["accessionNumber"], original["primaryDocument"], cache_dir
    )
    raw = combine_raw_tables(
        parse_information_table(original_docs.information_table_xml),
        parse_information_table(docs.information_table_xml),
    )
    return build_holdings_frame_from_raw(
        raw,
        cover_page_xml=original_docs.cover_page_xml,
        cik=inv["cik"],
        manager_name=inv["name"],
        period_date=filing["reportDate"],
        # the amendment's date: when the FULL picture (original +
        # newly-disclosed) first became public
        filing_date=filing["filingDate"],
    )


def build_all(
    investors: list[dict],
    client: EdgarClient,
    cache_dir: Path = CACHE_DIR,
    n_quarters: int = QUARTERS_TO_FETCH,
) -> pd.DataFrame:
    """Fetch + parse each investor's latest `n_quarters` 13F filings into
    one combined holdings frame, tagged with period_rank (0 = most
    recent).

    Failures are isolated as tightly as possible so one bad filing never
    takes down the whole run (important at 80+ investors -- something
    will eventually be malformed, e.g. a pre-XML-era filing with no
    machine-readable information table): a quarter that fails to fetch/
    parse is skipped (that investor keeps its other quarters), and an
    investor whose submissions/filing-list lookup itself fails is skipped
    entirely -- both logged as warnings/errors, not raised.
    """
    frames = []
    for inv in investors:
        try:
            submissions = client.get_submissions(inv["cik"])
            filings = list_13f_filings(submissions)
        except Exception as exc:
            logger.error("%s (CIK %s): failed to list filings: %s -- skipping", inv["name"], inv["cik"], exc)
            continue

        if not filings:
            logger.warning("no 13F filings found for %s (CIK %s)", inv["name"], inv["cik"])
            continue

        latest_filings = resolve_latest_filings(filings, n=n_quarters)
        if len(latest_filings) < n_quarters:
            logger.warning(
                "%s (CIK %s): only %d/%d quarters of history available",
                inv["name"], inv["cik"], len(latest_filings), n_quarters,
            )

        for period_rank, filing in enumerate(latest_filings):
            try:
                holdings = _process_one_filing(client, inv, filing, filings, cache_dir)
            except Exception as exc:
                logger.error(
                    "%s: failed to process %s (period_rank=%d, period %s): %s -- skipping this quarter",
                    inv["name"], filing["accessionNumber"], period_rank, filing["reportDate"], exc,
                )
                continue

            holdings["period_rank"] = period_rank
            frames.append(holdings)
            logger.info(
                "%s: %d rows from %s (period_rank=%d, period %s, filed %s)",
                inv["name"],
                len(holdings),
                filing["form"],
                period_rank,
                filing["reportDate"],
                filing["filingDate"],
            )

    if not frames:
        raise RuntimeError("no holdings fetched for any configured investor")
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    client = EdgarClient(user_agent=USER_AGENT)
    investors = load_investors()

    logger.info(
        "fetching latest %d quarters of 13F holdings for %d investors",
        QUARTERS_TO_FETCH,
        len(investors),
    )
    holdings = build_all(investors, client)

    save_holdings_table(holdings, DB_PATH)
    logger.info("saved %d holding rows to %s", len(holdings), DB_PATH)

    current = holdings[holdings["period_rank"] == 0]
    summary = summarize_by_manager(current)
    print("\n=== 투자자별 최신 13F 보유 요약 (옵션 제외) ===")
    print(summary.to_string(index=False))
    print(
        "\n주의: 13F는 미국 롱 주식(및 옵션)만 포함합니다. "
        "숏 포지션·채권·해외 주식·현금은 여기 나타나지 않습니다."
    )


if __name__ == "__main__":
    main()
