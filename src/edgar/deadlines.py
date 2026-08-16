"""13F filing-deadline calendar and refresh-cadence gating.

Pure date logic (no Streamlit, no network) -- powers the scheduled
GitHub Actions data-refresh workflow (scripts/should_refresh.py): refresh
twice a day normally, but every tick (every 3 hours) during the 3 days
leading up to and including each 13F 45-day deadline, since that's when
investors disproportionately file right before the cutoff.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

ELEVATED_WINDOW_DAYS = 3
NORMAL_CADENCE_HOURS_UTC = {0, 12}


def _shift_to_business_day(d: date) -> date:
    """SEC rule: a deadline landing on a weekend rolls to the next Monday.

    Federal holidays are not modeled -- the elevated window's 3-day
    buffer already absorbs the day or two of imprecision that could
    introduce.
    """
    if d.weekday() == 5:  # Saturday
        return d + timedelta(days=2)
    if d.weekday() == 6:  # Sunday
        return d + timedelta(days=1)
    return d


def thirteenf_deadlines_for_year(year: int) -> list[date]:
    """The four 13F filing deadlines (45 days after each calendar quarter
    end) that land in `year` -- the previous year's Q4 deadline (mid-Feb)
    plus this year's own Q1/Q2/Q3 deadlines (mid-May/mid-Aug/mid-Nov).

    The raw (pre-weekend-shift) dates are always Feb 14 / May 15 / Aug 14
    / Nov 14 -- calendar arithmetic 45 days past a quarter end lands on
    the same date every year regardless of leap years, since the
    intervening month (Jan/Apr/Jul/Oct) always has a fixed length.
    """
    raw = [
        date(year - 1, 12, 31) + timedelta(days=45),
        date(year, 3, 31) + timedelta(days=45),
        date(year, 6, 30) + timedelta(days=45),
        date(year, 9, 30) + timedelta(days=45),
    ]
    return sorted(_shift_to_business_day(d) for d in raw)


def is_within_elevated_window(today: date) -> bool:
    """True if `today` is within [deadline - 3 days, deadline] for any
    13F quarterly deadline.
    """
    candidates = [
        d
        for y in (today.year - 1, today.year, today.year + 1)
        for d in thirteenf_deadlines_for_year(y)
    ]
    return any(
        deadline - timedelta(days=ELEVATED_WINDOW_DAYS) <= today <= deadline
        for deadline in candidates
    )


def should_refresh_now(now: datetime, normal_cadence_hours: set[int] = NORMAL_CADENCE_HOURS_UTC) -> bool:
    """Whether a scheduled tick at `now` (expected to be UTC) should
    trigger a real data refresh: always during the elevated window,
    otherwise only at the designated normal-cadence hours.
    """
    if is_within_elevated_window(now.date()):
        return True
    return now.hour in normal_cadence_hours
