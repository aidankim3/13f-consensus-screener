import pytest

from src.edgar.fetch import (
    find_original_filing,
    identify_information_table_filename,
    resolve_latest_filing,
    resolve_latest_filings,
)


class TestResolveLatestFiling:
    def test_picks_most_recent_report_period(self):
        filings = [
            {"form": "13F-HR", "filingDate": "2025-08-14", "reportDate": "2025-06-30"},
            {"form": "13F-HR", "filingDate": "2025-11-03", "reportDate": "2025-09-30"},
            {"form": "13F-HR", "filingDate": "2025-05-15", "reportDate": "2025-03-31"},
        ]
        result = resolve_latest_filing(filings)
        assert result["reportDate"] == "2025-09-30"

    def test_amendment_filed_later_wins_over_original_same_period(self):
        # Real Scion Asset Management filings for period 2023-12-31.
        filings = [
            {"form": "13F-HR", "filingDate": "2024-02-14", "reportDate": "2023-12-31"},
            {"form": "13F-HR/A", "filingDate": "2024-02-16", "reportDate": "2023-12-31"},
        ]
        result = resolve_latest_filing(filings)
        assert result["form"] == "13F-HR/A"
        assert result["filingDate"] == "2024-02-16"

    def test_amendment_filed_before_a_later_period_does_not_win(self):
        # Even though 13F-HR/A exists, a newer *period*'s original filing
        # should still be picked over an amendment for an older period.
        filings = [
            {"form": "13F-HR", "filingDate": "2024-02-14", "reportDate": "2023-12-31"},
            {"form": "13F-HR/A", "filingDate": "2024-02-16", "reportDate": "2023-12-31"},
            {"form": "13F-HR", "filingDate": "2024-05-15", "reportDate": "2024-03-31"},
        ]
        result = resolve_latest_filing(filings)
        assert result["reportDate"] == "2024-03-31"
        assert result["form"] == "13F-HR"

    def test_multiple_amendments_same_period_picks_latest_by_filing_date(self):
        # Real Berkshire Hathaway filings for period 2023-09-30 (two amendments).
        filings = [
            {"form": "13F-HR", "filingDate": "2023-11-14", "reportDate": "2023-09-30"},
            {"form": "13F-HR/A", "filingDate": "2023-11-16", "reportDate": "2023-09-30"},
            {"form": "13F-HR/A", "filingDate": "2024-05-15", "reportDate": "2023-09-30"},
        ]
        result = resolve_latest_filing(filings)
        assert result["filingDate"] == "2024-05-15"

    def test_empty_list_raises(self):
        with pytest.raises(ValueError):
            resolve_latest_filing([])


class TestResolveLatestFilingsN:
    def test_returns_two_most_recent_distinct_periods(self):
        filings = [
            {"form": "13F-HR", "filingDate": "2025-02-14", "reportDate": "2024-12-31"},
            {"form": "13F-HR", "filingDate": "2025-05-15", "reportDate": "2025-03-31"},
            {"form": "13F-HR", "filingDate": "2025-08-14", "reportDate": "2025-06-30"},
        ]
        result = resolve_latest_filings(filings, n=2)
        assert [f["reportDate"] for f in result] == ["2025-06-30", "2025-03-31"]

    def test_each_period_independently_prefers_latest_amendment(self):
        # Real Scion Asset Management filings spanning two periods, one
        # of which (2023-12-31) has a same-period amendment.
        filings = [
            {"form": "13F-HR", "filingDate": "2024-02-14", "reportDate": "2023-12-31"},
            {"form": "13F-HR/A", "filingDate": "2024-02-16", "reportDate": "2023-12-31"},
            {"form": "13F-HR", "filingDate": "2024-05-15", "reportDate": "2024-03-31"},
        ]
        result = resolve_latest_filings(filings, n=2)
        assert result[0]["reportDate"] == "2024-03-31"
        assert result[1]["reportDate"] == "2023-12-31"
        assert result[1]["form"] == "13F-HR/A"

    def test_fewer_periods_available_than_n_returns_what_exists(self):
        filings = [
            {"form": "13F-HR", "filingDate": "2025-05-15", "reportDate": "2025-03-31"},
        ]
        result = resolve_latest_filings(filings, n=2)
        assert len(result) == 1
        assert result[0]["reportDate"] == "2025-03-31"

    def test_n_defaults_to_one(self):
        filings = [
            {"form": "13F-HR", "filingDate": "2025-05-15", "reportDate": "2025-03-31"},
            {"form": "13F-HR", "filingDate": "2025-08-14", "reportDate": "2025-06-30"},
        ]
        result = resolve_latest_filings(filings)
        assert len(result) == 1
        assert result[0]["reportDate"] == "2025-06-30"

    def test_empty_list_raises(self):
        with pytest.raises(ValueError):
            resolve_latest_filings([], n=2)


class TestFindOriginalFiling:
    def test_finds_the_non_amendment_13f_hr_for_the_period(self):
        # Real Berkshire Hathaway filings for period 2025-03-31: an
        # original 13F-HR, plus a later NEW-HOLDINGS 13F-HR/A.
        filings = [
            {"form": "13F-HR", "filingDate": "2025-05-15", "reportDate": "2025-03-31"},
            {"form": "13F-HR/A", "filingDate": "2025-08-14", "reportDate": "2025-03-31"},
        ]
        result = find_original_filing(filings, "2025-03-31")
        assert result["form"] == "13F-HR"
        assert result["filingDate"] == "2025-05-15"

    def test_ignores_other_periods(self):
        filings = [
            {"form": "13F-HR", "filingDate": "2025-05-15", "reportDate": "2025-03-31"},
            {"form": "13F-HR", "filingDate": "2025-08-14", "reportDate": "2025-06-30"},
        ]
        result = find_original_filing(filings, "2025-06-30")
        assert result["reportDate"] == "2025-06-30"

    def test_returns_none_when_only_amendments_exist_for_period(self):
        filings = [{"form": "13F-HR/A", "filingDate": "2025-05-15", "reportDate": "2025-03-31"}]
        assert find_original_filing(filings, "2025-03-31") is None

    def test_returns_none_when_period_not_found(self):
        filings = [{"form": "13F-HR", "filingDate": "2025-05-15", "reportDate": "2025-03-31"}]
        assert find_original_filing(filings, "2099-01-01") is None


class TestIdentifyInformationTableFilename:
    def test_finds_the_lone_non_cover_page_xml(self):
        # Real Pershing Square filing directory listing.
        items = [
            {"name": "0001172661-26-002336-index-headers.html"},
            {"name": "0001172661-26-002336-index.html"},
            {"name": "0001172661-26-002336.txt"},
            {"name": "infotable.xml"},
            {"name": "primary_doc.xml"},
        ]
        assert identify_information_table_filename(items, "primary_doc.xml") == "infotable.xml"

    def test_works_with_numeric_filenames(self):
        # Real Berkshire Hathaway filing directory listing.
        items = [
            {"name": "0001193125-26-226661-index-headers.html"},
            {"name": "0001193125-26-226661-index.html"},
            {"name": "0001193125-26-226661.txt"},
            {"name": "53405.xml"},
            {"name": "primary_doc.xml"},
        ]
        assert identify_information_table_filename(items, "primary_doc.xml") == "53405.xml"

    def test_no_xml_candidate_raises(self):
        items = [{"name": "primary_doc.xml"}, {"name": "filing.txt"}]
        with pytest.raises(ValueError):
            identify_information_table_filename(items, "primary_doc.xml")

    def test_ambiguous_candidates_raises(self):
        items = [
            {"name": "primary_doc.xml"},
            {"name": "infotable.xml"},
            {"name": "exhibit.xml"},
        ]
        with pytest.raises(ValueError):
            identify_information_table_filename(items, "primary_doc.xml")
