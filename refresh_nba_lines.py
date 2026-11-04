"""4-hourly NBA game-lines job (bk-nba-lines.timer, ops/bk-nba-lines.{service,timer}).

Why: NBA game lines refreshed once a day (bk-daily, 13:00 UTC) go past the 6h executable-price rule
(LIVE_LINES_MAX_AGE_HOURS, CLOCK A) for most of every evening, so customer surfaces withhold prices. A
4-hour cadence keeps a published slate inside 6h with ~2h headroom; the 6h boundary itself is unchanged.

This is NOT a second publisher. It calls the same entry as bk-daily's NBA step
(fetch_game_lines.main -> services.nba_lines_publisher.publish): shared kernel lock before any paid request,
the one event validation (game_lines_event_v1) and atomic three-file publish, the same receipts. One run
= one /odds call = 3 credits (h2h,spreads,totals x us). It never reuses (it IS the refresh); bk-daily
reuses this job's publish when it is <= REUSE_WINDOW_MINUTES old.

Exit codes (journal-visible, never "OK" on failure):
  0  UPDATED
  1  any failure (PROVIDER_ERROR / VALIDATION_FAILED / SCHEDULE_UNAVAILABLE / COST / PUBLISH)
  75 SKIPPED_LOCKED     another NBA lines publish held the lock; no request, nothing written
  76 LOCK_UNAVAILABLE   lock file could not be opened; no request, nothing written
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CALLER = "nba_lines_4h"
BOOKMAKERS = "draftkings,caesars,fanduel,betmgm"   # same books + window as refresh_nba_daily's lines step
DAYS = "5"


def build_args(extra=()) -> list[str]:
    return ["--sport", "basketball_nba", "--bookmakers", BOOKMAKERS, "--days", DAYS,
            "--caller", CALLER, *extra]


def main(argv=None) -> int:
    sys.path.insert(0, str(BASE_DIR))
    import fetch_game_lines
    print("=" * 60)
    print("BANKROLL KINGS - NBA GAME LINES (4-hourly)")
    print("=" * 60, flush=True)
    rc = int(fetch_game_lines.main(build_args(list(argv or []))))
    print(f"NBA lines job finished with exit {rc}"
          + (" (published)" if rc == 0 else " (NOT published; see the outcome line above)"), flush=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
