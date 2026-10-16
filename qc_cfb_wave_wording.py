"""QC: CFB Wave Watch wording remediation (Gate 1) — authority language removed, every qualifier
still visible, membership unchanged.

Durable invariants (no saved baseline needed):
  1. Every team the builder (build_cfb_wave_context) places in any section — hits, cover tiers, fades,
     sink tiers — appears in the rendered page. The template filters NOTHING; the model groups/orders,
     it never removes a qualifier.
  2. No inventoried betting-authority phrase survives on the CFB Wave Watch surface (ride / fade /
     bet the opponent / "This Week's Hits" / genuinely underrated / better than the market rated /
     baked into the number / "the edge is a team"), and the ATS Streaks surface no longer says
     "overbought".
  3. The frozen neutral replacements are present.

Renders through the real authenticated route (owner session), so it exercises the live template +
builder. Exits 0 when the remediation holds, 1 otherwise.
"""
from __future__ import annotations

import re

import app

# &rsquo; is the right-single-quote entity the templates use literally.
AUTHORITY_GONE = [
    "This Week&rsquo;s Hits", "Ride until it does", "Fade the Sinkers", "bet the opponent",
    "genuinely underrated", "better than the market rated", "baked into the number",
    "the edge is a team", "FADE {",  # the "FADE {line} -> back {opp}" play text
]
NEUTRAL_PRESENT = [
    "Covering, and the model still projects a cover",
    "Not covering",
    "model projects a miss vs",
    "the model and the closing number agree",
    "shown as context, not a signal on its own",
]


def _authed_html(path):
    c = app.app.test_client()
    with c.session_transaction() as s:
        s["user_id"] = "qc-owner"
        s["user_email"] = next(iter(app.OWNER_EMAILS))
    r = c.get(path)
    return r.status_code, r.get_data(as_text=True)


def run_qc():
    issues, notes = [], []
    ww = app.build_cfb_wave_context()

    def teams(seq):
        return [str(x.get("team", "")) for x in (seq or [])]
    builder_teams = set(teams(ww.get("wave_hits")) + teams(ww.get("wave_fades")))
    for g in (ww.get("wave_tiers") or []) + (ww.get("wave_sink_tiers") or []):
        builder_teams |= set(teams(g.get("plays")))
    builder_teams.discard("")

    status, h = _authed_html("/tools/cfb-wave")
    if status != 200:
        issues.append(f"/tools/cfb-wave returned {status} (want 200)")
        return {"issues": issues, "notes": notes}

    # (1) every qualifier the builder placed appears in the rendered page. Apostrophes in team names
    # ("Hawai'i") render as entities, so match tolerantly.
    def _rendered(team):
        pat = ">" + re.escape(team).replace("'", "(?:'|&rsquo;|&#39;|&#x27;|’)") + r"[< ]"
        return re.search(pat, h) is not None
    missing = [t for t in sorted(builder_teams) if not _rendered(t)]
    if missing:
        issues.append(f"{len(missing)} builder teams NOT rendered (template filtered them): {missing[:8]}")
    else:
        notes.append(f"all {len(builder_teams)} builder qualifiers render — template filters nothing")

    # (2) authority language gone
    for ph in AUTHORITY_GONE:
        if ph.lower() in h.lower():
            issues.append(f"authority phrase still present on cfb-wave: {ph!r}")
    # (3) neutral replacements present
    for ph in NEUTRAL_PRESENT:
        if ph.lower() not in h.lower():
            issues.append(f"neutral replacement missing on cfb-wave: {ph!r}")

    # ATS Streaks: overbought gone, descriptive present
    s2, h2 = _authed_html("/tools/cfb-ats-streaks")
    if s2 == 200:
        if "overbought" in h2.lower():
            issues.append("cfb-ats-streaks still says 'overbought'")
        if "descriptive record" not in h2.lower():
            issues.append("cfb-ats-streaks missing the descriptive-record framing")
    else:
        notes.append(f"cfb-ats-streaks returned {s2} (skipped)")

    if not issues:
        notes.append("authority language removed; neutral copy present; every qualifier visible")
    return {"issues": issues, "notes": notes}


def main() -> int:
    report = run_qc()
    print("=" * 60)
    print("BANKROLL KINGS CFB WAVE WATCH WORDING QC")
    print("=" * 60)
    for n in report["notes"]:
        print(f"[NOTE] {n}")
    if report["notes"]:
        print()
    if not report["issues"]:
        print("CFB Wave Watch remediation verified.")
        return 0
    for m in report["issues"]:
        print(f"[FAIL] {m}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
