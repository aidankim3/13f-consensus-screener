from pathlib import Path

import pandas as pd
import pytest

from src.edgar.parse import (
    build_holdings_frame,
    build_holdings_frame_from_raw,
    combine_raw_tables,
    detect_value_unit,
    is_partial_amendment,
    normalize_value,
    parse_information_table,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def scion_infotable_xml() -> str:
    return (FIXTURES / "scion_2025q3_infotable.xml").read_text(encoding="utf-8")


@pytest.fixture
def scion_cover_page_xml() -> str:
    return (FIXTURES / "scion_2025q3_primary_doc.xml").read_text(encoding="utf-8")


@pytest.fixture
def berkshire_x01_cover_page_xml() -> str:
    return (FIXTURES / "berkshire_2022q3_primary_doc_x01.xml").read_text(encoding="utf-8")


@pytest.fixture
def baupost_infotable_xml() -> str:
    return (FIXTURES / "baupost_2026q1_infotable.xml").read_text(encoding="utf-8")


@pytest.fixture
def baupost_cover_page_xml() -> str:
    return (FIXTURES / "baupost_2026q1_primary_doc.xml").read_text(encoding="utf-8")


@pytest.fixture
def berkshire_new_holdings_amendment_cover_page_xml() -> str:
    return (FIXTURES / "berkshire_2025q1_new_holdings_amendment_primary_doc.xml").read_text(
        encoding="utf-8"
    )


class TestDetectValueUnit:
    def test_x02_schema_is_whole_dollars(self, scion_cover_page_xml):
        assert detect_value_unit(scion_cover_page_xml) == "dollars"

    def test_x01_schema_missing_schema_version_is_thousands(self, berkshire_x01_cover_page_xml):
        assert detect_value_unit(berkshire_x01_cover_page_xml) == "thousands"

    def test_schema_only_trusts_declared_unit_without_raw_table(self, baupost_cover_page_xml):
        # Without cross-checking against actual values, we can only go by
        # what the filing declares -- which is wrong for this real filing
        # (see the raw_table-aware tests below). Documents the limitation.
        assert detect_value_unit(baupost_cover_page_xml) == "dollars"

    def test_catches_filer_declaring_dollars_but_reporting_thousands(
        self, baupost_cover_page_xml, baupost_infotable_xml, caplog
    ):
        # Real Baupost Group filing (period 2026-03-31): schema says X0202
        # (whole dollars), but treating `value` as dollars implies e.g.
        # Alphabet shares trading at ~$0.29 -- impossible. The filer
        # actually populated `value` in thousands despite the new schema.
        raw_table = parse_information_table(baupost_infotable_xml)
        with caplog.at_level("WARNING"):
            unit = detect_value_unit(baupost_cover_page_xml, raw_table)
        assert unit == "thousands"
        assert "implausible" in caplog.text

    def test_does_not_flip_a_correctly_declared_filing(
        self, scion_cover_page_xml, scion_infotable_xml
    ):
        # Sanity check against a filing known to be correctly reported in
        # dollars -- the plausibility check must not "correct" a filing
        # that wasn't wrong in the first place.
        raw_table = parse_information_table(scion_infotable_xml)
        assert detect_value_unit(scion_cover_page_xml, raw_table) == "dollars"


class TestNormalizeValue:
    def test_thousands_multiplies_by_1000(self):
        import pandas as pd

        result = normalize_value(pd.Series([95634]), "thousands")
        assert result.iloc[0] == 95_634_000

    def test_dollars_passthrough(self):
        import pandas as pd

        result = normalize_value(pd.Series([498992850]), "dollars")
        assert result.iloc[0] == 498992850

    def test_unknown_unit_raises(self):
        import pandas as pd

        with pytest.raises(ValueError):
            normalize_value(pd.Series([1]), "yen")


class TestParseInformationTable:
    def test_row_count_matches_real_filing(self, scion_infotable_xml):
        df = parse_information_table(scion_infotable_xml)
        assert len(df) == 8  # matches tableEntryTotal in the real cover page

    def test_plain_stock_row_has_no_put_call(self, scion_infotable_xml):
        df = parse_information_table(scion_infotable_xml)
        row = df[df["name_of_issuer"] == "SLM CORP"].iloc[0]
        assert row["cusip"] == "78442P106"
        assert row["value_raw"] == 13287895
        assert row["shares"] == 480054
        assert row["sh_prn_type"] == "SH"
        assert pd.isna(row["put_call"])

    def test_option_rows_carry_raw_put_call_text(self, scion_infotable_xml):
        df = parse_information_table(scion_infotable_xml)
        nvda = df[df["name_of_issuer"] == "NVIDIA CORPORATION"].iloc[0]
        pfizer = df[df["name_of_issuer"] == "PFIZER INC"].iloc[0]
        # Real EDGAR data uses mixed case ("Put"/"Call"), not all-caps.
        assert nvda["put_call"] == "Put"
        assert pfizer["put_call"] == "Call"

    def test_sum_of_raw_values_matches_filing_table_value_total(self, scion_infotable_xml):
        df = parse_information_table(scion_infotable_xml)
        assert df["value_raw"].sum() == 1_381_198_076  # cover page tableValueTotal


class TestBuildHoldingsFrame:
    def test_end_to_end_columns_and_row_count(self, scion_infotable_xml, scion_cover_page_xml):
        df = build_holdings_frame(
            information_table_xml=scion_infotable_xml,
            cover_page_xml=scion_cover_page_xml,
            cik="1649339",
            manager_name="Michael Burry",
            period_date="2025-09-30",
            filing_date="2025-11-03",
        )
        assert len(df) == 8
        assert list(df.columns) == [
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
        assert (df["cik"] == "0001649339").all()
        assert (df["manager_name"] == "Michael Burry").all()

    def test_value_usd_unnormalized_for_x02_schema(self, scion_infotable_xml, scion_cover_page_xml):
        df = build_holdings_frame(
            scion_infotable_xml, scion_cover_page_xml, "1649339", "Michael Burry",
            "2025-09-30", "2025-11-03",
        )
        assert df["value_usd"].sum() == 1_381_198_076

    def test_option_flag_matches_put_call_case_insensitively(
        self, scion_infotable_xml, scion_cover_page_xml
    ):
        df = build_holdings_frame(
            scion_infotable_xml, scion_cover_page_xml, "1649339", "Michael Burry",
            "2025-09-30", "2025-11-03",
        )
        options = df[df["is_option"]]
        stocks = df[~df["is_option"]]
        assert len(options) == 4  # Halliburton, Nvidia, Palantir, Pfizer
        assert len(stocks) == 4
        assert set(options["put_call"]) == {"PUT", "CALL"}

    def test_baupost_unit_mismatch_is_corrected_to_billions_not_millions(
        self, baupost_infotable_xml, baupost_cover_page_xml
    ):
        # Cover page's own tableValueTotal (5,115,380) taken at face value
        # under the declared X0202/dollars schema would put Baupost's 13F
        # book at ~$5.1 million -- implausible for a firm this size, and
        # the individual share prices confirm it (see TestDetectValueUnit).
        # The real figure is ~1000x larger.
        df = build_holdings_frame(
            baupost_infotable_xml,
            baupost_cover_page_xml,
            cik="1061768",
            manager_name="Seth Klarman",
            period_date="2026-03-31",
            filing_date="2026-05-14",
        )
        assert df["value_usd"].sum() == 5_115_380_000
        assert len(df) == 22


class TestIsPartialAmendment:
    def test_new_holdings_amendment_is_partial(
        self, berkshire_new_holdings_amendment_cover_page_xml
    ):
        # Real filing: Berkshire's 2025-03-31 13F-HR/A, amendmentType=NEW
        # HOLDINGS, discloses only 4 previously-confidential positions.
        assert is_partial_amendment(berkshire_new_holdings_amendment_cover_page_xml) is True

    def test_non_amendment_filing_is_not_partial(self, scion_cover_page_xml):
        assert is_partial_amendment(scion_cover_page_xml) is False

    def test_x01_schema_filing_without_amendment_fields_is_not_partial(
        self, berkshire_x01_cover_page_xml
    ):
        assert is_partial_amendment(berkshire_x01_cover_page_xml) is False


class TestCombineRawTablesAndBuildFromRaw:
    def test_combine_raw_tables_concatenates_rows(self, scion_infotable_xml, baupost_infotable_xml):
        table_a = parse_information_table(scion_infotable_xml)
        table_b = parse_information_table(baupost_infotable_xml)
        combined = combine_raw_tables(table_a, table_b)
        assert len(combined) == len(table_a) + len(table_b)

    def test_build_holdings_frame_from_raw_matches_build_holdings_frame(
        self, scion_infotable_xml, scion_cover_page_xml
    ):
        raw = parse_information_table(scion_infotable_xml)
        from_raw = build_holdings_frame_from_raw(
            raw, scion_cover_page_xml, "1649339", "Michael Burry", "2025-09-30", "2025-11-03"
        )
        direct = build_holdings_frame(
            scion_infotable_xml, scion_cover_page_xml, "1649339", "Michael Burry",
            "2025-09-30", "2025-11-03",
        )
        pd.testing.assert_frame_equal(from_raw, direct)

    def test_original_plus_amendment_combined_undercounts_less_than_amendment_alone(
        self, scion_infotable_xml, baupost_infotable_xml, scion_cover_page_xml
    ):
        # Simulates the real NEW-HOLDINGS scenario: "original" (scion, 8
        # rows) + "amendment" (baupost, 22 rows) combined should have all
        # 30 rows, not just the amendment's 22 or the original's 8.
        original = parse_information_table(scion_infotable_xml)
        amendment = parse_information_table(baupost_infotable_xml)
        combined = combine_raw_tables(original, amendment)
        result = build_holdings_frame_from_raw(
            combined, scion_cover_page_xml, "9999999999", "Test Manager", "2025-09-30", "2025-11-03"
        )
        assert len(result) == 8 + 22
