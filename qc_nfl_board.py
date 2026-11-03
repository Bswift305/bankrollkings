"""QC: NFL command board (/sports/nfl + its method boards + workbook matchup pages).

Self-contained (2026-11-03): this QC must pass on its merits on any checkout, with no network and no
local-only data, so it no longer depends on
  * the untracked one-off floor workbook `NFL_Floor_Plays_01032026.xlsx` -- a SYNTHETIC workbook in the
    real sheet layout is written to a temp dir and parsed by the real `load_nfl_floor_board` (disk cache
    bypassed, in-process cache entry dropped afterwards);
  * a QC account in the user store -- requests use the in-memory owner principal from
    `services.qc_auth.isolated_owner_client` (nothing is written to any user store);
  * stale page markers -- "Platform Lens" left the NFL dashboard in 6e32a16 and "Why This Method
    Matters" / "Historical Coverage" became "How to read this board" / "Data coverage" in 90dcbe7
    (both 2026-09-12); the markers below are what these routes actually render.
History rows come from the tracked `data/historical/NFL_*` files.

/sports/nfl renders the weather column changed by D1, so the slate weather contract is asserted on this
route too (synthetic slate via the D1 QC's fixture): missing weather reads "Weather unavailable" (never
indoor/calm/dome/0 mph) and a licensed, dated, matching forecast shows its real wind.
"""
from __future__ import annotations

import contextlib
import os
import tempfile
from datetime import datetime
from pathlib import Path

os.environ.setdefault("SECRET_KEY", "qc-nfl-board")  # app import needs one; synthetic QC

import app as bk  # noqa: E402
from app import (  # noqa: E402
    app,
    build_football_history_lab,
    build_football_history_status,
    build_football_live_games,
    build_football_live_prop_board,
    load_nfl_game_market_odds,
    load_nfl_props,
    load_nfl_schedule,
)
from services.qc_auth import isolated_owner_client  # noqa: E402
from services.qc_tracking import append_qc_run_log  # noqa: E402

FLOOR_WORKBOOK_NAME = "NFL_Floor_Plays_01032026.xlsx"
FIXTURE_SHEET = "BUF @ MIA"


def _contains_all(text: str, snippets: list[str]) -> bool:
    return all(snippet in text for snippet in snippets)


def _write_synthetic_floor_workbook(path: Path) -> None:
    """A minimal workbook in the layout `load_nfl_floor_board` parses: a SUMMARY sheet (title,
    PARAMETERS block, TOP FLOOR PLAYS block) and one matchup sheet (title, market line, two filler
    rows, then play rows: player, team, stat, line, floor, avg, hit%, streak, last-5 games)."""
    from openpyxl import Workbook

    plays = [
        ["QC Passer", "BUF", "Pass Att", 31.5, 32, 35.4, "100%", 5, 33, 36, 34, 38, 36],
        ["QC Receiver", "BUF", "Rec Yds", 54.5, 61, 78.2, "100%", 5, 66, 81, 72, 95, 77],
        ["QC Runner", "MIA", "Rush Yds", 48.5, 50, 63.0, "80%", 3, 55, 71, 44, 66, 79],
    ]
    wb = Workbook()
    summary = wb.active
    summary.title = "SUMMARY"
    for row in (["NFL Floor Play Heat Map (QC fixture)"], ["PARAMETERS"], ["Last 5 games, floor >= line"],
                ["TOP FLOOR PLAYS"], ["Player"], *plays):
        summary.append(row)
    sheet = wb.create_sheet(FIXTURE_SHEET)
    for row in (["Buffalo Bills @ Miami Dolphins"], ["BUF -3.0 | Total 44.5"], [""], ["Player"], *plays):
        sheet.append(row)
    wb.save(path)


@contextlib.contextmanager
def synthetic_floor_workbook():
    """Point the real `load_nfl_floor_board` at a synthetic workbook for the duration (BASE_DIR is
    swapped only inside that call; disk cache read/write are bypassed so nothing lands in data/cache)."""
    with tempfile.TemporaryDirectory(prefix="qc_nfl_floor_", ignore_cleanup_errors=True) as tmp:
        tmp_dir = Path(tmp)
        _write_synthetic_floor_workbook(tmp_dir / FLOOR_WORKBOOK_NAME)
        real_loader = bk.load_nfl_floor_board

        def fixture_loader():
            saved = (bk.BASE_DIR, bk._read_disk_ttl_cached_value, bk._write_disk_ttl_cached_value)
            bk.BASE_DIR = tmp_dir
            bk._read_disk_ttl_cached_value = lambda *a, **k: (False, None)
            bk._write_disk_ttl_cached_value = lambda *a, **k: None
            try:
                return real_loader()
            finally:
                bk.BASE_DIR, bk._read_disk_ttl_cached_value, bk._write_disk_ttl_cached_value = saved

        bk.RUNTIME_TTL_CACHE.pop("nfl_floor_board", None)
        bk.load_nfl_floor_board = fixture_loader
        try:
            yield
        finally:
            bk.load_nfl_floor_board = real_loader
            bk.RUNTIME_TTL_CACHE.pop("nfl_floor_board", None)


def check_slate_weather(issues: list[dict], notes: list[str]) -> None:
    """D1 contract on /sports/nfl's slate weather column (synthetic slate, offline)."""
    import qc_nfl_weather_venue_integrity as wxqc

    def _slate_text(client):
        resp = client.get("/sports/nfl?postseason=1")
        region = wxqc._region_dashboard(resp.get_data(as_text=True)) if resp.status_code == 200 else None
        return resp.status_code, (wxqc._strip(region) if region is not None else None)

    bad = []
    gate_before = bk.BK_WEATHER_SOURCE_LICENSED
    with tempfile.TemporaryDirectory(prefix="qc_nfl_board_wx_") as tmp:
        fx = wxqc.Fixture(Path(tmp))
        fx.install()
        try:
            client = app.test_client()
            fx.nfl_games = [wxqc._game("New England Patriots", "Miami Dolphins", wxqc.D_GAME)]
            for gate in (False, True):
                bk.BK_WEATHER_SOURCE_LICENSED = gate
                fx.set_weather([])
                status, text = _slate_text(client)
                if text is None:
                    bad.append(f"/sports/nfl slate not rendered (HTTP {status}) with a synthetic game")
                    continue
                hit = wxqc.FORBIDDEN_OUTDOOR.search(text)
                if hit or wxqc.UNAVAILABLE not in text:
                    bad.append(f"/sports/nfl slate, missing weather (licence {'on' if gate else 'off'}): "
                               f"{text[:140]!r} (forbidden={hit.group(0) if hit else None})")
            bk.BK_WEATHER_SOURCE_LICENSED = True
            fx.set_weather([{"Date": wxqc.D_GAME, "HomeTeam": "Miami Dolphins", "WindMph": 17.0, "GustMph": 26.0,
                             "PrecipMm": 9, "TempF": 79, "Roof": "outdoor", "Updated": wxqc.D_GAME + " 06:00"}])
            status, text = _slate_text(client)
            if not text or "17 mph" not in text:
                bad.append(f"/sports/nfl slate: licensed matching forecast (17 mph) not shown ({(text or '')[:140]!r})")
        finally:
            fx.restore()
            bk.BK_WEATHER_SOURCE_LICENSED = gate_before
            fx.clear_caches()
    for message in bad:
        issues.append({"severity": "high", "category": "weather", "message": message})
    if not bad:
        notes.append("/sports/nfl slate weather: missing -> 'Weather unavailable' (licence off and on), "
                     "licensed matching forecast -> '17 mph'")


def run_qc() -> dict:
    issues: list[dict] = []
    notes: list[str] = []

    history_lab = build_football_history_lab("nfl")
    history_status = build_football_history_status(history_lab)
    live_odds = load_nfl_game_market_odds()
    live_schedule = load_nfl_schedule()
    live_props = load_nfl_props()
    live_games = build_football_live_games(live_odds, live_schedule, date_filter="all")
    live_prop_rows = build_football_live_prop_board(
        live_props,
        live_odds,
        live_schedule,
        method_key="props",
        date_filter="all",
    )

    if int(history_lab.get("props_history_rows") or 0) <= 0:
        issues.append({
            "severity": "high",
            "category": "history",
            "message": "NFL prop archive is empty.",
        })
    if int(history_lab.get("game_line_history_rows") or 0) <= 0:
        issues.append({
            "severity": "high",
            "category": "history",
            "message": "NFL game-line history is empty.",
        })
    if history_status.get("state") != "ready":
        issues.append({
            "severity": "medium",
            "category": "history",
            "message": f"NFL history status is {history_status.get('state') or 'unknown'}, not ready.",
        })

    if not live_games and not live_prop_rows:
        notes.append(
            f"Live NFL slate is empty right now (schedule {len(live_schedule)}, odds {len(live_odds)}, props {len(live_props)}). "
            "Workbook and historical layers must carry the board until the next live pull."
        )

    with synthetic_floor_workbook(), isolated_owner_client() as client:
        board = bk.load_nfl_floor_board()
        if not board.get("available"):
            issues.append({
                "severity": "high",
                "category": "workbook",
                "message": "NFL floor workbook (synthetic fixture) is not available to the parser.",
            })

        games = list(board.get("games", []))
        top_plays = list(board.get("top_plays", []))
        if board.get("available") and not games:
            issues.append({
                "severity": "high",
                "category": "workbook",
                "message": "NFL floor workbook loaded but no matchup tabs were parsed.",
            })
        if board.get("available") and not top_plays:
            issues.append({
                "severity": "medium",
                "category": "workbook",
                "message": "NFL floor workbook loaded but no top plays were parsed.",
            })

        route_expectations = [
            ("/sports/nfl?postseason=1", ["Weekly Script Board", "Closeout Check", "Live Feed Status"]),
            ("/sports/nfl/game-lines?postseason=1", ["How to read this board", "Data coverage", "Plain-English Verdict"]),
            ("/sports/nfl/totals?postseason=1", ["How to read this board", "Data coverage", "Plain-English Verdict"]),
            ("/sports/nfl/trends?postseason=1", ["How to read this board", "Data coverage", "Plain-English Verdict"]),
            ("/sports/nfl/props?postseason=1", ["Market", "Confidence", "Player"]),
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

        if not games:
            issues.append({
                "severity": "high",
                "category": "matchup_route",
                "message": "No workbook matchup to exercise the matchup routes.",
            })
        else:
            first = games[0]
            sheet = str(first.get("sheet", "")).strip()
            slug = str(first.get("matchup_slug", "")).strip()
            if not sheet or not slug:
                issues.append({
                    "severity": "high",
                    "category": "matchup_route",
                    "message": f"Workbook matchup lacks a sheet/slug identity (sheet={sheet!r}, slug={slug!r}).",
                })
            if sheet:
                response = client.get(f"/sports/nfl/matchup/{sheet}?postseason=1")
                if response.status_code != 200:
                    issues.append({
                        "severity": "high",
                        "category": "matchup_route",
                        "message": f"Sheet-based NFL matchup route failed for {sheet} ({response.status_code}).",
                    })
            if slug:
                response = client.get(f"/sports/nfl/matchup/game/{slug}?postseason=1")
                if response.status_code != 200:
                    issues.append({
                        "severity": "high",
                        "category": "matchup_route",
                        "message": f"Slug-based NFL matchup route failed for {slug} ({response.status_code}).",
                    })
            # negative control: the routes really resolve against the workbook (an unknown tab 404s)
            response = client.get("/sports/nfl/matchup/game/qc-nowhere-at-qc-never?postseason=1")
            if response.status_code != 404:
                issues.append({
                    "severity": "high",
                    "category": "matchup_route",
                    "message": f"Unknown NFL matchup returned {response.status_code}, expected 404.",
                })

    check_slate_weather(issues, notes)

    report = {
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "workbook_games": len(games),
        "workbook_top_plays": len(top_plays),
        "history_props_rows": int(history_lab.get("props_history_rows") or 0),
        "history_line_rows": int(history_lab.get("game_line_history_rows") or 0),
        "live_games": len(live_games),
        "live_prop_rows": len(live_prop_rows),
        "issue_count": len(issues),
        "issues": issues,
        "notes": notes,
    }
    append_qc_run_log("nfl_board", report)
    return report


def main() -> int:
    report = run_qc()
    print("=" * 60)
    print("BANKROLL KINGS NFL QC")
    print("=" * 60)
    print(f"Checked at: {report['checked_at']}")
    print(f"Workbook matchups (synthetic fixture): {report['workbook_games']}")
    print(f"Workbook top plays (synthetic fixture): {report['workbook_top_plays']}")
    print(f"Historical prop rows: {report['history_props_rows']}")
    print(f"Historical game-line rows: {report['history_line_rows']}")
    print(f"Live game rows: {report['live_games']}")
    print(f"Live prop rows: {report['live_prop_rows']}")
    print(f"Issues found: {report['issue_count']}")
    print()
    for note in report["notes"]:
        print(f"[NOTE] {note}")
    if report["notes"]:
        print()
    if not report["issues"]:
        print("No blocking NFL QC issues detected.")
        return 0

    for issue in report["issues"]:
        print(f"[{issue['severity'].upper()}] {issue['category']}: {issue['message']}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
