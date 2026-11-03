"""QC: CFB command board (/sports/ncaaf + its method boards).

Self-contained (2026-11-03): this QC must pass on its merits on any checkout, with no network and no
local-only data, so it no longer depends on
  * the untracked CFBD/ESPN refresh outputs (current roster, player-stats history, returning production,
    transfer portal, roster coverage) -- SYNTHETIC CSVs in the real on-disk schema are written to a temp
    dir and read through the real formatters (`_format_ncaaf_*`) and the real current-season builder;
  * a QC account in the user store -- requests use the in-memory owner principal from
    `services.qc_auth.isolated_owner_client` (nothing is written to any user store);
  * a stale page marker -- "Historical Coverage" became "Data coverage" in 90dcbe7 (2026-09-12); the
    markers below are what these routes actually render.

/sports/ncaaf renders the slate weather column changed by D1: CFB has no wind source for that slate, so
every CFB row must read "Weather unavailable" (never indoor/calm/dome/0 mph) -- asserted on a synthetic
open-air college game via the D1 QC's fixture.
"""
from __future__ import annotations

import contextlib
import os
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd

os.environ.setdefault("SECRET_KEY", "qc-cfb-board")  # app import needs one; synthetic QC

import app as bk  # noqa: E402
from app import (  # noqa: E402
    app,
    build_football_history_lab,
    build_football_history_status,
    build_football_live_games,
    build_football_live_prop_board,
    load_ncaaf_game_market_odds,
    load_ncaaf_props,
    load_ncaaf_schedule,
)
from services.qc_auth import isolated_owner_client  # noqa: E402
from services.qc_tracking import append_qc_run_log  # noqa: E402


def _contains_all(text: str, snippets: list[str]) -> bool:
    return all(snippet in text for snippet in snippets)


# --- synthetic CFB current-season inputs (real column names; three programs) -------------------------
_TEAMS = ("Georgia", "Ohio State", "Oregon", "Miami")
_ROSTER = [
    # PlayerID, Player, Team, Position, Class
    ("qc1", "QC Quarterback One", "Georgia", "QB", "4"),
    ("qc2", "QC Tailback One", "Georgia", "RB", "3"),
    ("qc3", "QC Linebacker One", "Georgia", "LB", "4"),
    ("qc4", "QC Quarterback Two", "Ohio State", "QB", "3"),
    ("qc5", "QC Receiver Two", "Ohio State", "WR", "2"),
    ("qc6", "QC Safety Two", "Ohio State", "S", "4"),
    ("qc7", "QC Quarterback Three", "Oregon", "QB", "4"),
    ("qc8", "QC Receiver Three", "Oregon", "WR", "3"),
    ("qc9", "QC Linebacker Three", "Oregon", "LB", "3"),
    ("qc10", "QC Quarterback Four", "Miami", "QB", "4"),
    ("qc11", "QC End Four", "Miami", "TE", "3"),
    ("qc12", "QC Linebacker Four", "Miami", "LB", "4"),
]


def _write_synthetic_cfb_inputs(tmp: Path) -> dict[str, Path]:
    paths = {
        "roster": tmp / "NCAAF_CurrentRoster.csv",
        "history": tmp / "NCAAF_PlayerStats_History.csv",
        "returning": tmp / "NCAAF_ReturningProduction.csv",
        "portal": tmp / "NCAAF_TransferPortal.csv",
        "coverage": tmp / "NCAAF_CurrentRoster_Coverage.csv",
    }
    pd.DataFrame([{"PlayerID": pid, "Player": name, "Team": team, "Position": pos, "Class": cls}
                  for pid, name, team, pos, cls in _ROSTER]).to_csv(paths["roster"], index=False)
    history = []
    for pid, name, team, pos, cls in _ROSTER:
        stats = {"PassYds": 3100 if pos == "QB" else 0, "PassTD": 24 if pos == "QB" else 0,
                 "RushYds": 900 if pos == "RB" else 40, "Receptions": 55 if pos in ("WR", "TE") else 0,
                 "RecYds": 760 if pos in ("WR", "TE") else 0, "Tackles": 80 if pos in ("LB", "S") else 0}
        history.append({"PlayerID": pid, "Player": name, "Team": team, "Position": pos, "Class": cls,
                        "Season": 2025, "Games": 12, **stats})
    pd.DataFrame(history).to_csv(paths["history"], index=False)
    pd.DataFrame([{"Year": 2026, "Team": team, "Conference": "QC", "ReturningProduction": rp,
                   "PassingUsage": rp, "RushingUsage": rp, "ReceivingUsage": rp}
                  for team, rp in zip(_TEAMS, (0.72, 0.55, 0.64, 0.48))]).to_csv(paths["returning"], index=False)
    pd.DataFrame([{"Year": 2026, "PlayerID": "qc99", "Player": "QC Portal Mover", "Position": "WR",
                   "OriginTeam": "Oregon", "DestinationTeam": "Georgia", "TransferDate": "2026-01-10",
                   "Rating": 0.9, "Stars": 4, "Eligibility": "Immediate"}]).to_csv(paths["portal"], index=False)
    pd.DataFrame([{"RequestedTeam": team, "ResolvedTeam": team, "RosterRows": 3, "Status": "ok", "Error": ""}
                  for team in _TEAMS]).to_csv(paths["coverage"], index=False)
    return paths


@contextlib.contextmanager
def synthetic_cfb_season_inputs():
    """Swap the five NCAAF current-season loaders for readers of the synthetic CSVs (same formatters as
    the real loaders), and clear the memoized context before and after."""
    with tempfile.TemporaryDirectory(prefix="qc_cfb_board_") as tmp:
        paths = _write_synthetic_cfb_inputs(Path(tmp))

        def reader(key, transform=None):
            return lambda: bk._load_cached_csv(paths[key], transform=transform, default=pd.DataFrame())

        replacements = {
            "load_ncaaf_current_roster": reader("roster", bk._format_ncaaf_current_roster),
            "load_ncaaf_player_stats_history": reader("history", bk._format_ncaaf_player_stats_history),
            "load_ncaaf_returning_production": reader("returning", bk._format_ncaaf_returning_production),
            "load_ncaaf_transfer_portal": reader("portal", bk._format_ncaaf_transfer_portal),
            "load_ncaaf_current_roster_coverage": reader("coverage"),
        }
        saved = {name: getattr(bk, name) for name in replacements}
        bk._NCAAF_SEASON_CTX_CACHE.clear()
        for name, fn in replacements.items():
            setattr(bk, name, fn)
        try:
            yield
        finally:
            for name, fn in saved.items():
                setattr(bk, name, fn)
            bk._NCAAF_SEASON_CTX_CACHE.clear()


def check_slate_weather(issues: list[dict], notes: list[str]) -> None:
    """D1 contract on /sports/ncaaf's slate weather column (synthetic open-air college game)."""
    import qc_nfl_weather_venue_integrity as wxqc

    bad = []
    gate_before = bk.BK_WEATHER_SOURCE_LICENSED
    with tempfile.TemporaryDirectory(prefix="qc_cfb_board_wx_") as tmp:
        fx = wxqc.Fixture(Path(tmp))
        fx.install()
        try:
            client = app.test_client()
            fx.cfb_games = [wxqc._game("Georgia Tech", "Miami", wxqc.D_GAME)]
            for gate in (False, True):
                bk.BK_WEATHER_SOURCE_LICENSED = gate
                fx.clear_caches()
                resp = client.get("/sports/ncaaf?postseason=1")
                region = wxqc._region_dashboard(resp.get_data(as_text=True)) if resp.status_code == 200 else None
                if region is None:
                    bad.append(f"/sports/ncaaf slate not rendered (HTTP {resp.status_code}) with a synthetic game")
                    continue
                text = wxqc._strip(region)
                hit = wxqc.FORBIDDEN_OUTDOOR.search(text)
                if hit or wxqc.UNAVAILABLE not in text:
                    bad.append(f"/sports/ncaaf slate (licence {'on' if gate else 'off'}): {text[:140]!r} "
                               f"(forbidden={hit.group(0) if hit else None})")
        finally:
            fx.restore()
            bk.BK_WEATHER_SOURCE_LICENSED = gate_before
            fx.clear_caches()
    for message in bad:
        issues.append({"severity": "high", "category": "weather", "message": message})
    if not bad:
        notes.append("/sports/ncaaf slate weather: an open-air college game with no wind source reads "
                     "'Weather unavailable' (licence off and on), never indoor/calm/dome/0 mph")


def run_qc() -> dict:
    issues: list[dict] = []
    notes: list[str] = []

    history_lab = build_football_history_lab("ncaaf")
    history_status = build_football_history_status(history_lab)
    live_odds = load_ncaaf_game_market_odds()
    live_schedule = load_ncaaf_schedule()
    live_props = load_ncaaf_props()
    live_games = build_football_live_games(live_odds, live_schedule, date_filter="all")
    live_prop_rows = build_football_live_prop_board(
        live_props,
        live_odds,
        live_schedule,
        method_key="props",
        date_filter="all",
    )

    if int(history_lab.get("props_history_rows") or 0) == 0 and int(history_lab.get("game_line_history_rows") or 0) == 0:
        notes.append("CFB historical datasets are still empty; current roster, returning production, and portal layers are carrying the sport for now.")

    if not live_games and not live_prop_rows:
        notes.append(
            f"Live CFB slate is empty right now (schedule {len(live_schedule)}, odds {len(live_odds)}, props {len(live_props)})."
        )

    with synthetic_cfb_season_inputs(), isolated_owner_client() as client:
        current_context = bk.build_ncaaf_current_season_context()

        if current_context.get("state") != "ready":
            issues.append({
                "severity": "high",
                "category": "current_context",
                "message": f"CFB current-season context is {current_context.get('state') or 'unknown'}, not ready.",
            })

        if int((current_context.get("coverage_summary") or {}).get("ok") or 0) <= 0:
            issues.append({
                "severity": "high",
                "category": "rosters",
                "message": "No clean CFB roster coverage rows reached the current-season context.",
            })

        if int((current_context.get("coverage_summary") or {}).get("error") or 0) > 0:
            issues.append({
                "severity": "medium",
                "category": "rosters",
                "message": f"{current_context['coverage_summary']['error']} CFB roster pulls errored on the last refresh.",
            })

        if not current_context.get("team_signals"):
            issues.append({
                "severity": "medium",
                "category": "signals",
                "message": "CFB team signals are empty.",
            })

        # Markers must be what these routes ACTUALLY render, not aspirational text.
        # "Platform Lens" lives on other page types (game_lines/matchup), never on
        # the NCAAF command board. /sports/ncaaf/props is the shared props SCREENER
        # (render_props_screener_page -> props.html), so it renders board decision
        # columns, not the method-board markers (commit ad57615). "Historical
        # Coverage" was relabelled "Data coverage" in 90dcbe7.
        route_expectations = [
            ("/sports/ncaaf?postseason=1", ["Roster & Continuity", "Closeout Check"]),
            ("/sports/ncaaf/game-lines?postseason=1", ["Market Read", "Data coverage"]),
            ("/sports/ncaaf/totals?postseason=1", ["Matchup Read", "Data coverage"]),
            ("/sports/ncaaf/trends?postseason=1", ["Trend Read", "Data coverage"]),
            ("/sports/ncaaf/props?postseason=1", ["Market", "Confidence", "Player"]),
        ]
        for route, snippets in route_expectations:
            response = client.get(route)
            body = response.get_data(as_text=True)
            if response.status_code != 200:
                issues.append({
                    "severity": "high",
                    "category": "routes",
                    "message": f"{route} returned {response.status_code}.",
                })
                continue
            missing = [snippet for snippet in snippets if snippet not in body]
            if missing:
                issues.append({
                    "severity": "medium",
                    "category": "routes",
                    "message": f"{route} is missing expected framing text: {missing}.",
                })
        # the synthetic roster actually reached the command board (not an empty "waiting" shell)
        body = client.get("/sports/ncaaf?postseason=1").get_data(as_text=True)
        roster_section = body.split("Roster & Continuity", 1)[-1] if "Roster & Continuity" in body else ""
        if not any(team in roster_section for team in ("Ohio State", "Oregon", "Georgia")):
            issues.append({
                "severity": "high",
                "category": "routes",
                "message": "/sports/ncaaf did not render any team from the current-season roster layer.",
            })

    check_slate_weather(issues, notes)

    report = {
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "context_state": current_context.get("state") or "",
        "roster_ok": int((current_context.get("coverage_summary") or {}).get("ok") or 0),
        "team_signals": len(current_context.get("team_signals") or []),
        "history_props_rows": int(history_lab.get("props_history_rows") or 0),
        "history_line_rows": int(history_lab.get("game_line_history_rows") or 0),
        "history_state": history_status.get("state") or "",
        "live_games": len(live_games),
        "live_prop_rows": len(live_prop_rows),
        "issue_count": len(issues),
        "issues": issues,
        "notes": notes,
    }
    append_qc_run_log("cfb_board", report)
    return report


def main() -> int:
    report = run_qc()
    print("=" * 60)
    print("BANKROLL KINGS CFB QC")
    print("=" * 60)
    print(f"Checked at: {report['checked_at']}")
    print(f"Current context (synthetic inputs): {report['context_state']}")
    print(f"Roster coverage ok (synthetic inputs): {report['roster_ok']}")
    print(f"Team signals: {report['team_signals']}")
    print(f"Historical prop rows: {report['history_props_rows']}")
    print(f"Historical game-line rows: {report['history_line_rows']}")
    print(f"History state: {report['history_state']}")
    print(f"Live game rows: {report['live_games']}")
    print(f"Live prop rows: {report['live_prop_rows']}")
    print(f"Issues found: {report['issue_count']}")
    print()
    for note in report["notes"]:
        print(f"[NOTE] {note}")
    if report["notes"]:
        print()
    if not report["issues"]:
        print("No blocking CFB QC issues detected.")
        return 0

    for issue in report["issues"]:
        print(f"[{issue['severity'].upper()}] {issue['category']}: {issue['message']}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
