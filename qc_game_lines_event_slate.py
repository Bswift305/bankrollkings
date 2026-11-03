"""QC: event-aware game-lines contract (game_lines_event_v1) -- NBA game-lines correction, 2026-11.

Defect: fetch_game_lines validated NBA lines with a whole-file "new rows >= 50% of prior" test, so a normal
slate turnover (45 rows of last night's PLAYED games -> 15 rows of today's future games) was rejected, and
refresh_nba_daily then halted and skipped 11 later steps. This QC proves the shared, configurable
replacement (services/feed_validation.validate_game_lines_event_slate + NBA_GAME_LINES_EVENT_SPEC), the
fetcher wiring (UTC kickoff provenance, atomic three-file publish, receipt), orchestration isolation in
refresh_nba_daily, line-movement failure honesty, and customer containment on /game-lines + the NBA
command center.

OFFLINE: synthetic frames, a stubbed provider (get_json), temp directories, faked subprocesses. No network,
no Odds API credits, no real data file is read or written. Exit 0 on pass, 1 on any failure.
"""
from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import io
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# app.py enforces SECRET_KEY at import; the containment section imports it. QC-only dummy (precedent:
# qc_nba_gated_market_facts.py). Never a real secret.
os.environ.setdefault("SECRET_KEY", "qc-only-not-a-real-secret")

from services.feed_validation import (
    GAME_LINES_SPEC, NBA_GAME_LINES_EVENT_SPEC, FeedSpec, validate_feed, validate_game_lines_event_slate,
)
from services.timeutils import eastern_wall_to_utc_strict, to_eastern_datetime_str

FAILS: list[str] = []
NOTES: list[str] = []
NOW = "2026-11-03T15:00:00Z"
S = NBA_GAME_LINES_EVENT_SPEC


def check(cond, msg):
    (NOTES if cond else FAILS).append(msg)


def row(gid, kick, book, date="2026-11-03", time="19:30", lu="2026-11-03 09:00", **kw):
    r = dict(Date=date, Time=time, Away=f"Away {gid}", Home=f"Home {gid}", AwayFull=f"Away {gid}",
             HomeFull=f"Home {gid}", AwayML=120.0, HomeML=-140.0, Spread=-3.5, SpreadOdds=-110.0, Total=220.5,
             OverOdds=-110.0, UnderOdds=-110.0, Book=book, GameID=gid, EventCommenceAtUTC=kick, LastUpdated=lu)
    r.update(kw)
    return r


def frame(rows, legacy=False):
    df = pd.DataFrame(rows)
    return df.drop(columns=["EventCommenceAtUTC"]) if legacy else df


def v(cand, prior=None, now=NOW, books=("draftkings", "fanduel", "caesars"), **kw):
    return validate_game_lines_event_slate(cand, S, prior_df=prior, now=now, requested_books=list(books), **kw)


BOOKS = ("DraftKings", "FanDuel", "Caesars")
FUT = "2026-11-04T00:30:00Z"


# ------------------------------------------------------------------------------------------------ validator
def qc_validator():
    # (1) 45 prior (15 played legacy events x 3 books) -> 15 current (5 future x 3): ACCEPTED.
    prior = frame([row(f"p{i}", "", b, date="2026-11-02", time="19:30", lu="2026-11-02 19:20")
                   for i in range(15) for b in BOOKS], legacy=True)
    cand = frame([row(f"n{i}", FUT, b) for i in range(5) for b in BOOKS])
    ok, errs, r, pub = v(cand, prior)
    check(ok and len(pub) == 15 and r["completed_events_removed"] == 15 and r["completed_rows_removed"] == 45
          and r["prior_kickoff_basis"] == "DERIVED_LEGACY_KICKOFF" and r["derived_legacy_kickoff_rows"] == 45,
          f"45 prior (played) -> 15 current ACCEPTED (completed removed={r['completed_events_removed']}, "
          f"basis={r['prior_kickoff_basis']}, errs={errs[:1]})")
    ok_old, errs_old = validate_feed(cand.drop(columns=["EventCommenceAtUTC"]), GAME_LINES_SPEC, prior_df=prior)
    check(not ok_old and any("collapse" in e for e in errs_old),
          "defect reproduced: the legacy whole-file GAME_LINES_SPEC test rejects the same 45 -> 15 turnover")

    # (2) a still-future published event disappears -> REJECT at any size (even a 1-row prior event).
    prior2 = frame([row(e, FUT, b) for e in ("e1", "e2") for b in BOOKS] + [row("e3", FUT, "DraftKings")])
    cand2 = frame([row(e, FUT, b, lu="2026-11-03 10:00") for e in ("e1", "e2") for b in BOOKS])
    ok, errs, r, pub = v(cand2, prior2)
    check(not ok and r["reason_code"] == "EVENT_VANISHED" and pub is None
          and [x["event_id"] for x in r["vanished_events"]] == ["e3"],
          f"still-future event e3 (1 prior row) vanished -> REJECT EVENT_VANISHED ({r['reason_code']})")

    # (3) new sparse event: accepted with a coverage warning.
    prior3 = frame([row(e, FUT, b) for e in ("e1", "e2") for b in BOOKS])
    cand3 = frame([row(e, FUT, b, lu="2026-11-03 10:00") for e in ("e1", "e2") for b in BOOKS]
                  + [row("e9", FUT, "DraftKings", lu="2026-11-03 10:00")])
    ok, errs, r, pub = v(cand3, prior3)
    check(ok and r["new_events_added"] == 1 and [x["event_id"] for x in r["sparse_new_events"]] == ["e9"]
          and "NEW_EVENT_SPARSE" in r["warnings"] and r["coverage_status"] == "COVERAGE_DEGRADED",
          f"new sparse event (1/3 books) ACCEPTED with NEW_EVENT_SPARSE warning ({r['coverage_status']})")

    # (4) reduced books but >= 1 valid quote -> PUBLISHED and labelled COVERAGE_DEGRADED.
    cand4 = frame([row("e1", FUT, "DraftKings", lu="2026-11-03 10:00")]
                  + [row("e2", FUT, b, lu="2026-11-03 10:00") for b in BOOKS])
    ok, errs, r, pub = v(cand4, prior3)
    deg = {x["event_id"]: x for x in r["coverage_degraded_events"]}
    check(ok and len(pub) == 4 and r["coverage_status"] == "COVERAGE_DEGRADED" and "COVERAGE_DEGRADED" in r["warnings"]
          and deg.get("e1", {}).get("lost_books") == ["Caesars", "FanDuel"],
          f"reduced books (3 -> 1) with a valid quote PUBLISHED, COVERAGE_DEGRADED (lost {deg.get('e1', {}).get('lost_books')})")

    # (4b) event present but ZERO valid rows (no prices) -> treated as vanished -> REJECT.
    cand4b = frame([row("e1", FUT, b, lu="2026-11-03 10:00", AwayML=np.nan, HomeML=np.nan, SpreadOdds=np.nan,
                        OverOdds=np.nan, UnderOdds=np.nan) for b in BOOKS]
                   + [row("e2", FUT, b, lu="2026-11-03 10:00") for b in BOOKS])
    ok, errs, r, pub = v(cand4b, prior3)
    check(not ok and r["reason_code"] == "EVENT_VANISHED" and r["rows_dropped_by_reason"]["no_valid_market"] == 3,
          "previously published event with zero VALID rows -> REJECT (no per-event minimum, zero is zero)")

    # (4c) frozen malformed-row rule: market-level null, row drop, whole-feed reject.
    cand4c = frame([row("e1", FUT, "DraftKings", SpreadOdds=np.nan),            # M2 spreads incomplete
                    row("e1", FUT, "FanDuel", AwayML=1.91, HomeML=2.05),         # M1 decimal-looking price
                    row("e1", FUT, "Caesars", OverOdds=np.nan),                  # M3 totals incomplete
                    row("e1", FUT, ""),                                          # D1 blank book
                    row("e2", FUT, "DraftKings")])
    ok, errs, r, pub = v(cand4c)
    dk = pub[(pub["GameID"] == "e1") & (pub["Book"] == "DraftKings")] if pub is not None else pd.DataFrame()
    fd = pub[(pub["GameID"] == "e1") & (pub["Book"] == "FanDuel")] if pub is not None else pd.DataFrame()
    check(ok and len(dk) == 1 and pd.isna(dk.iloc[0]["Spread"]) and dk.iloc[0]["AwayML"] == 120.0
          and len(fd) == 1 and pd.isna(fd.iloc[0]["AwayML"]) and fd.iloc[0]["Total"] == 220.5,
          "market-level null: incomplete spreads / invalid h2h price blanked, row kept on its valid markets")
    check(ok and r["market_quotes_nulled_by_reason"] == {"h2h_incomplete": 1, "spreads_incomplete": 1,
                                                          "totals_incomplete": 1}
          and r["rows_dropped_by_reason"]["blank_book"] == 1 and len(pub) == 4,
          f"frozen rule counts: nulled={r['market_quotes_nulled_by_reason']}, dropped={r['rows_dropped_by_reason']}")
    for label, bad in (("non-finite price (inf)", dict(OverOdds=np.inf)),
                       ("blank GameID", dict(GameID="")),
                       ("non-canonical kickoff (+00:00)", dict(EventCommenceAtUTC="2026-11-04T00:30:00+00:00")),
                       ("blank team", dict(Home=""))):
        ok, errs, r, pub = v(frame([row("e1", FUT, "DraftKings", **bad), row("e2", FUT, "DraftKings")]))
        check(not ok and r["reason_code"] in ("STRUCTURAL_INVALID", "EVENT_IDENTITY_INVALID"),
              f"whole-feed REJECT on {label} ({r['reason_code']})")
    ok, errs, r, pub = v(frame([row("e1", FUT, "DraftKings"), row("e1", "2026-11-04T01:00:00Z", "FanDuel")]))
    check(not ok and r["reason_code"] == "EVENT_IDENTITY_INVALID", "one GameID with two kickoffs -> REJECT")
    ok, errs, r, pub = v(frame([row("e1", FUT, "DraftKings")]), provider_errors=1)
    check(not ok and r["reason_code"] == "PROVIDER_ERROR", "provider error -> REJECT")
    ok, errs, r, pub = v(frame([row("e1", "2026-11-03T14:00:00Z", "DraftKings")]))
    check(not ok and r["reason_code"] == "NO_USABLE_CURRENT_EVENT", "zero usable current events -> REJECT")
    ok, errs, r, pub = v(frame([row("e1", FUT, "DraftKings")]), prior_unreadable=True)
    check(not ok and r["reason_code"] == "PRIOR_BASELINE_INVALID", "unreadable prior -> REJECT (comparison never skipped)")

    # (8) boundaries: completed absent; kickoff == now excluded; now + 1s eligible.
    cand8 = frame([row("eq", NOW, "DraftKings"), row("p1", "2026-11-03T15:00:01Z", "DraftKings"),
                   row("old", "2026-11-02T00:30:00Z", "DraftKings")])
    ok, errs, r, pub = v(cand8)
    ids = set(pub["GameID"]) if pub is not None else set()
    check(ok and ids == {"p1"} and r["started_candidate_events"] == 2,
          f"kickoff == now excluded, now + 1s published, completed absent (published {sorted(ids)})")
    check(pub is not None and set(pub["EventCommenceAtUTC"]) == {"2026-11-03T15:00:01Z"},
          "published rows carry the candidate's provider UTC kickoff unchanged")


def qc_legacy_bridge():
    # (5) legacy Eastern conversion on both sides of DST.
    cases = [("2026-07-15", "19:30", "2026-07-15T23:30:00Z", "EDT"), ("2026-01-15", "19:30", "2026-01-16T00:30:00Z", "EST"),
             ("2026-03-08", "19:30", "2026-03-08T23:30:00Z", "EDT, spring-forward day"),
             ("2026-11-01", "19:30", "2026-11-02T00:30:00Z", "EST, fall-back day")]
    for d, t, want, label in cases:
        dt, code = eastern_wall_to_utc_strict(d, t)
        got = dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None
        check(code == "OK" and got == want, f"legacy {d} {t} ET ({label}) -> {got} (want {want})")
    for d, t, k, label in (("2026-07-15", "19:30", "2026-07-15T23:30:00Z", "EDT"),
                           ("2026-01-15", "19:30", "2026-01-16T00:30:00Z", "EST")):
        prior = frame([row("L1", "", "DraftKings", date=d, time=t, lu=f"{d} 12:00")], legacy=True)
        kick_ts = pd.Timestamp(k)
        cand = frame([row("n1", (kick_ts + pd.Timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"), "DraftKings",
                          lu=f"{d} 13:00")])
        ok_at, _, r_at, _ = v(cand, prior, now=k)
        ok_before, _, r_before, _ = v(cand, prior, now=(kick_ts - pd.Timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ"))
        check(ok_at and r_at["completed_events_removed"] == 1 and not ok_before
              and r_before["reason_code"] == "EVENT_VANISHED",
              f"{label} legacy prior: started at derived kickoff (removed), still active 1s before (vanish -> reject)")
    # (6) malformed / ambiguous / nonexistent / missing legacy time: fail closed.
    for d, t, code in (("2026-11-03", "", "MISSING"), ("2026-11-03", "7:30 PM", "UNPARSEABLE"),
                       ("2026-11-01", "01:30", "AMBIGUOUS"), ("2026-03-08", "02:30", "NONEXISTENT")):
        dt, c = eastern_wall_to_utc_strict(d, t)
        prior = frame([row("L1", "", "DraftKings", date=d, time=t)], legacy=True)
        ok, errs, r, pub = v(frame([row("n1", FUT, "DraftKings")]), prior)
        check(dt is None and c == code and not ok and r["reason_code"] == "PRIOR_BASELINE_INVALID"
              and r["prior_kickoff_invalid"].get(f"LEGACY_KICKOFF_{code}") == 1,
              f"legacy time {t!r} on {d} -> {c}: fail closed PRIOR_BASELINE_INVALID")


# ------------------------------------------------------------------------------------------------ fetcher
def _event(eid, commence, books=("draftkings", "fanduel", "caesars"), lu=None):
    titles = {"draftkings": "DraftKings", "fanduel": "FanDuel", "caesars": "Caesars"}
    lu = lu or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    home, away = f"Home {eid}", f"Away {eid}"
    return {"id": eid, "commence_time": commence, "home_team": home, "away_team": away, "bookmakers": [
        {"key": b, "title": titles[b], "last_update": lu, "markets": [
            {"key": "h2h", "outcomes": [{"name": home, "price": -140}, {"name": away, "price": 120}]},
            {"key": "spreads", "outcomes": [{"name": home, "point": -3.5, "price": -110},
                                            {"name": away, "point": 3.5, "price": -110}]},
            {"key": "totals", "outcomes": [{"name": "Over", "point": 220.5, "price": -110},
                                           {"name": "Under", "point": 220.5, "price": -110}]}]}
        for b in books]}


def _sha(p):
    try:
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()
    except OSError:
        return None


def _run_fetch(fg, base, sport, payload_or_exc, prefix):
    out = {k: base / f"{prefix}_{k}.csv" for k in ("odds", "sched", "alias")}

    def fake_get_json(url):
        if isinstance(payload_or_exc, Exception):
            raise payload_or_exc
        return payload_or_exc

    def no_network(*a, **k):
        raise RuntimeError("network disabled in QC")

    saved = (fg.BASE_DIR, fg.get_json, fg.urlopen, fg._QUOTA.print_receipt, list(sys.argv))
    fg.BASE_DIR, fg.get_json, fg.urlopen = base, fake_get_json, no_network
    fg._QUOTA.print_receipt = lambda **k: (True, {})
    sys.argv = ["fetch_game_lines.py", "--api-key", "qc-offline", "--sport", sport,
                "--bookmakers", "draftkings,fanduel,caesars", "--output", str(out["odds"]),
                "--schedules-output", str(out["sched"]), "--schedule-alias-output", str(out["alias"]),
                "--skip-line-movement"]
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            rc = fg.main()
    finally:
        fg.BASE_DIR, fg.get_json, fg.urlopen, fg._QUOTA.print_receipt, sys.argv[:] = saved[0], saved[1], saved[2], saved[3], saved[4]
    rp = base / "data" / "tracking" / f"_last_game_lines_fetch_{sport}.json"
    receipt = json.loads(rp.read_text(encoding="utf-8")) if rp.exists() else {}
    return rc, out, receipt


def qc_fetcher():
    import fetch_game_lines as fg
    from services.atomic_csv import CsvValidationError, atomic_write_csv_set
    now = datetime.now(timezone.utc).replace(microsecond=0)
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        # legacy prior (no EventCommenceAtUTC): 6 PLAYED events x 3 books, Eastern Date/Time only.
        played = []
        for i in range(6):
            kick = (now - timedelta(hours=20, minutes=i)).strftime("%Y-%m-%dT%H:%M:00Z")
            d, t = to_eastern_datetime_str(kick).split(" ")
            lu = to_eastern_datetime_str((now - timedelta(hours=21)).strftime("%Y-%m-%dT%H:%M:00Z"))
            for b in BOOKS:
                played.append(row(f"old{i}", "", b, date=d, time=t, lu=lu))
        prior = frame(played, legacy=True)
        for k in ("odds", "sched"):
            prior.to_csv(base / f"nba_{k}.csv", index=False)
        fg.build_schedule_alias(prior).to_csv(base / "nba_alias.csv", index=False)

        c1 = (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:45Z")              # seconds != :00 on purpose
        c2 = (now + timedelta(days=1, hours=1)).strftime("%Y-%m-%dT%H:%M:%S+00:00")  # offset spelling
        c3 = (now + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        rc, out, rec = _run_fetch(fg, base, "basketball_nba", [_event("g1", c1), _event("g2", c2), _event("g3", c3)], "nba")
        odds = pd.read_csv(out["odds"]) if out["odds"].exists() else pd.DataFrame()
        want = {"g1": c1, "g2": c2.replace("+00:00", "Z"), "g3": c3}
        got = dict(zip(odds.get("GameID", []), odds.get("EventCommenceAtUTC", [])))
        derived = {g: eastern_wall_to_utc_strict(d, t)[0].strftime("%Y-%m-%dT%H:%M:%SZ")
                   for g, d, t in zip(odds.get("GameID", []), odds.get("Date", []), odds.get("Time", []))}
        check(rc == 0 and rec.get("outcome") == "UPDATED" and got == want,
              f"published NBA rows carry provider commence_time as canonical UTC Z ({got})")
        check(got.get("g1") != derived.get("g1"),
              "EventCommenceAtUTC is the provider value, not the Eastern-derived value (provider :45s survives)")
        check(all("EventCommenceAtUTC" in pd.read_csv(out[k]).columns for k in ("odds", "sched", "alias")),
              "all three NBA artifacts (odds, schedules mirror, alias) carry EventCommenceAtUTC")
        check(not set(odds.get("GameID", [])) & {f"old{i}" for i in range(6)} and len(odds) == 9,
              "completed (played) prior games absent from the published file")
        val = rec.get("validation") or {}
        check(val.get("prior_kickoff_basis") == "DERIVED_LEGACY_KICKOFF" and val.get("completed_events_removed") == 6
              and val.get("decision") == "PUBLISH" and rec.get("published") is True,
              f"receipt: DERIVED_LEGACY_KICKOFF used only to classify the prior "
              f"(removed {val.get('completed_events_removed')}), decision PUBLISH")
        check("DERIVED_LEGACY_KICKOFF" not in odds.to_csv(index=False), "derived legacy label never written into the data file")

        # (9) failed publish preserves every output byte-for-byte (g3 vanishes -> reject).
        before = {k: _sha(p) for k, p in out.items()}
        rc2, out2, rec2 = _run_fetch(fg, base, "basketball_nba", [_event("g1", c1), _event("g2", c2)], "nba")
        after = {k: _sha(p) for k, p in out2.items()}
        check(rc2 == 1 and before == after and rec2.get("outcome") == "VALIDATION_FAILED"
              and (rec2.get("validation") or {}).get("reason_code") == "EVENT_VANISHED"
              and all(o["sha256_before"] == o["sha256_after"] for o in rec2["outputs"].values()),
              "rejected lines publish leaves all three files byte-identical (hashes unchanged, receipt agrees)")
        rc3, out3, rec3 = _run_fetch(fg, base, "basketball_nba", RuntimeError("HTTP 500"), "nba")
        check(rc3 == 1 and {k: _sha(p) for k, p in out3.items()} == before and rec3.get("outcome") == "PROVIDER_ERROR",
              "provider error -> exit 1, receipt PROVIDER_ERROR, files unchanged")

        # atomic set: a failure while staging the 2nd file leaves the 1st untouched, no temp left behind.
        a, b = base / "set_a.csv", base / "set_b.csv"
        pd.DataFrame([{"Away": "x", "Home": "y"}]).to_csv(a, index=False)
        ha = _sha(a)
        try:
            atomic_write_csv_set([(pd.DataFrame([{"Away": "1", "Home": "2"}]), a, {"required_cols": ["Away"]}),
                                  (pd.DataFrame([{"Q": 1}]), b, {"required_cols": ["Away"]})])
            raised = False
        except CsvValidationError:
            raised = True
        check(raised and _sha(a) == ha and not b.exists() and not list(base.glob("*.tmp")),
              "atomic_write_csv_set: staging failure leaves every target byte-identical, no temp files")

        # scope: WNBA keeps GAME_LINES_SPEC and its unchanged schema; zero events -> NO_ACTIVE_EVENTS receipt.
        rcw, outw, recw = _run_fetch(fg, base, "basketball_wnba", [_event("w1", c1)], "wnba")
        wcols = list(pd.read_csv(outw["odds"]).columns) if outw["odds"].exists() else []
        check(rcw == 0 and "EventCommenceAtUTC" not in wcols and recw.get("contract") == "GAME_LINES_SPEC whole-file",
              f"scope: WNBA still validates with GAME_LINES_SPEC and its schema has no new column ({len(wcols)} cols)")
        rcz, _, recz = _run_fetch(fg, base, "basketball_wnba", [], "wnba")
        check(rcz == 1 and recz.get("outcome") == "NO_ACTIVE_EVENTS",
              "provider answered zero events -> exit 1 with receipt NO_ACTIVE_EVENTS (proof for the benign skip)")


def qc_scope():
    expected = FeedSpec(kind="game_lines", required_cols=("Away", "Home", "LastUpdated"),
                        numeric_cols=("Spread", "Total", "SpreadOdds", "OverOdds", "UnderOdds", "AwayML", "HomeML"),
                        timestamp_col="LastUpdated", id_cols=("GameID", "Book"),
                        value_cols=("Spread", "Total", "SpreadOdds"), identity_cols=("Away", "Home"), min_rows=1)
    check(dataclasses.asdict(GAME_LINES_SPEC) == dataclasses.asdict(expected) and not GAME_LINES_SPEC.lines_event_aware,
          "scope: GAME_LINES_SPEC unchanged (whole-file contract) for every non-NBA sport")
    import fetch_game_lines as fg
    check(fg.EVENT_AWARE_GAME_LINES_SPORTS == frozenset({"basketball_nba"})
          and all(fg._event_spec_for(s) is None for s in fg.SPORT_OUTPUTS if s != "basketball_nba")
          and fg._event_spec_for("basketball_nba") is NBA_GAME_LINES_EVENT_SPEC,
          "scope: only basketball_nba is an event-aware game-lines consumer")
    cols = list(fg.build_dataframe([fg.parse_event_markets(_event("x", FUT), _event("x", FUT)["bookmakers"][0])]).columns)
    check("EventCommenceAtUTC" not in cols, "scope: non-event-aware build_dataframe schema unchanged")


# ------------------------------------------------------------------------------------------------ orchestration
class _Fake:
    def __init__(self, code):
        self.returncode = code


def qc_orchestration():
    import refresh_nba_daily as nba
    labels = [s[0] for s in nba.STEPS]
    check(set(labels) <= set(nba.STEP_LINES_DEPENDENCY), "every NBA daily step is classified in the dependency map")
    check(nba.STEP_LINES_DEPENDENCY["player_props"][0] is True,
          "player_props classified DEPENDENT (its validation uses NBA_Odds.csv as the event manifest)")
    import fetch_player_props as fpp
    check("data/odds/NBA_Odds.csv" in fpp.SPORT_EVENT_MANIFESTS.get("basketball_nba", []),
          "evidence: fetch_player_props' NBA eligible-event manifest is the game-lines file")

    def drive(lines_rc):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "data/tracking").mkdir(parents=True)
            (base / "data/props").mkdir(parents=True)
            saved = (nba.BASE_DIR, nba.PROPS_ARTIFACT, nba.subprocess.run)
            ran = []

            def fake_run(command, timeout=None):
                joined = " ".join(map(str, command))
                label = next(l for l, c, _ in nba.STEPS
                             if next(x for x in c if str(x).endswith(".py")) in joined)
                ran.append(label)
                if label == "game_lines":
                    return _Fake(lines_rc)
                if label == "player_props":
                    (base / "data/tracking/_last_props_fetch_basketball_nba.json").write_text(json.dumps(
                        {"events_found": 0}), encoding="utf-8")
                return _Fake(0)

            nba.BASE_DIR, nba.PROPS_ARTIFACT = base, base / "data/props/NBA_Props.csv"
            nba.subprocess.run = fake_run
            try:
                with contextlib.redirect_stdout(io.StringIO()) as buf:
                    rc = nba.main()
            finally:
                nba.BASE_DIR, nba.PROPS_ARTIFACT, nba.subprocess.run = saved
            sc = base / "data/tracking/_child_outcomes_nba_daily.json"
            side = json.loads(sc.read_text(encoding="utf-8")) if sc.exists() else {}
            return rc, ran, side, buf.getvalue()

    rc, ran, side, text = drive(1)
    dependent = {l for l in labels if nba.STEP_LINES_DEPENDENCY[l][0]}
    independent = [l for l in labels if not nba.STEP_LINES_DEPENDENCY[l][0] and l != "game_lines"]
    outs = side.get("outcomes", {})
    check(rc != 0 and not (dependent & set(ran)) and all(l in ran for l in independent),
          f"lines reject: dependents not run {sorted(dependent)}, independents all ran ({len(independent)}), rc={rc}")
    check(all(outs.get(l) == "SKIPPED_BLOCKED_BY_LINES" for l in dependent) and outs.get("game_lines") == "VALIDATION_FAILED"
          and side.get("degraded") is True and "DEGRADED" in text,
          f"dependents report SKIPPED_BLOCKED_BY_LINES; run DEGRADED/non-zero ({outs})")
    rc_ok, ran_ok, side_ok, _ = drive(0)
    check(rc_ok == 0 and ran_ok == labels and side_ok.get("outcomes", {}).get("player_props") == "NO_ACTIVE_EVENTS",
          "lines OK: full chain runs in order, props soft-outcome semantics unchanged (benign -> rc 0)")


def qc_line_movement():
    import refresh_line_movement_snapshots as lm
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "data/tracking").mkdir(parents=True)
        saved = (lm.BASE_DIR, lm.subprocess.run)

        def drive(plan):
            def fake_run(command, cwd=None, timeout=None):
                joined = " ".join(map(str, command))
                sport = "baseball_mlb" if "mlb" in joined else "basketball_wnba"
                rc, outcome = plan[sport]
                if outcome:
                    (base / "data/tracking" / f"_last_game_lines_fetch_{sport}.json").write_text(
                        json.dumps({"outcome": outcome, "exit_code": rc}), encoding="utf-8")
                return _Fake(rc)
            lm.BASE_DIR, lm.subprocess.run = base, fake_run
            try:
                with contextlib.redirect_stdout(io.StringIO()) as buf:
                    rc = lm.main()
            finally:
                lm.BASE_DIR, lm.subprocess.run = saved
            return rc, buf.getvalue()

        rc, text = drive({"baseball_mlb": (1, None), "basketball_wnba": (0, "UPDATED")})
        check(rc == 1 and "FAILED" in text.split("[MLB game lines]")[1].split("[WNBA")[0],
              "line-movement: exit 1 with no receipt proof -> FAILED, job non-zero (never OK)")
        rc, text = drive({"baseball_mlb": (1, "VALIDATION_FAILED"), "basketball_wnba": (0, "UPDATED")})
        check(rc == 1 and "outcome=VALIDATION_FAILED" in text, "line-movement: validation reject -> FAILED, never OK")
        rc, text = drive({"baseball_mlb": (1, "NO_ACTIVE_EVENTS"), "basketball_wnba": (0, "UPDATED")})
        check(rc == 0 and "SKIPPED (benign)" in text, "line-movement: receipt-proven NO_ACTIVE_EVENTS -> benign skip")
        # a STALE NO_ACTIVE_EVENTS receipt from an earlier run must not excuse this run's failure
        rc, text = drive({"baseball_mlb": (1, None), "basketball_wnba": (0, "UPDATED")})
        check(rc == 1, "line-movement: an old NO_ACTIVE_EVENTS receipt cannot excuse a new failure")
        rc, text = drive({"baseball_mlb": (2, "VALIDATION_FAILED"), "basketball_wnba": (0, "UPDATED")})
        check(rc == 1, "line-movement: any other non-zero exit -> FAILED")


# ------------------------------------------------------------------------------------------------ containment
def qc_containment():
    import app
    from services.timeutils import DISPLAY_TZ
    now = datetime.now(timezone.utc).replace(microsecond=0)

    def et(dt):
        return dt.astimezone(DISPLAY_TZ).strftime("%Y-%m-%d %H:%M")

    def raw(lu_age_h):
        lu = et(now - timedelta(hours=lu_age_h))
        rows = []
        for gid, away, home, kick in (("s1", "Utah Jazz", "Miami Heat", now - timedelta(hours=2)),
                                      ("f1", "Boston Celtics", "New York Knicks", now + timedelta(hours=3)),
                                      ("f2", "Denver Nuggets", "Phoenix Suns", now + timedelta(days=1))):
            d, t = et(kick).split(" ")
            rows.append(dict(Date=d, Time=t, Away=away, Home=home, AwayFull=away, HomeFull=home, AwayML=120,
                             HomeML=-140, Spread=-3.5, SpreadOdds=-110, Total=220.5, OverOdds=-110, UnderOdds=-110,
                             Book="DraftKings", GameID=gid, LastUpdated=lu))
        return pd.DataFrame(rows)   # legacy layout (no EventCommenceAtUTC) == what prod serves until a new publish

    email = next(iter(app.OWNER_EMAILS)) if app.OWNER_EMAILS else "owner@bankrollkings.com"
    owner = {"user_id": "qc-owner", "email": email, "role": "owner", "plan": "all_access", "is_admin": True,
             "display_name": "QC Owner"}
    saved = (app.load_game_market_odds, app.load_schedule, app.get_current_user)

    def render(age_h):
        frame_ = raw(age_h)
        app.load_game_market_odds = lambda: app._format_nba_game_market_odds(frame_.copy())
        app.load_schedule = lambda: app._format_schedule(frame_.copy())
        app.get_current_user = lambda: owner
        c = app.app.test_client()
        with c.session_transaction() as s:
            s["user_id"] = "qc-owner"
            s["user_email"] = email
        r = c.get("/game-lines?postseason=0")
        return r.status_code, r.get_data(as_text=True), app.nba_game_lines_status(app.load_game_market_odds())

    try:
        st_s, html_s, stat_s = render(10)     # stale (> 6h CLOCK A)
        st_f, html_f, stat_f = render(1)      # fresh
        # overlay over a cached command-center context
        frame_ = raw(10)
        app.load_game_market_odds = lambda: app._format_nba_game_market_odds(frame_.copy())
        ctx = {"upcoming_today": [{"Date": et(now + timedelta(hours=3)).split(" ")[0], "Away": "Boston Celtics",
                                   "Home": "New York Knicks", "market": {"spread": -3.5}, "market_summary": "NYK -3.5"}]}
        contained = app._apply_nba_lines_containment(ctx)
        frame_f = raw(1)
        app.load_game_market_odds = lambda: app._format_nba_game_market_odds(frame_f.copy())
        ctx2 = {"upcoming_today": [{"Date": et(now - timedelta(hours=2)).split(" ")[0], "Away": "Utah Jazz",
                                    "Home": "Miami Heat", "market": {"spread": -3.5}, "market_summary": "MIA -3.5"},
                                   {"Date": et(now + timedelta(hours=3)).split(" ")[0], "Away": "Boston Celtics",
                                    "Home": "New York Knicks", "market": {"spread": -3.5}, "market_summary": "NYK -3.5"}]}
        contained2 = app._apply_nba_lines_containment(ctx2)
    finally:
        app.load_game_market_odds, app.load_schedule, app.get_current_user = saved

    price = "+120 / -140"
    check(stat_s["is_stale"] and not stat_s["executable"] and stat_s["last_updated"].endswith("ET"),
          f"stale status: not executable, actual update time {stat_s['last_updated']} ({stat_s['age_hours']}h)")
    if st_s == 200 and st_f == 200:
        check('data-lines-executable="0"' in html_s and "Prices are withheld" in html_s and price not in html_s
              and stat_s["last_updated"] in html_s,
              "/game-lines stale: banner + actual update time shown, NO price rendered (no executable line)")
        check('data-lines-executable="1"' in html_f and price in html_f and stat_f["last_updated"] in html_f,
              "/game-lines fresh: prices render with the actual update time shown")
        check("Utah Jazz-Miami Heat" not in html_s and "Utah Jazz-Miami Heat" not in html_f
              and "Boston Celtics-New York Knicks" in html_f,
              "/game-lines: a started game is never listed as the current slate (fresh or stale)")
    else:
        FAILS.append(f"/game-lines did not render 200 (stale={st_s}, fresh={st_f})")
    g = contained["upcoming_today"][0]
    check(g["market"] == {} and g["market_summary"] == "" and g.get("market_withheld_reason") == "stale"
          and ctx["upcoming_today"][0]["market_summary"] == "NYK -3.5"
          and contained["nba_lines_status"]["executable"] is False,
          "command-center overlay: stale -> every game-line price withheld; cached context never mutated")
    s_game, f_game = contained2["upcoming_today"]
    check(s_game.get("lines_started") and s_game["market"] == {} and f_game["market_summary"] == "NYK -3.5",
          "command-center overlay (fresh): started game marked + price withheld, future game keeps its price")


def main() -> int:
    for fn in (qc_validator, qc_legacy_bridge, qc_scope, qc_fetcher, qc_orchestration, qc_line_movement,
               qc_containment):
        try:
            fn()
        except Exception as exc:  # a crash is a failure, never a pass
            import traceback
            FAILS.append(f"{fn.__name__} crashed: {exc!r}\n{traceback.format_exc()}")
    print("=" * 64)
    print("QC: EVENT-AWARE GAME LINES (game_lines_event_v1)")
    print("=" * 64)
    for n in NOTES:
        print(f"[OK]   {n}")
    for f in FAILS:
        print(f"[FAIL] {f}")
    print(f"\n{len(NOTES)} passed, {len(FAILS)} failed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
