import pandas as pd
import pytest

from src.analytics.backtest import consensus_asof_schedule, simulate_portfolio


def _holding(period_date, filing_date, cik, cusip, value, name=None):
    return {
        "period_date": period_date,
        "filing_date": filing_date,
        "cik": cik,
        "manager_name": f"Manager {cik}",
        "cusip": cusip,
        "name_of_issuer": name or f"Stock {cusip}",
        "value_usd": value,
        "shares": value,
    }


class TestConsensusAsofSchedule:
    @pytest.fixture
    def holdings(self) -> pd.DataFrame:
        rows = [
            # Quarter 1: X held by both managers (consensus), Y only by B.
            _holding("2024-03-31", "2024-05-10", "A", "X", 100),
            _holding("2024-03-31", "2024-05-15", "B", "X", 50),
            _holding("2024-03-31", "2024-05-15", "B", "Y", 30),
            # Quarter 2: Y held by both (consensus), Z only by B.
            _holding("2024-06-30", "2024-08-01", "A", "Y", 40),
            _holding("2024-06-30", "2024-08-05", "B", "Y", 20),
            _holding("2024-06-30", "2024-08-05", "B", "Z", 60),
        ]
        return pd.DataFrame(rows)

    def test_columns(self, holdings):
        result = consensus_asof_schedule(holdings, top_n=1)
        assert list(result.columns) == [
            "period_date", "entry_date", "days_after_period_end", "cusips",
        ]

    def test_one_row_per_quarter_sorted_by_entry_date(self, holdings):
        result = consensus_asof_schedule(holdings, top_n=1)
        assert list(result["period_date"]) == ["2024-03-31", "2024-06-30"]

    def test_entry_date_is_max_filing_date_not_period_end(self, holdings):
        # Quarter 1: manager A filed 05-10, manager B filed 05-15 -- the
        # consensus isn't complete until the LATER filer's date.
        result = consensus_asof_schedule(holdings, top_n=1)
        assert result.loc[0, "entry_date"] == "2024-05-15"

    def test_days_after_period_end_computed_correctly(self, holdings):
        result = consensus_asof_schedule(holdings, top_n=1)
        # 2024-03-31 -> 2024-05-15 is exactly 45 days (the 13F deadline).
        assert result.loc[0, "days_after_period_end"] == 45

    def test_top_n_picks_the_consensus_holding(self, holdings):
        result = consensus_asof_schedule(holdings, top_n=1)
        assert result.loc[0, "cusips"] == ["X"]  # held by both managers
        assert result.loc[1, "cusips"] == ["Y"]  # held by both managers

    def test_top_n_2_includes_the_singly_held_name_too(self, holdings):
        result = consensus_asof_schedule(holdings, top_n=2)
        assert set(result.loc[0, "cusips"]) == {"X", "Y"}

    def test_empty_holdings_returns_empty_with_columns(self):
        empty = pd.DataFrame(columns=["period_date", "filing_date", "cik", "manager_name", "cusip", "name_of_issuer", "value_usd", "shares"])
        result = consensus_asof_schedule(empty, top_n=5)
        assert result.empty
        assert "entry_date" in result.columns


class TestSimulatePortfolio:
    @pytest.fixture
    def price_history(self) -> pd.DataFrame:
        dates = pd.date_range("2024-01-01", periods=6, freq="D")
        return pd.DataFrame(
            {
                "A": [100, 102, 104, 106, 108, 110],
                "B": [200, 196, 192, 188, 184, 180],
            },
            index=dates,
        )

    def test_first_rebalance_starts_at_100_with_no_turnover_cost(self, price_history):
        rebalances = [{"entry_date": "2024-01-01", "tickers": ["A", "B"]}]
        result = simulate_portfolio(price_history, rebalances, cost_bps=100)
        assert result["value"].iloc[0] == pytest.approx(100.0)
        assert pd.isna(result["turnover_pct"].iloc[0])

    def test_equal_weight_basket_tracks_average_of_opposite_moves(self, price_history):
        # A rises ~2%/day, B falls ~2%/day -> equal-weight basket ~flat.
        rebalances = [{"entry_date": "2024-01-01", "tickers": ["A", "B"]}]
        result = simulate_portfolio(price_history, rebalances, cost_bps=0)
        day2 = result.loc["2024-01-02", "value"]
        # A: 102/100=1.02, B: 196/200=0.98 -> mean=1.00 -> value=100
        assert day2 == pytest.approx(100.0, abs=0.01)

    def test_rebalance_applies_turnover_cost_and_new_basket(self, price_history):
        rebalances = [
            {"entry_date": "2024-01-01", "tickers": ["A", "B"]},
            {"entry_date": "2024-01-04", "tickers": ["A"]},
        ]
        result = simulate_portfolio(price_history, rebalances, cost_bps=100)

        # Value flat at 100 through day 3 (basket A+B averages to ~flat).
        day3_value = result.loc["2024-01-03", "value"]
        assert day3_value == pytest.approx(100.0, abs=0.01)

        # At day4 rebalance: dropping B, keeping A -> turnover:
        # removed={B}(1), added={}(0), denom=|{A,B}|+|{A}|=3 -> 33.333%
        day4 = result.loc["2024-01-04"]
        assert day4["turnover_pct"] == pytest.approx(100 / 3)
        expected_day4_value = day3_value * (1 - 100 / 10000 * (100 / 3) / 100)
        assert day4["value"] == pytest.approx(expected_day4_value)

        # After day4, only A drives returns.
        day6_value = result.loc["2024-01-06", "value"]
        expected_day6_value = day4["value"] * (110 / 106)
        assert day6_value == pytest.approx(expected_day6_value)

    def test_missing_ticker_dropped_not_fatal(self, price_history):
        rebalances = [{"entry_date": "2024-01-01", "tickers": ["A", "DOES_NOT_EXIST"]}]
        result = simulate_portfolio(price_history, rebalances, cost_bps=0)
        # Basket falls back to just A -> tracks A's own return exactly.
        day6 = result.loc["2024-01-06", "value"]
        assert day6 == pytest.approx(100 * (110 / 100))

    def test_no_rebalances_returns_empty(self, price_history):
        result = simulate_portfolio(price_history, [], cost_bps=10)
        assert result.empty

    def test_rebalance_order_independent_of_input_order(self, price_history):
        rebalances_reversed = [
            {"entry_date": "2024-01-04", "tickers": ["A"]},
            {"entry_date": "2024-01-01", "tickers": ["A", "B"]},
        ]
        result = simulate_portfolio(price_history, rebalances_reversed, cost_bps=100)
        assert result["value"].iloc[0] == pytest.approx(100.0)
        assert len(result) == 6
