"""13F information table + cover page XML -> normalized pandas DataFrame.

Pure functions only (XML text in, DataFrame out) — no network, no disk,
no Streamlit. All amount-unit and option-handling rules live here because
this is the one place both documents (cover page + information table) are
available together.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

import lxml.etree as ET
import pandas as pd

from src.edgar.client import normalize_cik

logger = logging.getLogger(__name__)

# Columns of the final normalized holdings frame, in order.
HOLDINGS_COLUMNS = [
    "cik",
    "manager_name",
    "period_date",
    "filing_date",
    "name_of_issuer",
    "cusip",
    "value_usd",
    "shares",
    "sh_prn_type",
    "put_call",
    "is_option",
]

_OPTION_TYPES = {"PUT", "CALL"}

# Sanity bounds for a *median* implied share price across a filing's plain
# stock rows, used to catch filings whose declared schema doesn't match
# their actual reported unit (see detect_value_unit). A handful of penny
# stocks can legitimately show up in a 13F, but the median position across
# a diversified institutional portfolio essentially never prices under $1;
# $1,000,000 comfortably covers Berkshire Class A (~$500-900k historically)
# with headroom.
_PLAUSIBLE_PRICE_PER_SHARE = (1.0, 1_000_000)


def _root_namespace(root: ET._Element) -> Optional[str]:
    """Extract the default XML namespace URI from a root element's tag, if any."""
    match = re.match(r"\{(.*)\}", root.tag)
    return match.group(1) if match else None


def _local_text(element: ET._Element, tag_name: str, ns_uri: Optional[str]) -> Optional[str]:
    tag = f"{{{ns_uri}}}{tag_name}" if ns_uri else tag_name
    child = element.find(tag)
    if child is None or child.text is None:
        return None
    text = child.text.strip()
    return text or None


def _schema_declared_unit(cover_page_xml: str | bytes) -> str:
    """Unit implied by the cover page's schema version alone.

    SEC's structured 13F schema was revised (X01 -> X02) for filings filed
    on/after 2023-02-14, switching `value` from thousands of dollars to
    whole dollars. Filings on the old X01 schema omit the <schemaVersion>
    element entirely; X02+ filings declare it (e.g. "X0202"). Confirmed
    empirically against real EDGAR filings (see tests/fixtures) rather
    than assumed from a fixed cutoff date, since the schema — not the
    calendar — is what actually determines the unit.
    """
    xml_bytes = cover_page_xml.encode("utf-8") if isinstance(cover_page_xml, str) else cover_page_xml
    root = ET.fromstring(xml_bytes)
    ns_uri = _root_namespace(root)
    version = _local_text(root, "schemaVersion", ns_uri)
    if version is None:
        return "thousands"
    return "thousands" if version.strip().upper().startswith("X01") else "dollars"


def _median_implied_price_per_share(raw_table: pd.DataFrame, unit: str) -> float:
    """Median value/share for plain-stock rows, assuming the given unit."""
    stock_rows = raw_table[(raw_table["sh_prn_type"] == "SH") & (raw_table["shares"] > 0)]
    if stock_rows.empty:
        return float("nan")
    multiplier = 1000 if unit == "thousands" else 1
    implied_price = (stock_rows["value_raw"] * multiplier) / stock_rows["shares"]
    return float(implied_price.median())


def detect_value_unit(cover_page_xml: str | bytes, raw_table: pd.DataFrame | None = None) -> str:
    """Detect whether a 13F filing's info table `value` is in whole dollars
    or thousands of dollars.

    Primary signal is the cover page's declared schema version (see
    _schema_declared_unit). This is cross-checked against real data when
    `raw_table` (parse_information_table() output) is given: some filers
    declare the new whole-dollar schema (X02+) but still populate `value`
    in thousands, a filing-agent bug rather than a schema quirk — seen in
    practice on a real Baupost Group filing (period 2026-03-31), where
    trusting the schema alone implied Alphabet/Amazon shares trading at
    ~$0.30 apiece. When the schema-implied unit produces an implausible
    median share price and the alternate unit produces a plausible one,
    the alternate unit wins and a warning is logged — this is exactly the
    "값이 1000배 어긋나는" trap the schema tag alone can't catch.

    Returns "dollars" or "thousands".
    """
    schema_unit = _schema_declared_unit(cover_page_xml)
    if raw_table is None or raw_table.empty:
        return schema_unit

    price_under_schema_unit = _median_implied_price_per_share(raw_table, schema_unit)
    if pd.isna(price_under_schema_unit):
        return schema_unit  # no plain-stock rows to sanity-check against

    lo, hi = _PLAUSIBLE_PRICE_PER_SHARE
    if lo <= price_under_schema_unit <= hi:
        return schema_unit

    alternate_unit = "dollars" if schema_unit == "thousands" else "thousands"
    price_under_alternate_unit = _median_implied_price_per_share(raw_table, alternate_unit)
    if lo <= price_under_alternate_unit <= hi:
        logger.warning(
            "schema declares unit=%s but implied median share price is $%.4f "
            "(implausible) -- using unit=%s instead ($%.2f/share median), "
            "likely a filer data-entry mismatch against the declared schema",
            schema_unit,
            price_under_schema_unit,
            alternate_unit,
            price_under_alternate_unit,
        )
        return alternate_unit

    logger.warning(
        "unit=%s from schema gives implausible median share price $%.4f, and "
        "unit=%s gives $%.4f too -- keeping schema-declared unit=%s but this "
        "filing's amounts may need manual review",
        schema_unit,
        price_under_schema_unit,
        alternate_unit,
        price_under_alternate_unit,
        schema_unit,
    )
    return schema_unit


def normalize_value(value_raw: pd.Series, unit: str) -> pd.Series:
    """Convert raw `value` figures to whole US dollars."""
    if unit == "thousands":
        return value_raw * 1000
    if unit == "dollars":
        return value_raw
    raise ValueError(f'unit must be "thousands" or "dollars", got: {unit!r}')


def parse_information_table(information_table_xml: str | bytes) -> pd.DataFrame:
    """Parse a 13F information table XML into a raw DataFrame.

    Columns: name_of_issuer, cusip, value_raw (native filing unit, NOT
    yet normalized to dollars), shares, sh_prn_type, put_call (raw text,
    may be None for plain stock rows).
    """
    xml_bytes = (
        information_table_xml.encode("utf-8")
        if isinstance(information_table_xml, str)
        else information_table_xml
    )
    root = ET.fromstring(xml_bytes)
    ns_uri = _root_namespace(root)
    info_table_tag = f"{{{ns_uri}}}infoTable" if ns_uri else "infoTable"
    shrs_tag = f"{{{ns_uri}}}shrsOrPrnAmt" if ns_uri else "shrsOrPrnAmt"

    rows = []
    for info in root.iter(info_table_tag):
        shrs = info.find(shrs_tag)
        shares = _local_text(shrs, "sshPrnamt", ns_uri) if shrs is not None else None
        sh_prn_type = _local_text(shrs, "sshPrnamtType", ns_uri) if shrs is not None else None
        rows.append(
            {
                "name_of_issuer": _local_text(info, "nameOfIssuer", ns_uri),
                "cusip": _local_text(info, "cusip", ns_uri),
                "value_raw": _local_text(info, "value", ns_uri),
                "shares": shares,
                "sh_prn_type": sh_prn_type,
                "put_call": _local_text(info, "putCall", ns_uri),
            }
        )

    df = pd.DataFrame(
        rows,
        columns=["name_of_issuer", "cusip", "value_raw", "shares", "sh_prn_type", "put_call"],
    )
    df["value_raw"] = pd.to_numeric(df["value_raw"], errors="raise").round().astype("int64")
    df["shares"] = pd.to_numeric(df["shares"], errors="raise").round().astype("int64")
    return df


def is_partial_amendment(cover_page_xml: str | bytes) -> bool:
    """True if this filing's information table is NOT a full quarter
    snapshot on its own.

    SEC's Form 13F amendment schema marks each 13F-HR/A with an
    <amendmentType> of either "RESTATEMENT" (a full replacement of the
    original -- safe to use standalone) or "NEW HOLDINGS" (adds ONLY
    previously-confidential positions the filer is now allowed to
    disclose -- everything else from the original filing is simply
    absent from this document). Treating a "NEW HOLDINGS" amendment as
    the complete holdings for that quarter silently undercounts it.

    Confirmed on a real filing: Berkshire Hathaway's 2025-03-31 13F-HR/A
    (accession 0000950123-25-008361) has amendmentType=NEW HOLDINGS and
    contains only 4 infoTable rows (D.R. Horton, Lennar x2, Nucor), vs.
    ~114 in the original 13F-HR for that same quarter -- those 4 were
    previously filed under a confidential-treatment request that later
    expired (confDeniedExpired=true), not Berkshire's whole book.
    """
    xml_bytes = cover_page_xml.encode("utf-8") if isinstance(cover_page_xml, str) else cover_page_xml
    root = ET.fromstring(xml_bytes)
    ns_uri = _root_namespace(root)
    # isAmendment/amendmentInfo live under formData/coverPage, not as
    # direct children of the root -- search all descendants for them.
    is_amendment_tag = f"{{{ns_uri}}}isAmendment" if ns_uri else "isAmendment"
    is_amendment_el = root.find(f".//{is_amendment_tag}")
    if is_amendment_el is None or (is_amendment_el.text or "").strip() != "true":
        return False
    amendment_info_tag = f"{{{ns_uri}}}amendmentInfo" if ns_uri else "amendmentInfo"
    amendment_info = root.find(f".//{amendment_info_tag}")
    if amendment_info is None:
        return False
    amendment_type = _local_text(amendment_info, "amendmentType", ns_uri)
    return amendment_type == "NEW HOLDINGS"


def combine_raw_tables(*tables: pd.DataFrame) -> pd.DataFrame:
    """Concatenate multiple parse_information_table() outputs into one
    raw table -- e.g. an original 13F-HR plus a "NEW HOLDINGS" amendment
    that only supplements it (see is_partial_amendment)."""
    return pd.concat(tables, ignore_index=True)


def build_holdings_frame(
    information_table_xml: str,
    cover_page_xml: str,
    cik: str,
    manager_name: str,
    period_date: str,
    filing_date: str,
) -> pd.DataFrame:
    """Combine one filing's information table + cover page into the final
    normalized holdings frame (see HOLDINGS_COLUMNS).

    Applies dollar-unit normalization (schema version, cross-checked
    against implied share price — see detect_value_unit) and flags
    PUT/CALL rows as options rather than long stock. `putCall` text case
    varies by filer (seen both "PUT" and "Put" in real filings), so the
    option check is case-insensitive.
    """
    df = parse_information_table(information_table_xml)
    return build_holdings_frame_from_raw(df, cover_page_xml, cik, manager_name, period_date, filing_date)


def build_holdings_frame_from_raw(
    raw_table: pd.DataFrame,
    cover_page_xml: str,
    cik: str,
    manager_name: str,
    period_date: str,
    filing_date: str,
) -> pd.DataFrame:
    """Same as build_holdings_frame, but takes an already-parsed raw table
    (parse_information_table() output, possibly combine_raw_tables()'d
    from more than one filing) instead of a single XML string."""
    df = raw_table.copy()
    unit = detect_value_unit(cover_page_xml, df)
    df["value_usd"] = normalize_value(df["value_raw"], unit)
    df["is_option"] = df["put_call"].str.upper().isin(_OPTION_TYPES)
    df["put_call"] = df["put_call"].str.upper()

    df["cik"] = normalize_cik(cik)
    df["manager_name"] = manager_name
    df["period_date"] = period_date
    df["filing_date"] = filing_date

    logger.info(
        "parsed %d holdings rows for manager=%s period=%s unit=%s "
        "(raw sum=%s, normalized sum=$%s)",
        len(df),
        manager_name,
        period_date,
        unit,
        df["value_raw"].sum(),
        f"{df['value_usd'].sum():,}",
    )

    return df[HOLDINGS_COLUMNS]
