from pathlib import Path

import pytest

from src.edgar.form4 import _find_form4_xml_filename, parse_form4_xml

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def purchase_example_xml() -> str:
    return (FIXTURES / "form4_purchase_example.xml").read_text(encoding="utf-8")


class TestParseForm4Xml:
    def test_returns_one_row_per_transaction(self, purchase_example_xml):
        result = parse_form4_xml(purchase_example_xml)
        assert len(result) == 2  # one P, one S in the fixture

    def test_issuer_fields_attached_to_every_row(self, purchase_example_xml):
        result = parse_form4_xml(purchase_example_xml)
        for row in result:
            assert row["issuer_cik"] == "0000320193"
            assert row["issuer_name"] == "Apple Inc."
            assert row["ticker"] == "AAPL"
            assert row["owner_name"] == "Example Director"

    def test_purchase_transaction_fields(self, purchase_example_xml):
        result = parse_form4_xml(purchase_example_xml)
        purchase = next(r for r in result if r["transaction_code"] == "P")
        assert purchase["transaction_date"] == "2026-07-14"
        assert purchase["acquired_disposed"] == "A"
        assert purchase["shares"] == 2000.0
        assert purchase["price_per_share"] == pytest.approx(210.50)
        assert purchase["value_usd"] == pytest.approx(2000 * 210.50)

    def test_sale_transaction_also_parsed_unfiltered(self, purchase_example_xml):
        # parse_form4_xml itself does not filter by code -- that's
        # fetch_insider_buys_for_issuer's job, so a caller inspecting the
        # raw parse can still see sales, gifts, etc.
        result = parse_form4_xml(purchase_example_xml)
        sale = next(r for r in result if r["transaction_code"] == "S")
        assert sale["shares"] == 500.0
        assert sale["acquired_disposed"] == "D"

    def test_no_transactions_returns_empty_list(self):
        xml = """<?xml version="1.0"?>
        <ownershipDocument>
            <issuer>
                <issuerCik>0000320193</issuerCik>
                <issuerName>Apple Inc.</issuerName>
                <issuerTradingSymbol>AAPL</issuerTradingSymbol>
            </issuer>
            <reportingOwner>
                <reportingOwnerId><rptOwnerName>Nobody</rptOwnerName></reportingOwnerId>
            </reportingOwner>
            <nonDerivativeTable></nonDerivativeTable>
        </ownershipDocument>"""
        assert parse_form4_xml(xml) == []


class TestFindForm4XmlFilename:
    def test_single_xml_file_found(self):
        items = [
            {"name": "0001140361-26-032884-index.html"},
            {"name": "0001140361-26-032884.txt"},
            {"name": "form4.xml"},
        ]
        assert _find_form4_xml_filename(items) == "form4.xml"

    def test_no_xml_file_returns_none(self):
        items = [{"name": "index.html"}, {"name": "doc.txt"}]
        assert _find_form4_xml_filename(items) is None

    def test_multiple_xml_files_returns_none(self):
        # Ambiguous -- caller should skip rather than guess wrong.
        items = [{"name": "form4.xml"}, {"name": "other.xml"}]
        assert _find_form4_xml_filename(items) is None
