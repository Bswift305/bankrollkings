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
import re
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


def parse_operator_log(text: str) -> list[dict]:
    """Legacy best-effort (directive #4): reconstruct ordered pseudo-ledger rows from the operator log's
    own QUOTA RECEIPT blocks (our format, printed by services/odds_quota.print_receipt). Each receipt
    becomes one aggregated row carrying its END cumulative used/remaining + the step's last-sum. Only
    receipts that actually printed x-requests-remaining are usable; the rest are a pre-ledger gap. No
    network, no secrets -- this parses our own emitted receipt text, not arbitrary free-form."""
    rows: list[dict] = []
    # split on the receipt banner, keep each block
    blocks = re.split(r"-{4}\s*QUOTA RECEIPT\s*-{4}", text)
    for block in blocks[1:]:
        def _grab(pat):
            m = re.search(pat, block)
            return m.group(1).strip() if m else None
        fam = _grab(r"endpoint family\s*:\s*(.+)")
        sport = _grab(r"sport\s*:\s*(.+)")
        last = _grab(r"x-requests-last[^:]*:\s*(-?\d+)")
        used = _grab(r"x-requests-used\s*:\s*(-?\d+)")
        remaining = _grab(r"x-requests-remaining\s*:\s*(-?\d+)")
        if remaining is None and used is None:
            continue  # a receipt with no cumulative headers -- unusable, counts as a gap elsewhere
        rows.append({
            "ts": "",
            "sport": sport or "?",
            "endpoint_family": fam or "?",
            "last": int(last) if last is not None else None,
            "used": int(used) if used is not None else None,
            "remaining": int(remaining) if remaining is not None else None,
        })
    return rows


def reconcile(rows: list[dict], baseline_remaining: int | None, final_remaining: int | None) -> dict:
    """Attribute spend from ordered cumulative `remaining` drops. Returns a report dict with ok flag.

    ATTRIBUTION always auto-baselines from the FIRST usable row (its remaining + that call's own cost),
    so each row is charged only its OWN step cost -- never the account's lifetime usage. The explicit
    --baseline-remaining / --final-remaining are used ONLY to compute the account delta and therefore how
    much spend happened OUTSIDE these rows (the unattributed remainder). This keeps a single operator
    log's per-step attribution correct while still exposing a pre-ledger gap against the owner-read
    account window."""
    problems: list[str] = []
    with_remaining = [r for r in rows if r.get("remaining") is not None]
    gaps = len(rows) - len(with_remaining)
    if gaps:
        problems.append(f"{gaps} call row(s) had NO remaining header -- their spend cannot be attributed")

    # Attribution baseline = the remaining JUST BEFORE the first recorded call. Prefer the owner-supplied
    # baseline; otherwise derive it from the first row (its remaining + that call's own x-requests-last).
    # If a supplied baseline is NOT the immediate-prior reading (it sits above remaining[0] by more than
    # the first call's own cost), the first row's drop would absorb earlier, pre-window spend -- detect
    # that and warn, so the operator passes a tight window start (or omits it to auto-derive).
    attr_baseline = None
    derived_baseline = False
    if with_remaining:
        first = with_remaining[0]
        auto = int(first["remaining"]) + int(first.get("last") or 0)
        mismatch = (baseline_remaining is not None and first.get("last") is not None
                    and (baseline_remaining - int(first["remaining"])) != int(first["last"]))
        if mismatch:
            # Supplied baseline is NOT the reading just before the first call. Charge the first row only
            # its own cost (auto) so earlier spend is not mis-attributed to it; the excess becomes
            # unattributed via the account-delta comparison below.
            attr_baseline = auto
            over = baseline_remaining - auto
            problems.append(f"--baseline-remaining ({baseline_remaining}) is not the reading just before the "
                            f"first recorded call (its cost was {first['last']}); {over} credit(s) of earlier "
                            "spend are OUTSIDE these rows and are counted as unattributed, not charged to the "
                            "first row. Pass the window-start remaining (or omit it) for a tight window.")
        elif baseline_remaining is not None:
            attr_baseline = baseline_remaining
        else:
            attr_baseline = auto
            derived_baseline = True

    by_key: dict[tuple[str, str], int] = defaultdict(int)
    attributed = 0
    prev = attr_baseline
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
        problems.append(f"{non_monotonic} non-monotonic step(s) in cumulative remaining (interleaving/corruption)")

    ledger_final = with_remaining[-1]["remaining"] if with_remaining else None
    # Account delta (the authoritative spend for the window) from owner-read endpoints when given; else it
    # is just what these rows attributed (a self-contained window -> nothing unattributed by definition).
    if baseline_remaining is not None and final_remaining is not None:
        account_delta = baseline_remaining - final_remaining
    else:
        account_delta = attributed

    unattributed = account_delta - attributed
    if ledger_final is not None and final_remaining is not None and final_remaining < ledger_final:
        problems.append(f"account remaining ({final_remaining}) is below the last recorded reading "
                        f"({ledger_final}) -- {ledger_final - final_remaining} credit(s) spent by calls that "
                        "were never recorded")
    if unattributed != 0:
        problems.append(f"{unattributed} credit(s) of the {account_delta} account delta are UNATTRIBUTED "
                        "(spent outside the recorded rows -- a pre-ledger / missing-receipt gap)")
    # report the window baseline we actually used for attribution
    baseline_remaining = baseline_remaining if baseline_remaining is not None else attr_baseline

    ok = (not problems) and (account_delta is not None) and (unattributed == 0)
    return {
        "ok": ok,
        "baseline_remaining": baseline_remaining,
        "baseline_derived": derived_baseline,
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
    p.add_argument("--from-operator-log", default=None,
                   help="LEGACY best-effort: reconstruct ordered rows from an operator log's QUOTA RECEIPT "
                        "blocks instead of the ledger (for the pre-ledger incident window). Offline.")
    args = p.parse_args()

    source = "ledger"
    if args.from_operator_log:
        source = f"operator log {args.from_operator_log}"
        try:
            rows = parse_operator_log(Path(args.from_operator_log).read_text(encoding="utf-8", errors="replace"))
        except OSError as exc:
            print(f"[FAIL] cannot read operator log: {exc}")
            return 2
        ledger_path = Path(args.from_operator_log)
    else:
        ledger_path = Path(args.ledger) if args.ledger else (BASE_DIR / LEDGER_REL)
        rows = load_ledger(ledger_path, since=args.since)
    report = reconcile(rows, args.baseline_remaining, args.final_remaining)

    print("=" * 70)
    print("ODDS API QUOTA RECONCILIATION (cumulative-delta attribution)")
    print("=" * 70)
    print(f"source            : {source} ({report['ledger_calls']} call rows"
          f"{' since ' + args.since if args.since else ''})")
    if args.from_operator_log:
        print("mode              : LEGACY best-effort reconstruction (pre-ledger window)")
    print(f"baseline remaining: {report['baseline_remaining']}"
          f"{' (derived from first row)' if report.get('baseline_derived') else ''}")
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
