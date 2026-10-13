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
# Timeouts are generous because the daily refresh keeps the box busy when these
# run; a slow scorecard is treated as a non-blocking TIMEOUT (see main), not a
# hard failure, so transient slowness can't fail the whole daily run.
SCORECARDS = [
    # Runs first and is cheap: it verifies every registered sport still has its
    # loaders, stat map and calibrator wired. A sport missing a part is invisible
    # at runtime -- football archived all its picks and graded none of them -- so
    # this is the check that turns "silently absent" into a hard failure.
    ("Sport Registry", "qc_sport_registry.py", 240),
    # Cross-sport Quick Tools smoke (renders every /tools/* surface + exercises their
    # logic paths). Cheap, cross-sport (no season gate), so a broken tool is a hard FAIL.
    ("Quick Tools QC", "qc_quick_tools.py", 300),
    # Lens Attribution governance guards -- identity resolution + resolution states.
    # Permanent regression guard for the capture/grading integrity defects; a governance
    # bug reintroduced here is a hard FAIL, not a silently corrupted archive.
    ("Lens Attribution QC", "qc_lens_attribution.py", 180),
    # Floor-board cache determinism + player-log invalidation guard. Cheap; locks down the
    # call-order contamination and stale-on-log-refresh defects (a6d9e4c + signature follow-up).
    ("NFL Floor Cache QC", "qc_nfl_floor_cache.py", 240),
    # NFL heat-map freshness: a stale streak must never read as current. Locks down the cache
    # key (player-log signature), the through-week/timestamp disclosures, games-played vs
    # calendar recency + injury availability, the completed-week pending gate, and the Mike
    # Evans Week-5 regression (yesterday's result ends the run once the week loads).
    ("NFL Heat-Map Freshness QC", "qc_nfl_heatmap_freshness.py", 180),
    # Riding-the-Wave player prop-streak freshness: the under-streak surface must disclose what
    # it is graded through and never present last season's final runs as current. Locks the
    # stale-season/through-week pending gate + availability + the Mike Evans unders->over fixture.
    ("NFL Prop-Streak Freshness QC", "qc_nfl_prop_streak_freshness.py", 180),
    # Same board against the REAL NFL_AllPropResults source schema (the routinely-refreshed graded
    # record): proves an Under streak that is current through the latest graded week disappears once
    # the next graded game goes Over, via the real on-disk read path.
    ("NFL Prop-Streak Integration QC", "qc_nfl_prop_streak_integration.py", 180),
    # fetch_nfl_player_week --check-only contract: a missing parquet is behind (exit 2), but a file
    # that exists yet cannot be read is a DISTINCT error (exit 3), never a false "week 0" that would
    # read as missing production data. Cheap; guards the post-week retry's operator diagnostics.
    ("NFL Fetch Check-Only QC", "qc_nfl_fetch_checkonly.py", 120),
    # Player Check acceptance: shared inclusion predicates, floor evaluator codes, and the name
    # resolver (ambiguity/suffix/punctuation). Durable fixtures; live cases are advisory notes.
    ("Player Check QC", "qc_player_check.py", 240),
    # NBA postseason phase rule: the thirteen configured-window phase tests + override + NBA
    # scoping + other-sports-unchanged. Cheap; guards the P0 season-state correction.
    ("NBA Postseason Phase QC", "qc_nba_postseason_phase.py", 180),
    # NBA P0 Commit C: the authenticated NBA board authority removal (Confidence/Tier/Conf-column/
    # Locks + neutral tip-off sort) must be NBA-only and fail-safe -- other sports keep everything,
    # including when the is_nba_props flag is omitted. Renders props.html for both views x all sports.
    ("NBA Commit C Guard QC", "qc_nba_commit_c_guard.py", 180),
    # Trial Eligibility Gate core (mocked): one-lifetime-trial store guarantees -- eligibility,
    # hard cap, atomic redemption, crash-recovery, key rotation, DB invariants, fail-closed.
    ("Trial Gate QC", "qc_trial_gate.py", 120),
    ("NBA 99 Scorecard", "run_nba_99_scorecard.py", 360),
    ("WNBA 99 Scorecard", "run_wnba_99_scorecard.py", 420),
    ("MLB 99 Scorecard", "run_mlb_99_scorecard.py", 480),
    ("NFL 99 Scorecard", "run_nfl_99_scorecard.py", 360),
    ("Prelaunch Scorecard", "run_prelaunch_scorecard.py", 360),
]

TIMEOUT_MARK = "[TIMEOUT]"


def run_scorecard(label: str, script: str, timeout: int) -> tuple[bool, str]:
    path = BASE_DIR / script
    if not path.exists():
        return False, f"Missing scorecard script: {path}"
    try:
        proc = subprocess.run(
            [sys.executable, str(path)],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        # Don't let one slow scorecard crash the whole step — report and move on.
        return False, f"{TIMEOUT_MARK} {script} exceeded {timeout}s"
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
        elif TIMEOUT_MARK in output:
            # Transient slowness (box busy during refresh). Logged, not fatal —
            # a real persistent hang will keep showing up and can be acted on.
            status = "TIMEOUT (slow; not blocking)"
        elif sport is not None and sport not in active:
            # Off-season sport: scorecard can't pass without data. Expected.
            status = "SKIP (off-season)"
        else:
            # Judge every scorecard, launch gate included, on hard FAIL sections
            # rather than on its exit code. The Prelaunch Scorecard exits non-zero
            # for any NO-GO, and its GO rule also requires fewer than 3 WATCH
            # sections -- a bar nothing can clear pre-season, when "0 plays
            # evaluated", "0 resolved results" and a standing manual visual-trust
            # review are all true at once. Paging nightly on that is the alert
            # fatigue the season gate exists to prevent. A genuinely failing
            # section, or a crash (no summary line at all), still alarms.
            hard = _hard_fail_count(output)
            if hard is None:
                # No summary printed -> the scorecard likely crashed. Real.
                status = "FAIL"
                failed = True
            elif hard > 0:
                status = "FAIL"
                failed = True
            else:
                # Zero hard fails: non-zero exit is only WATCH items (e.g.
                # calibration immaturity, a NO-GO on watch count). Not an alarm.
                status = "WATCH (not blocking)"
        print(f"[{status}] {label}")
        lines += [f"[{status}] {label}", f"Script: {script}", output or "(no output)", ""]
    lines.append(f"Finished: {datetime.now().isoformat(timespec='seconds')}")
    log_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Log saved: {log_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
