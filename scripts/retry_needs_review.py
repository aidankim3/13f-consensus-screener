"""Retry the investors from find_investor_ciks.py's "needs review" list,
either because of transient SEC 503/timeout errors, or because the
extracted search term needs adjusting (e.g. brand name != filer name).
"""
from __future__ import annotations

import time
from pathlib import Path

import yaml

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.find_investor_ciks import (
    HEADERS, SLEEP, company_search_ciks, get_submission, latest_13f_date, score_candidate,
)

# (dataroma_display, retry_search_term)
RETRIES = [
    ("Bryan Lawrence - Oakcliff Capital", "Oakcliff Capital"),
    ("Mohnish Pabrai - Pabrai Investments", "Pabrai"),
    ("Christopher Davis - Davis Advisors", "Davis Selected"),
    ("Torray Funds", "Torray"),
    ("William Von Mueffling - Cantillon Capital Management", "Cantillon Capital Management"),
    ("Guy Spier - Aquamarine Capital", "Aquamarine"),
    ("Carl Icahn - Icahn Capital Management", "Icahn"),
    ("Bill Nygren - Oakmark Funds", "Harris Associates"),
    ("Bill & Melinda Gates Foundation Trust", "Gates Foundation"),
    ("Christopher Bloomstran - Semper Augustus", "Semper Augustus"),
    ("Valley Forge Capital Management", "Valley Forge Capital"),
    ("Leon Cooperman", "Omega Advisors"),
    ("Arnold Van Den Berg - Century Management", "Century Management"),
    ("Bill Miller - Miller Value Partners", "Miller Value Partners"),
    ("Triple Frond Partners", "Triple Frond"),
    ("Ruane Cunniff LP", "Ruane Cunniff"),
    ("Dodge & Cox Funds", "Dodge & Cox"),
    ("Mairs & Power Funds", "Mairs Power"),
    ("Muhlenkamp", "Muhlenkamp"),
]


def main() -> None:
    results = []
    for i, (display, term) in enumerate(RETRIES):
        time.sleep(SLEEP * 2)
        try:
            ciks = company_search_ciks(term)
        except Exception as exc:
            print(f"[{i+1}/{len(RETRIES)}] {display} (term={term!r}): FAILED AGAIN ({exc})", file=sys.stderr)
            results.append({"dataroma": display, "term": term, "reason": f"failed: {exc}"})
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
                {"cik": cik10, "name": name, "last_13f": last_13f, "score": score_candidate(term, name, last_13f)}
            )
        candidates.sort(key=lambda c: c["score"], reverse=True)

        print(f"[{i+1}/{len(RETRIES)}] {display}  (retry term: {term!r})", file=sys.stderr)
        for c in candidates[:4]:
            print(f"    {c['score']:3d}  CIK {c['cik']}  {c['name']!r}  last_13f={c['last_13f']}", file=sys.stderr)

        results.append({"dataroma": display, "term": term, "candidates": candidates[:4]})

    out_path = Path(__file__).resolve().parent.parent / "data" / "cik_retry_results.yaml"
    out_path.write_text(yaml.safe_dump(results, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"\nWritten to {out_path}")


if __name__ == "__main__":
    main()
