import pandas as pd
import pytest

from src.analytics.sp500_grid import sp500_ownership_summary


def _holding(cik, manager_name, cusip, name_of_issuer, value_usd):
    return {
        "cik": cik, "manager_name": manager_name, "cusip": cusip, "name_of_issuer": name_of_issuer,
        "value_usd": value_usd, "shares": value_usd,
    }


class TestSp500OwnershipSummary:
    @pytest.fixture
    def holdings(self) -> pd.DataFrame:
        # A: X=60 (S&P500), Y=40 (not S&P500) | B: X=150 (S&P500), Z=50 (S&P500)
        rows = [
            _holding("A", "Manager A", "CUSIP_X", "Stock X", 60),
            _holding("A", "Manager A", "CUSIP_Y", "Stock Y (not S&P)", 40),
            _holding("B", "Manager B", "CUSIP_X", "Stock X", 150),
            _holding("B", "Manager B", "CUSIP_Z", "Stock Z", 50),
        ]
        return pd.DataFrame(rows)

    @pytest.fixture
    def sp500(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"ticker": "XX", "name": "Stock X Inc", "sector": "Technology"},
                {"ticker": "ZZ", "name": "Stock Z Inc", "sector": "Financials"},
                {"ticker": "UNHELD", "name": "Never Held Co", "sector": "Energy"},
            ]
        )

    @pytest.fixture
    def ticker_by_cusip(self) -> dict:
        return {"CUSIP_X": "XX", "CUSIP_Y": "YY", "CUSIP_Z": "ZZ"}

    def test_columns(self, holdings, sp500, ticker_by_cusip):
        result = sp500_ownership_summary(holdings, sp500, ticker_by_cusip)
        assert list(result.columns) == [
            "ticker", "name", "sector", "cusip", "holder_count", "avg_weight_pct", "total_value_usd",
        ]

    def test_excludes_non_sp500_holdings(self, holdings, sp500, ticker_by_cusip):
        result = sp500_ownership_summary(holdings, sp500, ticker_by_cusip)
        assert "YY" not in set(result["ticker"])  # Stock Y resolved but not in sp500 list

    def test_excludes_sp500_tickers_with_zero_holders(self, holdings, sp500, ticker_by_cusip):
        result = sp500_ownership_summary(holdings, sp500, ticker_by_cusip)
        assert "UNHELD" not in set(result["ticker"])

    def test_holder_count_and_sector_attached(self, holdings, sp500, ticker_by_cusip):
        result = sp500_ownership_summary(holdings, sp500, ticker_by_cusip).set_index("ticker")
        assert result.loc["XX", "holder_count"] == 2
        assert result.loc["XX", "sector"] == "Technology"
        assert result.loc["ZZ", "holder_count"] == 1
        assert result.loc["ZZ", "sector"] == "Financials"

    def test_sorted_by_holder_count_descending(self, holdings, sp500, ticker_by_cusip):
        result = sp500_ownership_summary(holdings, sp500, ticker_by_cusip)
        assert list(result["ticker"]) == ["XX", "ZZ"]

    def test_empty_holdings_returns_empty_with_columns(self, sp500, ticker_by_cusip):
        result = sp500_ownership_summary(
            pd.DataFrame(columns=["cik", "cusip", "name_of_issuer", "value_usd"]), sp500, ticker_by_cusip
        )
        assert result.empty
        assert list(result.columns) == [
            "ticker", "name", "sector", "cusip", "holder_count", "avg_weight_pct", "total_value_usd",
        ]

    def test_empty_sp500_returns_empty_with_columns(self, holdings, ticker_by_cusip):
        result = sp500_ownership_summary(holdings, pd.DataFrame(columns=["ticker", "name", "sector"]), ticker_by_cusip)
        assert result.empty

    def test_unresolved_ticker_excluded_not_crashed(self, holdings, sp500):
        # CUSIP_X has no entry in ticker_by_cusip at all
        result = sp500_ownership_summary(holdings, sp500, {"CUSIP_Z": "ZZ"})
        assert list(result["ticker"]) == ["ZZ"]
