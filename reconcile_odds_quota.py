"""
Bankroll Kings - Odds API quota reconciliation (incident 2026-10-24, directive #4).
===================================================================================

Reconcile the account's credit delta over a window and attribute EVERY credit by sport and endpoint
family, using the ORDERED cumulative usage headers -- NOT the per-request x-requests-last (which read 0
for the NBA probe and cannot be trusted alone). The receipt FAILS if any portion of the account delta
is unattributed.

How the cumulative method works: The Odds API returns x-requests-remaining (and x-requests-used) on
every response -- a monotonic account counter. Between two consecutive recorded calls the drop in
`remaining` is the credits consumed up to and including the later call; we attribute that drop to that
call's (sport, endpoint family). The ledger (services/odds_quota.py -> data/tracking/
odds_quota_ledger.jsonl) records one line per paid call with its cumulative headers.

  attributed_total = baseline_remaining - ledger's final remaining
  account_delta    = baseline_remaining - final_remaining           (the authoritative spend)
  unattributed     = account_delta - attributed_total               (calls the ledger never saw)

FAIL if unattributed != 0, if any ledger call lacks a `remaining` reading (a gap we cannot attribute),
or if the cumulative counter is non-monotonic (ledger corruption / interleaving).

Usage (on the box with the ledger; the owner supplies the window endpoints they can read in the
dashboard, e.g. the 100000 -> 98960 incident window):
    python reconcile_odds_quota.py --baseline-remaining 100000 --final-remaining 98960
    python reconcile_odds_quota.py --since 2026-10-24T00:00:00   # window by timestamp, endpoints from ledger
Exit 0 only when the full delta is attributed; non-zero otherwise.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from services.odds_quota import LEDGER_REL

BASE_DIR = Path(__file__).resolve().parent


def load_ledger(path: Path, since: str | None = None) -> list[dict]:
    rows: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return rows
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if since and str(rec.get("ts") or "") < since:
            continue
        rows.append(rec)
    return rows


def reconcile(rows: list[dict], baseline_remaining: int | None, final_remaining: int | None) -> dict:
    """Attribute spend from ordered cumulative `remaining` drops. Returns a report dict with ok flag."""
    problems: list[str] = []
    # Keep ledger order (insertion), which is chronological per append.
    with_remaining = [r for r in rows if r.get("remaining") is not None]
    gaps = len(rows) - len(with_remaining)
    if gaps:
        problems.append(f"{gaps} ledger call(s) had NO remaining header -- their spend cannot be attributed")

    by_key: dict[tuple[str, str], int] = defaultdict(int)
    attributed = 0
    prev = baseline_remaining
    non_monotonic = 0
    for r in with_remaining:
        rem = int(r["remaining"])
        if prev is not None:
            drop = prev - rem
            if drop < 0:
                non_monotonic += 1
            else:
                by_key[(r.get("sport") or "?", r.get("endpoint_family") or "?")] += drop
                attributed += drop
        prev = rem
    if non_monotonic:
        problems.append(f"{non_monotonic} non-monotonic step(s) in cumulative remaining (ledger interleaving/corruption)")

    ledger_final = with_remaining[-1]["remaining"] if with_remaining else baseline_remaining
    # The authoritative account delta: baseline -> final (both owner-supplied when known).
    account_delta = None
    if baseline_remaining is not None and final_remaining is not None:
        account_delta = baseline_remaining - final_remaining
    elif baseline_remaining is not None and ledger_final is not None:
        account_delta = baseline_remaining - ledger_final

    unattributed = None
    if account_delta is not None:
        unattributed = account_delta - attributed
        # a tail gap: the account dropped more than the ledger's last reading shows
        if final_remaining is not None and ledger_final is not None and final_remaining < ledger_final:
            problems.append(f"account remaining ({final_remaining}) is below the ledger's last reading "
                            f"({ledger_final}) -- {ledger_final - final_remaining} credit(s) spent by calls the "
                            "ledger never recorded")
        if unattributed != 0:
            problems.append(f"{unattributed} credit(s) of the {account_delta} account delta are UNATTRIBUTED")

    ok = (not problems) and (account_delta is not None) and (unattributed == 0)
    return {
        "ok": ok,
        "baseline_remaining": baseline_remaining,
        "final_remaining": final_remaining,
        "ledger_final_remaining": ledger_final,
        "account_delta": account_delta,
        "attributed_total": attributed,
        "unattributed": unattributed,
        "ledger_calls": len(rows),
        "by_key": {f"{s} | {fam}": v for (s, fam), v in sorted(by_key.items(), key=lambda kv: -kv[1])},
        "problems": problems,
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Reconcile + attribute the Odds API credit delta (directive #4).")
    p.add_argument("--baseline-remaining", type=int, default=None,
                   help="x-requests-remaining at the START of the window (owner-read, e.g. 100000).")
    p.add_argument("--final-remaining", type=int, default=None,
                   help="x-requests-remaining at the END of the window (owner-read, e.g. 98960).")
    p.add_argument("--since", default=None, help="Only ledger rows with ts >= this ISO timestamp.")
    p.add_argument("--ledger", default=None, help="Ledger path (default: data/tracking/odds_quota_ledger.jsonl).")
    args = p.parse_args()

    ledger_path = Path(args.ledger) if args.ledger else (BASE_DIR / LEDGER_REL)
    rows = load_ledger(ledger_path, since=args.since)
    report = reconcile(rows, args.baseline_remaining, args.final_remaining)

    print("=" * 70)
    print("ODDS API QUOTA RECONCILIATION (cumulative-delta attribution)")
    print("=" * 70)
    print(f"ledger            : {ledger_path} ({report['ledger_calls']} call rows"
          f"{' since ' + args.since if args.since else ''})")
    print(f"baseline remaining: {report['baseline_remaining']}")
    print(f"final remaining   : {report['final_remaining']}  (ledger last: {report['ledger_final_remaining']})")
    print(f"account delta     : {report['account_delta']}")
    print(f"attributed total  : {report['attributed_total']}")
    print(f"unattributed      : {report['unattributed']}")
    print("-" * 70)
    if report["by_key"]:
        print("attributed by sport | endpoint family:")
        for key, credits in report["by_key"].items():
            print(f"  {credits:>6}  {key}")
    else:
        print("attributed by sport | endpoint family: (none -- ledger has no usable cumulative readings)")
    for problem in report["problems"]:
        print(f"[FAIL] {problem}")
    print("-" * 70)
    if report["ok"]:
        print("[OK] every credit of the account delta is attributed.")
        return 0
    if report["account_delta"] is None:
        print("[FAIL] cannot reconcile: supply --baseline-remaining and --final-remaining (owner-read) "
              "or populate the ledger so endpoints are known.")
    print("[FAIL] reconciliation incomplete -- do NOT treat spend as fully accounted.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
