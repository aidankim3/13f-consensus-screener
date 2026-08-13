from src.edgar.seen_store import filter_new_filings


def _filing(accession, form="13F-HR", filing_date="2026-05-15"):
    return {"accessionNumber": accession, "form": form, "filingDate": filing_date}


class TestFilterNewFilings:
    def test_first_run_reports_nothing_new_but_establishes_baseline(self, tmp_path):
        db_path = tmp_path / "seen.db"
        filings = [_filing("A1"), _filing("A2")]
        new_filings, is_first_run = filter_new_filings("cik1:13F", filings, db_path)
        assert is_first_run is True
        assert new_filings == []

    def test_second_run_with_no_changes_reports_nothing_new(self, tmp_path):
        db_path = tmp_path / "seen.db"
        filings = [_filing("A1"), _filing("A2")]
        filter_new_filings("cik1:13F", filings, db_path)  # baseline
        new_filings, is_first_run = filter_new_filings("cik1:13F", filings, db_path)
        assert is_first_run is False
        assert new_filings == []

    def test_second_run_with_a_new_filing_reports_only_that_one(self, tmp_path):
        db_path = tmp_path / "seen.db"
        filter_new_filings("cik1:13F", [_filing("A1"), _filing("A2")], db_path)  # baseline
        new_filings, is_first_run = filter_new_filings(
            "cik1:13F", [_filing("A1"), _filing("A2"), _filing("A3")], db_path
        )
        assert is_first_run is False
        assert [f["accessionNumber"] for f in new_filings] == ["A3"]

    def test_third_run_after_seeing_a3_does_not_report_it_again(self, tmp_path):
        db_path = tmp_path / "seen.db"
        filter_new_filings("cik1:13F", [_filing("A1")], db_path)  # baseline
        filter_new_filings("cik1:13F", [_filing("A1"), _filing("A2")], db_path)  # sees A2
        new_filings, _ = filter_new_filings("cik1:13F", [_filing("A1"), _filing("A2")], db_path)
        assert new_filings == []

    def test_tracking_keys_are_independent(self, tmp_path):
        # Same underlying investor, but 13F and 13D/13G feeds must not
        # bleed into each other's seen-state.
        db_path = tmp_path / "seen.db"
        filter_new_filings("cik1:13F", [_filing("A1")], db_path)
        new_filings, is_first_run = filter_new_filings("cik1:13D-G", [_filing("A1")], db_path)
        # Same accession number, but a DIFFERENT tracking_key -> still a
        # fresh baseline for this feed.
        assert is_first_run is True
        assert new_filings == []

    def test_empty_filings_list_is_first_run_with_nothing_new(self, tmp_path):
        db_path = tmp_path / "seen.db"
        new_filings, is_first_run = filter_new_filings("cik1:13F", [], db_path)
        assert is_first_run is True
        assert new_filings == []
