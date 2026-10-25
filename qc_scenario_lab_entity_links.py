"""QC: Scenario Lab entity-linking is BLOCKED on canonical player identity (audit + revert check).

Group-3 finding (reviewer, 2026-10-25): the NFL Scenario Lab export stores SHORT FORMS (e.g. 'B.Purdy'),
while the NFL resolver keys FULL-NAME roster identities ('Brock Purdy'). Their normalized keys differ
('bpurdy' vs 'brockpurdy'), so the player column could NEVER resolve — not even on a populated prod
keyset. Wrapping it would only ever render plain text, and initial+surname is not unique, so no fuzzy
back-mapping is safe. The player-column wiring was therefore REVERTED; unblocking requires adding a
stable canonical identity to the export itself (research/nfl_scenarios/build_scenario_export.py),
collision-tested.

This QC (1) proves the identity mismatch with REAL-SHAPE fixtures incl. a collision, (2) shows the
resolver fails closed (short form -> None -> plain text), and (3) verifies the Group-3 wiring is reverted
(builder does not wrap, template has no entity wiring). It does not test any speculative future helper.
"""
import os
import sys

os.environ.setdefault("SECRET_KEY", "qc-only-not-a-real-secret")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TPL = os.path.join(HERE, 'templates')
fails = []


def check(cond, msg):
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        fails.append(msg)


def test_identity_mismatch_blocks():
    print("\n[A] BLOCKING FINDING — short-form export names cannot match full-name roster keys")
    nk = app._normalize_nfl_roster_player_key
    jk = app._normalize_player_join_key
    # the exact case from the real export (B.Purdy) vs the roster identity (Brock Purdy)
    check(nk('B.Purdy') == 'bpurdy' and nk('Brock Purdy') == 'brockpurdy' and nk('B.Purdy') != nk('Brock Purdy'),
          "roster-key: 'B.Purdy'(%r) != 'Brock Purdy'(%r) -> short form can't resolve"
          % (nk('B.Purdy'), nk('Brock Purdy')))
    check(jk('B.Purdy') != jk('Brock Purdy'),
          "join-key: short form also mismatches the full name (%r vs %r)" % (jk('B.Purdy'), jk('Brock Purdy')))
    # COLLISION: distinct full names collapse to the SAME short form -> initial+surname is NOT unique,
    # so a short->full back-mapping would be ambiguous and must never be assumed.
    short_aaron = 'A.Smith'   # short form of BOTH 'Aaron Smith' and 'Andre Smith'
    check(nk('A.Smith') == 'asmith', "collision key 'A.Smith' -> 'asmith'")
    check(nk('Aaron Smith') != nk('Andre Smith'),
          "'Aaron Smith'(%r) and 'Andre Smith'(%r) are distinct players..." % (nk('Aaron Smith'), nk('Andre Smith')))
    check(nk('A.Smith') != nk('Aaron Smith') and nk('A.Smith') != nk('Andre Smith'),
          "...yet both share short form 'A.Smith' -> ambiguous; no fuzzy initial+surname mapping is safe")
    # the resolver does the SAFE thing with a short form: no match -> None -> plain text (no wrong link)
    check(app.player_url('nfl', 'B.Purdy') is None, "resolver returns None for the short form (safe, plain text)")

    # SANITY: the resolver itself works for a FULL name shape (fixture) — the block is the data shape,
    # not the resolver. (Full-name resolution is already exercised by qc_bk_power / qc_entity_links.)
    _orig = app._entity_player_known
    app._entity_player_known = lambda s, n: (s == 'nfl' and n == 'Brock Purdy') or _orig(s, n)
    try:
        c = app._entity_cell('player', 'nfl', 'Brock Purdy')
        check(isinstance(c['url'], str) and c['url'].startswith('/tools/player-check'),
              "a FULL-name identity would resolve (fixture) -> the gap is export identity, not the resolver")
    finally:
        app._entity_player_known = _orig


def test_wiring_reverted():
    print("\n[B] Group-3 wiring REVERTED — builder does not wrap, template has no entity wiring")
    ctx = app.build_scenario_lab_context()
    sd = ctx.get('scenario_data') or {}
    scopes = sd.get('scopes') or {}
    if scopes:
        sk = next(iter(scopes)); sc = scopes[sk]
        pos = next(iter(sc.get('players') or {'': {}}))
        boards = (sc.get('players', {}).get(pos, {}) or {}).get('boards') or {}
        if boards:
            bk = next(iter(boards))
            check(boards[bk].get('entity_col') is None, "players board is NOT wrapped (no entity_col)")
            row0 = (boards[bk].get('rows') or [[None]])[0]
            check(not isinstance(row0[0], dict), "players board col 0 is a plain value, not a {text,url} cell")
        else:
            print("  [note] no player boards locally; structural revert checked on the template instead")
    else:
        print("  [note] scenario data absent locally; template revert is the authoritative check")
    src = open(os.path.join(TPL, 'scenario_lab.html'), encoding='utf-8').read()
    check("_entity_cell.html" not in src and 'bkEntityCell' not in src and 'data-ent' not in src
          and 'entity_col' not in src,
          "scenario_lab.html has NO entity wiring (include / bkEntityCell / data-ent / entity_col)")


if __name__ == '__main__':
    print("=" * 72)
    print("SCENARIO LAB — BLOCKED ON CANONICAL IDENTITY (audit + revert verification)")
    print("=" * 72)
    test_identity_mismatch_blocks()
    test_wiring_reverted()
    print("\nClean:", not fails)
    sys.exit(1 if fails else 0)
