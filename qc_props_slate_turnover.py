"""QC: event-aware football props validation -- a normal slate turnover publishes; a real collapse does not.

RC 2026-11-02: the Monday NFL props fetch returned 380 valid rows (13 events, 0 provider errors) and the
whole-file guard rejected it as "380 < 50% of prior 2831" -- but 2,636 of those prior rows were for games
already played. NCAAF did the same (87 vs 2,552, all 46 prior events started). The 26 credits bought a
valid response that was discarded only because the calendar rolled from Sunday to Monday.

Fully synthetic and offline (no provider call, no repo data read or written). The replay fixtures use the
per-event row counts and kickoffs observed on prod on 2026-11-02 (counts only; no prices or names).
Checks:
  A. NFL Sunday full slate -> Monday early-week slate (the RC replay): ACCEPTED; the legacy whole-file
     rule still REJECTS the same frames (the fixture reproduces the incident).
  B. Monday sparse postings growing later in the week: ACCEPTED.
  C. A still-eligible event losing more than the governed 50%: REJECTED; a published future event that
     vanishes is REJECTED at ANY prior size (123 -> 0, 19 -> 0, 1 -> 0). The 50% / 20-row values are
     inherited conservative thresholds, not football-validated constants.
  D. Provider success but zero usable current events: REJECTED.
  E. Missing / unparseable / non-UTC event identity or kickoff, or conflicting kickoffs: REJECTED.
  F. Completed/started games are absent from the published frame.
  G. NCAAF replay (all prior events started): ACCEPTED.
  H. Provider error: REJECTED.
  I. Market-type contract: every configured NFL/NCAAF market is classified line-based or binary
     (anytime TD); binary rows are valid without a provider line; malformed rows are dropped + counted.
  L. Boundaries: kickoff == now is excluded, now + 1s is eligible; other spellings of a UTC instant
     are rejected (frozen contract: canonical ...Z only).
  J. End to end through fetch_player_props.main(): a failed validation leaves the prior file
     byte-identical with no temp leftovers; --allow-collapse bypasses nothing; a valid turnover is
     published atomically; the shape receipt keeps raw rows_fetched apart from the published file.
  K. Scope: only NFL + NCAAF opt in; NBA/WNBA/MLB paths and PLAYER_PROPS_SPEC are unchanged.
Exit 0 = all pass.
"""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from services.feed_validation import (
    FOOTBALL_PLAYER_PROPS_EVENT_SPEC as SPEC,
    NBA_PLAYER_PROPS_SLATE_SPEC,
    PLAYER_PROPS_SPEC,
    validate_feed,
    validate_feed_event_slate,
)

results: list[tuple[bool, str]] = []
NOW = pd.Timestamp("2026-11-02T13:00:00Z")   # the RC bk-daily fetch time


def ok(cond, msg):
    results.append((bool(cond), msg))


def z(ts) -> str:
    return pd.Timestamp(ts).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def rows(eid: str, kickoff: str, n: int, *, start: int = 0, book: str = "DraftKings",
         market: str = "player_receptions", line=None) -> list[dict]:
    out = []
    for i in range(start, start + n):
        ln = (2.5 + (i % 7)) if line is None else line
        out.append({
            "Player": f"Player {eid}-{i}", "Team": "", "Stat": market, "MarketKey": market,
            "Line": ln, "Game": f"Away {eid}@Home {eid}", "Book": book,
            "LastUpdated": "2026-11-02 08:00", "EventId": eid, "EventCommenceAtUTC": kickoff,
            "SourceUpdatedAtUTC": "2026-11-02T12:55:00Z", "CurrentLine": ln,
            "OverOdds": -115, "UnderOdds": 105,   # synthetic-fixture
        })
    return out


def frame(*parts) -> pd.DataFrame:
    return pd.DataFrame([r for p in parts for r in p])


def run(df, prior, now=NOW, errors=0, path="NFL_Props.csv", tokens=("NFL",)):
    return validate_feed_event_slate(df, SPEC, prior_df=prior, path=path, sport_tokens=tokens,
                                     provider_errors=errors, now=now)


# --- the observed 2026-11-02 NFL slate (counts + kickoffs from prod; names/prices synthetic) ---------
SUN = ["2026-11-01T17:00:00Z"] * 8 + ["2026-11-01T20:05:00Z"] * 2 + ["2026-11-01T20:25:00Z"] * 2
MNF = ("nfl-mnf", "2026-11-03T01:20:00Z")
TNF = ("nfl-tnf", "2026-11-06T01:15:00Z")
NEXT_SUN = "2026-11-08T18:00:00Z"
NEXT_SUN_COUNTS = [7, 6, 6, 7, 6, 3, 1]          # four more events posted 0 rows (not in the frame)


def nfl_sunday_prior() -> pd.DataFrame:
    counts = [220] * 8 + [219] * 4                   # 12 played games = 2,636 rows
    parts = [rows(f"nfl-sun{i}", k, n) for i, (k, n) in enumerate(zip(SUN, counts))]
    return frame(*parts, rows(*MNF, 195))           # + Monday night, still eligible = 2,831


def nfl_monday_candidate() -> pd.DataFrame:
    parts = [rows(*MNF, 221), rows(*TNF, 123)]
    parts += [rows(f"nfl-next{i}", NEXT_SUN, n) for i, n in enumerate(NEXT_SUN_COUNTS)]
    return frame(*parts)                             # 380 rows, 9 events with rows


def check_replay_nfl():
    prior, cand = nfl_sunday_prior(), nfl_monday_candidate()
    ok(len(prior) == 2831 and len(cand) == 380, f"A: replay fixture matches prod counts ({len(prior)} -> {len(cand)})")
    legacy_ok, legacy_errs = validate_feed(cand, PLAYER_PROPS_SPEC, prior_df=prior, path="NFL_Props.csv",
                                           sport_tokens=("NFL",))
    ok(not legacy_ok and any("collapse" in e for e in legacy_errs),
       "A: the legacy whole-file rule rejects this exact turnover (incident reproduced)")
    good, errs, rc, pub = run(cand, prior)
    ok(good, f"A: Sunday full slate -> Monday early-week slate is ACCEPTED ({errs})")
    ok(rc["completed_events_removed"] == 12 and rc["completed_rows_removed"] == 2636,
       f"A: 12 played games / 2,636 rows removed from the comparison ({rc['completed_events_removed']}, "
       f"{rc['completed_rows_removed']})")
    ok(rc["overlapping_events_retained"] == 1 and rc["new_events_added"] == 8 and rc["sparse_future_events"] == 7,
       f"A: overlap=1 (MNF), new=8, sparse=7 ({rc['overlapping_events_retained']}, {rc['new_events_added']}, "
       f"{rc['sparse_future_events']})")
    ok(rc["final_published_rows"] == 380 and rc["reason_code"] == "CURRENT_SLATE_VALID",
       f"A: all 380 current rows published ({rc['final_published_rows']}, {rc['reason_code']})")
    return pub


def check_week_growth(monday_pub):
    wed = pd.Timestamp("2026-11-04T13:00:00Z")
    parts = [rows(*TNF, 150)] + [rows(f"nfl-next{i}", NEXT_SUN, 60) for i in range(11)]
    good, errs, rc, pub = run(frame(*parts), monday_pub, now=wed)
    ok(good, f"B: sparse Monday postings growing by Wednesday are ACCEPTED ({errs})")
    ok(rc["completed_events_removed"] == 1 and rc["new_events_added"] == 4 and rc["overlapping_events_retained"] == 8,
       f"B: MNF retired, 4 newly posted, 8 carried ({rc['completed_events_removed']}, {rc['new_events_added']}, "
       f"{rc['overlapping_events_retained']})")
    # small (<20 row) early postings may fluctuate without tripping the per-event guard
    shrink = [rows(*TNF, 150)] + [rows(f"nfl-next{i}", NEXT_SUN, 1) for i in range(7)]
    good2, errs2, _, _ = run(frame(*shrink), monday_pub, now=wed)
    ok(good2, f"B: sub-threshold early postings that shrink are not treated as a collapse ({errs2})")


def check_event_collapse(monday_pub):
    tue = pd.Timestamp("2026-11-03T13:00:00Z")
    parts = [rows(*TNF, 30)] + [rows(f"nfl-next{i}", NEXT_SUN, n) for i, n in enumerate(NEXT_SUN_COUNTS)]
    good, errs, rc, pub = run(frame(*parts), monday_pub, now=tue)
    ok(not good and rc["reason_code"] == "EVENT_COLLAPSE" and pub is None,
       f"C: still-eligible TNF 123 -> 30 rows is REJECTED ({rc['reason_code']}: {errs})")
    ok(rc["collapsed_events"] == [{"event_id": "nfl-tnf", "prior_rows": 123, "new_rows": 30}],
       f"C: the collapsed event is named with its counts ({rc['collapsed_events']})")
    vanished = [rows(f"nfl-next{i}", NEXT_SUN, n) for i, n in enumerate(NEXT_SUN_COUNTS)]
    good2, _, rc2, _ = run(frame(*vanished), monday_pub, now=tue)
    ok(not good2 and rc2["reason_code"] == "EVENT_VANISHED"
       and rc2["vanished_events"] == [{"event_id": "nfl-tnf", "prior_rows": 123}],
       f"C: a still-eligible event (123 rows) that vanishes entirely is REJECTED ({rc2['reason_code']})")
    exactly_half = [rows(*TNF, 62)] + vanished
    good3, errs3, _, _ = run(frame(*exactly_half), monday_pub, now=tue)
    ok(good3, f"C: a drop to >= 50% of the same event is within the governed threshold ({errs3})")
    # vanishing fails closed at ANY prior size -- the 20-row minimum governs percentages only.
    for prior_n in (1, 19):
        prior = frame(rows(*TNF, 123), rows("nfl-tiny", NEXT_SUN, prior_n))
        good4, _, rc4, pub4 = run(frame(rows(*TNF, 123)), prior, now=tue)
        ok(not good4 and rc4["reason_code"] == "EVENT_VANISHED" and pub4 is None,
           f"C: a published future event going {prior_n} -> 0 rows is REJECTED ({rc4['reason_code']})")
        shrink = frame(rows(*TNF, 123), rows("nfl-tiny", NEXT_SUN, 1))
        good5, errs5, _, _ = run(shrink, prior, now=tue)
        ok(good5, f"C: the same sparse event going {prior_n} -> 1 row is below the percentage floor ({errs5})")


def check_no_usable_event():
    played = frame(rows("nfl-sun0", SUN[0], 40))
    good, errs, rc, _ = run(played, nfl_sunday_prior())
    ok(not good and rc["reason_code"] == "NO_USABLE_CURRENT_EVENT",
       f"D: provider success with only already-started events is REJECTED ({rc['reason_code']})")
    empty = pd.DataFrame(columns=list(rows(*MNF, 1)[0].keys()))
    good2, _, rc2, _ = run(empty, nfl_sunday_prior())
    ok(not good2 and rc2["reason_code"] == "NO_USABLE_CURRENT_EVENT",
       f"D: provider success with zero rows is REJECTED ({rc2['reason_code']})")


def check_identity():
    base = nfl_monday_candidate()
    prior = nfl_sunday_prior()
    cases = {
        "blank EventId": ("EventId", ""),
        "missing EventId (NaN)": ("EventId", float("nan")),
        "unparseable kickoff": ("EventCommenceAtUTC", "Sunday 1pm"),
        "naive kickoff (no zone)": ("EventCommenceAtUTC", "2026-11-08 18:00:00"),
        "non-zero-offset kickoff": ("EventCommenceAtUTC", "2026-11-08T13:00:00-05:00"),
        "blank kickoff": ("EventCommenceAtUTC", ""),
    }
    for label, (col, val) in cases.items():
        bad = base.copy()
        bad.loc[bad.index[5], col] = val
        good, _, rc, pub = run(bad, prior)
        ok(not good and rc["reason_code"] == "EVENT_IDENTITY_INVALID" and pub is None,
           f"E: {label} on one row REJECTS the candidate ({rc['reason_code']})")
    conflict = base.copy()
    conflict.loc[conflict["EventId"] == "nfl-tnf", "EventCommenceAtUTC"] = [
        TNF[1] if i % 2 else "2026-11-06T02:15:00Z" for i in range(int((conflict["EventId"] == "nfl-tnf").sum()))]
    good, _, rc, _ = run(conflict, prior)
    ok(not good and rc["reason_code"] == "EVENT_IDENTITY_INVALID",
       f"E: one event carrying two kickoff times is REJECTED ({rc['reason_code']})")
    no_col = base.drop(columns=["EventCommenceAtUTC"])
    good, errs, _, _ = run(no_col, prior)
    ok(not good and any("EventCommenceAtUTC" in e for e in errs), "E: a frame without the kickoff column is REJECTED")


def check_completed_absent(monday_pub):
    ok(monday_pub is not None and (_kick(monday_pub) > NOW).all(),
       "F: the published Monday frame contains no event that has kicked off")
    ok(not monday_pub["EventId"].str.startswith("nfl-sun").any(), "F: no Sunday (played) event is published")
    stray = frame(rows(*MNF, 221), rows(*TNF, 123), rows("nfl-sun3", SUN[3], 15))   # a started game the feed still returned
    good, errs, rc, pub = run(stray, nfl_sunday_prior())
    ok(good and rc["started_candidate_rows_removed"] == 15 and "nfl-sun3" not in set(pub["EventId"]),
       f"F: a started event in the candidate is dropped, counted, never published ({rc['started_candidate_rows_removed']}; {errs})")


def _kick(df):
    return pd.to_datetime(df["EventCommenceAtUTC"], utc=True)


def check_ncaaf():
    sat = ["2026-10-31T16:00:00Z", "2026-10-31T19:30:00Z", "2026-11-01T00:00:00Z"]
    counts = [55] * 24 + [56] * 22                      # 46 played events = 2,552 rows
    prior = frame(*[rows(f"cfb-old{i}", sat[i % 3], n) for i, n in enumerate(counts)])
    cand = frame(rows("cfb-a", "2026-11-04T00:00:00Z", 33), rows("cfb-b", "2026-11-05T00:30:00Z", 32),
                 rows("cfb-c", "2026-11-07T17:00:00Z", 22))
    ok(len(prior) == 2552 and len(cand) == 87, f"G: NCAAF replay fixture matches prod counts ({len(prior)} -> {len(cand)})")
    legacy_ok, _ = validate_feed(cand, PLAYER_PROPS_SPEC, prior_df=prior, path="NCAAF_Props.csv",
                                 sport_tokens=("NCAAF",))
    ok(not legacy_ok, "G: the legacy rule rejects the NCAAF turnover (incident reproduced)")
    good, errs, rc, pub = run(cand, prior, path="NCAAF_Props.csv", tokens=("NCAAF",))
    ok(good and rc["completed_events_removed"] == 46 and rc["final_published_rows"] == 87,
       f"G: NCAAF turnover ACCEPTED, 46 played events removed, 87 published ({errs})")
    collapse = frame(rows("cfb-a", "2026-11-04T00:00:00Z", 5), rows("cfb-b", "2026-11-05T00:30:00Z", 32),
                     rows("cfb-c", "2026-11-07T17:00:00Z", 22))
    good2, _, rc2, _ = run(collapse, cand, now=pd.Timestamp("2026-11-03T13:00:00Z"),
                           path="NCAAF_Props.csv", tokens=("NCAAF",))
    ok(not good2 and rc2["reason_code"] == "EVENT_COLLAPSE",
       f"G: NCAAF still-eligible event 33 -> 5 rows is REJECTED ({rc2['reason_code']})")
    good3, errs3, _, _ = run(cand, prior, path="NFL_Props.csv", tokens=("NCAAF",))
    ok(not good3 and any("sport tokens" in e for e in errs3), "G: wrong-sport output path is still REJECTED")


def check_provider_error():
    good, _, rc, _ = run(nfl_monday_candidate(), nfl_sunday_prior(), errors=1)
    ok(not good and rc["reason_code"] == "PROVIDER_ERROR", f"H: a provider error REJECTS ({rc['reason_code']})")


def check_malformed():
    cand = nfl_monday_candidate()
    cand.loc[cand.index[0], "Line"] = float("nan")
    cand.loc[cand.index[1], ["OverOdds", "UnderOdds"]] = [float("nan"), float("nan")]
    good, errs, rc, pub = run(cand, nfl_sunday_prior())
    ok(good and rc["rejected_malformed_rows"] == 2 and rc["final_published_rows"] == 378 and len(pub) == 378,
       f"I: 2 malformed market rows dropped + counted, 378 published ({rc['malformed_by_reason']}; {errs})")
    one_sided = nfl_monday_candidate()
    one_sided["UnderOdds"] = float("nan")
    good2, _, rc2, _ = run(one_sided, nfl_sunday_prior())
    ok(good2 and rc2["rejected_malformed_rows"] == 0, "I: a price on one side only is a valid row, not malformed")


def check_market_contract():
    """The line-vs-binary contract must cover every configured NFL + NCAAF props market exactly once, and
    a binary market is validated as binary -- never discarded for lacking a provider line."""
    import fetch_player_props as fp

    line_set, bin_set = set(SPEC.line_markets), set(SPEC.binary_markets)
    ok(not (line_set & bin_set), "I: no market is both line-based and binary")
    for sport in ("americanfootball_nfl", "americanfootball_ncaaf"):
        cfg = set(fp.SPORT_DEFAULT_MARKETS[sport])
        ok(cfg <= (line_set | bin_set), f"I: every configured {sport} market is classified "
           f"(unclassified: {sorted(cfg - line_set - bin_set)})")
    ok(bin_set == {"player_anytime_td"}, f"I: the binary set is exactly anytime TD ({sorted(bin_set)})")
    # the parser's binary representation: YES/NO without a provider point -> Line 0.5
    ev = {"id": "e1", "away_team": "A", "home_team": "H", "commence_time": "2026-11-08T18:00:00Z"}
    bk = {"key": "draftkings", "title": "DraftKings", "last_update": "2026-11-02T12:00:00Z",
          "markets": [{"key": "player_anytime_td", "last_update": "2026-11-02T12:00:00Z",
                       "outcomes": [{"name": "Yes", "description": "Some Player", "price": 150}]}]}  # synthetic-fixture
    parsed = fp.parse_market_rows(ev, bk, ["player_anytime_td"])
    ok(len(parsed) == 1 and parsed[0]["Line"] == 0.5,
       f"I: the parser represents a line-less Yes/No market as Line 0.5 ({[r['Line'] for r in parsed]})")

    td = lambda eid, n, line: rows(eid, NEXT_SUN, n, market="player_anytime_td", line=line)
    base = [rows(*MNF, 221), rows(*TNF, 123)]
    g1, e1, r1, _ = run(frame(*base, td("td-a", 10, float("nan")), td("td-b", 10, 0.5)), nfl_sunday_prior())
    ok(g1 and r1["rejected_malformed_rows"] == 0 and r1["final_published_rows"] == 364,
       f"I: binary rows with no line or Line 0.5 are VALID and published ({r1['malformed_by_reason']}; {e1})")
    g2, _, r2, _ = run(frame(*base, td("td-c", 4, 1.5)), nfl_sunday_prior())
    ok(g2 and r2["malformed_by_reason"]["binary_market_with_non_binary_line"] == 4,
       f"I: a binary market carrying a non-binary line is dropped + counted ({r2['malformed_by_reason']})")
    g3, _, r3, _ = run(frame(*base, rows("odd", NEXT_SUN, 3, market="player_kicking_points")), nfl_sunday_prior())
    ok(g3 and r3["malformed_by_reason"]["market_outside_contract"] == 3,
       f"I: a market outside the contract is dropped + counted ({r3['malformed_by_reason']})")
    nl = frame(*base)
    nl.loc[nl.index[0], "Line"] = float("nan")
    g4, _, r4, _ = run(nl, nfl_sunday_prior())
    ok(g4 and r4["malformed_by_reason"]["line_market_without_finite_line"] == 1,
       f"I: a line market without a finite line is dropped + counted ({r4['malformed_by_reason']})")


def check_boundaries():
    t = pd.Timestamp("2026-11-05T18:00:00Z")   # before TNF, so only the boundary events are in question
    prior = frame(rows(*TNF, 123))
    cand = frame(rows(*TNF, 123), rows("kick-now", z(t), 30), rows("kick-1s", z(t + pd.Timedelta(seconds=1)), 30))
    good, errs, rc, pub = run(cand, prior, now=t)
    ids = set(pub["EventId"]) if pub is not None else set()
    ok(good and "kick-now" not in ids and rc["started_candidate_rows_removed"] == 30,
       f"L: kickoff exactly equal to validation time is EXCLUDED ({rc['started_candidate_rows_removed']}; {errs})")
    ok(good and "kick-1s" in ids, "L: kickoff one second in the future remains ELIGIBLE")
    for spelling in ("2026-11-08T18:00:00+00:00", "2026-11-08T18:00:00.000Z", "2026-11-08t18:00:00z",
                     "2026-11-08 18:00:00Z", "2026-11-08T13:00:00-05:00"):
        alt = frame(rows(*TNF, 123), rows("alt", spelling, 30))
        g, _, r, _ = run(alt, prior, now=pd.Timestamp("2026-11-03T13:00:00Z"))
        ok(not g and r["reason_code"] == "EVENT_IDENTITY_INVALID",
           f"L: equivalent-instant spelling {spelling!r} is REJECTED (frozen contract: canonical ...Z only)")


# --- J. end to end through fetch_player_props.main() ----------------------------------------------------
def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _drive_main(fp, sport, root: Path, out: Path, events: list[dict], per_event: dict,
                errors_for: set = frozenset(), extra_args: tuple = ()):
    """Run fetch_player_props.main() offline: the provider is stubbed, the quota ledger is stubbed, and
    BASE_DIR points at a temp root so the real shape-receipt writer runs without touching repo data."""
    class _Q:
        def print_receipt(self, **kw):
            return True, {}

    saved = (fp.fetch_events, fp.fetch_event_props, fp._QUOTA, fp.BASE_DIR, sys.argv[:])

    def fake_event_props(api_key, sport_, event, bookmakers, markets, regions):
        if event["id"] in errors_for:
            raise RuntimeError("synthetic provider error")
        got = [dict(r) for r in per_event.get(event["id"], [])]
        fp._record_event_shape(event, {r["MarketKey"] for r in got}, markets, 1, len(got))
        return got

    fp.fetch_events = lambda api_key, sport_, days: events
    fp.fetch_event_props = fake_event_props
    fp._QUOTA = _Q()
    fp.BASE_DIR = root
    sys.argv = ["fetch_player_props.py", "--api-key", "qc-offline-dummy", "--sport", sport,
                "--output", str(out), "--days", "7", *extra_args]
    try:
        return fp.main()
    finally:
        fp.fetch_events, fp.fetch_event_props, fp._QUOTA, fp.BASE_DIR, sys.argv = saved


def _shape(root: Path, sport: str) -> dict:
    import json
    return json.loads((root / "data" / "tracking" / f"_last_props_fetch_{sport}.json").read_text(encoding="utf-8"))


def check_end_to_end():
    import fetch_player_props as fp

    now = datetime.now(timezone.utc).replace(microsecond=0)
    past, soon, later = (z(now - timedelta(hours=20)), z(now + timedelta(hours=12)), z(now + timedelta(days=3)))
    for sport, token in (("americanfootball_nfl", "NFL"), ("americanfootball_ncaaf", "NCAAF")):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = root / "props" / f"{token}_Props.csv"
            out.parent.mkdir(parents=True)
            prior = frame(*[rows(f"old{i}", past, 200) for i in range(10)], rows("live", soon, 120),
                          rows("tiny", later, 3))
            prior.to_csv(out, index=False)
            before = _sha(out)
            ev = [{"id": "live", "home_team": "Home live", "away_team": "Away live", "commence_time": soon},
                  {"id": "tiny", "home_team": "Home tiny", "away_team": "Away tiny", "commence_time": later},
                  {"id": "nx", "home_team": "Home nx", "away_team": "Away nx", "commence_time": later},
                  {"id": "kicked", "home_team": "Home k", "away_team": "Away k", "commence_time": past}]
            healthy = {"live": rows("live", soon, 130), "tiny": rows("tiny", later, 3),
                       "nx": rows("nx", later, 5), "kicked": rows("kicked", past, 15)}

            def preserved(label, rc_, rc_expect=1):
                leftovers = [p.name for p in out.parent.iterdir() if p.name != out.name]
                ok(rc_ == rc_expect and _sha(out) == before and not leftovers,
                   f"J[{token}]: {label} -> exit 1, prior file byte-identical, no temp files "
                   f"(rc={rc_}, leftovers={leftovers})")

            # 1) a still-eligible event collapses -> rejected, prior file byte-identical, no temp files.
            preserved("collapse", _drive_main(fp, sport, root, out, ev, {**healthy, "live": rows("live", soon, 10)}))
            rec = _shape(root, sport).get("publish", {})
            ok(rec.get("published") is False and rec.get("published_rows") == 0 and rec.get("reason_code") == "EVENT_COLLAPSE",
               f"J[{token}]: the shape receipt records the rejected publish ({rec.get('reason_code')}, rows={rec.get('published_rows')})")
            # 2) provider error on one event -> rejected, prior preserved.
            preserved("provider error", _drive_main(fp, sport, root, out, ev, healthy, errors_for={"nx"}))
            # 3) --allow-collapse cannot bypass any event-aware protection.
            for label, feed in (("collapse", {**healthy, "live": rows("live", soon, 10)}),
                                ("3 -> 0 vanish", {k: v for k, v in healthy.items() if k != "tiny"}),
                                ("bad kickoff", {**healthy, "nx": rows("nx", "Sunday", 5)})):
                preserved(f"--allow-collapse + {label}",
                          _drive_main(fp, sport, root, out, ev, feed, extra_args=("--allow-collapse",)))

            # 4) the normal turnover -> published atomically; played events gone; nothing retained to pad rows.
            rc_ok = _drive_main(fp, sport, root, out, ev, healthy)
            pub = pd.read_csv(out)
            ok(rc_ok == 0 and _sha(out) != before and len(pub) == 138,
               f"J[{token}]: the slate turnover publishes the 138 current rows (rc={rc_ok}, rows={len(pub)})")
            ok(not pub["EventId"].astype(str).str.match(r"^(old|kicked)").any()
               and (pd.to_datetime(pub["EventCommenceAtUTC"], utc=True) > pd.Timestamp(now)).all(),
               f"J[{token}]: played/started events are absent after publication (never retained to inflate the count)")
            shape = _shape(root, sport)
            pubrec = shape.get("publish", {})
            ok(shape.get("rows_fetched") == 153 and pubrec.get("published") is True
               and pubrec.get("published_rows") == len(pub) == pubrec.get("final_published_rows")
               and pubrec.get("started_candidate_rows_removed") == 15,
               f"J[{token}]: receipt keeps raw rows_fetched=153 apart from the published filtered file "
               f"({pubrec.get('published_rows')} rows; 15 started rows removed)")
            leftovers = [p.name for p in out.parent.iterdir() if p.name != out.name]
            ok(not leftovers, f"J[{token}]: no temp files left after the atomic publish ({leftovers})")


def check_scope():
    import fetch_player_props as fp

    ok(fp.EVENT_AWARE_PROPS_SPORTS == frozenset({"americanfootball_nfl", "americanfootball_ncaaf"}),
       f"K: only NFL + NCAAF opt in ({sorted(fp.EVENT_AWARE_PROPS_SPORTS)})")
    ok(not PLAYER_PROPS_SPEC.event_aware and not NBA_PLAYER_PROPS_SLATE_SPEC.event_aware
       and NBA_PLAYER_PROPS_SLATE_SPEC.slate_aware,
       "K: PLAYER_PROPS_SPEC (WNBA/MLB) and the NBA slate spec are unchanged")
    big = frame(*[rows(f"w{i}", "2026-11-03T00:00:00Z", 100) for i in range(10)])
    small = frame(rows("w0", "2026-11-03T00:00:00Z", 100))
    legacy_ok, _ = validate_feed(small, PLAYER_PROPS_SPEC, prior_df=big, path="WNBA_Props.csv", sport_tokens=("WNBA",))
    ok(not legacy_ok, "K: the whole-file collapse rule still guards the non-football props feeds")


def main() -> int:
    monday_pub = check_replay_nfl()
    check_week_growth(monday_pub)
    check_event_collapse(monday_pub)
    check_no_usable_event()
    check_identity()
    check_completed_absent(monday_pub)
    check_ncaaf()
    check_provider_error()
    check_malformed()
    check_market_contract()
    check_boundaries()
    check_end_to_end()
    check_scope()

    print("=" * 60)
    print("BANKROLL KINGS PROPS SLATE-TURNOVER QC")
    print("=" * 60)
    for passed, msg in results:
        print(f"[{'PASS' if passed else 'FAIL'}] {msg}")
    n_fail = sum(1 for p, _ in results if not p)
    print(f"\n{len(results) - n_fail}/{len(results)} passed")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    os.environ.setdefault("SECRET_KEY", "qc-props-slate-turnover")
    raise SystemExit(main())
