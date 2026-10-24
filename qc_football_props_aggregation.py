"""
Integration QC for refresh_football_props.py parent aggregation (directive #3), offline.

Fakes the child fetchers (no network / no spend): each fake writes the response-shape receipt the real
fetch_player_props would, and optionally advances the artifact, then returns an exit code. Proves the
parent:
  - returns 0 only when EVERY child is benign (UPDATED / NO_MARKETS_POSTED / NO_ACTIVE_EVENTS), and
  - returns non-zero (DEGRADED) when a child is VALIDATION_FAILED -- EVEN THOUGH the child exited 1 in
    BOTH the benign and the failing case (the exit code alone cannot tell them apart; the receipt can).
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pandas as pd

import refresh_football_props as rfp


class _FakeResult:
    def __init__(self, code):
        self.returncode = code


def _slug_for(cmd):
    joined = " ".join(cmd)
    if "nfl_player_props" in joined:
        return "americanfootball_nfl", "NFL"
    return "americanfootball_ncaaf", "NCAAF"


def _run_scenario(base: Path, nfl_plan: dict, ncaaf_plan: dict) -> int:
    (base / "data/props").mkdir(parents=True, exist_ok=True)
    (base / "data/tracking").mkdir(parents=True, exist_ok=True)
    rfp.BASE_DIR = base
    rfp.STEPS = [
        ("nfl_player_props", ["py", "fetch_nfl_player_props.py", "--days", "7"], 300,
         "americanfootball_nfl", base / "data/props/NFL_Props.csv"),
        ("ncaaf_player_props", ["py", "fetch_ncaaf_player_props.py", "--days", "7"], 300,
         "americanfootball_ncaaf", base / "data/props/NCAAF_Props.csv"),
    ]
    plans = {"NFL": nfl_plan, "NCAAF": ncaaf_plan}

    def fake_run(cmd, timeout=None):
        slug, sport = _slug_for(cmd)
        plan = plans[sport]
        # write the shape receipt exactly where fetch_player_props would
        receipt = {
            "sport": slug, "events_found": plan["events"], "rows_fetched": plan["rows"],
            "provider_error_count": plan.get("errors", 0),
            "markets_present_anywhere": plan.get("present", []),
            "shape_proves_no_markets_posted": plan.get("proven", False),
        }
        (base / "data/tracking" / f"_last_props_fetch_{slug}.json").write_text(json.dumps(receipt), encoding="utf-8")
        if plan.get("advance"):
            pd.DataFrame([{"Player": "x"}]).to_csv(base / "data/props" / f"{sport}_Props.csv", index=False)
        return _FakeResult(plan["exit"])

    orig = rfp.subprocess.run
    rfp.subprocess.run = fake_run
    os.environ["ODDS_API_KEY"] = "qc-fake-key"  # so main() does not early-skip
    try:
        return rfp.main()
    finally:
        rfp.subprocess.run = orig


def main() -> int:
    failures: list[str] = []
    saved = (rfp.BASE_DIR, list(rfp.STEPS))
    try:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            # A: both UPDATED -> parent 0
            rc = _run_scenario(base,
                               {"events": 14, "rows": 500, "present": ["player_pass_yds"], "exit": 0, "advance": True},
                               {"events": 40, "rows": 900, "present": ["player_pass_yds"], "exit": 0, "advance": True})
            if rc != 0:
                failures.append(f"A both-updated: expected 0, got {rc}")
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            # B: NFL proven NO_MARKETS_POSTED (exit 1, no advance), NCAAF UPDATED -> parent 0 (all benign)
            rc = _run_scenario(base,
                               {"events": 14, "rows": 0, "present": [], "proven": True, "exit": 1, "advance": False},
                               {"events": 40, "rows": 900, "present": ["player_pass_yds"], "exit": 0, "advance": True})
            if rc != 0:
                failures.append(f"B nfl-no-markets-proven: expected 0, got {rc}")
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            # C: NFL zero rows but markets WERE present (exit 1, not proven) -> VALIDATION_FAILED -> parent 1
            rc = _run_scenario(base,
                               {"events": 14, "rows": 0, "present": ["player_pass_yds"], "proven": False, "exit": 1, "advance": False},
                               {"events": 40, "rows": 900, "present": ["player_pass_yds"], "exit": 0, "advance": True})
            if rc != 1:
                failures.append(f"C nfl-validation-failed: expected 1 (degraded), got {rc}")
    finally:
        rfp.BASE_DIR, rfp.STEPS = saved

    print("=" * 64)
    print("QC: FOOTBALL PROPS PARENT AGGREGATION")
    print("=" * 64)
    if failures:
        for x in failures:
            print(f"[FAIL] {x}")
        return 1
    print("[OK] parent PASSes only on all-benign children; a non-advancing artifact without proof degrades it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
