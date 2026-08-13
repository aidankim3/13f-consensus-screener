import pandas as pd
import pytest

from src.analytics.overlap import jaccard_similarity, pairwise_overlap, similarity_matrix


def _row(cusip, name, shares, change_type):
    return {"cusip": cusip, "name_of_issuer": name, "curr_shares": shares, "change_type": change_type}


class TestPairwiseOverlap:
    @pytest.fixture
    def portfolio_a(self) -> pd.DataFrame:
        return pd.DataFrame([
            _row("P", "Stock P", 10, "add"),        # common w/ B, both non-opposite
            _row("Q", "Stock Q", 5, "unchanged"),    # only_a (B sold out)
            _row("R", "Stock R", 0, "sold_out"),     # neither holds -> excluded entirely
            _row("S", "Stock S", 3, "new_buy"),      # common w/ B, opposite (A buys, B trims)
        ])

    @pytest.fixture
    def portfolio_b(self) -> pd.DataFrame:
        return pd.DataFrame([
            _row("P", "Stock P", 8, "unchanged"),
            _row("Q", "Stock Q", 0, "sold_out"),
            _row("T", "Stock T", 2, "new_buy"),      # only_b
            _row("S", "Stock S", 1, "trim"),
        ])

    def test_columns(self, portfolio_a, portfolio_b):
        result = pairwise_overlap(portfolio_a, portfolio_b)
        assert list(result.columns) == [
            "cusip", "name_of_issuer", "a_change_type", "b_change_type",
            "a_shares", "b_shares", "relationship", "opposite_trade",
        ]

    def test_relationship_classification(self, portfolio_a, portfolio_b):
        result = pairwise_overlap(portfolio_a, portfolio_b).set_index("cusip")
        assert result.loc["P", "relationship"] == "common"
        assert result.loc["Q", "relationship"] == "only_a"
        assert result.loc["T", "relationship"] == "only_b"
        assert result.loc["S", "relationship"] == "common"

    def test_neither_holds_is_excluded(self, portfolio_a, portfolio_b):
        result = pairwise_overlap(portfolio_a, portfolio_b)
        assert "R" not in set(result["cusip"])  # both fully sold out -> nothing to compare

    def test_opposite_trade_flagged_when_one_buys_other_sells(self, portfolio_a, portfolio_b):
        result = pairwise_overlap(portfolio_a, portfolio_b).set_index("cusip")
        assert result.loc["S", "opposite_trade"] == True  # A new_buy, B trim
        assert result.loc["P", "opposite_trade"] == False  # A add, B unchanged -- not a sell

    def test_only_a_with_sold_out_other_side_not_opposite(self, portfolio_a, portfolio_b):
        # Q: A holds (unchanged, not "buying"), B sold_out (selling) --
        # not flagged opposite since A wasn't actively buying.
        result = pairwise_overlap(portfolio_a, portfolio_b).set_index("cusip")
        assert result.loc["Q", "opposite_trade"] == False

    def test_cusip_unknown_to_one_side_has_nan_change_type(self, portfolio_a, portfolio_b):
        result = pairwise_overlap(portfolio_a, portfolio_b).set_index("cusip")
        assert pd.isna(result.loc["T", "a_change_type"])  # A never touched T at all

    def test_both_empty_returns_empty(self):
        empty = pd.DataFrame(columns=["cusip", "name_of_issuer", "curr_shares", "change_type"])
        result = pairwise_overlap(empty, empty)
        assert result.empty


class TestJaccardSimilarity:
    def test_partial_overlap(self):
        a = pd.DataFrame({"cusip": ["P", "Q", "R"]})
        b = pd.DataFrame({"cusip": ["P", "S"]})
        # intersection={P} (1), union={P,Q,R,S} (4) -> 0.25
        assert jaccard_similarity(a, b) == pytest.approx(0.25)

    def test_identical_sets(self):
        a = pd.DataFrame({"cusip": ["P", "Q"]})
        b = pd.DataFrame({"cusip": ["Q", "P"]})
        assert jaccard_similarity(a, b) == pytest.approx(1.0)

    def test_disjoint_sets(self):
        a = pd.DataFrame({"cusip": ["P"]})
        b = pd.DataFrame({"cusip": ["Q"]})
        assert jaccard_similarity(a, b) == pytest.approx(0.0)

    def test_both_empty_is_zero_not_nan(self):
        empty = pd.DataFrame({"cusip": []})
        assert jaccard_similarity(empty, empty) == 0.0

    def test_duplicate_cusips_within_one_side_ignored(self):
        # e.g. a manager reporting the same cusip across split sub-account
        # rows shouldn't affect the SET-based similarity calculation.
        a = pd.DataFrame({"cusip": ["P", "P", "Q"]})
        b = pd.DataFrame({"cusip": ["P"]})
        assert jaccard_similarity(a, b) == pytest.approx(1 / 2)


class TestSimilarityMatrix:
    @pytest.fixture
    def holdings(self) -> pd.DataFrame:
        rows = [
            {"cik": "A", "manager_name": "Manager A", "cusip": "P"},
            {"cik": "A", "manager_name": "Manager A", "cusip": "Q"},
            {"cik": "B", "manager_name": "Manager B", "cusip": "P"},
            {"cik": "B", "manager_name": "Manager B", "cusip": "R"},
            {"cik": "C", "manager_name": "Manager C", "cusip": "Z"},
        ]
        return pd.DataFrame(rows)

    def test_diagonal_is_100(self, holdings):
        matrix = similarity_matrix(holdings)
        for name in ["Manager A", "Manager B", "Manager C"]:
            assert matrix.loc[name, name] == pytest.approx(100.0)

    def test_symmetric(self, holdings):
        matrix = similarity_matrix(holdings)
        assert matrix.loc["Manager A", "Manager B"] == pytest.approx(matrix.loc["Manager B", "Manager A"])

    def test_known_pairwise_value(self, holdings):
        matrix = similarity_matrix(holdings)
        # A={P,Q}, B={P,R} -> intersection={P}(1), union={P,Q,R}(3) -> 33.33%
        assert matrix.loc["Manager A", "Manager B"] == pytest.approx(100 / 3)

    def test_no_overlap_is_zero(self, holdings):
        matrix = similarity_matrix(holdings)
        # A={P,Q}, C={Z} -> no overlap
        assert matrix.loc["Manager A", "Manager C"] == pytest.approx(0.0)

    def test_shape_matches_manager_count(self, holdings):
        matrix = similarity_matrix(holdings)
        assert matrix.shape == (3, 3)
