from unittest.mock import patch

import pytest

from src.edgar.client import (
    RateLimiter,
    build_headers,
    filing_archive_dir_url,
    list_13f_filings,
    list_activist_filings,
    list_recent_filings,
    normalize_cik,
)


class TestBuildHeaders:
    def test_valid_user_agent_produces_expected_header(self):
        headers = build_headers("Aidan Kim aidankim3@gmail.com")
        assert headers["User-Agent"] == "Aidan Kim aidankim3@gmail.com"
        assert "Accept-Encoding" in headers

    @pytest.mark.parametrize("bad_agent", ["", None, "Aidan Kim", "no-at-sign.com"])
    def test_missing_or_malformed_contact_rejected(self, bad_agent):
        with pytest.raises(ValueError):
            build_headers(bad_agent)


class TestNormalizeCik:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("1067983", "0001067983"),
            (1067983, "0001067983"),
            ("0001067983", "0001067983"),
            ("1", "0000000001"),
        ],
    )
    def test_zero_pads_to_ten_digits(self, raw, expected):
        assert normalize_cik(raw) == expected

    @pytest.mark.parametrize("bad_cik", ["abc", "12-34", "", "1067983x"])
    def test_rejects_non_numeric(self, bad_cik):
        with pytest.raises(ValueError):
            normalize_cik(bad_cik)


class TestRateLimiter:
    def test_first_call_does_not_sleep(self):
        limiter = RateLimiter(max_per_second=5)
        with patch("time.monotonic", return_value=100.0), patch(
            "time.sleep"
        ) as mock_sleep:
            limiter.wait()
        mock_sleep.assert_not_called()

    def test_second_call_within_window_sleeps_for_remaining_interval(self):
        limiter = RateLimiter(max_per_second=5)  # min interval = 0.2s
        with patch("time.monotonic", side_effect=[100.0, 100.05]), patch(
            "time.sleep"
        ) as mock_sleep:
            limiter.wait()  # sets _last_call = 100.0
            limiter.wait()  # now=100.05 -> elapsed=0.05 -> sleep(0.15)
        mock_sleep.assert_called_once()
        (slept_for,) = mock_sleep.call_args.args
        assert slept_for == pytest.approx(0.15)

    def test_call_after_window_elapsed_does_not_sleep(self):
        limiter = RateLimiter(max_per_second=5)  # min interval = 0.2s
        with patch("time.monotonic", side_effect=[100.0, 100.5]), patch(
            "time.sleep"
        ) as mock_sleep:
            limiter.wait()
            limiter.wait()
        mock_sleep.assert_not_called()

    def test_rejects_non_positive_rate(self):
        with pytest.raises(ValueError):
            RateLimiter(max_per_second=0)


class TestFilingArchiveDirUrl:
    def test_strips_leading_zeros_from_cik_and_dashes_from_accession(self):
        url = filing_archive_dir_url("0001067983", "0001193125-26-226661")
        assert url == "https://www.sec.gov/Archives/edgar/data/1067983/000119312526226661"

    def test_accepts_int_cik(self):
        url = filing_archive_dir_url(1067983, "0001193125-26-226661")
        assert url.startswith("https://www.sec.gov/Archives/edgar/data/1067983/")


class TestList13FFilings:
    def _submissions(self, forms, extra_form="10-K"):
        n = len(forms)
        return {
            "filings": {
                "recent": {
                    "form": forms,
                    "filingDate": [f"2024-0{i + 1}-15" for i in range(n)],
                    "reportDate": [f"2023-1{i}-31" for i in range(n)],
                    "accessionNumber": [f"0001-24-00000{i}" for i in range(n)],
                    "primaryDocument": [f"doc{i}.xml" for i in range(n)],
                }
            }
        }

    def test_filters_only_13f_forms(self):
        submissions = self._submissions(["13F-HR", "10-K", "13F-HR/A", "4"])
        result = list_13f_filings(submissions)
        assert [f["form"] for f in result] == ["13F-HR", "13F-HR/A"]

    def test_preserves_all_fields(self):
        submissions = self._submissions(["13F-HR"])
        [filing] = list_13f_filings(submissions)
        assert set(filing.keys()) == {
            "form",
            "filingDate",
            "reportDate",
            "accessionNumber",
            "primaryDocument",
        }

    def test_empty_recent_returns_empty_list(self):
        submissions = {"filings": {"recent": {"form": []}}}
        assert list_13f_filings(submissions) == []

    def test_missing_filings_key_returns_empty_list(self):
        assert list_13f_filings({}) == []


class TestListActivistFilings:
    def _submissions(self, forms):
        n = len(forms)
        return {
            "filings": {
                "recent": {
                    "form": forms,
                    "filingDate": [f"2026-0{i + 1}-15" for i in range(n)],
                    "reportDate": [f"2025-1{i}-31" for i in range(n)],
                    "accessionNumber": [f"0001-26-00000{i}" for i in range(n)],
                    "primaryDocument": [f"doc{i}.htm" for i in range(n)],
                }
            }
        }

    def test_filters_current_naming_convention(self):
        # Real, current (2025-2026) EDGAR labels.
        submissions = self._submissions(
            ["SCHEDULE 13D", "SCHEDULE 13G", "SCHEDULE 13G/A", "13F-HR"]
        )
        result = list_activist_filings(submissions)
        assert [f["form"] for f in result] == ["SCHEDULE 13D", "SCHEDULE 13G", "SCHEDULE 13G/A"]

    def test_filters_legacy_naming_convention(self):
        # Real, older (pre-~2025) EDGAR labels for the same forms -- seen
        # on real filer history (Appaloosa LP, CIK 1656456).
        submissions = self._submissions(["SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A"])
        result = list_activist_filings(submissions)
        assert len(result) == 4

    def test_excludes_13f(self):
        submissions = self._submissions(["13F-HR", "13F-HR/A"])
        assert list_activist_filings(submissions) == []


class TestListRecentFilings:
    def _submissions(self, forms):
        n = len(forms)
        return {
            "filings": {
                "recent": {
                    "form": forms,
                    "filingDate": [f"2026-01-{i + 1:02d}" for i in range(n)],
                    "accessionNumber": [f"0001-26-00000{i}" for i in range(n)],
                }
            }
        }

    def test_not_restricted_to_any_form_type(self):
        # Unlike list_13f_filings/list_activist_filings, every form type
        # passes through -- this is a general "recent activity" feed.
        submissions = self._submissions(["13F-HR", "10-K", "4", "SC 13G", "8-K"])
        result = list_recent_filings(submissions, limit=5)
        assert [f["form"] for f in result] == ["13F-HR", "10-K", "4", "SC 13G", "8-K"]

    def test_limit_takes_the_first_n_not_a_sort(self):
        # SEC's own "recent" block is already most-recent-first; this is
        # a slice, not a re-sort.
        submissions = self._submissions(["13F-HR", "10-K", "4", "SC 13G", "8-K"])
        result = list_recent_filings(submissions, limit=2)
        assert [f["form"] for f in result] == ["13F-HR", "10-K"]

    def test_limit_larger_than_available_returns_all(self):
        submissions = self._submissions(["13F-HR", "10-K"])
        result = list_recent_filings(submissions, limit=10)
        assert len(result) == 2

    def test_preserves_form_filingdate_accessionnumber_only(self):
        submissions = self._submissions(["13F-HR"])
        [filing] = list_recent_filings(submissions, limit=1)
        assert set(filing.keys()) == {"form", "filingDate", "accessionNumber"}

    def test_empty_recent_returns_empty_list(self):
        submissions = {"filings": {"recent": {"form": []}}}
        assert list_recent_filings(submissions) == []

    def test_missing_filings_key_returns_empty_list(self):
        assert list_recent_filings({}) == []
