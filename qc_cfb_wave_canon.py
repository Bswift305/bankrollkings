"""QC: CFB wave-local team canonicalization + COLLISION AUDIT (pre-ship gate).

Proves `app._cfb_wave_team_key(name) = cff._resolve(normalize_ncaaf_team_name(name))` collapses the CFBD
short/long name divergence (App State / Appalachian State ...) WITHOUT collapsing distinct teams, before
it is wired into the Active ATS Wave (docs/cfb_runtime_data_corrective.md, Option 1). Any collision among
distinct teams fails the gate. Exits 0 on success, 1 otherwise. No network.
"""
from __future__ import annotations

import app

K = app._cfb_wave_team_key

# Short/full aliases that MUST resolve identically (the whole point of the helper).
ALIAS_PAIRS = [
    ("App State", "Appalachian State"), ("Southern Miss", "Southern Mississippi"),
    ("UConn", "Connecticut"), ("UL Monroe", "Louisiana Monroe"), ("UT Martin", "Tennessee Martin"),
    ("Miami (OH)", "Miami OH"), ("Miami (Ohio)", "Miami OH"),
]

# One canonical name per DISTINCT team (CFBD uses one name per team within a feed). No two may share a
# key. Includes the ambiguous families the directive calls out.
DISTINCT_TEAMS = [
    "Miami (FL)", "Miami (OH)",                                   # Miami/Miami (OH)
    "USC", "South Carolina",                                      # USC variants
    "Louisiana-Lafayette", "UL Monroe", "Louisiana Tech", "LSU",  # Louisiana schools
    "Washington", "Washington State",                            # Washington/Washington State
    "Delaware", "Delaware State", "Idaho", "Idaho State",        # FCS lookalikes
    "Montana", "Montana State", "Sam Houston", "Sam Houston State",
    "App State", "Southern Miss", "UConn", "UT Martin",          # the diverging FBS teams
    "Georgia", "Alabama", "Oregon", "Ohio State", "Auburn", "Kansas", "Missouri", "Pittsburgh",
]

# FBS-vs-FCS games: the FBS side key must exist and differ from the FCS opponent's key.
FBS_FCS = [("App State", "Maine"), ("Kansas", "Long Island University"), ("UConn", "Lafayette"),
           ("Southern Miss", "Alcorn State"), ("Mississippi State", "UL Monroe")]


def qc_aliases_resolve_identically():
    issues = []
    for short, full in ALIAS_PAIRS:
        if K(short) != K(full):
            issues.append(f"{short!r} ({K(short)!r}) != {full!r} ({K(full)!r}) — alias did not merge")
    return issues


def qc_idempotent():
    issues = []
    for t in DISTINCT_TEAMS + [full for _, full in ALIAS_PAIRS]:
        once = K(t)
        if K(once) != once:
            issues.append(f"not idempotent: K({t!r})={once!r} but K({once!r})={K(once)!r}")
    return issues


def qc_distinct_teams_no_collision():
    """The gate: one name per distinct team -> no two map to the same key."""
    coll = app._cfb_wave_key_collisions(DISTINCT_TEAMS)
    if coll:
        return [f"COLLISION — distinct teams merged to one key: {coll}"]
    return []


def qc_ambiguous_families_distinct():
    """Explicit pairwise checks for the named ambiguous families (defense in depth)."""
    issues = []
    must_differ = [("Miami (FL)", "Miami (OH)"), ("USC", "South Carolina"),
                   ("Louisiana-Lafayette", "UL Monroe"), ("Louisiana Tech", "LSU"),
                   ("Washington", "Washington State"), ("Delaware", "Delaware State"),
                   ("Idaho", "Idaho State"), ("Montana", "Montana State"),
                   ("Sam Houston", "Sam Houston State")]
    for a, b in must_differ:
        if K(a) == K(b):
            issues.append(f"COLLISION {a!r} and {b!r} both -> {K(a)!r}")
    return issues


def qc_fbs_fcs_side_distinct():
    issues = []
    for fbs, fcs in FBS_FCS:
        if not K(fbs):
            issues.append(f"FBS side {fbs!r} produced an empty key")
        if K(fbs) == K(fcs):
            issues.append(f"FBS {fbs!r} and FCS {fcs!r} collapsed to {K(fbs)!r}")
    return issues


CHECKS = [("aliases_resolve_identically", qc_aliases_resolve_identically),
          ("idempotent", qc_idempotent),
          ("distinct_teams_no_collision", qc_distinct_teams_no_collision),
          ("ambiguous_families_distinct", qc_ambiguous_families_distinct),
          ("fbs_fcs_side_distinct", qc_fbs_fcs_side_distinct)]


def main() -> int:
    print("=" * 60)
    print("BANKROLL KINGS CFB WAVE CANONICALIZATION + COLLISION AUDIT")
    print("=" * 60)
    failed = 0
    for name, fn in CHECKS:
        try:
            issues = fn()
        except Exception as e:  # noqa
            import traceback
            issues = [f"EXCEPTION {type(e).__name__}: {e}"]
            traceback.print_exc()
        if issues:
            failed += 1
            for i in issues:
                print(f"[FAIL] {name}: {i}")
        else:
            print(f"[PASS] {name}")
    print("-" * 60)
    print(f"FAIL: {failed}" if failed else "Wave canonicalization verified; no distinct-team collisions.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
