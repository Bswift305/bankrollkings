"""QC: NBA team-mapping abstention under the NBA.com data-rights gate (F3b).

A prop row's NBA team comes ONLY from build_current_team_map (gamelogs + player snapshot + roster
overrides). Gamelogs and the snapshot are NBA.com-derived and gated empty while BK_NBA_STATS_ENABLED is
off, and the licensed Odds props feed carries the matchup (AWAY@HOME) but not the player's side. So:

  * gated + EMPTY team map      -> qc_nba_board records TEAM_MAPPING_UNAVAILABLE (data-rights gated),
                                   no MEDIUM defect, exit 0 when nothing else is wrong;
  * stats ENABLED + missing     -> the MEDIUM "missing team mapping" defect fires, exit 1 (unchanged);
  * gated + NON-empty map + miss -> the MEDIUM still fires (a real defect is never hidden);
  * a team is NEVER derived from the Game string;
  * the market-only player page abstains VISIBLY under the gate and is unchanged when stats are enabled.

Synthetic fixtures only; loaders are monkeypatched; no network, no production data, no file writes
(the QC run-log append is stubbed). Exits 0 when every check passes, 1 otherwise.
"""
from __future__ import annotations

import contextlib
import io
import os
from datetime import datetime, timedelta

import pandas as pd

import app
import qc_nba_board
from services import nba_source_gate

GATE_ENV = "BK_NBA_STATS_ENABLED"
LABEL = "TEAM_MAPPING_UNAVAILABLE (data-rights gated)"
UI_LABEL = "Team unavailable (data-rights gated)"

_TODAY = datetime.now().date()
_D = lambda n: (_TODAY + timedelta(days=n)).strftime("%Y-%m-%d")  # noqa: E731

GAME = "Boston Celtics@Dallas Mavericks"   # both names resolve in TEAM_NAME_TO_ABBR (BOS / DAL)

PROPS = pd.DataFrame([
    {"Player": "Alpha Guard", "Stat": "PTS", "Line": 20.5, "CurrentLine": 20.5, "OverOdds": -110,
     "UnderOdds": -110, "Book": "DraftKings", "Game": GAME, "Team": ""},
    {"Player": "Bravo Wing", "Stat": "REB", "Line": 6.5, "CurrentLine": 6.5, "OverOdds": -115,
     "UnderOdds": -105, "Book": "DraftKings", "Game": GAME, "Team": None},
    {"Player": "Charlie Big", "Stat": "AST", "Line": 3.5, "CurrentLine": 3.5, "OverOdds": 100,
     "UnderOdds": -120, "Book": "FanDuel", "Game": GAME, "Team": ""},
])
# Gamelogs that map ONE of the three players (so two rows stay missing when stats are enabled).
GAMELOGS_PARTIAL = pd.DataFrame([
    {"Player": "Alpha Guard", "Team": "BOS", "Date": _D(-2), "PTS": 22},
])
PLAYOFF_LOGS = pd.DataFrame([{"Player": "Alpha Guard", "Team": "BOS", "Date": _D(-1)}])
PLAYOFF_RESULTS = pd.DataFrame([{"Away": "BOS", "Home": "DAL", "Date": _D(-1)}])
SCHEDULE = pd.DataFrame([{"Away": "BOS", "Home": "DAL", "Date": _D(0)},
                         {"Away": "DAL", "Home": "BOS", "Date": _D(1)}])
OVERRIDES_ONE = pd.DataFrame([{"Player": "Alpha Guard", "Team": "BOS", "Note": "fixture"}])
EMPTY = pd.DataFrame()


@contextlib.contextmanager
def _gate(enabled: bool):
    prev = os.environ.get(GATE_ENV)
    if enabled:
        os.environ[GATE_ENV] = "1"
    else:
        os.environ.pop(GATE_ENV, None)
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop(GATE_ENV, None)
        else:
            os.environ[GATE_ENV] = prev


@contextlib.contextmanager
def _board_fixtures(gamelogs, snapshot, overrides):
    """Patch every loader qc_nba_board.run_qc reads (names bound in the qc module) with fixtures."""
    patches = {
        "load_playoff_gamelogs": lambda: PLAYOFF_LOGS.copy(),
        "load_playoff_results": lambda: PLAYOFF_RESULTS.copy(),
        "load_gamelogs": lambda: gamelogs.copy(),
        "load_schedule": lambda: SCHEDULE.copy(),
        "load_props": lambda: PROPS.copy(),
        "load_player_snapshot": lambda: snapshot.copy(),
        "load_current_team_overrides": lambda: overrides.copy(),
        "load_canonical_live_props": lambda *a, **k: PROPS.iloc[0:0].copy(),
        "_load_live_props": lambda: [],
        "append_qc_run_log": lambda *a, **k: None,
    }
    orig = {k: getattr(qc_nba_board, k) for k in patches}
    try:
        for k, v in patches.items():
            setattr(qc_nba_board, k, v)
        yield
    finally:
        for k, v in orig.items():
            setattr(qc_nba_board, k, v)


def _run_main():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = qc_nba_board.main()
    return code, buf.getvalue()


def check_board_scenarios():
    results = []

    def rec(ok, msg):
        results.append((ok, msg))

    # (1) gated + empty map -> abstention, no MEDIUM, exit 0
    with _gate(False), _board_fixtures(EMPTY, EMPTY, EMPTY):
        report = qc_nba_board.run_qc()
        code, out = _run_main()
    medium = [i for i in report["issues"] if "missing team mapping" in i["message"]]
    abst = report.get("abstentions") or []
    rec(not medium, "gated + empty map: no MEDIUM missing-team defect")
    rec(len(abst) == 1 and abst[0]["status"] == "TEAM_MAPPING_UNAVAILABLE" and abst[0]["row_count"] == 3,
        f"gated + empty map: TEAM_MAPPING_UNAVAILABLE abstention with row_count=3 (got {abst})")
    rec(report["issue_count"] == 0, f"gated + empty map: no other issues in fixture (got {report['issues']})")
    rec(code == 0, f"gated + empty map: qc_nba_board.main() exits 0 (got {code})")
    rec(LABEL in out and "[ABSTAIN]" in out, "gated + empty map: abstention status printed")
    rec("[MEDIUM]" not in out, "gated + empty map: no [MEDIUM] line printed")

    # (2) stats ENABLED + missing teams -> MEDIUM fires, exit 1 (unchanged behaviour)
    with _gate(True), _board_fixtures(GAMELOGS_PARTIAL, EMPTY, EMPTY):
        report = qc_nba_board.run_qc()
        code, out = _run_main()
    medium = [i for i in report["issues"] if i["severity"] == "medium" and "missing team mapping" in i["message"]]
    rec(len(medium) == 1 and medium[0]["message"].startswith("2 resolved prop rows"),
        f"enabled + 2 unmapped rows: MEDIUM fires with count 2 (got {report['issues']})")
    rec(not report.get("abstentions"), "enabled: no abstention recorded")
    rec(code == 1, f"enabled + missing: main() exits 1 (got {code})")
    rec("[MEDIUM] props_data: 2 resolved prop rows are still missing team mapping." in out,
        "enabled: MEDIUM line printed exactly as before")

    # (2b) stats ENABLED + EMPTY map -> still MEDIUM (the gate, not the empty map, grants the abstention)
    with _gate(True), _board_fixtures(EMPTY, EMPTY, EMPTY):
        report = qc_nba_board.run_qc()
    rec(any("3 resolved prop rows are still missing" in i["message"] for i in report["issues"])
        and not report.get("abstentions"), "enabled + empty map: MEDIUM fires, no abstention")

    # (3) gated + NON-empty map (override present) with misses -> MEDIUM still fires
    with _gate(False), _board_fixtures(EMPTY, EMPTY, OVERRIDES_ONE):
        report = qc_nba_board.run_qc()
        code, _ = _run_main()
    rec(any("2 resolved prop rows are still missing" in i["message"] for i in report["issues"])
        and not report.get("abstentions"),
        f"gated + non-empty map with misses: MEDIUM still fires (got {report['issues']})")
    rec(code == 1, f"gated + non-empty map: main() exits 1 (got {code})")

    # (4) all rows mapped -> neither issue nor abstention (gated, via overrides)
    full = pd.DataFrame([{"Player": p, "Team": "BOS", "Note": "fx"} for p in PROPS["Player"]])
    with _gate(False), _board_fixtures(EMPTY, EMPTY, full):
        report = qc_nba_board.run_qc()
    rec(not report["issues"] and not report.get("abstentions"), "fully mapped: no issue, no abstention")
    return results


def check_never_from_game():
    results = []
    for enabled in (False, True):
        with _gate(enabled):
            resolved = app.apply_current_team_context(PROPS.copy(), EMPTY, EMPTY, EMPTY)
        teams = set(resolved["Team"].astype(str).str.strip())
        results.append((teams == {""},
                        f"stats {'enabled' if enabled else 'gated'}: empty map -> Team stays blank, never "
                        f"BOS/DAL from Game (got {sorted(teams)})"))
    # classify_team_mapping never mutates/fills Team either
    with _gate(False):
        before = PROPS.copy()
        qc_nba_board.classify_team_mapping(before, {})
    results.append((before["Team"].fillna("").astype(str).str.strip().eq("").all(),
                    "classify_team_mapping does not fill Team"))
    # gate helper contract
    with _gate(False):
        g_empty, g_nonempty = nba_source_gate.team_mapping_gated({}), nba_source_gate.team_mapping_gated({"x": "BOS"})
    with _gate(True):
        e_empty = nba_source_gate.team_mapping_gated({})
    results.append((g_empty and not g_nonempty and not e_empty,
                    "team_mapping_gated: True only when gated AND map empty"))
    return results


def _owner_user():
    email = next(iter(app.OWNER_EMAILS)) if app.OWNER_EMAILS else "owner@bankrollkings.com"
    return {"user_id": "qc-owner", "email": email, "role": "owner", "plan": "all_access",
            "is_admin": True, "display_name": "QC Owner"}


def _authed_html(path):
    c = app.app.test_client()
    with c.session_transaction() as s:
        s["user_id"] = "qc-owner"
        s["user_email"] = _owner_user()["email"]
    r = c.get(path)
    return r.status_code, r.get_data(as_text=True)


def check_market_player_page():
    results = []
    page_props = PROPS.copy()
    page_props.loc[page_props["Player"] == "Charlie Big", "Team"] = "Dallas Mavericks"  # a row WITH a team
    orig = {k: getattr(app, k) for k in ("load_props", "get_current_user")}
    try:
        app.load_props = lambda: page_props.copy()
        app.get_current_user = _owner_user
        for enabled in (False, True):
            tag = "enabled" if enabled else "gated"
            with _gate(enabled):
                app._ENTITY_MARKET_KEYSET_CACHE.clear()
                ctx = app.build_market_player_page("nba", "Alpha Guard")
                ctx_team = app.build_market_player_page("nba", "Charlie Big")
                st, html = _authed_html("/tools/nba-player?q=Alpha+Guard")
                st2, html2 = _authed_html("/tools/nba-player?q=Charlie+Big")
            if enabled:
                # Behaviour-identical when enabled: no status, no label, team simply omitted as before.
                results.append((ctx["team_status"] == "" and ctx["team"] == "",
                                f"{tag}: blank team -> no team_status (got {ctx['team_status']!r})"))
                results.append((st == 200 and UI_LABEL not in html,
                                f"{tag}: page shows no gated label (status {st})"))
            else:
                results.append((ctx["found"] and ctx["team"] == "" and ctx["team_status"] == "TEAM_MAPPING_UNAVAILABLE",
                                f"{tag}: blank team -> team_status TEAM_MAPPING_UNAVAILABLE (got {ctx})"))
                results.append((st == 200, f"{tag}: /tools/nba-player renders (got {st})"))
                results.append((UI_LABEL in html, f"{tag}: page shows '{UI_LABEL}'"))
                results.append(("Boston Celtics" not in html.split("<h1", 1)[-1].split("</h1>", 1)[0]
                                and "Dallas Mavericks" not in html.split("<h1", 1)[-1].split("</h1>", 1)[0],
                                f"{tag}: header never shows a team inferred from Game"))
            if enabled:
                # Enabled: identity resolves via the stats keyset (pre-existing behaviour, untouched here);
                # the only contract is that the gate abstention never appears.
                results.append((ctx_team["team_status"] == "",
                                f"{tag}: no abstention status on any row (got {ctx_team['team_status']!r})"))
            else:
                # a present team is shown and never replaced by the abstention label
                results.append((ctx_team["team"] == "Dallas Mavericks" and ctx_team["team_status"] == "",
                                f"{tag}: present team kept, no abstention (got {ctx_team['team']!r}/{ctx_team['team_status']!r})"))
            results.append((st2 == 200 and UI_LABEL not in html2,
                            f"{tag}: page for a player with a known team shows no gated label (status {st2})"))
    finally:
        for k, v in orig.items():
            setattr(app, k, v)
        app._ENTITY_MARKET_KEYSET_CACHE.clear()
    return results


def main() -> int:
    print("=" * 60)
    print("BANKROLL KINGS NBA TEAM-MAPPING GATE QC (F3b)")
    print("=" * 60)
    results = check_board_scenarios() + check_never_from_game() + check_market_player_page()
    fails = 0
    for ok, msg in results:
        print(f"[{'ok' if ok else 'FAIL'}] {msg}")
        fails += 0 if ok else 1
    print()
    print(f"{len(results) - fails} ok, {fails} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
