"""One-off script: given a list of investor display names (e.g. scraped
from Dataroma's superinvestor list), find and score candidate SEC CIKs
via EDGAR company search + submissions history.

This does NOT write to config/investors.yaml directly -- per project
convention, a name-based CIK guess is never trusted blindly. It prints a
report: high-confidence matches (recent 13F-HR activity + close name
match) vs. ones that need manual review, plus a ready-to-paste YAML
block for the high-confidence ones only.

Usage:
    ..\\.venv\\Scripts\\python.exe scripts\\find_investor_ciks.py
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import requests
import yaml

USER_AGENT = "Aidan Kim aidankim3@gmail.com"
HEADERS = {"User-Agent": USER_AGENT}
SLEEP = 0.15  # ~6-7 req/sec, under SEC's 10/sec limit

# (dataroma_code, dataroma_display_name) -- "Person - Firm" or just "Firm"
DATAROMA_ENTRIES = [
    ("OCL", "Bryan Lawrence - Oakcliff Capital"),
    ("PI", "Mohnish Pabrai - Pabrai Investments"),
    ("TF", "Nelson Peltz - Trian Fund Management"),
    ("WIM", "Wallace Weitz - Weitz Investment Management"),
    ("TA", "Third Avenue Management"),
    ("SSHFX", "Harry Burn - Sound Shore"),
    ("ca", "Francis Chou - Chou Associates"),
    ("AKO", "AKO Capital"),
    ("YAM", "Yacktman Asset Management"),
    ("DAV", "Christopher Davis - Davis Advisors"),
    ("VVP", "Vulcan Value Partners"),
    ("TB", "Tweedy Browne"),
    ("PIM", "Richard Pzena - Pzena Investment Management"),
    ("JIM", "Jensen Investment Management"),
    ("CHE", "Steven Check - Check Capital Management"),
    ("FE", "First Eagle Investment Management"),
    ("pcm", "Polen Capital Management"),
    ("MKL", "Thomas Gayner - Markel Group"),
    ("T", "Torray Funds"),
    ("cc", "William Von Mueffling - Cantillon Capital Management"),
    ("GA", "Greenhaven Associates"),
    ("EC", "John Armitage - Egerton Capital"),
    ("MAVFX", "David Katz - Matrix Asset Advisors"),
    ("LT", "Lindsell Train"),
    ("aq", "Guy Spier - Aquamarine Capital"),
    ("oc", "Howard Marks - Oaktree Capital Management"),
    ("HH", "Duan Yongping - H&H International Investment"),
    ("ABI", "Abrams Bison Investments"),
    ("mc", "Lee Ainslie - Maverick Capital"),
    ("vg", "Viking Global Investors"),
    ("VA", "ValueAct Capital"),
    ("HC", "Li Lu - Himalaya Capital Management"),
    ("GLRE", "David Einhorn - Greenlight Capital"),
    ("ic", "Carl Icahn - Icahn Capital Management"),
    ("fairx", "Bruce Berkowitz - Fairholme Capital"),
    ("HA", "Bill Nygren - Oakmark Funds"),
    ("GFT", "Bill & Melinda Gates Foundation Trust"),
    ("psc", "Bill Ackman - Pershing Square Capital Management"),
    ("PC", "Norbert Lou - Punch Card Management"),
    ("DCP", "Henry Ellenbogen - Durable Capital Partners"),
    ("SA", "Christopher Bloomstran - Semper Augustus"),
    ("SE", "Mason Hawkins - Southeastern Asset Management"),
    ("CCM", "Glenn Greenberg - Brave Warrior Advisors"),
    ("tp", "Daniel Loeb - Third Point"),
    ("BRK", "Warren Buffett - Berkshire Hathaway"),
    ("LPC", "Stephen Mandel - Lone Pine Capital"),
    ("AIM", "Alex Roepers - Atlantic Investment Management"),
    ("VFC", "Valley Forge Capital Management"),
    ("WP", "David Rolfe - Wedgewood Partners"),
    ("AM", "David Tepper - Appaloosa Management"),
    ("TGM", "Chase Coleman - Tiger Global Management"),
    ("ENG", "Glenn Welling - Engaged Capital"),
    ("CAS", "Clifford Sosin - CAS Investment Partners"),
    ("AP", "AltaRock Partners"),
    ("GC", "Francois Rochon - Giverny Capital"),
    ("oa", "Leon Cooperman"),
    ("VAN", "Arnold Van Den Berg - Century Management"),
    ("LMM", "Bill Miller - Miller Value Partners"),
    ("DA", "Pat Dorsey - Dorsey Asset Management"),
    ("tci", "Chris Hohn - TCI Fund Management"),
    ("FS", "Terry Smith - Fundsmith"),
    ("FFH", "Prem Watsa - Fairfax Financial Holdings"),
    ("HCM", "Hillman Capital Management"),
    ("TFP", "Triple Frond Partners"),
    ("MP", "Tom Bancroft - Makaira Partners"),
    ("RC", "Ruane Cunniff LP"),
    ("CM", "Greg Alexander - Conifer Management"),
    ("AI", "John Rogers - Ariel Investments"),
    ("abc", "David Abrams - Abrams Capital Management"),
    ("AC", "Chuck Akre - Akre Capital Management"),
    ("BAUPOST", "Seth Klarman - Baupost Group"),
    ("SP", "Dennis Hong - ShawSpring Partners"),
    ("CAU", "Sarah Ketterer - Causeway Capital Management"),
    ("DAC", "Dodge & Cox Funds"),
    ("PTNT", "Samantha McLemore - Patient Capital Management"),
    ("FPA", "First Pacific Advisors"),
    ("MPF", "Mairs & Power Funds"),
    ("GR", "Thomas Russo - Gardner Russo & Quinn"),
    ("RVC", "Robert Vinall - RV Capital GmbH"),
    ("GLC", "Josh Tarasoff - Greenlea Lane Capital"),
    ("KB", "Kahn Brothers Group"),
    ("MUHL", "Muhlenkamp"),
    ("SAM", "Michael Burry - Scion Asset Management"),
]

_SUFFIXES = {
    "LLC", "LP", "LLLP", "INC", "CORP", "CORPORATION", "CO", "COMPANY", "LTD",
    "LIMITED", "GROUP", "GRP", "MANAGEMENT", "MGMT", "CAPITAL", "PARTNERS",
    "PARTNER", "ADVISORS", "ADVISERS", "ASSOCIATES", "FUND", "FUNDS", "THE",
    "AND", "HOLDINGS", "INVESTMENTS", "INVESTMENT", "ASSET", "ASSETS", "GMBH",
    "TRUST", "INTERNATIONAL",
}


def normalize(name: str) -> str:
    name = name.upper()
    name = re.sub(r"[^A-Z0-9 ]", " ", name)
    tokens = [t for t in name.split() if t not in _SUFFIXES]
    return " ".join(tokens)


def search_term(display_name: str) -> str:
    if " - " in display_name:
        return display_name.split(" - ", 1)[1].strip()
    return display_name.strip()


def company_search_ciks(term: str) -> list[str]:
    url = "https://www.sec.gov/cgi-bin/browse-edgar"
    params = {
        "action": "getcompany", "company": term, "type": "13F-HR",
        "dateb": "", "owner": "include", "count": "40", "output": "atom",
    }
    r = requests.get(url, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return re.findall(r"<cik>(\d+)</cik>", r.text)


def get_submission(cik10: str) -> dict:
    url = f"https://data.sec.gov/submissions/CIK{cik10}.json"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def latest_13f_date(sub: dict) -> str | None:
    """Most recent filing date among ACTUAL holdings reports (13F-HR /
    13F-HR/A) only.

    Deliberately excludes 13F-NT ("notice") filings, which some entities
    in a manager group file on their own CIK to say "see a related filer
    for the real holdings" -- they contain no position data at all. Two
    real, confirmed traps from this exact mistake (matching on any
    form.startswith("13F")): Nelson Peltz/Trian Fund Management GP, LLC
    and Carl Icahn/Icahn Capital LP both file 13F-NT under their most
    "obvious"-sounding CIK, while a same-group sibling CIK (Trian Fund
    Management, L.P.; Icahn Carl C) files the real 13F-HR. Also seen with
    ValueAct Capital Management, L.P., which switched entirely to 13F-NT
    in 2008 while ValueAct Holdings, L.P. kept filing 13F-HR.
    """
    recent = sub.get("filings", {}).get("recent", {})
    for form, date in zip(recent.get("form", []), recent.get("filingDate", [])):
        if form in ("13F-HR", "13F-HR/A"):
            return date
    return None


def score_candidate(term: str, name: str, last_13f: str | None) -> int:
    s = 0
    if last_13f and last_13f >= "2024-01-01":
        s += 10
    elif last_13f:
        s += 3
    n_norm, t_norm = normalize(name), normalize(term)
    if n_norm == t_norm:
        s += 8
    elif t_norm and (t_norm in n_norm or n_norm in t_norm):
        s += 4
    return s


def main() -> None:
    high_confidence = []
    needs_review = []

    for i, (code, display) in enumerate(DATAROMA_ENTRIES):
        term = search_term(display)
        time.sleep(SLEEP)
        try:
            ciks = company_search_ciks(term)
        except Exception as exc:
            needs_review.append({"dataroma": display, "reason": f"search failed: {exc}"})
            print(f"[{i+1}/{len(DATAROMA_ENTRIES)}] {display}: SEARCH FAILED ({exc})", file=sys.stderr)
            continue

        candidates = []
        for cik in ciks[:6]:
            cik10 = cik.zfill(10)
            time.sleep(SLEEP)
            try:
                sub = get_submission(cik10)
            except Exception:
                continue
            name = sub.get("name", "")
            last_13f = latest_13f_date(sub)
            candidates.append(
                {
                    "cik": cik10,
                    "name": name,
                    "last_13f": last_13f,
                    "score": score_candidate(term, name, last_13f),
                }
            )

        candidates.sort(key=lambda c: c["score"], reverse=True)
        print(f"[{i+1}/{len(DATAROMA_ENTRIES)}] {display}  (search term: {term!r})", file=sys.stderr)
        for c in candidates[:3]:
            print(f"    {c['score']:3d}  CIK {c['cik']}  {c['name']!r}  last_13f={c['last_13f']}", file=sys.stderr)

        if not candidates:
            needs_review.append({"dataroma": display, "reason": "no candidates found"})
            continue

        best = candidates[0]
        second = candidates[1] if len(candidates) > 1 else None
        confident = best["score"] >= 14 and (second is None or best["score"] - second["score"] >= 4)

        entry = {
            "dataroma": display,
            "dataroma_code": code,
            "cik": best["cik"],
            "edgar_name": best["name"],
            "last_13f": best["last_13f"],
            "score": best["score"],
        }
        if confident:
            high_confidence.append(entry)
        else:
            entry["candidates"] = candidates[:3]
            needs_review.append(entry)

    out_dir = Path(__file__).resolve().parent.parent / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "cik_match_high_confidence.yaml").write_text(
        yaml.safe_dump(high_confidence, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    (out_dir / "cik_match_needs_review.yaml").write_text(
        yaml.safe_dump(needs_review, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    print(f"\n\n=== DONE: {len(high_confidence)} high-confidence, {len(needs_review)} need review ===")
    print("Written to data/cik_match_high_confidence.yaml and data/cik_match_needs_review.yaml")


if __name__ == "__main__":
    main()
