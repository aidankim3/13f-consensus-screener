"""Print "true"/"false": whether the current scheduled tick (invoked by
.github/workflows/refresh_data.yml every 3 hours) should actually run a
data refresh.

Normal cadence is 2x/day; during the 3 days leading up to and including
each 13F 45-day deadline, every tick runs (see src/edgar/deadlines.py).

Usage:
    python scripts/should_refresh.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.edgar.deadlines import should_refresh_now

if __name__ == "__main__":
    now = datetime.now(timezone.utc)
    print("true" if should_refresh_now(now) else "false")
