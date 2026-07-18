from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"


def _python(script: str, *args: str) -> list[str]:
    return [sys.executable, str(BASE_DIR / script), *args]


def _active_refresh_steps(sports: set[str]) -> list[tuple[str, list[str], int]]:
    steps: list[tuple[str, list[str], int]] = [
        ("All-sport injuries", _python("refresh_all_sport_injuries.py"), 300),
        ("Football line movement", _python("refresh_football_line_movement.py"), 600),
        ("Futures odds movement", _python("refresh_futures_odds.py"), 420),
        ("NFL current rosters", _python("fetch_nfl_current_roster.py"), 180),
        # Rebuild the per-game NFL fantasy gamelog from the historical/current
        # player-stats extracts (preseason baselines on last season; converges as
        # the year plays out). Cheap; keeps NFL fantasy rankings fresh.
        ("NFL fantasy gamelogs", _python("build_nfl_gamelogs.py"), 180),
        # College football roster/stats/returning-production/portal + player master.
        # This lived only in batch/REFRESH_FOOTBALL_DATA.bat (Windows dev box), so
        # prod had a valid CFBD_API_KEY but no refresh path and every NCAAF data
        # file was missing. Self-skips when CFBD_API_KEY is absent.
        ("CFB data refresh", _python("refresh_cfb_data.py"), 2400),
    ]
    if "mlb" in sports:
        steps.append(("MLB daily refresh", _python("refresh_mlb_daily.py"), 900))
        # Snapshot MLB featured-candidate results vs gamelogs. The 99 scorecard's
        # Archive & Replay check requires MLB_FeaturedResults.csv; without this
        # step it is never produced (mirrors the WNBA featured-results step).
        steps.append(("MLB featured results", _python("refresh_mlb_featured_results.py"), 600))
    if "nba" in sports:
        steps.append(("NBA daily refresh", _python("refresh_nba_daily.py"), 900))
    if "wnba" in sports:
        steps.extend([
            ("WNBA game lines", _python("fetch_wnba_game_lines.py", "--days", "5"), 300),
            ("WNBA player props", _python("fetch_wnba_player_props.py", "--days", "5"), 300),
            ("WNBA player logs", _python("refresh_wnba_player_logs.py"), 300),
            ("WNBA candidate archive", _python("archive_daily_candidates.py"), 300),
            ("WNBA featured results", _python("refresh_wnba_featured_results.py"), 300),
            ("WNBA calibration", _python("calibrate_wnba_model.py"), 300),
            ("Runtime snapshots", _python("refresh_runtime_snapshots.py", "--sports", "wnba", "--skip-prewarm"), 300),
        ])
    # Rebuild the market-independent Elo power ratings LAST, so they reflect the
    # freshly-refreshed game results / gamelogs the model is built from.
    steps.append(("Power ratings", _python("power_ratings.py"), 300))
    return steps


def _run_step(label: str, command: list[str], timeout: int) -> tuple[bool, str]:
    script_path = Path(command[1]) if len(command) > 1 else None
    if script_path and script_path.suffix == ".py" and not script_path.exists():
        return False, f"Missing script: {script_path}"
    try:
        proc = subprocess.run(
            command,
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        parts = [f"Timed out after {timeout} seconds."]
        if exc.stdout:
            stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else exc.stdout
            parts.append(stdout.strip())
        if exc.stderr:
            stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr
            parts.append(stderr.strip())
        return False, "\n".join(part for part in parts if part)
    parts = []
    if proc.stdout:
        parts.append(proc.stdout.strip())
    if proc.stderr:
        parts.append(proc.stderr.strip())
    return proc.returncode == 0, "\n".join(parts)


def _parse_sports(raw: str) -> set[str]:
    sports = {item.strip().lower() for item in raw.split(",") if item.strip()}
    valid = {"nba", "wnba", "mlb"}
    unknown = sports - valid
    if unknown:
        raise ValueError(f"Unsupported daily sport(s): {', '.join(sorted(unknown))}")
    return sports or valid


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Bankroll Kings daily refresh and analysis chain.")
    parser.add_argument("--sports", default="nba,wnba,mlb", help="Comma-separated active sports. Default: nba,wnba,mlb")
    parser.add_argument("--skip-refresh", action="store_true", help="Skip sport data refresh scripts.")
    parser.add_argument("--skip-edge", action="store_true", help="Skip Edge Engine analysis pipeline.")
    parser.add_argument("--skip-scorecards", action="store_true", help="Skip all 99%%/prelaunch scorecards.")
    parser.add_argument("--continue-on-error", action="store_true", help="Run later steps even if one step fails.")
    args = parser.parse_args()

    try:
        sports = _parse_sports(args.sports)
    except ValueError as exc:
        print(f"[FAIL] {exc}")
        return 2

    steps: list[tuple[str, list[str], int]] = []
    if not args.skip_refresh:
        steps.extend(_active_refresh_steps(sports))
        # Grade props against the now-fresh gamelogs (Pending -> Hit/Miss). Must run after
        # the sport refreshes and before the Edge Engine, which builds streak-heat and
        # calibration from resolved results.
        steps.append(("All prop results grading", _python("refresh_all_prop_results.py"), 1200))
    if not args.skip_edge:
        steps.append(("Edge Engine pipeline", _python("run_bk_edge_engine_pipeline.py"), 1800))
    if not args.skip_scorecards:
        steps.append(("All scorecards", _python("run_all_scorecards.py"), 1200))

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"daily_operator_{stamp}.log"
    lines = [
        "Bankroll Kings Daily Operator",
        "=" * 31,
        f"Started: {datetime.now().isoformat(timespec='seconds')}",
        f"Sports: {', '.join(sorted(sports)).upper()}",
        "",
    ]
    failed = False
    for label, command, timeout in steps:
        print(f"[RUN] {label}")
        ok, output = _run_step(label, command, timeout)
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {label}")
        lines += [
            f"[{status}] {label}",
            "Command: " + " ".join(command),
            output or "(no output)",
            "",
        ]
        if not ok:
            failed = True
            if not args.continue_on_error:
                break

    lines.append(f"Finished: {datetime.now().isoformat(timespec='seconds')}")
    log_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Log saved: {log_path}")

    print("[RUN] Run status")
    ok, output = _run_step("Run status", _python("generate_run_status.py"), 300)
    print(f"[{'PASS' if ok else 'FAIL'}] Run status")
    if output:
        print(output)
    if not ok:
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
