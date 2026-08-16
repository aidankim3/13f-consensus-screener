"""SEC EDGAR HTTP client.

Pure request/parsing helpers for talking to SEC EDGAR. No Streamlit
import here or anywhere under src/edgar — this module must stay usable
from a future non-Streamlit service (e.g. FastAPI) unchanged.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
SEC_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data/{cik_no_zeros}/{accession_no_dashes}"

# SEC's hard limit is 10 requests/second; default stays under it with margin.
DEFAULT_MAX_REQUESTS_PER_SECOND = 8.0

_13F_FORMS = {"13F-HR", "13F-HR/A"}

# EDGAR has used two different label conventions for the same form over
# the years -- "SC 13D"/"SC 13G" (older filings) and "SCHEDULE 13D"/
# "SCHEDULE 13G" (current, ~2025+). Confirmed on a real filer (Appaloosa
# LP, CIK 1656456) whose history contains both. Both are included so
# nothing is missed regardless of when a filing was made.
_13D_13G_FORMS = {
    "SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A",
    "SCHEDULE 13D", "SCHEDULE 13D/A", "SCHEDULE 13G", "SCHEDULE 13G/A",
}


class RateLimiter:
    """Thread-safe limiter that spaces out calls to at most N per second."""

    def __init__(self, max_per_second: float = DEFAULT_MAX_REQUESTS_PER_SECOND):
        if max_per_second <= 0:
            raise ValueError("max_per_second must be positive")
        self._min_interval = 1.0 / max_per_second
        self._lock = threading.Lock()
        self._last_call: Optional[float] = None

    def wait(self) -> None:
        """Block until it is safe to issue another request."""
        with self._lock:
            now = time.monotonic()
            if self._last_call is None:
                self._last_call = now
                return
            elapsed = now - self._last_call
            remaining = self._min_interval - elapsed
            if remaining > 0:
                time.sleep(remaining)
                self._last_call = now + remaining
            else:
                self._last_call = now


def build_headers(user_agent: str) -> dict[str, str]:
    """Build SEC-compliant request headers.

    SEC requires a descriptive User-Agent with a name and contact email,
    e.g. "Aidan Kim aidankim3@gmail.com". Requests without one are liable
    to be throttled or blocked at SEC's edge.
    """
    if not user_agent or "@" not in user_agent:
        raise ValueError(
            'user_agent must include a name and contact email, e.g. '
            '"Aidan Kim aidankim3@gmail.com"'
        )
    return {
        "User-Agent": user_agent,
        "Accept-Encoding": "gzip, deflate",
    }


def normalize_cik(cik: str | int) -> str:
    """Zero-pad a CIK to the 10-digit form SEC's JSON endpoints require."""
    raw = str(cik).strip()
    if not raw.isdigit():
        raise ValueError(f"CIK must be numeric, got: {cik!r}")
    return raw.zfill(10)


def filing_archive_dir_url(cik: str | int, accession_number: str) -> str:
    """Build the Archives directory URL for one filing.

    Unlike the JSON submissions endpoint, this path wants the CIK WITHOUT
    leading zeros and the accession number WITHOUT dashes.
    """
    cik_no_zeros = str(int(normalize_cik(cik)))
    accession_no_dashes = accession_number.replace("-", "")
    return SEC_ARCHIVES_URL.format(
        cik_no_zeros=cik_no_zeros, accession_no_dashes=accession_no_dashes
    )


@dataclass
class EdgarClient:
    """Thin, rate-limited SEC EDGAR client.

    Holds no Streamlit state; callers own caching/persistence decisions.
    """

    user_agent: str
    max_requests_per_second: float = DEFAULT_MAX_REQUESTS_PER_SECOND
    session: requests.Session = field(default_factory=requests.Session)
    _rate_limiter: RateLimiter = field(init=False, repr=False)
    _headers: dict[str, str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._headers = build_headers(self.user_agent)
        self._rate_limiter = RateLimiter(self.max_requests_per_second)

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        """Rate-limited GET with SEC-compliant headers."""
        self._rate_limiter.wait()
        logger.debug("GET %s", url)
        response = self.session.get(url, headers=self._headers, timeout=30, **kwargs)
        response.raise_for_status()
        return response

    def get_submissions(self, cik: str | int) -> dict[str, Any]:
        """Fetch the filer's submissions index (includes recent filings list)."""
        cik10 = normalize_cik(cik)
        url = SEC_SUBMISSIONS_URL.format(cik10=cik10)
        return self.get(url).json()

    def get_filing_index(self, cik: str | int, accession_number: str) -> dict[str, Any]:
        """Fetch the machine-readable directory listing for one filing."""
        url = f"{filing_archive_dir_url(cik, accession_number)}/index.json"
        return self.get(url).json()

    def get_filing_document(self, cik: str | int, accession_number: str, filename: str) -> str:
        """Fetch one document (by filename) from a filing's directory."""
        url = f"{filing_archive_dir_url(cik, accession_number)}/{filename}"
        return self.get(url).text


def list_filings(submissions: dict[str, Any], form_types: set[str]) -> list[dict[str, Any]]:
    """Extract filing metadata matching `form_types` from a submissions payload.

    Pure function — takes the dict returned by get_submissions() (or an
    equivalent fixture) and returns one record per matching filing, in
    the order SEC returned them (most recent first). This does not
    resolve amendments to their originals; that's a caller concern once
    report periods are known (see fetch.resolve_latest_filings for 13F).
    """
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    filings = []
    for i, form in enumerate(forms):
        if form not in form_types:
            continue
        filings.append(
            {
                "form": form,
                "filingDate": recent["filingDate"][i],
                "reportDate": recent["reportDate"][i],
                "accessionNumber": recent["accessionNumber"][i],
                "primaryDocument": recent["primaryDocument"][i],
            }
        )
    return filings


def list_13f_filings(submissions: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract 13F-HR / 13F-HR/A filing metadata from a submissions payload."""
    return list_filings(submissions, _13F_FORMS)


def list_recent_filings(submissions: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    """The most recent `limit` filings of ANY form type from a submissions
    payload, most recent first -- unlike list_filings/list_13f_filings,
    not restricted to a specific set of forms. SEC's own submissions.json
    already orders "recent" most-recent-first, so this is just a slice,
    not a sort. Powers a general "what has this filer submitted lately"
    activity feed (e.g. Home's "Superinvestor Portfolio Updates"), as
    opposed to the 13F-specific holdings pipeline.
    """
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    filing_dates = recent.get("filingDate", [])
    accession_numbers = recent.get("accessionNumber", [])
    n = min(limit, len(forms), len(filing_dates), len(accession_numbers))
    return [
        {"form": forms[i], "filingDate": filing_dates[i], "accessionNumber": accession_numbers[i]}
        for i in range(n)
    ]


def list_activist_filings(submissions: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract 13D/13G (+ amendments) filing metadata from a submissions
    payload.

    Unlike 13F (quarterly, up to 45 days after quarter-end), Schedule
    13D/13G filings are near-real-time disclosures: 13D is due within a
    few business days of crossing the 5%+ activist-intent threshold, 13G
    within 45 days of year-end for passive holders (sooner if crossing
    certain thresholds). Treated as a separate, faster-cadence feed —
    see src/jobs/refresh.py.
    """
    return list_filings(submissions, _13D_13G_FORMS)
