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

import contextlib
import io
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

    # 5b. Auto-baseline: a ledger-only probe window (NFL 97) with NO explicit endpoints self-attributes.
    probe = [
        _row("americanfootball_nfl", "player_props", used=1061, remaining=98939, last=8),
        _row("americanfootball_nfl", "player_props", used=1150, remaining=98850, last=89),
    ]
    rp = rec.reconcile(probe, baseline_remaining=None, final_remaining=None)
    if not rp["ok"] or not rp["baseline_derived"] or rp["attributed_total"] != 97:
        f.append(f"auto-baseline probe should self-attribute 97; got {rp['attributed_total']} ok={rp['ok']}")

    # 5c. Operator-log reconstruction: per-step costs 3 + 97, NOT the cumulative 1053.
    oplog = (
        "---- QUOTA RECEIPT ----\n  endpoint family: game_lines /events + /odds\n  sport          : nfl\n"
        "  x-requests-last (sum = fetch cost): 3\n  x-requests-used: 1053\n  x-requests-remaining              : 98947\n"
        "---- QUOTA RECEIPT ----\n  endpoint family: player_props /events + /odds\n  sport          : nfl\n"
        "  x-requests-last (sum = fetch cost): 97\n  x-requests-used: 1150\n  x-requests-remaining              : 98850\n"
    )
    prows = rec.parse_operator_log(oplog)
    rlog = rec.reconcile(prows, baseline_remaining=None, final_remaining=None)
    if rlog["attributed_total"] != 100 or rlog["by_key"].get("nfl | game_lines /events + /odds") != 3:
        f.append(f"operator-log per-step attribution wrong: {rlog['by_key']} total={rlog['attributed_total']}")

    # 5d. A lifetime baseline (not the window start) must NOT mis-charge the first row; excess is
    #     unattributed and flagged.
    rmis = rec.reconcile(prows, baseline_remaining=100000, final_remaining=98850)
    if rmis["attributed_total"] != 100 or rmis["unattributed"] != 1050 or rmis["ok"]:
        f.append(f"lifetime-baseline misuse should attribute 100 / unattributed 1050 / FAIL; got {rmis}")

    # 5e. Parser must recognize the REAL print_receipt format (not just hand-written fixtures): build a
    #     7-receipt recovery log via the actual printer, descending 100000 -> 98960, and reconcile to
    #     1040 with 0 unattributed. Guards against the "parser silently finds 0 rows" defect class.
    seq = [
        ("game_lines /events + /odds", "americanfootball_nfl", ("3", "3", "99997")),
        ("game_lines /events + /odds", "americanfootball_ncaaf", ("3", "6", "99994")),
        ("game_lines /events + /odds", "basketball_wnba", ("3", "9", "99991")),
        ("game_lines /events + /odds", "baseball_mlb", ("3", "12", "99988")),
        ("player_props /events + /odds", "americanfootball_nfl", ("97", "109", "99891")),
        ("player_props /events + /odds", "americanfootball_ncaaf", ("830", "939", "99061")),
        ("futures /sports + /odds(outrights)", "(all)", ("101", "1040", "98960")),
    ]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        for fam, sport, (last, used, rem) in seq:
            q = QuotaRecorder()
            q.record({"x-requests-last": last, "x-requests-used": used, "x-requests-remaining": rem})
            q.print_receipt(endpoint_family=fam, sport=sport)
    parsed = rec.parse_operator_log(buf.getvalue())
    if len(parsed) != 7:
        f.append(f"real print_receipt format: parser should find 7 receipts, found {len(parsed)}")
    rr = rec.reconcile(parsed, baseline_remaining=100000, final_remaining=98960)
    if not rr["ok"] or rr["attributed_total"] != 1040 or rr["unattributed"] != 0:
        f.append(f"real 7-receipt log should reconcile 1040/0; got {rr['attributed_total']}/{rr['unattributed']}")
    if rr["by_key"].get("americanfootball_ncaaf | player_props /events + /odds") != 830:
        f.append(f"per-family attribution wrong on real format: {rr['by_key']}")
    # a header-less receipt (no cumulative data) is skipped, never crashes the parser.
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        QuotaRecorder().print_receipt(endpoint_family="x", sport="y")
    if len(rec.parse_operator_log(buf2.getvalue())) != 0:
        f.append("a header-less receipt must be skipped, not parsed as a usable row")

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
