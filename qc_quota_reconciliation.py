"""
QC for reconcile_odds_quota.py (incident 2026-10-24 #4) + the QuotaRecorder ledger.

Proves:
  - reconciliation attributes credits by sport/endpoint family from ORDERED cumulative `remaining`
    drops -- and gives the right answer EVEN WHEN x-requests-last is 0/absent (the NBA case);
  - it FAILS, not passes, when any portion of the account delta is unattributed (a ledger gap or a
    tail of calls the ledger never saw);
  - QuotaRecorder.write_ledger appends one usable row per recorded call.
Offline: synthetic ledger rows + a temp ledger file.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import reconcile_odds_quota as rec
from services.odds_quota import QuotaRecorder


def _row(sport, fam, used, remaining, last=None):
    return {"ts": "2026-10-24T03:00:00+00:00", "sport": sport, "endpoint_family": fam,
            "seq": 0, "last": last, "used": used, "remaining": remaining}


def main() -> int:
    f = []

    # 1. Clean full attribution. baseline 100000. Three calls spend 3 (NFL lines), 97 (NFL props),
    #    1 (futures) = 101 -> final 99899. x-requests-last deliberately None to prove we don't use it.
    rows = [
        _row("americanfootball_nfl", "game_lines", used=101, remaining=99997, last=None),
        _row("americanfootball_nfl", "player_props", used=198, remaining=99900, last=None),
        _row("(all)", "futures", used=199, remaining=99899, last=None),
    ]
    r = rec.reconcile(rows, baseline_remaining=100000, final_remaining=99899)
    if not r["ok"]:
        f.append(f"clean case should reconcile ok; problems={r['problems']}")
    if r["attributed_total"] != 101 or r["unattributed"] != 0:
        f.append(f"clean case attribution wrong: attributed={r['attributed_total']}, unattributed={r['unattributed']}")
    # NFL props got the 97-credit drop even though x-requests-last was None -> cumulative method works.
    if r["by_key"].get("americanfootball_nfl | player_props") != 97:
        f.append(f"NFL props should be 97 via cumulative delta; got {r['by_key']}")

    # 2. The NBA zero-cost probe: remaining does NOT move (9 responses, 0 credits) -> attributed 0 for
    #    NBA, and the window still reconciles because nothing was spent.
    rows2 = [_row("basketball_nba", "player_props", used=199, remaining=99899, last=0)]
    r2 = rec.reconcile(rows2, baseline_remaining=99899, final_remaining=99899)
    if not r2["ok"] or r2["account_delta"] != 0 or r2["attributed_total"] != 0:
        f.append(f"NBA zero-cost window should reconcile to 0 spend; got {r2}")

    # 3. Unattributed tail: account dropped 1040 but the ledger is EMPTY -> must FAIL with 1040 unattributed
    #    (this is the historical 100000->98960 window with no ledger).
    r3 = rec.reconcile([], baseline_remaining=100000, final_remaining=98960)
    if r3["ok"]:
        f.append("empty ledger over a 1040 delta must FAIL, not pass")
    if r3["unattributed"] != 1040:
        f.append(f"empty-ledger unattributed should be 1040; got {r3['unattributed']}")

    # 4. Gap: a ledger call missing its remaining header -> cannot attribute -> FAIL.
    rows4 = [_row("x", "game_lines", used=5, remaining=None, last=3)]
    r4 = rec.reconcile(rows4, baseline_remaining=100000, final_remaining=99997)
    if r4["ok"]:
        f.append("a ledger call with no remaining header must FAIL reconciliation")

    # 5. QuotaRecorder.write_ledger appends usable rows.
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        q = QuotaRecorder()
        q.record({"x-requests-last": "3", "x-requests-used": "44", "x-requests-remaining": "99956"})
        q.record({"x-requests-last": "0", "x-requests-used": "44", "x-requests-remaining": "99956"})
        n = q.write_ledger("game_lines /events + /odds", "americanfootball_nfl", base, markets=["h2h"])
        if n != 2:
            f.append(f"write_ledger should append 2 rows, got {n}")
        ledger = (base / "data/tracking/odds_quota_ledger.jsonl").read_text(encoding="utf-8").splitlines()
        if len(ledger) != 2 or json.loads(ledger[0])["remaining"] != 99956:
            f.append("ledger rows not written with cumulative remaining")

    print("=" * 64)
    print("QC: ODDS QUOTA RECONCILIATION")
    print("=" * 64)
    if f:
        for x in f:
            print(f"[FAIL] {x}")
        return 1
    print("[OK] cumulative-delta attribution works without x-requests-last; unattributed spend FAILS.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
