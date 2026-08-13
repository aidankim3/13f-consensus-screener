import pandas as pd
import pytest

from src.analytics.investor import investor_portfolio, portfolio_summary


def _holding(cik, manager_name, cusip, name_of_issuer, value_usd, shares=None, is_option=False):
    return {
        "cik": cik,
        "manager_name": manager_name,
        "cusip": cusip,
        "name_of_issuer": name_of_issuer,
        "value_usd": value_usd,
        "shares": shares if shares is not None else value_usd,
        "is_option": is_option,
    }


class TestInvestorPortfolio:
    @pytest.fixture
    def previous(self) -> pd.DataFrame:
        rows = [
            _holding("A", "Manager A", "P", "Stock P", 1000, shares=100),  # -> add
            _holding("A", "Manager A", "Q", "Stock Q", 500, shares=50),  # -> sold_out
            _holding("A", "Manager A", "S", "Stock S", 200, shares=20),  # -> unchanged
        ]
        return pd.DataFrame(rows)

    @pytest.fixture
    def current(self) -> pd.DataFrame:
        rows = [
            _holding("A", "Manager A", "P", "Stock P", 1600, shares=150),  # add
            _holding("A", "Manager A", "R", "Stock R", 300, shares=30),  # new_buy
            _holding("A", "Manager A", "S", "Stock S", 200, shares=20),  # unchanged
        ]
        return pd.DataFrame(rows)

    def test_columns(self, previous, current):
        result = investor_portfolio(previous, current)
        assert list(result.columns) == [
            "cik", "manager_name", "cusip", "name_of_issuer",
            "prev_shares", "curr_shares", "shares_delta",
            "prev_value_usd", "curr_value_usd", "value_delta_usd",
            "prev_weight_pct", "curr_weight_pct", "weight_delta_pct",
            "change_type",
        ]

    def test_includes_unchanged_rows_unlike_quarter_changes(self, previous, current):
        result = investor_portfolio(previous, current).set_index("cusip")
        assert len(result) == 4  # P, Q, R, S -- quarter_changes would drop S
        assert result.loc["S", "change_type"] == "unchanged"
        assert result.loc["S", "shares_delta"] == 0

    def test_sold_out_row_stays_visible_with_zero_current_value(self, previous, current):
        result = investor_portfolio(previous, current).set_index("cusip")
        assert result.loc["Q", "change_type"] == "sold_out"
        assert result.loc["Q", "curr_value_usd"] == 0
        assert result.loc["Q", "curr_shares"] == 0

    def test_all_four_change_types_present(self, previous, current):
        result = investor_portfolio(previous, current)
        assert set(result["change_type"]) == {"add", "sold_out", "new_buy", "unchanged"}

    def test_sorted_by_current_value_descending(self, previous, current):
        result = investor_portfolio(previous, current)
        values = list(result["curr_value_usd"])
        assert values == sorted(values, reverse=True)

    def test_rejects_multiple_managers_in_previous(self, current):
        previous = pd.DataFrame([
            _holding("A", "Manager A", "P", "Stock P", 1000, shares=100),
            _holding("B", "Manager B", "P", "Stock P", 500, shares=50),
        ])
        with pytest.raises(ValueError):
            investor_portfolio(previous, current)

    def test_rejects_multiple_managers_in_current(self, previous):
        current = pd.DataFrame([
            _holding("A", "Manager A", "P", "Stock P", 1000, shares=100),
            _holding("B", "Manager B", "P", "Stock P", 500, shares=50),
        ])
        with pytest.raises(ValueError):
            investor_portfolio(previous, current)

    def test_both_empty_returns_empty_with_columns(self):
        empty = pd.DataFrame(columns=["cik", "manager_name", "cusip", "name_of_issuer", "value_usd", "shares"])
        result = investor_portfolio(empty, empty)
        assert result.empty
        assert "change_type" in result.columns


class TestPortfolioSummary:
    def test_n_holdings_excludes_sold_out(self):
        portfolio = pd.DataFrame([
            {"cusip": "P", "curr_value_usd": 100, "change_type": "add"},
            {"cusip": "Q", "curr_value_usd": 0, "change_type": "sold_out"},
            {"cusip": "R", "curr_value_usd": 50, "change_type": "new_buy"},
        ])
        result = portfolio_summary(portfolio, pd.DataFrame(columns=["is_option", "value_usd"]))
        assert result.loc[0, "n_holdings"] == 2  # P, R -- not Q

    def test_top10_concentration_with_fewer_than_10_holdings_is_100pct(self):
        portfolio = pd.DataFrame([
            {"cusip": "P", "curr_value_usd": 60, "change_type": "unchanged"},
            {"cusip": "Q", "curr_value_usd": 40, "change_type": "unchanged"},
        ])
        result = portfolio_summary(portfolio, pd.DataFrame(columns=["is_option", "value_usd"]))
        assert result.loc[0, "top10_concentration_pct"] == pytest.approx(100.0)

    def test_top10_concentration_excludes_11th_position(self):
        # 10 positions of value 10 each (=100 total), plus one tiny 12th
        # position of value 1 (=101 total) -- top10 should be 100/101, not 100%.
        rows = [
            {"cusip": f"S{i}", "curr_value_usd": 10, "change_type": "unchanged"} for i in range(10)
        ]
        rows.append({"cusip": "TINY", "curr_value_usd": 1, "change_type": "unchanged"})
        portfolio = pd.DataFrame(rows)
        result = portfolio_summary(portfolio, pd.DataFrame(columns=["is_option", "value_usd"]))
        assert result.loc[0, "top10_concentration_pct"] == pytest.approx(100 / 101 * 100)

    def test_turnover_formula(self):
        # 2 unchanged (held both), 1 new_buy (held now only), 1 sold_out (held prev only)
        # n_prev = unchanged(2) + sold_out(1) = 3; n_curr = unchanged(2) + new_buy(1) = 3
        # turnover = (1 new_buy + 1 sold_out) / (3+3) * 100 = 2/6*100 = 33.33%
        portfolio = pd.DataFrame([
            {"cusip": "A", "curr_value_usd": 10, "change_type": "unchanged"},
            {"cusip": "B", "curr_value_usd": 10, "change_type": "unchanged"},
            {"cusip": "C", "curr_value_usd": 10, "change_type": "new_buy"},
            {"cusip": "D", "curr_value_usd": 0, "change_type": "sold_out"},
        ])
        result = portfolio_summary(portfolio, pd.DataFrame(columns=["is_option", "value_usd"]))
        assert result.loc[0, "turnover_pct"] == pytest.approx(100 / 3)

    def test_turnover_is_nan_when_no_prior_quarter_data(self):
        # everything is new_buy -> n_prev == 0 -> no baseline to compare against
        portfolio = pd.DataFrame([
            {"cusip": "A", "curr_value_usd": 10, "change_type": "new_buy"},
        ])
        result = portfolio_summary(portfolio, pd.DataFrame(columns=["is_option", "value_usd"]))
        assert pd.isna(result.loc[0, "turnover_pct"])

    def test_option_weight_pct_computed_from_raw_frame_independent_of_portfolio(self):
        # portfolio itself has no rows at all (e.g. options were excluded
        # upstream and the manager holds nothing but options) -- option
        # weight should still reflect the raw current holdings.
        portfolio = pd.DataFrame(columns=["cusip", "curr_value_usd", "change_type"])
        current_with_options = pd.DataFrame([
            {"is_option": False, "value_usd": 300},
            {"is_option": True, "value_usd": 700},
        ])
        result = portfolio_summary(portfolio, current_with_options)
        assert result.loc[0, "option_weight_pct"] == pytest.approx(70.0)
        assert result.loc[0, "n_holdings"] == 0  # unaffected by the raw frame

    def test_empty_current_holdings_with_options_gives_zero_option_weight(self):
        portfolio = pd.DataFrame([
            {"cusip": "A", "curr_value_usd": 10, "change_type": "unchanged"},
        ])
        result = portfolio_summary(portfolio, pd.DataFrame(columns=["is_option", "value_usd"]))
        assert result.loc[0, "option_weight_pct"] == 0.0

    def test_columns(self):
        portfolio = pd.DataFrame(columns=["cusip", "curr_value_usd", "change_type"])
        result = portfolio_summary(portfolio, pd.DataFrame(columns=["is_option", "value_usd"]))
        assert list(result.columns) == [
            "n_holdings", "top10_concentration_pct", "turnover_pct", "option_weight_pct",
        ]
