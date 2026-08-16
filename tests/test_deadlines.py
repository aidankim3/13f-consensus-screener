from datetime import date, datetime, timedelta

from src.edgar.deadlines import (
    is_within_elevated_window,
    should_refresh_now,
    thirteenf_deadlines_for_year,
)


class TestThirteenFDeadlinesForYear:
    def test_four_deadlines_returned_in_order(self):
        deadlines = thirteenf_deadlines_for_year(2026)
        assert len(deadlines) == 4
        assert deadlines == sorted(deadlines)

    def test_close_to_the_raw_45_day_dates_and_never_a_weekend(self):
        # Raw (pre-weekend-shift) dates are always Feb 14 / May 15 / Aug 14
        # / Nov 14 -- a shift only ever moves a date forward by 0-2 days.
        raw_dates = [date(2026, 2, 14), date(2026, 5, 15), date(2026, 8, 14), date(2026, 11, 14)]
        deadlines = thirteenf_deadlines_for_year(2026)
        for actual, raw in zip(deadlines, raw_dates):
            assert 0 <= (actual - raw).days <= 2
            assert actual.weekday() < 5  # Mon-Fri

    def test_q4_deadline_belongs_to_the_following_year(self):
        # Q4 (Oct-Dec) of year Y is due ~Feb of year Y+1.
        deadlines_2027 = thirteenf_deadlines_for_year(2027)
        assert deadlines_2027[0].month == 2
        assert deadlines_2027[0].year == 2027


class TestIsWithinElevatedWindow:
    def test_true_on_deadline_day(self):
        deadline = thirteenf_deadlines_for_year(2026)[1]
        assert is_within_elevated_window(deadline) is True

    def test_true_three_days_before(self):
        deadline = thirteenf_deadlines_for_year(2026)[1]
        assert is_within_elevated_window(deadline - timedelta(days=3)) is True

    def test_false_four_days_before(self):
        deadline = thirteenf_deadlines_for_year(2026)[1]
        assert is_within_elevated_window(deadline - timedelta(days=4)) is False

    def test_false_the_day_after_deadline(self):
        deadline = thirteenf_deadlines_for_year(2026)[1]
        assert is_within_elevated_window(deadline + timedelta(days=1)) is False

    def test_false_far_from_any_deadline(self):
        assert is_within_elevated_window(date(2026, 7, 1)) is False


class TestShouldRefreshNow:
    def test_elevated_window_always_refreshes(self):
        deadline = thirteenf_deadlines_for_year(2026)[1]
        # An hour that would normally be skipped (not in {0, 12}).
        now = datetime(deadline.year, deadline.month, deadline.day, 15, 0)
        assert should_refresh_now(now) is True

    def test_normal_cadence_only_refreshes_at_designated_hours(self):
        now_offhour = datetime(2026, 7, 1, 15, 0)
        now_onhour = datetime(2026, 7, 1, 12, 0)
        assert should_refresh_now(now_offhour) is False
        assert should_refresh_now(now_onhour) is True

    def test_custom_cadence_hours_respected(self):
        now = datetime(2026, 7, 1, 6, 0)
        assert should_refresh_now(now, normal_cadence_hours={6, 18}) is True
