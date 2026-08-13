"""CLI job: check for new 13F and 13D/13G filings across tracked
investors, and log/alert on anything new since the last run.

13F (quarterly, filed up to 45 days after quarter-end) and 13D/13G
(near-real-time activist / 5%+-ownership disclosures, filed within days
of the triggering event) are checked as two SEPARATE feeds per investor,
since they have very different disclosure cadences and this job is meant
to be run frequently (e.g. daily) to catch the fast-moving 13D/13G feed.

Usage:
    .venv\\Scripts\\python.exe -m src.jobs.refresh
"""
from __future__ import annotations

import logging
import os
import smtplib
import time
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import yaml

from src.edgar.client import EdgarClient, list_13f_filings, list_activist_filings
from src.edgar.seen_store import filter_new_filings

ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = ROOT / "config" / "investors.yaml"
SEEN_DB_PATH = ROOT / "data" / "seen_filings.db"
LOG_DIR = ROOT / "data" / "logs"

USER_AGENT = "Aidan Kim aidankim3@gmail.com"

logger = logging.getLogger(__name__)


@dataclass
class NewFilingAlert:
    manager_name: str
    cik: str
    feed: str  # "13F" or "13D/13G"
    filings: list[dict[str, Any]] = field(default_factory=list)


def load_investors(config_path: Path = CONFIG_PATH) -> list[dict]:
    return yaml.safe_load(config_path.read_text(encoding="utf-8"))["investors"]


def check_investor(
    client: EdgarClient, investor: dict, db_path: Path = SEEN_DB_PATH
) -> list[NewFilingAlert]:
    """Check one investor's 13F and 13D/13G feeds for filings not seen on
    a prior run. Returns one alert per feed that has new filings (0, 1,
    or 2 alerts). The very first run for a feed just establishes a
    baseline silently -- see seen_store.filter_new_filings.
    """
    submissions = client.get_submissions(investor["cik"])
    alerts = []

    for feed_name, lister in [("13F", list_13f_filings), ("13D/13G", list_activist_filings)]:
        filings = lister(submissions)
        tracking_key = f"{investor['cik']}:{feed_name}"
        new_filings, is_first_run = filter_new_filings(tracking_key, filings, db_path)

        if is_first_run:
            logger.info(
                "%s (%s): baseline established with %d existing filing(s), nothing to alert on",
                investor["name"],
                feed_name,
                len(filings),
            )
            continue

        if new_filings:
            alerts.append(
                NewFilingAlert(
                    manager_name=investor["name"],
                    cik=investor["cik"],
                    feed=feed_name,
                    filings=new_filings,
                )
            )

    return alerts


def format_alert_text(alerts: list[NewFilingAlert]) -> str:
    lines = ["=== 13F 컨센서스 스크리너 — 신규 공시 알림 ===", f"확인 시각: {time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
    if not alerts:
        lines.append("새 공시 없음.")
        return "\n".join(lines)

    for alert in alerts:
        lines.append(f"[{alert.feed}] {alert.manager_name} (CIK {alert.cik}) — {len(alert.filings)}건")
        for f in alert.filings:
            lines.append(
                f"  - {f['form']} | 제출일={f['filingDate']} | 기준일={f['reportDate']} "
                f"| accession={f['accessionNumber']}"
            )
        lines.append("")
    return "\n".join(lines)


def write_log(text: str, log_dir: Path = LOG_DIR) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"refresh_{timestamp}.log"
    log_path.write_text(text, encoding="utf-8")
    return log_path


def maybe_send_email(text: str, has_alerts: bool) -> None:
    """Send an email only if both SMTP_HOST and ALERT_EMAIL_TO are set in
    the environment AND there are real alerts to report. Email is
    entirely opt-in -- missing config is not an error, just a no-op, and
    a send failure is logged rather than raised (a broken mail relay
    should never fail the whole refresh run).
    """
    if not has_alerts:
        return
    host = os.environ.get("SMTP_HOST")
    to_addr = os.environ.get("ALERT_EMAIL_TO")
    if not host or not to_addr:
        logger.info("SMTP_HOST/ALERT_EMAIL_TO not set — skipping email (file/console log only)")
        return

    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    from_addr = os.environ.get("ALERT_EMAIL_FROM", user or "13f-screener@localhost")

    msg = EmailMessage()
    msg["Subject"] = "13F 컨센서스 스크리너 — 신규 공시 알림"
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(text)

    try:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls()
            if user and password:
                server.login(user, password)
            server.send_message(msg)
        logger.info("alert email sent to %s", to_addr)
    except Exception as exc:  # a mail relay hiccup must not fail the job
        logger.warning("failed to send alert email: %s", exc)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    client = EdgarClient(user_agent=USER_AGENT)
    investors = load_investors()

    all_alerts: list[NewFilingAlert] = []
    for investor in investors:
        try:
            all_alerts.extend(check_investor(client, investor))
        except Exception as exc:
            logger.error("failed to check %s (CIK %s): %s", investor["name"], investor["cik"], exc)

    text = format_alert_text(all_alerts)
    print(text)

    log_path = write_log(text)
    logger.info("log written to %s", log_path)

    maybe_send_email(text, has_alerts=bool(all_alerts))


if __name__ == "__main__":
    main()
