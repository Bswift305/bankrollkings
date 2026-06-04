from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
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
    failed = False
    for label, script, timeout in SCORECARDS:
        print(f"[RUN] {label}")
        ok, output = run_scorecard(label, script, timeout)
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {label}")
        lines += [f"[{status}] {label}", f"Script: {script}", output or "(no output)", ""]
        if not ok:
            failed = True
    lines.append(f"Finished: {datetime.now().isoformat(timespec='seconds')}")
    log_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Log saved: {log_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
