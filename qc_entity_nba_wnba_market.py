"""QC: additive NBA/WNBA market-only entity destinations (Option A) + gate-aware resolution.

While the NBA.com stats gate is OFF (BK_NBA_STATS_ENABLED unset), NBA/WNBA entity links must point to
the new minimal, cleared market-only pages whose identity resolves from the LICENSED Odds feed, never
to the gated rich /player /team stats pages — so the link keeps working without touching stats.nba.com.
When the gate is ON, resolution reverts to the rich pages. The market-only pages show licensed
market/schedule facts only and abstain on statistics visibly.

Deterministic: loaders are monkeypatched with small fixtures (the real props/odds files are absent
off-season and gitignored), and the owner access gate is satisfied by patching the identity boundary.
Exits 0 when the contract holds, 1 otherwise.
"""
from __future__ import annotations

import os
import re

import pandas as pd

import app
import services.entity_links as el

NBA_PROPS = pd.DataFrame([
    {'Player': 'Jayson Tatum', 'Stat': 'Points', 'Line': 27.5, 'CurrentLine': 27.5,
     'OverOdds': -110, 'UnderOdds': -110, 'Book': 'DraftKings', 'Team': 'Boston Celtics'},
    {'Player': 'Jayson Tatum', 'Stat': 'Rebounds', 'Line': 8.5, 'CurrentLine': 8.5,
     'OverOdds': -115, 'UnderOdds': -105, 'Book': 'DraftKings', 'Team': 'Boston Celtics'},
    {'Player': 'Luka Doncic', 'Stat': 'Points', 'Line': 31.5, 'CurrentLine': 31.5,
     'OverOdds': -105, 'UnderOdds': -115, 'Book': 'FanDuel', 'Team': 'Dallas Mavericks'},
])
WNBA_PROPS = pd.DataFrame([
    {'Player': "A'ja Wilson", 'Stat': 'Points', 'Line': 22.5, 'CurrentLine': 22.5,
     'OverOdds': -120, 'UnderOdds': 100, 'Book': 'DraftKings', 'Team': 'Las Vegas Aces'},
])
NBA_ODDS = pd.DataFrame([
    {'Away': 'Boston Celtics', 'Home': 'Dallas Mavericks', 'Date': '2026-11-01', 'Time': '7:30'},
    {'Away': 'Golden State Warriors', 'Home': 'Boston Celtics', 'Date': '2026-11-03', 'Time': '10:00'},
])


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


def _has_nested_anchor(html):
    # True if any <a ...> opens before the previous one closed.
    depth = 0
    for tok in re.findall(r'<a\b|</a>', html, re.IGNORECASE):
        if tok.lower() == '</a>':
            depth = max(0, depth - 1)
        else:
            depth += 1
            if depth > 1:
                return True
    return False


def _install_fixtures():
    app.load_props = lambda: NBA_PROPS.copy()
    app.load_wnba_props = lambda: WNBA_PROPS.copy()
    app.load_game_market_odds = lambda: NBA_ODDS.copy()
    app.get_current_user = _owner_user
    app._ENTITY_MARKET_KEYSET_CACHE.clear()


def run_qc():
    issues, notes = [], []
    os.environ.pop('BK_NBA_STATS_ENABLED', None)  # ensure gated (default)

    orig = {k: getattr(app, k) for k in ('load_props', 'load_wnba_props', 'load_game_market_odds',
                                         'get_current_user')}
    try:
        _install_fixtures()

        # ---- (1) gate OFF: resolver points NBA/WNBA entity links at the market-only pages ----
        checks = [
            ("player_url nba known -> market page",
             app.player_url('nba', 'Jayson Tatum'), '/tools/nba-player?q=Jayson+Tatum'),
            ("player_url wnba known -> market page",
             app.player_url('wnba', "A'ja Wilson"), '/tools/wnba-player?q=A%27ja+Wilson'),
            ("team_url nba known -> market page",
             app.team_url('nba', 'Boston Celtics'), '/tools/nba-team?team=Boston+Celtics'),
        ]
        for label, got, want in checks:
            if got != want:
                issues.append(f"[gated] {label}: got {got!r}, want {want!r}")
            else:
                notes.append(f"[gated] {label} -> {got}")

        # unknown / ambiguous -> plain text (None)
        if app.player_url('nba', 'Nobody McNoface') is not None:
            issues.append("[gated] unknown NBA player resolved to a link (should be plain text)")
        else:
            notes.append("[gated] unknown NBA player -> plain text")
        if app.team_url('nba', 'Nowhere United') is not None:
            issues.append("[gated] unknown NBA team resolved to a link (should be plain text)")
        else:
            notes.append("[gated] unknown NBA team -> plain text")
        # ambiguous key (two distinct entities share a normalized key) -> not linked
        orig_keyset = app._entity_market_player_keyset
        app._entity_market_player_keyset = lambda sport: {app.normalize_player_lookup_name('Ambi Guous')
                                                          or 'ambi guous': 2}
        try:
            if app.player_url('nba', 'Ambi Guous') is not None:
                issues.append("[gated] ambiguous NBA player (count>1) resolved to a link")
            else:
                notes.append("[gated] ambiguous NBA player -> plain text")
        finally:
            app._entity_market_player_keyset = orig_keyset

        # WNBA team unchanged (still the existing minimal page); MLB unaffected
        if app.team_url('wnba', 'X', require_known=False) != '/tools/wnba-team?team=X':
            issues.append("[gated] WNBA team path changed unexpectedly")
        if app.team_url('mlb', 'Y', require_known=False) != '/tools/mlb-team?team=Y':
            issues.append("[gated] MLB team path changed unexpectedly")

        # ---- (2) gate OFF: the market-only pages render cleared facts + abstain on stats ----
        st, h = _authed_html('/tools/nba-player?q=Jayson Tatum')
        if st != 200:
            issues.append(f"/tools/nba-player returned {st}")
        else:
            for need in ('market-only', 'statistics are not available here', 'Points', 'Rebounds',
                         '· NBA'):
                if need.lower() not in h.lower():
                    issues.append(f"nba-player page missing {need!r}")
            if _has_nested_anchor(h):
                issues.append("nba-player page has a NESTED anchor")
            notes.append("nba-player market page: identity + prop markets + abstain banner, no nesting")

        st, h = _authed_html('/tools/nba-player?q=Nobody McNoface')
        if st != 200 or "doesn't resolve" not in h and "doesn&rsquo;t resolve" not in h:
            issues.append("nba-player unknown did not show the honest 'not a current player' state")
        else:
            notes.append("nba-player unknown -> honest not-found state")

        st, h = _authed_html('/tools/wnba-player?q=A\'ja Wilson')
        if st != 200 or '· WNBA' not in h or 'statistics are not available here' not in h.lower():
            issues.append("wnba-player page missing identity/abstain (status %s)" % st)
        else:
            notes.append("wnba-player market page renders with WNBA identity + abstain banner")

        st, h = _authed_html('/tools/nba-team?team=Boston Celtics')
        if st != 200:
            issues.append(f"/tools/nba-team returned {st}")
        else:
            for need in ('market', 'statistics are not available here', '· NBA'):
                if need.lower() not in h.lower():
                    issues.append(f"nba-team page missing {need!r}")
            if '/tools/nba-team?team=' not in h:
                issues.append("nba-team page opponent is not an entity link to the market team page")
            if _has_nested_anchor(h):
                issues.append("nba-team page has a NESTED anchor")
            notes.append("nba-team market page: identity + schedule + opponent links + abstain, no nesting")

        # ---- (3) gate ON: resolution reverts to the rich /player /team pages ----
        os.environ['BK_NBA_STATS_ENABLED'] = '1'
        try:
            pairs = [
                ("player nba", app.player_url('nba', 'anyone', require_known=False), '/player/anyone?sport=nba'),
                ("player wnba", app.player_url('wnba', 'anyone', require_known=False), '/player/anyone?sport=wnba'),
                ("team nba", app.team_url('nba', 'anyone', require_known=False), '/team/anyone?sport=nba'),
            ]
            for label, got, want in pairs:
                if got != want:
                    issues.append(f"[stats ON] {label}: got {got!r}, want {want!r}")
                else:
                    notes.append(f"[stats ON] {label} -> rich page {got}")
        finally:
            os.environ.pop('BK_NBA_STATS_ENABLED', None)
    finally:
        for k, v in orig.items():
            setattr(app, k, v)
        app._ENTITY_MARKET_KEYSET_CACHE.clear()

    if not issues:
        notes.append("Option A market-only destinations + gate-aware resolution verified")
    return {"issues": issues, "notes": notes}


def main() -> int:
    report = run_qc()
    print("=" * 60)
    print("BANKROLL KINGS NBA/WNBA MARKET-ONLY ENTITY QC (Option A)")
    print("=" * 60)
    for n in report["notes"]:
        print(f"[NOTE] {n}")
    if report["notes"]:
        print()
    if not report["issues"]:
        print("NBA/WNBA market-only entity destinations verified.")
        return 0
    for m in report["issues"]:
        print(f"[FAIL] {m}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
