from src.jobs.refresh import NewFilingAlert, format_alert_text


class TestFormatAlertText:
    def test_no_alerts_says_nothing_new(self):
        text = format_alert_text([])
        assert "새 공시 없음" in text

    def test_includes_manager_feed_and_filing_details(self):
        alerts = [
            NewFilingAlert(
                manager_name="Warren Buffett",
                cik="1067983",
                feed="13F",
                filings=[
                    {
                        "form": "13F-HR",
                        "filingDate": "2026-05-15",
                        "reportDate": "2026-03-31",
                        "accessionNumber": "0001193125-26-226661",
                    }
                ],
            )
        ]
        text = format_alert_text(alerts)
        assert "Warren Buffett" in text
        assert "13F" in text
        assert "1067983" in text
        assert "0001193125-26-226661" in text
        assert "2026-05-15" in text

    def test_multiple_alerts_all_present(self):
        alerts = [
            NewFilingAlert("Manager A", "1", "13F", [{"form": "13F-HR", "filingDate": "d", "reportDate": "d", "accessionNumber": "A1"}]),
            NewFilingAlert("Manager B", "2", "13D/13G", [{"form": "SCHEDULE 13D", "filingDate": "d", "reportDate": "d", "accessionNumber": "B1"}]),
        ]
        text = format_alert_text(alerts)
        assert "Manager A" in text
        assert "Manager B" in text
        assert "A1" in text
        assert "B1" in text
