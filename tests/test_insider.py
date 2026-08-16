import pandas as pd
import pytest

from src.analytics.insider import insider_buy_summary


def _txn(ticker, issuer_name, value_usd):
    return {"ticker": ticker, "issuer_name": issuer_name, "value_usd": value_usd}


class TestInsiderBuySummary:
    @pytest.fixture
    def transactions(self) -> pd.DataFrame:
        rows = [
            _txn("AAA", "Stock AAA Inc", 100_000),
            _txn("AAA", "Stock AAA Inc", 50_000),
            _txn("AAA", "Stock AAA Inc", 200_000),
            _txn("BBB", "Stock BBB Inc", 30_000),
            _txn("CCC", "Stock CCC Inc", 10_000),  # below default min_value_usd in some tests
        ]
        return pd.DataFrame(rows)

    def test_columns(self, transactions):
        result = insider_buy_summary(transactions)
        assert list(result.columns) == ["ticker", "issuer_name", "n_buys", "total_value_usd"]

    def test_counts_and_sums_per_ticker(self, transactions):
        result = insider_buy_summary(transactions).set_index("ticker")
        assert result.loc["AAA", "n_buys"] == 3
        assert result.loc["AAA", "total_value_usd"] == pytest.approx(350_000)
        assert result.loc["BBB", "n_buys"] == 1
        assert result.loc["BBB", "total_value_usd"] == pytest.approx(30_000)

    def test_issuer_name_carried_through(self, transactions):
        result = insider_buy_summary(transactions).set_index("ticker")
        assert result.loc["AAA", "issuer_name"] == "Stock AAA Inc"

    def test_sorted_by_count_then_value_descending(self, transactions):
        result = insider_buy_summary(transactions)
        # AAA has 3 buys (most), BBB and CCC both have 1 -- BBB's value ($30k) > CCC's ($10k)
        assert list(result["ticker"]) == ["AAA", "BBB", "CCC"]

    def test_min_value_usd_filters_before_aggregating(self, transactions):
        result = insider_buy_summary(transactions, min_value_usd=50_000)
        # CCC's only transaction ($10k) is dropped entirely
        assert "CCC" not in set(result["ticker"])
        # AAA's $50k row survives (>=), its $100k and $200k rows survive too
        assert result.set_index("ticker").loc["AAA", "n_buys"] == 3

    def test_empty_input_returns_empty_with_columns(self):
        result = insider_buy_summary(pd.DataFrame(columns=["ticker", "issuer_name", "value_usd"]))
        assert result.empty
        assert list(result.columns) == ["ticker", "issuer_name", "n_buys", "total_value_usd"]

    def test_all_below_threshold_returns_empty(self, transactions):
        result = insider_buy_summary(transactions, min_value_usd=10_000_000)
        assert result.empty
