import pandas as pd
import pytest

from src.analytics.entry_price import with_entry_price_comparison


def _portfolio_row(cusip, name, curr_shares, curr_value_usd, change_type, curr_weight_pct=10.0):
    return {
        "cusip": cusip,
        "name_of_issuer": name,
        "curr_shares": curr_shares,
        "curr_value_usd": curr_value_usd,
        "curr_weight_pct": curr_weight_pct,
        "change_type": change_type,
    }


class TestWithEntryPriceComparison:
    def test_columns(self):
        portfolio = pd.DataFrame([_portfolio_row("A", "Stock A", 100, 10000, "unchanged")])
        prices = pd.DataFrame([{"cusip": "A", "ticker": "AAA", "entry_price": 90.0, "current_price": 99.0}])
        result = with_entry_price_comparison(portfolio, prices)
        assert list(result.columns) == [
            "cusip", "name_of_issuer", "ticker", "change_type",
            "curr_shares", "curr_value_usd", "curr_weight_pct",
            "entry_price", "current_price", "price_diff_pct",
        ]

    def test_price_diff_pct_positive_when_current_above_entry(self):
        portfolio = pd.DataFrame([_portfolio_row("A", "Stock A", 100, 10000, "add")])
        prices = pd.DataFrame([{"cusip": "A", "ticker": "AAA", "entry_price": 100.0, "current_price": 120.0}])
        result = with_entry_price_comparison(portfolio, prices)
        assert result.loc[0, "price_diff_pct"] == pytest.approx(20.0)

    def test_price_diff_pct_negative_when_current_below_entry(self):
        portfolio = pd.DataFrame([_portfolio_row("A", "Stock A", 100, 10000, "add")])
        prices = pd.DataFrame([{"cusip": "A", "ticker": "AAA", "entry_price": 100.0, "current_price": 80.0}])
        result = with_entry_price_comparison(portfolio, prices)
        assert result.loc[0, "price_diff_pct"] == pytest.approx(-20.0)

    def test_missing_ticker_keeps_row_with_nan_diff(self):
        portfolio = pd.DataFrame([_portfolio_row("A", "Stock A", 100, 10000, "unchanged")])
        prices = pd.DataFrame([{"cusip": "A", "ticker": None, "entry_price": None, "current_price": None}])
        result = with_entry_price_comparison(portfolio, prices)
        assert len(result) == 1  # row kept, not dropped
        assert pd.isna(result.loc[0, "price_diff_pct"])

    def test_missing_entry_price_only_keeps_row_with_nan_diff(self):
        portfolio = pd.DataFrame([_portfolio_row("A", "Stock A", 100, 10000, "unchanged")])
        prices = pd.DataFrame([{"cusip": "A", "ticker": "AAA", "entry_price": None, "current_price": 99.0}])
        result = with_entry_price_comparison(portfolio, prices)
        assert pd.isna(result.loc[0, "price_diff_pct"])

    def test_cusip_not_in_prices_frame_at_all_keeps_row(self):
        portfolio = pd.DataFrame([_portfolio_row("A", "Stock A", 100, 10000, "unchanged")])
        prices = pd.DataFrame(columns=["cusip", "ticker", "entry_price", "current_price"])
        result = with_entry_price_comparison(portfolio, prices)
        assert len(result) == 1
        assert pd.isna(result.loc[0, "ticker"])
        assert pd.isna(result.loc[0, "price_diff_pct"])

    def test_multiple_rows_independent(self):
        portfolio = pd.DataFrame([
            _portfolio_row("A", "Stock A", 100, 10000, "add"),
            _portfolio_row("B", "Stock B", 50, 5000, "trim"),
        ])
        prices = pd.DataFrame([
            {"cusip": "A", "ticker": "AAA", "entry_price": 100.0, "current_price": 110.0},
            {"cusip": "B", "ticker": "BBB", "entry_price": 200.0, "current_price": 190.0},
        ])
        result = with_entry_price_comparison(portfolio, prices).set_index("cusip")
        assert result.loc["A", "price_diff_pct"] == pytest.approx(10.0)
        assert result.loc["B", "price_diff_pct"] == pytest.approx(-5.0)

    def test_empty_portfolio_returns_empty_with_columns(self):
        portfolio = pd.DataFrame(columns=["cusip", "name_of_issuer", "curr_shares", "curr_value_usd", "curr_weight_pct", "change_type"])
        prices = pd.DataFrame(columns=["cusip", "ticker", "entry_price", "current_price"])
        result = with_entry_price_comparison(portfolio, prices)
        assert result.empty
        assert "price_diff_pct" in result.columns
