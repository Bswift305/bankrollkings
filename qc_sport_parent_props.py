"""
Integration QC (directive #3): the NBA and MLB daily parents must treat player props with the shared
outcome vocabulary -- classify from the response-shape receipt, NEVER abort the rest of the chain when
props are unavailable, continue the safe downstream steps, and leave the run DEGRADED only on a
non-benign outcome. Offline: every child subprocess is faked (no network / no spend).
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pandas as pd

import refresh_nba_daily as nba
import refresh_mlb_daily as mlb


class _Fake:
    def __init__(self, code):
        self.returncode = code


def _drive(parent_mod, slug, plan, env_key=False):
    """Run a parent.main() with faked subprocess.run. plan controls the props child: whether it advances
    the artifact + the receipt it writes. Returns (exit_code, steps_run_after_props, child_sidecar)."""
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "data/props").mkdir(parents=True, exist_ok=True)
        (base / "data/tracking").mkdir(parents=True, exist_ok=True)
        parent_mod.BASE_DIR = base
        parent_mod.PROPS_ARTIFACT = base / "data/props" / f"{slug.split('_')[-1].upper()}_Props.csv"
        import services.run_outcomes as ro

        steps_after = {"count": 0}
        props_seen = {"v": False}

        def fake_run(command, timeout=None):
            joined = " ".join(map(str, command))
            is_props = "player_props" in command_label(command)
            if is_props:
                props_seen["v"] = True
                receipt = {
                    "sport": slug, "events_found": plan["events"], "rows_fetched": plan["rows"],
                    "provider_error_count": plan.get("errors", 0),
                    "markets_present_anywhere": plan.get("present", []),
                    "shape_proves_no_markets_posted": plan.get("proven", False),
                }
                (base / "data/tracking" / f"_last_props_fetch_{slug}.json").write_text(json.dumps(receipt), encoding="utf-8")
                if plan.get("advance"):
                    pd.DataFrame([{"Player": "x"}]).to_csv(parent_mod.PROPS_ARTIFACT, index=False)
                return _Fake(plan["exit"])
            if props_seen["v"]:
                steps_after["count"] += 1
            return _Fake(0)

        def command_label(command):
            # the props step runs fetch_*player_props.py
            return " ".join(str(c) for c in command)

        import os
        orig_run = parent_mod.subprocess.run
        parent_mod.subprocess.run = fake_run
        if env_key:
            os.environ["ODDS_API_KEY"] = "qc-fake"
        try:
            rc = parent_mod.main()
        finally:
            parent_mod.subprocess.run = orig_run
        sidecar_path = base / "data/tracking" / f"_child_outcomes_{'nba_daily' if parent_mod is nba else 'mlb_daily'}.json"
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8")) if sidecar_path.exists() else None
        return rc, steps_after["count"], sidecar


def main() -> int:
    f = []

    # NBA: props VALIDATION_FAILED (markets present, 0 rows) -> run DEGRADED (rc!=0) but chain CONTINUES
    # (steps after props ran) and the child outcome is recorded.
    rc, after, sidecar = _drive(nba, "basketball_nba",
                                {"events": 8, "rows": 0, "present": ["player_points"], "proven": False,
                                 "exit": 1, "advance": False})
    if rc == 0:
        f.append("NBA: VALIDATION_FAILED props should leave the run DEGRADED (rc!=0)")
    if after == 0:
        f.append("NBA: downstream steps must still run after an unavailable props step (no abort)")
    if not sidecar or sidecar["outcomes"].get("player_props") != "VALIDATION_FAILED":
        f.append(f"NBA: child outcome sidecar should record VALIDATION_FAILED; got {sidecar}")

    # NBA: props proven NO_MARKETS_POSTED -> benign -> rc 0 and chain complete.
    rc2, after2, sidecar2 = _drive(nba, "basketball_nba",
                                   {"events": 8, "rows": 0, "present": [], "proven": True,
                                    "exit": 1, "advance": False})
    if rc2 != 0:
        f.append(f"NBA: proven NO_MARKETS_POSTED should be benign (rc 0); got {rc2}")
    if not sidecar2 or sidecar2["outcomes"].get("player_props") != "NO_MARKETS_POSTED":
        f.append(f"NBA: sidecar should record NO_MARKETS_POSTED; got {sidecar2}")

    # MLB: same contract -- VALIDATION_FAILED continues the chain, degrades the run, records the outcome.
    rc3, after3, sidecar3 = _drive(mlb, "baseball_mlb",
                                   {"events": 1, "rows": 0, "present": ["batter_hits"], "proven": False,
                                    "exit": 1, "advance": False}, env_key=True)
    if rc3 == 0:
        f.append("MLB: VALIDATION_FAILED props should leave the run DEGRADED (rc!=0)")
    if after3 == 0:
        f.append("MLB: downstream steps must still run after an unavailable props step (no abort)")
    if not sidecar3 or sidecar3["outcomes"].get("player_props") != "VALIDATION_FAILED":
        f.append(f"MLB: child outcome sidecar should record VALIDATION_FAILED; got {sidecar3}")

    print("=" * 64)
    print("QC: NBA/MLB PARENT PROPS OUTCOMES (no-abort + vocabulary)")
    print("=" * 64)
    if f:
        for x in f:
            print(f"[FAIL] {x}")
        return 1
    print("[OK] NBA+MLB classify props via the shared vocabulary, never abort the chain, record the outcome.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
