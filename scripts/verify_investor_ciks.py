"""One-off check: confirm each CIK in config/investors.yaml resolves to the
expected entity name on SEC EDGAR, and has at least one 13F-HR filing.

Run manually when editing config/investors.yaml:
    .venv\\Scripts\\python.exe scripts\\verify_investor_ciks.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.edgar.client import EdgarClient, list_13f_filings

USER_AGENT = "Aidan Kim aidankim3@gmail.com"


def main() -> None:
    config_path = Path(__file__).resolve().parent.parent / "config" / "investors.yaml"
    investors = yaml.safe_load(config_path.read_text(encoding="utf-8"))["investors"]

    client = EdgarClient(user_agent=USER_AGENT)

    for inv in investors:
        submissions = client.get_submissions(inv["cik"])
        actual_name = submissions.get("name", "<missing>")
        filings = list_13f_filings(submissions)
        latest = filings[0] if filings else None

        match = "OK" if actual_name.strip().lower().startswith(
            inv["entity"].split(",")[0].split(" LLC")[0].split(" L.P.")[0].strip().lower()
        ) else "MISMATCH"

        print(f"[{match}] {inv['name']} (CIK {inv['cik']})")
        print(f"    config entity : {inv['entity']}")
        print(f"    EDGAR name    : {actual_name}")
        print(f"    13F filings   : {len(filings)} found")
        if latest:
            print(
                f"    latest        : {latest['form']} filed {latest['filingDate']} "
                f"(period {latest['reportDate']})"
            )
        print()


if __name__ == "__main__":
    main()
