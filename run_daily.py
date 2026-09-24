from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from season_utils import active_sports, sport_for_label


BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"


def _python(script: str, *args: str) -> list[str]:
    return [sys.executable, str(BASE_DIR / script), *args]


def _active_refresh_steps(sports: set[str]) -> list[tuple[str, list[str], int]]:
    steps: list[tuple[str, list[str], int]] = [
        # Loud guard FIRST: a dead Odds API key (or broken fetch) is otherwise SILENT
        # -- fetches preserve the last-good file, so the site serves stale lines for
        # days. This fails the daily run visibly. (2026-08-08: the key had died on
        # Jul 28 and nothing screamed for 11 days until someone checked by hand.)
        ("Odds feed health", _python("qc_odds_feed.py"), 120),
        ("All-sport injuries", _python("refresh_all_sport_injuries.py"), 300),
        # Diff the fresh NFL injury feed against the prior snapshot to surface status
        # transitions (Questionable -> Out, new injuries, clearances) -- a timing signal.
        ("NFL injury change tracker", _python("track_nfl_injury_changes.py"), 120),
        ("Football line movement", _python("refresh_football_line_movement.py"), 600),
        # First-half spread/total (Odds API per-event markets, not in the bulk feed
        # or CFBD). Self-empties out of season; ~2 credits/event so --days is kept
        # tight. Feeds the "1H" line on the game-lines board.
        ("NFL first-half lines", _python("fetch_football_first_half.py",
                                         "--sport", "americanfootball_nfl", "--days", "4"), 300),
        ("CFB first-half lines", _python("fetch_football_first_half.py",
                                         "--sport", "americanfootball_ncaaf", "--days", "4"), 600),
        # Player props for NFL + NCAAF. The line-movement step above fetches GAME
        # LINES; this fetches player PROPS, which previously lived only in the
        # Windows batch and so never ran on prod. Self-gating and cheap in the
        # offseason (no games within 7 days -> one empty events call); activates
        # automatically once games come within a week. Without it, football has a
        # working board/archive/grader but no prop feed to act on.
        ("Football player props", _python("refresh_football_props.py"), 900),
        ("Futures odds movement", _python("refresh_futures_odds.py"), 420),
        # True season-long team/player O/U markets (win totals and milestones).
        # Provider-neutral and self-skipping until a licensed feed is configured.
        ("Season-long markets", _python("refresh_season_markets.py"), 420),
        # NFL preseason game lines (separate Odds API sport key). Feeds the Preseason
        # O/U Markets card; self-empties out of the ~Aug window. --days 30 spans the
        # whole preseason; skip line-movement tracking (only the current O/U is shown).
        ("NFL preseason lines", _python(
            "fetch_game_lines.py", "--sport", "americanfootball_nfl_preseason",
            "--bookmakers", "draftkings,caesars,fanduel,betmgm", "--days", "30",
            "--skip-line-movement"), 180),
        # Game-day wind forecast for upcoming OUTDOOR NFL games (Open-Meteo, no key).
        # Powers the validated high-wind UNDER flag; self-empties out of the ~16-day
        # forecast window and skips cleanly on any network error.
        ("NFL game weather", _python("fetch_nfl_weather.py"), 180),
        # Score THIS WEEK's props with the validated PropScore model. Must run after
        # the props fetch, the game lines and the weather pull, since it needs all
        # three to build the game-script and wind tags. Until this existed, nothing
        # scored a live prop and the board could only reuse a 2024/25 score for a
        # matching player/stat/direction/line.
        ("NFL live prop scoring", _python("score_live_nfl_props.py"), 600),
        # Live-results record: snapshot this week's PropScore board, then grade any
        # past week that now has nflverse actuals (dedupe-safe). Builds the running
        # live hit-rate log the calibration story needs. See grade_nfl_week.py.
        ("NFL board snapshot", _python("grade_nfl_week.py", "--snapshot"), 180),
        ("NFL board grade (resolve)", _python("grade_nfl_week.py", "--resolve"), 300),
        ("NFL current rosters", _python("fetch_nfl_current_roster.py"), 180),
        # Prior-season team map for the early-season usage gate (flags movers whose
        # PropScore is projected on last year's role). Cheap; static once built.
        ("NFL prior-season team map", _python("build_nfl_prior_team_map.py"), 120),
        # Receiver aDOT/archetype profile for the archetype gate (flags volatile
        # deep-threat receptions props). One nflverse call; cheap.
        ("NFL receiver profile", _python("build_nfl_receiver_profile.py"), 120),
        # Current-season team form (offense + defense splits + pressure, league-ranked)
        # so the matchup card reasons off how teams play NOW, not last year. One
        # nflverse call; writes committable data/scenarios/nfl_2026_form.json.
        ("NFL team form", _python("build_nfl_team_form.py"), 180),
        # Current-season defensive-player tackle form (solo/combined pace) so the
        # matchup card can read tackle props vs real volume -- the offense-first
        # model's blind spot. One nflverse call; writes data/scenarios/nfl_2026_defense.json.
        ("NFL defense form", _python("build_nfl_defense_form.py"), 180),
        # Rebuild the per-game NFL fantasy gamelog from the historical/current
        # player-stats extracts (preseason baselines on last season; converges as
        # the year plays out). Cheap; keeps NFL fantasy rankings fresh.
        ("NFL fantasy gamelogs", _python("build_nfl_gamelogs.py"), 180),
        # Snapshot NFL featured-play results vs gamelogs. Mirrors the MLB and WNBA
        # featured-results steps; NFL was simply never added, so prod had no
        # NFL_FeaturedResults.csv and the 99 scorecard's Archive & Replay check
        # hard-failed on the missing artifact the moment NFL came into season.
        # Runs after the gamelog rebuild so the grader has fresh results to grade.
        ("NFL featured results", _python("refresh_nfl_featured_results.py"), 600),
        # Confirmed MLB lineups. Without these every batter prop is stuck on
        # "LINEUP PENDING", which downgrades the verdict and blocks archiving.
        # This run is early for most slates (see bk-mlb-lineups.timer, which
        # re-fetches and re-archives through the afternoon as lineups post).
        ("MLB lineups", _python("fetch_mlb_lineups.py"), 180),
        # College football roster/stats/returning-production/portal + player master.
        # This lived only in batch/REFRESH_FOOTBALL_DATA.bat (Windows dev box), so
        # prod had a valid CFBD_API_KEY but no refresh path and every NCAAF data
        # file was missing. Self-skips when CFBD_API_KEY is absent.
        ("CFB data refresh", _python("refresh_cfb_data.py"), 2400),
        # Snapshot NCAAF featured-play results vs gamelogs. Same omission as NFL:
        # the prelaunch scorecard requires NCAAF_FeaturedResults.csv once CFB is
        # in season, and nothing in the daily chain produced it, so the launch
        # gate hard-failed on a missing artifact the week CFB props went live.
        ("NCAAF featured results", _python("refresh_ncaaf_featured_results.py"), 600),
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
    active = active_sports()
    failed = False
    for label, command, timeout in steps:
        print(f"[RUN] {label}")
        ok, output = _run_step(label, command, timeout)
        if ok:
            status = "PASS"
        else:
            # Same season gate the Edge Engine pipeline and the scorecard runner
            # already use: a sport with no live props has no data for its refresh
            # to work on, so its failure is expected and must not fire the daily
            # alert. (2026-09-09: NBA's board QC correctly reports "no upcoming
            # schedule" all summer, which failed the whole run every night.)
            sport = sport_for_label(label)
            status = "SKIP (off-season)" if sport and sport not in active else "FAIL"
        print(f"[{status}] {label}")
        lines += [
            f"[{status}] {label}",
            "Command: " + " ".join(command),
            output or "(no output)",
            "",
        ]
        if status == "FAIL":
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
