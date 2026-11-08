"""Smoke QC for the cross-sport Quick Tools (/tools/*).

These surfaces were built fast and share loaders / caches / precomputed JSON exports, so a
regression in any one (a renamed context key, a bad groupby, a template typo, a missing
data export) would otherwise ship silently. This renders each route with an authenticated
QC session and asserts a 200 plus a distinctive CONTENT marker (not just the hero, so an
empty-state or broken data-load is caught), then exercises the filter/input paths that
carry the real logic (best-lines pagination, risk-radar flag filter, ticket-check parsing,
and the pick-analyzer's Statcast read of a pasted leg).

Covers the newer analytics tools too: NFL Scenario Lab, MLB Real vs Luck, MLB Situational
Lab, CFB Regression Watch, Pick Analyzer, and NRFI / First Inning.

SELF-CONTAINED (2026-11 NBA lines v4, owner decision 6). Best Lines, Risk Radar and Slate Pulse read the
central NBA/WNBA executable-props loaders changed on this branch, so this QC no longer depends on whatever
happens to sit in the local data/ directory or in the user store:
  * Auth: services.qc_auth.isolated_member_client (in-memory all_access member). No user-store writes.
  * Data: a private temp DATA_DIR holding SYNTHETIC NBA/WNBA props (the real loaders + the central 6h gate
    run against it); the tools backed by committed exports (data/scenarios/*.json via BASE_DIR) read the
    tracked repo copies, which every checkout and `git archive` export carries.
  * MLB Real vs Luck: the season Statcast profile CSVs are gitignored runtime data, so missing local MLB data
    is NOT a waiver -- the QC synthesizes the hitter/pitcher expected-vs-actual frames it needs and swaps the
    single data boundary (app.load_statcast_dataframe) for the duration of the run.
  * The run log goes to a temp file, never data/tracking/QC_Run_Log.csv.
  * Changed-loader proof: Best Lines / Risk Radar / Slate Pulse show the synthetic NBA/WNBA quote when the
    feed is fresh and nothing executable when it is stale.
No network. Exit 0 on pass, 1 otherwise.
"""
from __future__ import annotations

import contextlib
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

os.environ.setdefault("SECRET_KEY", "qc-quick-tools")   # app import needs one; synthetic, offline QC

import app as app_module  # noqa: E402
from app import app  # noqa: E402
from services import qc_tracking  # noqa: E402
from services.qc_auth import isolated_member_client  # noqa: E402
from services.qc_tracking import append_qc_run_log  # noqa: E402
from services.timeutils import DISPLAY_TZ  # noqa: E402


# (path, [any-of markers that prove the page rendered its own content, not an error/gate])
ROUTES = [
    ("/tools/slate-pulse", ["Slate", "slate-table", "Live Sports"]),
    ("/tools/market-movers", ["Market", "mm-disclaimer", "Movement depth"]),
    ("/tools/best-lines", ["Best", "best-lines-table", "Best Number"]),
    ("/tools/risk-radar", ["Risk", "rr-table", "verified warnings", "No warnings"]),
    ("/tools/ticket-check", ["Ticket", "Check Ticket", "Paste a ticket"]),
    ("/tools/game-context", ["Game", "Context Coverage", "gc-matrix"]),
    ("/tools/track-record", ["Track", "Break-Even", "Forward-captured"]),
    ("/tools/season-markets", ["Season Markets", "comparison engine is installed", "Our Findings vs Vegas"]),
    ("/tools/injury-report", ["Injury", "inj-table", "Injury Report"]),
    # Newer analytics tools (data-proving markers, so an empty/broken export fails here).
    ("/tools/scenario-lab", ["Plays Graded", "Team Profiles"]),
    ("/tools/real-vs-luck", ["Hitters Graded", "Riding luck"]),
    ("/tools/mlb-situational", ["Plate Appearances"]),
    ("/tools/cfb-regression", ["Due to Fall", "FBS Teams"]),
    ("/tools/pick-analyzer", ["Analyze my picks"]),
    ("/tools/nrfi", ["League NRFI", "Starting Pitchers"]),
]

# Paths that exercise the logic-bearing query/input handling.
LOGIC_PATHS = [
    "/tools/best-lines?league=mlb&direction=OVER&multi=1",
    "/tools/best-lines?page=2",
    "/tools/market-movers?all=1&league=mlb",
    "/tools/risk-radar?flag=injury",
    "/tools/track-record?sport=MLB&min_sample=50",
    "/tools/season-markets?sport=NFL&type=team&market=Regular%20Season%20Wins",
    "/tools/ticket-check?legs=MLB%20%7C%20Aaron%20Judge%20%7C%20Home%20Runs%20%7C%20Over%20%7C%20%2B150",
    "/tools/pick-analyzer?legs=MLB%20%7C%20Aaron%20Judge%20%7C%20Home%20Runs%20%7C%20Over%20%7C%20%2B250",
]

QC_PLAYER = {"nba": "Qcquick Nbaguard", "wnba": "Qcquick Wnbaguard"}
QC_PRICE = -113
_MTIME = [1_700_100_000]


def _et(dt):
    return dt.astimezone(DISPLAY_TZ).strftime("%Y-%m-%d %H:%M")


def _write_props(root: Path, sport: str, age_hours: float) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    rows = []
    for i, (stat, line, book) in enumerate((("PTS", 21.5, "DraftKings"), ("PTS", 21.5, "FanDuel"),
                                             ("REB", 7.5, "DraftKings"))):
        rows.append({"Player": QC_PLAYER[sport], "Team": "QCX", "Stat": stat, "MarketKey": f"player_{stat.lower()}",
                     "Line": line, "CurrentLine": line, "OpenLine": line, "Game": "QCX @ QCY", "Book": book,
                     "OverOdds": QC_PRICE, "UnderOdds": -107, "OpenOverOdds": QC_PRICE, "OpenUnderOdds": -107,
                     "LastUpdated": _et(now - timedelta(hours=age_hours, minutes=i)),
                     # b12eec3 remediation: freshness is governed ONLY by the zone-explicit provider source time
                     "SourceUpdatedAtUTC": (now - timedelta(hours=age_hours, minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ")})
    path = root / "props" / ("NBA_Props.csv" if sport == "nba" else "WNBA_Props.csv")
    pd.DataFrame(rows).to_csv(path, index=False)
    _MTIME[0] += 10
    os.utime(path, (_MTIME[0], _MTIME[0]))


def _synthetic_statcast(role: str) -> pd.DataFrame:
    """Expected-vs-actual profile rows in the Statcast loader's column layout (enough qualified players for
    both the 'lucky' and 'unlucky' boards)."""
    rows = []
    for i in range(30):
        woba = 0.300 + (i % 10) * 0.006
        rows.append({"Player": f"Qc {role.title()} {i:02d}", "Expected_pa": 250 + i * 5, "Expected_ba": 0.250,
                     "Expected_est_ba": 0.255, "Expected_woba": woba, "Expected_est_woba": woba + (i - 15) * 0.002,
                     "Percentile_hard_hit_percent": 50 + i, "Barrel_brl_percent": 8.0 + i / 10,
                     "FetchedAt": "2026-10-01T12:00:00Z"})
    return pd.DataFrame(rows)


@contextlib.contextmanager
def sandbox():
    """Private DATA_DIR (synthetic props), patched Statcast data boundary, temp run log. Restored on exit."""
    names = ("DATA_DIR", "DERIVATIVE_SPORT_PROP_PATHS", "ACTIVE_USER_HEARTBEAT_PATH", "LIVE_SCORES_PATH",
             "load_statcast_dataframe")
    saved = {n: getattr(app_module, n) for n in names}
    saved_log = (qc_tracking.QC_RUN_LOG_PATH, qc_tracking.TRACKING_DIR)
    td = tempfile.TemporaryDirectory(prefix="qc_quick_tools_")
    root = Path(td.name)
    for sub in ("props", "cache", "odds", "schedules", "gamelogs", "tracking", "injuries", "live_scores"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    statcast = {"hitter": _synthetic_statcast("hitter"), "pitcher": _synthetic_statcast("pitcher")}
    try:
        app_module.DATA_DIR = root
        app_module.DERIVATIVE_SPORT_PROP_PATHS = {k: root / "props" / v.name
                                                  for k, v in saved["DERIVATIVE_SPORT_PROP_PATHS"].items()}
        app_module.ACTIVE_USER_HEARTBEAT_PATH = root / "live_scores" / "active_user_heartbeat.txt"
        app_module.LIVE_SCORES_PATH = root / "live_scores" / "Live_Scores.csv"
        app_module.load_statcast_dataframe = lambda role="hitter", *a, **k: statcast.get(role, pd.DataFrame()).copy()
        qc_tracking.TRACKING_DIR = root / "tracking"
        qc_tracking.QC_RUN_LOG_PATH = root / "tracking" / "QC_Run_Log.csv"
        app_module.RUNTIME_TTL_CACHE.clear()
        _write_props(root, "nba", 1.0)
        _write_props(root, "wnba", 1.0)
        yield root
    finally:
        for n, v in saved.items():
            setattr(app_module, n, v)
        qc_tracking.QC_RUN_LOG_PATH, qc_tracking.TRACKING_DIR = saved_log
        app_module.RUNTIME_TTL_CACHE.clear()
        td.cleanup()


def _changed_loader_checks(client, root: Path) -> list[str]:
    """Best Lines / Risk Radar / Slate Pulse read the central NBA/WNBA executable-props loaders: fresh
    synthetic quote present, stale feed -> nothing executable."""
    failures = []
    for state, age in (("fresh", 1.0), ("stale", app_module.LIVE_LINES_MAX_AGE_HOURS + 4)):
        _write_props(root, "nba", age)
        _write_props(root, "wnba", age)
        app_module.RUNTIME_TTL_CACHE.clear()
        bl = client.get("/tools/best-lines").get_data(as_text=True)
        rr = client.get("/tools/risk-radar").get_data(as_text=True)
        ctx = app_module.build_slate_pulse_context()
        pulse = {r["key"]: r for r in (ctx.get("rows", []) if isinstance(ctx, dict) else [])}
        n_props = int(pulse.get("nba", {}).get("props") or 0)
        names = list(QC_PLAYER.values())
        if state == "fresh":
            if not all(n in bl for n in names) or str(QC_PRICE) not in bl:
                failures.append("best-lines: fresh synthetic NBA/WNBA quote did not render")
            if not all(n in rr for n in names):
                failures.append("risk-radar: fresh synthetic NBA/WNBA markets did not render")
            if n_props <= 0:
                failures.append("slate-pulse: fresh synthetic NBA feed counted 0 executable props")
        else:
            if any(n in bl for n in names) or str(QC_PRICE) in bl:
                failures.append("best-lines: a STALE NBA/WNBA quote rendered")
            if any(n in rr for n in names):
                failures.append("risk-radar: a STALE NBA/WNBA market rendered")
            if n_props != 0 or pulse.get("nba", {}).get("state") != "stale":
                failures.append(f"slate-pulse: stale NBA feed reads {pulse.get('nba')}")
    _write_props(root, "nba", 1.0)
    _write_props(root, "wnba", 1.0)
    app_module.RUNTIME_TTL_CACHE.clear()
    return failures


def run_qc() -> dict:
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    failures: list[str] = []
    checks = 0
    with sandbox() as root, isolated_member_client(plan="all_access") as client:
        for path, markers in ROUTES:
            checks += 1
            try:
                resp = client.get(path)
            except Exception as exc:  # a raised exception in the view is the worst case
                failures.append(f"{path}: raised {type(exc).__name__}: {str(exc)[:120]}")
                continue
            text = resp.get_data(as_text=True)
            if resp.status_code != 200:
                failures.append(f"{path}: HTTP {resp.status_code} (expected 200).")
            elif not any(marker in text for marker in markers):
                failures.append(f"{path}: 200 but none of the expected markers rendered {markers}.")

        for path in LOGIC_PATHS:
            checks += 1
            try:
                resp = client.get(path)
            except Exception as exc:
                failures.append(f"{path}: raised {type(exc).__name__}: {str(exc)[:120]}")
                continue
            if resp.status_code != 200:
                failures.append(f"{path}: HTTP {resp.status_code} (expected 200).")

        # The ticket parser must actually flag an all-over injured ticket.
        checks += 1
        ticket = ("MLB | Aaron Judge | Home Runs | Over | +150\n"
                  "MLB | Aaron Judge | Total Bases | Over | +120\n"
                  "NBA | Some Longshot | Points | Over | +800")
        from urllib.parse import quote
        tresp = client.get("/tools/ticket-check?legs=" + quote(ticket))
        ttext = tresp.get_data(as_text=True)
        if "All-OVER" not in ttext:
            failures.append("ticket-check: an all-over ticket did not raise the All-OVER warning.")

        # The pick analyzer must actually read a pasted MLB leg against Statcast: a matched
        # player renders a lean chip (pa-lean). This guards the parse -> statcast signal ->
        # template pipeline, incl. the pitcher-stat fallback.
        checks += 1
        pick_ticket = ("MLB | Aaron Judge | Home Runs | Over | +250\n"
                       "MLB | Tarik Skubal | Strikeouts | Over | -115")
        presp = client.get("/tools/pick-analyzer?legs=" + quote(pick_ticket))
        ptext = presp.get_data(as_text=True)
        if "pa-lean" not in ptext:
            failures.append("pick-analyzer: a known MLB slugger + pitcher produced no Statcast data read (pa-lean).")

        # Changed loaders (this branch): fresh vs stale through the central gate.
        checks += 1
        failures.extend(_changed_loader_checks(client, root))

        report = {
            "checked_at": checked_at,
            "check_count": checks,
            "failure_count": len(failures),
            "clean": not failures,
            "failures": failures,
        }
        append_qc_run_log("quick_tools", {   # temp run log inside the sandbox
            "checked_at": checked_at,
            "clean": not failures,
            "pass_count": checks - len(failures),
            "warning_count": 0,
            "failure_count": len(failures),
            "notes": f"Quick Tools smoke: {checks - len(failures)}/{checks} checks passed.",
        })
    return report


def main() -> int:
    report = run_qc()
    print("=" * 64)
    print("QUICK TOOLS SMOKE QC")
    print("=" * 64)
    print(f"Checked at: {report['checked_at']}")
    print(f"Checks: {report['check_count']}")
    print(f"Failures: {report['failure_count']}")
    print(f"Clean: {report['clean']}")
    print()
    if report["clean"]:
        print("All Quick Tools rendered and their logic paths held.")
        return 0
    for failure in report["failures"]:
        print(f"[FAIL] {failure}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
