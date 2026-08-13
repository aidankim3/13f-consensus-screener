"""Fetch + cache 13F filing documents (cover page + information table).

Side-effecting by nature (network + disk I/O), but Streamlit-free — this
must stay usable from a future non-Streamlit service unchanged.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from src.edgar.client import EdgarClient, normalize_cik

logger = logging.getLogger(__name__)

_MANIFEST_NAME = "manifest.json"


def resolve_latest_filings(filings: list[dict[str, Any]], n: int = 1) -> list[dict[str, Any]]:
    """Pick up to `n` filings to use as successive quarterly snapshots: the
    `n` most recent distinct reporting periods, each resolved to its
    latest-filed 13F-HR/A amendment if one exists for that period.

    Returns at most `n` filings, ordered most recent period first. Returns
    fewer than `n` if the filer doesn't have that much history (e.g. a
    fund that only recently started filing).

    Pure function over the list returned by client.list_13f_filings().
    """
    if not filings:
        raise ValueError("no 13F filings to resolve")
    periods = sorted({f["reportDate"] for f in filings}, reverse=True)[:n]
    resolved = []
    for period in periods:
        same_period = [f for f in filings if f["reportDate"] == period]
        resolved.append(max(same_period, key=lambda f: f["filingDate"]))
    return resolved


def resolve_latest_filing(filings: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the filing to use for "current holdings": the most recent
    reporting period, preferring the latest-filed 13F-HR/A amendment over
    the original 13F-HR if one exists for that same period.

    Pure function over the list returned by client.list_13f_filings().
    """
    return resolve_latest_filings(filings, n=1)[0]


def find_original_filing(filings: list[dict[str, Any]], period_date: str) -> Optional[dict[str, Any]]:
    """The initial, non-amendment 13F-HR filed for a given period, if any.

    Used to recover a full holdings snapshot when the latest filing for a
    period turns out to be a "NEW HOLDINGS"-type amendment (see
    parse.is_partial_amendment) that only supplements the original rather
    than replacing it.
    """
    candidates = [f for f in filings if f["reportDate"] == period_date and f["form"] == "13F-HR"]
    if not candidates:
        return None
    return min(candidates, key=lambda f: f["filingDate"])


def identify_information_table_filename(
    index_items: list[dict[str, Any]], cover_page_filename: str
) -> str:
    """Given a filing's index.json directory listing, find the information
    table XML — the one .xml file that isn't the cover page. Info table
    filenames vary by filing agent (e.g. "infotable.xml", "53405.xml"),
    so we identify it by elimination rather than a fixed name.
    """
    cover_page_lower = cover_page_filename.lower()
    candidates = [
        item["name"]
        for item in index_items
        if item["name"].lower().endswith(".xml") and item["name"].lower() != cover_page_lower
    ]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ValueError(
            f"no information table XML found alongside {cover_page_filename!r} "
            f"in filing index"
        )
    raise ValueError(
        f"ambiguous information table candidates alongside {cover_page_filename!r}: "
        f"{candidates}"
    )


@dataclass
class FilingDocuments:
    cover_page_xml: str
    information_table_xml: str
    cover_page_path: Path
    information_table_path: Path


def fetch_filing_documents(
    client: EdgarClient,
    cik: str,
    accession_number: str,
    primary_document: str,
    cache_dir: Path,
) -> FilingDocuments:
    """Download (or reuse cached) cover page + information table XML for
    one 13F filing.

    Cached under cache_dir/{cik10}/{accession_no_dashes}/ so re-running
    the build never re-hits EDGAR for a filing already on disk.
    """
    cik10 = normalize_cik(cik)
    accession_no_dashes = accession_number.replace("-", "")
    filing_dir = cache_dir / cik10 / accession_no_dashes
    manifest_path = filing_dir / _MANIFEST_NAME

    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        cover_page_path = filing_dir / manifest["cover_page"]
        info_table_path = filing_dir / manifest["information_table"]
        if cover_page_path.exists() and info_table_path.exists():
            logger.info("cache hit: %s/%s", cik10, accession_no_dashes)
            return FilingDocuments(
                cover_page_xml=cover_page_path.read_text(encoding="utf-8"),
                information_table_xml=info_table_path.read_text(encoding="utf-8"),
                cover_page_path=cover_page_path,
                information_table_path=info_table_path,
            )

    filing_dir.mkdir(parents=True, exist_ok=True)
    cover_page_filename = Path(primary_document).name

    index = client.get_filing_index(cik, accession_number)
    items = index["directory"]["item"]
    info_table_filename = identify_information_table_filename(items, cover_page_filename)

    cover_page_xml = client.get_filing_document(cik, accession_number, cover_page_filename)
    information_table_xml = client.get_filing_document(cik, accession_number, info_table_filename)

    cover_page_path = filing_dir / cover_page_filename
    info_table_path = filing_dir / info_table_filename
    cover_page_path.write_text(cover_page_xml, encoding="utf-8")
    info_table_path.write_text(information_table_xml, encoding="utf-8")
    manifest_path.write_text(
        json.dumps({"cover_page": cover_page_filename, "information_table": info_table_filename}),
        encoding="utf-8",
    )
    logger.info(
        "fetched + cached: %s/%s (info table: %s)",
        cik10,
        accession_no_dashes,
        info_table_filename,
    )

    return FilingDocuments(
        cover_page_xml=cover_page_xml,
        information_table_xml=information_table_xml,
        cover_page_path=cover_page_path,
        information_table_path=info_table_path,
    )
