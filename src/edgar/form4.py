"""Form 4 (insider beneficial-ownership change) fetch + parse.

Pure request/parsing helpers, no Streamlit -- same rules as the rest of
src/edgar. Form 4 filings are indexed under the REPORTING OWNER's own
CIK (a company officer/director/10%+ holder), not the issuer's -- but
EDGAR's classic browse-edgar endpoint also cross-references Form 4s to
the ISSUER's CIK (owner=include), which is what "insider buys of a
company we hold" needs: we know the issuer (from our 13F holdings), not
which individual executives file against it.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import lxml.etree as ET
import pandas as pd

from src.edgar.client import EdgarClient, normalize_cik

logger = logging.getLogger(__name__)

FORM4_BROWSE_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
_ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}

TRANSACTION_COLUMNS = [
    "issuer_cik",
    "ticker",
    "issuer_name",
    "accession_number",
    "filing_date",
    "transaction_date",
    "owner_name",
    "officer_title",
    "transaction_code",
    "acquired_disposed",
    "shares",
    "price_per_share",
    "value_usd",
]

# Open-market/private purchase. "A" (grant/award) and "M" (option
# exercise) are deliberately excluded -- they aren't the insider putting
# their own cash into the stock the way a "P" is.
_BUY_TRANSACTION_CODE = "P"


def list_form4_filings(client: EdgarClient, issuer_cik: str, count: int = 40) -> list[dict[str, Any]]:
    """List recent Form 4 filings cross-referenced to an ISSUER's CIK via
    EDGAR's classic browse-edgar atom feed, most recent first. Returns
    accession number + filing date per filing (not yet fetched/parsed).

    EDGAR's `type` query param is a PREFIX match, not exact -- `type=4`
    also returns "4/A", "424B5", "424B3", etc. (confirmed against a real
    issuer whose results included a 424B5 prospectus). Each entry's own
    `<category term="...">` is checked for an exact "4" to filter those
    out, rather than trusting the query param alone.
    """
    params = {
        "action": "getcompany",
        "CIK": normalize_cik(issuer_cik),
        "type": "4",
        "dateb": "",
        "owner": "include",
        "count": str(count),
        "output": "atom",
    }
    response = client.get(FORM4_BROWSE_URL, params=params)
    root = ET.fromstring(response.content)

    filings = []
    for entry in root.findall("a:entry", _ATOM_NS):
        category = entry.find("a:category", _ATOM_NS)
        if category is None or category.get("term") != "4":
            continue
        content = entry.find("a:content", _ATOM_NS)
        if content is None:
            continue
        accession = content.findtext("a:accession-number", namespaces=_ATOM_NS)
        filing_date = content.findtext("a:filing-date", namespaces=_ATOM_NS)
        if accession and filing_date:
            filings.append({"accessionNumber": accession, "filingDate": filing_date})
    return filings


def parse_form4_xml(xml_text: str) -> list[dict[str, Any]]:
    """Extract non-derivative (common stock) transactions from one Form 4
    XML document. Returns one row per transaction -- a single filing can
    report several transactions/dates for the same reporting owner.
    Derivative (options/RSU) transactions are not included; an open-
    market common-stock purchase is the clearest "insider is buying"
    signal and what Dataroma-style "Insider Buys" screens show.
    """
    root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)

    issuer_cik = root.findtext("issuer/issuerCik")
    issuer_name = root.findtext("issuer/issuerName")
    ticker = root.findtext("issuer/issuerTradingSymbol")
    owner_name = root.findtext("reportingOwner/reportingOwnerId/rptOwnerName")
    officer_title = root.findtext("reportingOwner/reportingOwnerRelationship/officerTitle")

    rows = []
    for txn in root.findall(".//nonDerivativeTransaction"):
        date = txn.findtext("transactionDate/value")
        code = txn.findtext("transactionCoding/transactionCode")
        acquired_disposed = txn.findtext("transactionAmounts/transactionAcquiredDisposedCode/value")
        shares_text = txn.findtext("transactionAmounts/transactionShares/value")
        price_text = txn.findtext("transactionAmounts/transactionPricePerShare/value")
        if not date or not code or shares_text is None:
            continue
        try:
            shares = float(shares_text)
            price = float(price_text) if price_text else 0.0
        except ValueError:
            continue

        rows.append(
            {
                "issuer_cik": issuer_cik,
                "issuer_name": issuer_name,
                "ticker": ticker,
                "owner_name": owner_name,
                "officer_title": officer_title,
                "transaction_date": date,
                "transaction_code": code,
                "acquired_disposed": acquired_disposed,
                "shares": shares,
                "price_per_share": price,
                "value_usd": shares * price,
            }
        )
    return rows


def _find_form4_xml_filename(index_items: list[dict[str, Any]]) -> Optional[str]:
    """A Form 4 filing directory has exactly one .xml document (unlike a
    13F, which needs disambiguation between cover page and info table).
    """
    xml_files = [item["name"] for item in index_items if item["name"].lower().endswith(".xml")]
    if len(xml_files) != 1:
        return None
    return xml_files[0]


def _fetch_form4_xml(client: EdgarClient, issuer_cik: str, accession_number: str, cache_dir: Path) -> Optional[str]:
    """Fetch (or reuse cached) one Form 4 filing's XML document."""
    cik10 = normalize_cik(issuer_cik)
    accession_no_dashes = accession_number.replace("-", "")
    filing_dir = cache_dir / cik10 / accession_no_dashes
    cache_path = filing_dir / "form4.xml"

    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")

    index = client.get_filing_index(issuer_cik, accession_number)
    items = index.get("directory", {}).get("item", [])
    filename = _find_form4_xml_filename(items)
    if filename is None:
        logger.warning(
            "issuer %s accession %s: could not identify a single Form 4 XML document -- skipping",
            issuer_cik, accession_number,
        )
        return None

    xml_text = client.get_filing_document(issuer_cik, accession_number, filename)
    filing_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(xml_text, encoding="utf-8")
    return xml_text


def fetch_insider_buys_for_issuer(
    client: EdgarClient,
    issuer_cik: str,
    ticker: str,
    since_date: str,
    cache_dir: Path,
) -> pd.DataFrame:
    """All open-market insider PURCHASES (transaction_code == 'P') for one
    issuer, filed on or after `since_date`. Individual filing XML is
    disk-cached under cache_dir so a re-run doesn't re-fetch filings
    already seen. `ticker` overrides whatever issuerTradingSymbol the
    filing itself reports (our own resolved ticker is the single source
    of truth used elsewhere in the app).
    """
    filings = list_form4_filings(client, issuer_cik)
    rows: list[dict[str, Any]] = []

    for filing in filings:
        if filing["filingDate"] < since_date:
            continue
        try:
            xml_text = _fetch_form4_xml(client, issuer_cik, filing["accessionNumber"], cache_dir)
        except Exception as exc:
            logger.warning(
                "issuer %s accession %s: failed to fetch Form 4 XML: %s -- skipping",
                issuer_cik, filing["accessionNumber"], exc,
            )
            continue
        if xml_text is None:
            continue

        for txn in parse_form4_xml(xml_text):
            if txn["transaction_code"] != _BUY_TRANSACTION_CODE:
                continue
            if txn["transaction_date"] < since_date:
                continue
            txn["accession_number"] = filing["accessionNumber"]
            txn["filing_date"] = filing["filingDate"]
            txn["ticker"] = ticker
            rows.append(txn)

    if not rows:
        return pd.DataFrame(columns=TRANSACTION_COLUMNS)
    return pd.DataFrame(rows)[TRANSACTION_COLUMNS]
