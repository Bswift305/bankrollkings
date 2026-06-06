from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
STEPS = [
    ("NFL historical backfill", "build_nfl_historical_calibration.py"),
    ("NFL base calibration", "calibrate_nfl_model.py"),
    ("NFL EdgeScore", "calculate_nfl_edge_score.py"),
    ("NFL PropScore", "calculate_nfl_prop_score.py"),
    ("NFL simulation", "simulate_nfl_props.py"),
    ("Active sport simulations", "simulate_active_sport_props.py"),
    ("Team strength priors", "calculate_team_strength_priors.py"),
    ("NFL calibration notes", "generate_nfl_calibration_notes.py"),
    ("NCAAF game-line backfill", "build_ncaaf_game_line_backfill.py"),
    ("NCAAF EdgeScore", "calculate_ncaaf_edge_score.py"),
    ("NCAAF calibration", "calibrate_cfb_model.py"),
    ("MLB weather context", "fetch_mlb_weather_context.py"),
    ("MLB umpire assignment fetch", "fetch_mlb_umpire_assignments.py"),
    ("MLB umpire context", "build_mlb_umpire_context.py"),
    ("MLB game context", "build_mlb_game_context.py"),
    ("MLB ContextScore", "calculate_mlb_context_scores.py"),
    ("Result metadata normalization", "normalize_result_metadata.py"),
    ("Sport driver calibration", "generate_sport_driver_calibration.py"),
    ("Cross-sport calibration", "generate_cross_sport_calibration_summary.py"),
    ("Promotion signal inputs", "generate_promotion_signal_inputs.py"),
    ("Streak heat index", "rebuild_streak_heat_index.py"),
    ("Live drift alerts", "generate_drift_alerts.py"),
    ("Formula status", "generate_formula_status.py"),
]


def run_step(label: str, script: str) -> tuple[bool, str]:
    path = BASE_DIR / script
    if not path.exists():
        return False, f"Missing script: {path}"
    proc = subprocess.run(
        [sys.executable, str(path)],
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        timeout=300,
    )
    output = []
    if proc.stdout:
        output.append(proc.stdout.strip())
    if proc.stderr:
        output.append(proc.stderr.strip())
    return proc.returncode == 0, "\n".join(output)


def main() -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"bk_edge_engine_pipeline_{stamp}.log"
    lines = [
        "Bankroll Kings Edge Engine Pipeline",
        "=" * 42,
        f"Started: {datetime.now().isoformat(timespec='seconds')}",
        "",
    ]
    failed = False
    for label, script in STEPS:
        print(f"[RUN] {label}")
        ok, output = run_step(label, script)
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {label}")
        lines += [
            f"[{status}] {label}",
            f"Script: {script}",
            output or "(no output)",
            "",
        ]
        if not ok:
            failed = True
            # Continue-on-error: each step is independent. A failure in one step
            # (e.g. an off-season sport whose history file is missing) must not
            # abort the rest of the pipeline and starve in-season sports of
            # simulations, priors, calibration, streak heat, and drift alerts.

    lines += [f"Finished: {datetime.now().isoformat(timespec='seconds')}"]
    log_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Log saved: {log_path}")

    print("[RUN] Run status")
    ok, output = run_step("Run status", "generate_run_status.py")
    print(f"[{'PASS' if ok else 'FAIL'}] Run status")
    if output:
        print(output)
    if not ok:
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
