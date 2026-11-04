"""NBA market orchestrator: ONE sequential entrypoint for NBA lines then props (v5 owner decision 1).

Proposed unit: ops/bk-nba-market-refresh.{service,timer} (00/4:15 UTC, Persistent=false) -- NOT installed;
see the TIMER-ENABLEMENT BLOCKER in the unit headers and docs/game_lines_event_contract.md.

State machine (services/nba_market.run_market_refresh):
  L  ensure_nba_lines   UPDATED / REUSED_FRESH / REUSED_FRESH_AFTER_LOCK -> P
                        anything else (SKIPPED_LOCKED 75, LOCK_UNAVAILABLE 76, NO_FRESH_AFTER_LOCK,
                        SCHEDULE_UNAVAILABLE, PROVIDER_ERROR, VALIDATION_FAILED, timeout)
                        -> props NOT attempted (SKIPPED_BLOCKED_BY_LINES, zero props requests); exit = lines exit
  P  ensure_nba_props   benign (UPDATED / REUSED_* / NO_MARKETS_POSTED / NO_ACTIVE_EVENTS) -> exit 0
                        alerting -> exit = props exit (non-zero)
  R  ONE structured receipt for both stages, written atomically to
     <runtime root>/nba_market/last_nba_market_refresh.json on every path.

The stages are the SAME ensure functions bk-daily's NBA steps call (canonical command, reuse-under-lock,
--no-fetch-after-lock, timeouts from services/nba_market_budget.py), so the orchestrator and bk-daily never
make a duplicate paid request or a duplicate write: whichever gets a publisher lock second reuses the
receipt-verified publish, or fails honestly (never OK) if the holder failed.

Exit codes are never masked: 0 = both stages benign; 75 / 76 / 1 / 124 = the first failing stage's exit.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="NBA market orchestrator: lines, then props, one receipt")
    parser.add_argument("--caller", default=None, help="recorded in every receipt (default nba_market_4h)")
    args = parser.parse_args(argv)
    os.chdir(BASE_DIR)   # stage commands are relative to the checkout
    sys.path.insert(0, str(BASE_DIR))
    from services import nba_market
    print("=" * 60)
    print("BANKROLL KINGS - NBA MARKET REFRESH (lines -> props)")
    print("=" * 60, flush=True)
    rc, receipt = nba_market.run_market_refresh(base_dir=BASE_DIR,
                                                caller=args.caller or nba_market.ORCHESTRATOR_CALLER)
    for st in receipt["stages"]:
        print(f"[{st['outcome']}] {st['stage']} ran={st['ran']} exit={st['exit_code']} seconds={st['seconds']} "
              f"credits={json.dumps(st['credits'].get('x_requests_last_sum'))}: {st['detail']}", flush=True)
    print(f"NBA market refresh result={receipt['result']} exit={rc} receipt={receipt['receipt_path']}", flush=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
