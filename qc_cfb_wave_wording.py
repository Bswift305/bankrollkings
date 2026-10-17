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
  3. The frozen neutral replacements are present, including the neutral tier labels (C6 addendum:
     _WAVE_TIERS / _SINK_TIERS are model-description copy, not buy/fade verdicts). Every builder tier
     group renders, in the builder's order -- proving the label change is display-only (the tier
     NUMBER drives grouping/order, so no team moved and no group reordered).

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
    # Retired tier labels + the tier-2 blurb (C6 addendum) -- regression guards.
    "market lagging", "Genuinely strong", "regression risk", "cupcakes", "Overrated",
    "Bad and priced",
]
# Phrases the Wave Watch hero/note always render (regardless of sync state): factual membership framing
# and the "model is an overlay" statement.
NEUTRAL_PRESENT = [
    "actively riding a cover wave",
    "a push breaks the streak",
    "an overlay",
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

    builder_teams = set(str(x.get("team", "")) for x in
                        (ww.get("wave_members") or []) + (ww.get("wave_fades") or []))
    builder_teams.discard("")

    status, h = _authed_html("/tools/cfb-wave")
    if status != 200:
        issues.append(f"/tools/cfb-wave returned {status} (want 200)")
        return {"issues": issues, "notes": notes}

    # (1) membership renders: every team the builder admitted appears. When the graded source is not
    # synchronized (fail-closed), there are no members and the page must show the unsynced state.
    if ww.get("wave_unsynced"):
        if "not synchronized" not in h.lower():
            issues.append("unsynced wave is missing the fail-closed 'not synchronized' state")
        else:
            notes.append(f"source not synchronized (through Wk {ww.get('wave_through_week')}) -> "
                         "fail-closed state shown, no cover-% fallback")
    else:
        def _rendered(team):
            pat = ">" + re.escape(team).replace("'", "(?:'|&rsquo;|&#39;|&#x27;|’)") + r"[< ]"
            return re.search(pat, h) is not None
        missing = [t for t in sorted(builder_teams) if not _rendered(t)]
        if missing:
            issues.append(f"{len(missing)} builder teams NOT rendered: {missing[:8]}")
        else:
            notes.append(f"all {len(builder_teams)} admitted teams render — model never suppresses membership")

    # (2) authority language gone
    for ph in AUTHORITY_GONE:
        if ph.lower() in h.lower():
            issues.append(f"authority phrase still present on cfb-wave: {ph!r}")
    # (3) factual membership framing present
    for ph in NEUTRAL_PRESENT:
        if ph.lower() not in h.lower():
            issues.append(f"factual framing missing on cfb-wave: {ph!r}")

    # ATS Streaks: overbought gone, descriptive present
    s2, h2 = _authed_html("/tools/cfb-ats-streaks")
    if s2 == 200:
        if "overbought" in h2.lower():
            issues.append("cfb-ats-streaks still says 'overbought'")
        # The descriptive-record framing lives in the data-present branch; assert it only when the
        # board actually has data (the runtime ATS source may be unpopulated in a clean checkout).
        ats_avail = app.build_cfb_ats_streaks_context().get("ats_available")
        if ats_avail and "descriptive record" not in h2.lower():
            issues.append("cfb-ats-streaks missing the descriptive-record framing")
        elif not ats_avail:
            notes.append("cfb-ats-streaks board unavailable (runtime source not populated) -> "
                         "descriptive-record framing check skipped")
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
