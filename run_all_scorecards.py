from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from season_utils import active_sports, sport_for_label


BASE_DIR = Path(__file__).resolve().parent


def _hard_fail_count(output: str):
    """Pull the hard-FAIL tally from a 99% scorecard's summary (e.g. 'FAIL: 1').

    Returns the count, or None if no summary line was found (which usually means
    the scorecard crashed before printing one).
    """
    matches = re.findall(r"FAIL:\s*(\d+)", output or "")
    if not matches:
        return None
    return int(matches[-1])
LOG_DIR = BASE_DIR / "logs"
SCORECARDS = [
    ("NBA 99 Scorecard", "run_nba_99_scorecard.py", 180),
    ("WNBA 99 Scorecard", "run_wnba_99_scorecard.py", 180),
    ("MLB 99 Scorecard", "run_mlb_99_scorecard.py", 360),
    ("NFL 99 Scorecard", "run_nfl_99_scorecard.py", 180),
    ("Prelaunch Scorecard", "run_prelaunch_scorecard.py", 180),
]


def run_scorecard(label: str, script: str, timeout: int) -> tuple[bool, str]:
    path = BASE_DIR / script
    if not path.exists():
        return False, f"Missing scorecard script: {path}"
    proc = subprocess.run(
        [sys.executable, str(path)],
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    parts = []
    if proc.stdout:
        parts.append(proc.stdout.strip())
    if proc.stderr:
        parts.append(proc.stderr.strip())
    return proc.returncode == 0, "\n".join(parts)


def main() -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"all_scorecards_{stamp}.log"
    lines = [
        "Bankroll Kings Scorecard Runner",
        "=" * 35,
        f"Started: {datetime.now().isoformat(timespec='seconds')}",
        "",
    ]
    active = active_sports()
    failed = False
    for label, script, timeout in SCORECARDS:
        print(f"[RUN] {label}")
        ok, output = run_scorecard(label, script, timeout)
        sport = sport_for_label(label)
        if ok:
            status = "PASS"
        elif sport is None:
            # Cross-sport / launch gate (Prelaunch Scorecard). It is already
            # season-aware internally, so its exit code is authoritative.
            status = "FAIL"
            failed = True
        elif sport not in active:
            # Off-season sport: scorecard can't pass without data. Expected.
            status = "SKIP (off-season)"
        else:
            hard = _hard_fail_count(output)
            if hard is None:
                # No summary printed -> the scorecard likely crashed. Real.
                status = "FAIL"
                failed = True
            elif hard > 0:
                status = "FAIL"
                failed = True
            else:
                # In-season with zero hard fails: non-zero exit is only WATCH
                # items (e.g. calibration immaturity). Not an alarm.
                status = "WATCH (not blocking)"
        print(f"[{status}] {label}")
        lines += [f"[{status}] {label}", f"Script: {script}", output or "(no output)", ""]
    lines.append(f"Finished: {datetime.now().isoformat(timespec='seconds')}")
    log_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Log saved: {log_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
