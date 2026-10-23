"""QC: CFB Matchup "This Week's Matchups" total-rendering contract (regression for da2c3c2).

The header line for each week game (templates/cfb_matchup.html, the .mu-wk-ln span) must show
the POSTED over/under number and nothing else -- never the raw Python object behind g.total.

Why this exists: build_cfb_matchup_context() sets wg['total'] = cfb_current_form.total_read(...),
which returns a MAPPING ({proj_total, line, lean, edge, skill_note, away_qb_out, ...}) or None.
The template used to render g.total directly when it was not a number, dumping the whole dict
("{'proj_total': 54.2, 'line': 48.5, ...}") into the matchup line (mirror of the NFL defect fixed
in 24273df). The fix shows g.total.line, handling mapping / bare-number / empty.

This renders the REAL route (/tools/cfb-matchup) through the REAL template with build_cfb_matchup_context
monkeypatched to a fixed mu_week, so a regression on that one template line is caught deterministically
with no dependence on live CFB data. It exercises the five shapes g.total can take:

  1. mapping with a numeric line  -> the posted O/U renders
  2. mapping with line = None      -> no O/U, no leak
  3. missing total (None)          -> no O/U, no leak
  4. legacy scalar total (number)  -> the number renders as O/U
  5. malformed mapping             -> no O/U, no leak (a naive else-branch would dump the dict)

Assertion: for every game, the rendered button contains NO Python-dict representation (braces or a
mapping key name such as proj_total / skill_note / away_qb_out / 'line'), NO literal 'None', and no
other malformed-object text; and for the numeric cases the .mu-wk-ln span shows "O/U <number>".

Exits 0 when the contract holds, 1 otherwise.
"""
from __future__ import annotations

import re

import app

ROUTE = "/tools/cfb-matchup"

# data-away is unique per fixture so each rendered button maps back to its case.
GAMES = [
    {
        "key": "mapping-numeric-line",
        "away": "QCMapNum", "home": "QCHomeA",
        "spread": "QCHomeA -3.5", "time": "Sat 3:30",
        "total": {"proj_total": 54.2, "line": 48.5, "lean": "OVER", "edge": 5.7,
                  "league_pts": 27.0, "skill_note": None, "away_qb_out": None},
        "expect_ou": "48.5",
    },
    {
        "key": "mapping-line-none",
        "away": "QCLineNil", "home": "QCHomeB",
        "spread": "QCHomeB -7", "time": "Sat 7:00",
        "total": {"proj_total": 51.0, "line": None, "lean": None, "edge": None,
                  "league_pts": 27.0, "skill_note": None, "away_qb_out": None},
        "expect_ou": None,
    },
    {
        "key": "missing-total",
        "away": "QCNoTotal", "home": "QCHomeC",
        "spread": "QCHomeC -1", "time": "Sat 12:00",
        "total": None,
        "expect_ou": None,
    },
    {
        "key": "legacy-scalar",
        "away": "QCScalar", "home": "QCHomeD",
        "spread": "QCHomeD -10", "time": "Fri 8:00",
        "total": 47.5,  # legacy shape: a bare posted number
        "expect_ou": "47.5",
    },
    {
        "key": "malformed-mapping",
        "away": "QCMalformed", "home": "QCHomeE",
        "spread": "", "time": "",
        # A corrupt total_read payload: non-numeric line, stray keys. A naive renderer would dump it.
        "total": {"proj_total": None, "line": "n/a", "skill_note": "garbage",
                  "away_qb_out": "Starter QB", "junk": ["x", "y"]},
        "expect_ou": None,
    },
]

# Dict-leak signatures that must never reach the rendered matchup button.
LEAK_SIGNATURES = ["{", "}", "proj_total", "skill_note", "away_qb_out", "'line'",
                   "league_pts", "[", "]", "None"]


def _fixture_context():
    week = []
    for g in GAMES:
        week.append({
            "away": g["away"], "home": g["home"],
            "spread": g["spread"], "total": g["total"], "time": g["time"],
            "date": "2026-11-07",
            # Keep every other week-block field inert so only the total line is exercised.
            "form": None, "move": None, "wx": None, "coach": None,
            "prior_ctx": None, "streaks": {"away": {}, "home": {}},
        })
    return {
        "mu_data": {"teamList": ["Texas", "Georgia"], "teams": {}, "meta": {}},
        "mu_meta": {},
        "mu_available": True,
        "mu_week": week,
    }


def _owner_user():
    # Minimal owner principal: is_owner_user() passes on role=='owner', so the access gate is
    # satisfied deterministically without depending on whether the owner happens to exist in the
    # local users store. We are testing the template contract, not the identity lookup.
    email = next(iter(app.OWNER_EMAILS)) if app.OWNER_EMAILS else "owner@bankrollkings.com"
    return {"user_id": "qc-owner", "email": email, "role": "owner", "plan": "all_access",
            "is_admin": True, "display_name": "QC Owner"}


def _authed_html(client, path):
    with client.session_transaction() as s:
        s["user_id"] = "qc-owner"
        s["user_email"] = _owner_user()["email"]
    r = client.get(path)
    return r.status_code, r.get_data(as_text=True)


def _buttons_by_away(html):
    """Map data-away -> that game's full <button> HTML, in render order."""
    out = {}
    for m in re.finditer(r'<button[^>]*class="mu-wk"[^>]*data-away="([^"]*)"[^>]*>(.*?)</button>',
                         html, re.DOTALL):
        out[m.group(1)] = m.group(0)
    return out


def _ln_span(button_html):
    m = re.search(r'<span class="mu-wk-ln">(.*?)</span>', button_html, re.DOTALL)
    return m.group(1) if m else ""


def run_qc():
    issues, notes = [], []
    orig_ctx = app.build_cfb_matchup_context
    orig_user = app.get_current_user
    app.build_cfb_matchup_context = _fixture_context
    app.get_current_user = _owner_user
    try:
        client = app.app.test_client()
        status, html = _authed_html(client, ROUTE)
    finally:
        app.build_cfb_matchup_context = orig_ctx
        app.get_current_user = orig_user

    if status != 200:
        issues.append(f"{ROUTE} returned {status} (want 200)")
        return {"issues": issues, "notes": notes}

    buttons = _buttons_by_away(html)
    for g in GAMES:
        btn = buttons.get(g["away"])
        if btn is None:
            issues.append(f"[{g['key']}] game not rendered (data-away={g['away']!r} missing) "
                          f"-- every admitted week game must render")
            continue
        ln = _ln_span(btn)

        # (A) no dict / malformed-object text anywhere in this game's button
        for sig in LEAK_SIGNATURES:
            if sig in btn:
                issues.append(f"[{g['key']}] leak signature {sig!r} reached rendered HTML: "
                              f"...{btn[max(0, btn.find(sig) - 30):btn.find(sig) + 40]}...")

        # (B) the O/U contract itself
        if g["expect_ou"] is None:
            if "O/U" in ln:
                issues.append(f"[{g['key']}] O/U rendered for a game with no posted total: {ln!r}")
            else:
                notes.append(f"[{g['key']}] no O/U shown and no leak -- correct")
        else:
            needle = f"O/U {g['expect_ou']}"
            if needle not in ln:
                issues.append(f"[{g['key']}] expected {needle!r} in matchup line, got: {ln!r}")
            else:
                notes.append(f"[{g['key']}] posted O/U {g['expect_ou']} rendered -- correct")

    if not issues:
        notes.append("CFB matchup total contract holds across all five g.total shapes")
    return {"issues": issues, "notes": notes}


def main() -> int:
    report = run_qc()
    print("=" * 60)
    print("BANKROLL KINGS CFB MATCHUP TOTAL-RENDER QC")
    print("=" * 60)
    for n in report["notes"]:
        print(f"[NOTE] {n}")
    if report["notes"]:
        print()
    if not report["issues"]:
        print("CFB matchup total-rendering contract verified.")
        return 0
    for m in report["issues"]:
        print(f"[FAIL] {m}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
