import pandas as pd
import pytest

from src.analytics.consensus import (
    consensus_holdings,
    quarter_changes,
    top_buys,
    top_sells,
)


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


class TestConsensusHoldings:
    @pytest.fixture
    def holdings(self) -> pd.DataFrame:
        # A: X=60, Y=40 (total 100) | B: X=150, Z=50 (total 200) | C: Y=50 (total 50)
        rows = [
            _holding("A", "Manager A", "X", "Stock X", 60),
            _holding("A", "Manager A", "Y", "Stock Y", 40),
            _holding("B", "Manager B", "X", "Stock X", 150),
            _holding("B", "Manager B", "Z", "Stock Z", 50),
            _holding("C", "Manager C", "Y", "Stock Y", 50),
        ]
        return pd.DataFrame(rows)

    def test_columns(self, holdings):
        result = consensus_holdings(holdings)
        assert list(result.columns) == [
            "cusip", "name_of_issuer", "holder_count", "total_value_usd",
            "avg_weight_pct", "equal_weight_score", "value_weight_score",
        ]

    def test_holder_count_and_total_value(self, holdings):
        result = consensus_holdings(holdings).set_index("cusip")
        assert result.loc["X", "holder_count"] == 2
        assert result.loc["X", "total_value_usd"] == 210
        assert result.loc["Y", "holder_count"] == 2
        assert result.loc["Y", "total_value_usd"] == 90
        assert result.loc["Z", "holder_count"] == 1
        assert result.loc["Z", "total_value_usd"] == 50

    def test_avg_weight_pct_is_mean_of_own_portfolio_weights(self, holdings):
        result = consensus_holdings(holdings).set_index("cusip")
        # X: A holds 60/100=60%, B holds 150/200=75% -> mean 67.5%
        assert result.loc["X", "avg_weight_pct"] == pytest.approx(67.5)
        # Y: A holds 40/100=40%, C holds 50/50=100% -> mean 70%
        assert result.loc["Y", "avg_weight_pct"] == pytest.approx(70.0)

    def test_equal_weight_score_is_holder_share_of_all_managers(self, holdings):
        result = consensus_holdings(holdings).set_index("cusip")
        # 3 managers total; X and Y held by 2/3, Z by 1/3
        assert result.loc["X", "equal_weight_score"] == pytest.approx(200 / 3)
        assert result.loc["Z", "equal_weight_score"] == pytest.approx(100 / 3)

    def test_value_weight_score_is_share_of_grand_total_value(self, holdings):
        result = consensus_holdings(holdings).set_index("cusip")
        # grand total = 60+40+150+50+50 = 350
        assert result.loc["X", "value_weight_score"] == pytest.approx(210 / 350 * 100)
        assert result.loc["Z", "value_weight_score"] == pytest.approx(50 / 350 * 100)

    def test_sorted_by_holder_count_then_value_descending(self, holdings):
        result = consensus_holdings(holdings)
        assert list(result["cusip"]) == ["X", "Y", "Z"]

    def test_empty_input_returns_empty_with_columns(self):
        result = consensus_holdings(pd.DataFrame(columns=["cik", "cusip", "name_of_issuer", "value_usd"]))
        assert result.empty
        assert list(result.columns) == [
            "cusip", "name_of_issuer", "holder_count", "total_value_usd",
            "avg_weight_pct", "equal_weight_score", "value_weight_score",
        ]

    def test_split_sub_account_rows_count_as_one_holder(self):
        # Real Berkshire Hathaway filings report the same cusip across
        # multiple line items (different insurance-subsidiary sub-accounts
        # with separate investment discretion). A manager splitting one
        # position into 3 rows must still count as 1 holder with the
        # position's TOTAL value, not 3 separate (smaller) holders.
        rows = [
            _holding("A", "Manager A", "X", "Stock X", 100),
            _holding("A", "Manager A", "X", "Stock X", 200),
            _holding("A", "Manager A", "X", "Stock X", 300),
            _holding("B", "Manager B", "X", "Stock X", 400),
        ]
        result = consensus_holdings(pd.DataFrame(rows)).set_index("cusip")
        assert result.loc["X", "holder_count"] == 2
        assert result.loc["X", "total_value_usd"] == 1000  # 100+200+300+400
        # A's total portfolio is only stock X (across 3 rows) -> 100% weight;
        # B's total portfolio is only stock X too -> 100% weight. Mean = 100%,
        # not skewed by A appearing 3 times.
        assert result.loc["X", "avg_weight_pct"] == pytest.approx(100.0)


class TestQuarterChanges:
    @pytest.fixture
    def previous(self) -> pd.DataFrame:
        rows = [
            _holding("A", "Manager A", "P", "Stock P", 1000, shares=100),
            _holding("A", "Manager A", "Q", "Stock Q", 500, shares=50),
            _holding("B", "Manager B", "S", "Stock S", 2000, shares=200),
        ]
        return pd.DataFrame(rows)

    @pytest.fixture
    def current(self) -> pd.DataFrame:
        rows = [
            _holding("A", "Manager A", "P", "Stock P", 1600, shares=150),  # add
            _holding("A", "Manager A", "R", "Stock R", 300, shares=30),  # new_buy
            # Q dropped entirely -> sold_out
            _holding("B", "Manager B", "S", "Stock S", 1200, shares=120),  # trim
        ]
        return pd.DataFrame(rows)

    def test_columns(self, previous, current):
        result = quarter_changes(previous, current)
        assert list(result.columns) == [
            "cik", "manager_name", "cusip", "name_of_issuer",
            "prev_shares", "curr_shares", "shares_delta",
            "prev_value_usd", "curr_value_usd", "value_delta_usd",
            "prev_weight_pct", "curr_weight_pct", "weight_delta_pct",
            "change_type",
        ]

    def test_classifies_all_four_change_types(self, previous, current):
        result = quarter_changes(previous, current).set_index("cusip")
        assert result.loc["P", "change_type"] == "add"
        assert result.loc["Q", "change_type"] == "sold_out"
        assert result.loc["R", "change_type"] == "new_buy"
        assert result.loc["S", "change_type"] == "trim"

    def test_shares_and_value_deltas(self, previous, current):
        result = quarter_changes(previous, current).set_index("cusip")
        assert result.loc["P", "shares_delta"] == 50
        assert result.loc["P", "value_delta_usd"] == 600
        assert result.loc["Q", "shares_delta"] == -50
        assert result.loc["Q", "value_delta_usd"] == -500
        assert result.loc["R", "shares_delta"] == 30
        assert result.loc["S", "shares_delta"] == -80

    def test_weight_pct_computed_within_each_manager_snapshot(self, previous, current):
        result = quarter_changes(previous, current).set_index("cusip")
        # prev: A total=1500 -> P weight=1000/1500*100=66.667%
        assert result.loc["P", "prev_weight_pct"] == pytest.approx(1000 / 1500 * 100)
        # curr: A total=1900 -> P weight=1600/1900*100=84.211%
        assert result.loc["P", "curr_weight_pct"] == pytest.approx(1600 / 1900 * 100)
        # sold_out row: curr_weight_pct must be 0, not NaN
        assert result.loc["Q", "curr_weight_pct"] == 0
        # new_buy row: prev_weight_pct must be 0, not NaN
        assert result.loc["R", "prev_weight_pct"] == 0
        # S is B's only holding both quarters -> 100% weight both times
        assert result.loc["S", "prev_weight_pct"] == pytest.approx(100.0)
        assert result.loc["S", "curr_weight_pct"] == pytest.approx(100.0)

    def test_unchanged_shares_are_dropped(self):
        previous = pd.DataFrame([_holding("A", "Manager A", "P", "Stock P", 1000, shares=100)])
        current = pd.DataFrame([_holding("A", "Manager A", "P", "Stock P", 1000, shares=100)])
        result = quarter_changes(previous, current)
        assert result.empty

    def test_split_sub_account_rows_do_not_explode_into_cartesian_product(self):
        # Real bug: Berkshire reports American Express across 3 rows (same
        # cusip) in both quarters. An outer merge on non-unique (cik,cusip)
        # keys without consolidating first produces 3x3=9 spurious "changes"
        # instead of 1 real one, with nonsensical inflated deltas.
        previous = pd.DataFrame([
            _holding("A", "Manager A", "X", "Stock X", 100, shares=10),
            _holding("A", "Manager A", "X", "Stock X", 200, shares=20),
            _holding("A", "Manager A", "X", "Stock X", 300, shares=30),
        ])
        current = pd.DataFrame([
            _holding("A", "Manager A", "X", "Stock X", 150, shares=15),
            _holding("A", "Manager A", "X", "Stock X", 250, shares=25),
            _holding("A", "Manager A", "X", "Stock X", 350, shares=35),
        ])
        result = quarter_changes(previous, current)
        assert len(result) == 1  # not 9
        row = result.iloc[0]
        assert row["prev_shares"] == 60  # 10+20+30
        assert row["curr_shares"] == 75  # 15+25+35
        assert row["shares_delta"] == 15
        assert row["change_type"] == "add"

    def test_both_empty_returns_empty_with_columns(self):
        empty = pd.DataFrame(columns=["cik", "manager_name", "cusip", "name_of_issuer", "value_usd", "shares"])
        result = quarter_changes(empty, empty)
        assert result.empty
        assert "change_type" in result.columns


class TestTopBuys:
    @pytest.fixture
    def changes(self) -> pd.DataFrame:
        # AAA: new_buy by M1 (+100, +5pp), new_buy by M2 (+200, +10pp), add by M3 (+50, +2pp)
        # BBB: add only by M1 (+20, +1pp)
        rows = [
            {"cik": "M1", "cusip": "AAA", "name_of_issuer": "Stock AAA", "change_type": "new_buy",
             "value_delta_usd": 100, "weight_delta_pct": 5},
            {"cik": "M2", "cusip": "AAA", "name_of_issuer": "Stock AAA", "change_type": "new_buy",
             "value_delta_usd": 200, "weight_delta_pct": 10},
            {"cik": "M3", "cusip": "AAA", "name_of_issuer": "Stock AAA", "change_type": "add",
             "value_delta_usd": 50, "weight_delta_pct": 2},
            {"cik": "M1", "cusip": "BBB", "name_of_issuer": "Stock BBB", "change_type": "add",
             "value_delta_usd": 20, "weight_delta_pct": 1},
        ]
        return pd.DataFrame(rows)

    def test_columns(self, changes):
        result = top_buys(changes)
        assert list(result.columns) == [
            "cusip", "name_of_issuer", "n_new_buyers", "total_value_added_usd", "avg_weight_change_pct",
        ]

    def test_n_new_buyers_counts_only_new_buy_rows(self, changes):
        result = top_buys(changes).set_index("cusip")
        assert result.loc["AAA", "n_new_buyers"] == 2
        assert result.loc["BBB", "n_new_buyers"] == 0

    def test_total_value_added_pools_new_buy_and_add(self, changes):
        result = top_buys(changes).set_index("cusip")
        assert result.loc["AAA", "total_value_added_usd"] == 350  # 100+200+50
        assert result.loc["BBB", "total_value_added_usd"] == 20

    def test_avg_weight_change_pools_new_buy_and_add(self, changes):
        result = top_buys(changes).set_index("cusip")
        assert result.loc["AAA", "avg_weight_change_pct"] == pytest.approx((5 + 10 + 2) / 3)

    def test_sorted_by_new_buyers_then_value_added(self, changes):
        result = top_buys(changes)
        assert list(result["cusip"]) == ["AAA", "BBB"]

    def test_sells_only_input_returns_empty(self):
        changes = pd.DataFrame([
            {"cik": "M1", "cusip": "X", "name_of_issuer": "X", "change_type": "sold_out",
             "value_delta_usd": -10, "weight_delta_pct": -1},
        ])
        result = top_buys(changes)
        assert result.empty


class TestTopSells:
    @pytest.fixture
    def changes(self) -> pd.DataFrame:
        # CCC: sold_out by M1 (-100), sold_out by M2 (-150)
        # DDD: trim only by M1 (-30)
        rows = [
            {"cik": "M1", "cusip": "CCC", "name_of_issuer": "Stock CCC", "change_type": "sold_out",
             "value_delta_usd": -100, "weight_delta_pct": -8},
            {"cik": "M2", "cusip": "CCC", "name_of_issuer": "Stock CCC", "change_type": "sold_out",
             "value_delta_usd": -150, "weight_delta_pct": -12},
            {"cik": "M1", "cusip": "DDD", "name_of_issuer": "Stock DDD", "change_type": "trim",
             "value_delta_usd": -30, "weight_delta_pct": -3},
        ]
        return pd.DataFrame(rows)

    def test_columns(self, changes):
        result = top_sells(changes)
        assert list(result.columns) == ["cusip", "name_of_issuer", "n_sold_out", "total_value_reduced_usd"]

    def test_n_sold_out_counts_only_sold_out_rows(self, changes):
        result = top_sells(changes).set_index("cusip")
        assert result.loc["CCC", "n_sold_out"] == 2
        assert result.loc["DDD", "n_sold_out"] == 0

    def test_total_value_reduced_is_positive_magnitude(self, changes):
        result = top_sells(changes).set_index("cusip")
        assert result.loc["CCC", "total_value_reduced_usd"] == 250
        assert result.loc["DDD", "total_value_reduced_usd"] == 30

    def test_sorted_by_sold_out_then_value_reduced(self, changes):
        result = top_sells(changes)
        assert list(result["cusip"]) == ["CCC", "DDD"]

    def test_buys_only_input_returns_empty(self):
        changes = pd.DataFrame([
            {"cik": "M1", "cusip": "X", "name_of_issuer": "X", "change_type": "new_buy",
             "value_delta_usd": 10, "weight_delta_pct": 1},
        ])
        result = top_sells(changes)
        assert result.empty
