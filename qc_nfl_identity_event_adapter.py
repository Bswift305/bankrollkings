"""QC: governed NFL identity + event adapter (Step 3, synthetic fixtures only).

Covers the success path, EVERY abstention reason code, wrong-event pairing, single-snapshot/TOCTOU
resistance, fingerprint-keyed cache invalidation, a collision that appears on refresh, stale/schema-invalid
artifacts, a UTC kickoff, and end-to-end capture + provenance retention through the v4 store. Temp files
only; no route, flag, UI, unit, prod path, or deploy.
"""
import hashlib
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SECRET_KEY", "qc-adapter-dummy")   # only needed if app is ever imported transitively
import services.research_candidate as rc                   # noqa: E402
import services.research_candidate_store as rcs            # noqa: E402
import services.nfl_identity_event_adapter as ad           # noqa: E402

UTC = timezone.utc
NOW = datetime(2026, 11, 1, 18, 0, tzinfo=UTC)      # season 2026 (listed)
FUTURE = datetime(2026, 12, 15, 18, 0, tzinfo=UTC)
FUTURE2 = datetime(2026, 12, 16, 18, 0, tzinfo=UTC)
PAST = datetime(2026, 10, 1, 18, 0, tzinfo=UTC)
SU_OK = "2026-10-30T12:00:00+00:00"
CLOCK = lambda: NOW                                  # noqa: E731

fails = []


def check(cond, msg):
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        fails.append(msg)


def tmp():
    return tempfile.TemporaryDirectory(ignore_cleanup_errors=True)


def _iso(dt):
    return dt.isoformat()


def _csv(path, df, age_h=1.0):
    df.to_csv(path, index=False)
    ts = NOW.timestamp() - age_h * 3600.0
    os.utime(path, (ts, ts))


def std_props_df():
    rows = [
        ("Josh Allen", "evt1", _iso(FUTURE), SU_OK),
        ("Stefon Diggs", "evt2", _iso(FUTURE), SU_OK),
        ("Ghost Player", "evtG", _iso(FUTURE), SU_OK),      # not in roster -> NAME_UNRESOLVED
        ("Mike Williams", "evtM", _iso(FUTURE), SU_OK),     # 2 roster ids -> NAME_AMBIGUOUS
        ("Robert Griffin", "evtA", _iso(FUTURE), SU_OK),    # 1 id, 2 displays -> ALIAS_CONFLICT
        ("Blank Kicker", "evtK", "", SU_OK),                # blank kickoff -> KICKOFF_MISSING
        ("Conf Player", "evtC", _iso(FUTURE), SU_OK),       # evtC has two distinct kickoffs -> CONFLICT
        ("Conf Player", "evtC", _iso(FUTURE2), SU_OK),
        ("Past Player", "evtP", _iso(PAST), SU_OK),         # kickoff in the past -> EVENT_PAST
        ("No Source", "evtNS", _iso(FUTURE), ""),           # bound-row SourceUpdatedAtUTC blank -> PROPS_SCHEMA_INVALID
    ]
    return pd.DataFrame(rows, columns=["Player", "EventId", "EventCommenceAtUTC", "SourceUpdatedAtUTC"])


def std_roster_df(season=2026):
    rows = [
        ("00-001", "Josh Allen", season),
        ("00-010", "Mike Williams", season),
        ("00-011", "Mike Williams", season),       # same name, two ids
        ("00-ALIAS", "Robert Griffin", season),
        ("00-ALIAS", "RG3", season),               # same id, two display names
    ]
    return pd.DataFrame(rows, columns=["player_id", "player_display_name", "season"])


def setup(d, clock=CLOCK, props_df=None, roster_df=None, props_age_h=1.0):
    pp, rp = os.path.join(d, "NFL_Props.csv"), os.path.join(d, "roster.parquet")
    _csv(pp, std_props_df() if props_df is None else props_df, age_h=props_age_h)
    (std_roster_df() if roster_df is None else roster_df).to_parquet(rp)
    return ad.NflIdentityEventAdapter(pp, rp, clock=clock), pp, rp


def is_abstain(res, code):
    return isinstance(res, ad.Abstention) and res.reason_code == code


# =========================================================================== success + UTC kickoff
def test_success_and_utc_kickoff():
    print("\n[A] a clean board selection resolves to a governed input + UTC kickoff + evidence")
    with tmp() as d:
        a, _, _ = setup(d)
        r = a.resolve("Josh Allen", "evt1")
        check(isinstance(r, ad.ResolvedObservationInput), "returns a ResolvedObservationInput")
        if isinstance(r, ad.ResolvedObservationInput):
            check(r.entity.canonical_id == "00-001" and r.entity.resolution is rc.Resolution.RESOLVED
                  and r.entity.display == "Josh Allen", "entity bound to the roster player_id + display")
            check(r.event.canonical_id == "evt1" and r.event.event_effective == FUTURE
                  and r.event.event_effective.utcoffset() == timedelta(0), "event id + UTC kickoff bound")
            ev = r.evidence
            check(ev.resolver_id == ad.RESOLVER_ID and ev.resolver_version == ad.RESOLVER_VERSION
                  and len(ev.props_sha256) == 64 and len(ev.roster_sha256) == 64
                  and ev.roster_season == 2026 and ev.event_id == "evt1" and ev.player_id == "00-001"
                  and ev.resolved_at == NOW, "evidence carries resolver + both shas + season + binding + time")


# =========================================================================== every abstention code
def test_all_abstention_codes():
    print("\n[B] every governed abstention reason code is produced by its condition")
    with tmp() as d:
        a, pp, rp = setup(d)
        check(is_abstain(a.resolve("Josh Allen", "nope"), "EVENT_NOT_FOUND"), "EVENT_NOT_FOUND")
        check(is_abstain(a.resolve("Stefon Diggs", "evt1"), "PLAYER_EVENT_MISMATCH"),
              "PLAYER_EVENT_MISMATCH (valid player + valid but unpaired event)")
        check(is_abstain(a.resolve("No Source", "evtNS"), "PROPS_SCHEMA_INVALID"),
              "PROPS_SCHEMA_INVALID (bound-row SourceUpdatedAtUTC blank)")
        check(is_abstain(a.resolve("Blank Kicker", "evtK"), "KICKOFF_MISSING"), "KICKOFF_MISSING")
        check(is_abstain(a.resolve("Conf Player", "evtC"), "KICKOFF_CONFLICT"), "KICKOFF_CONFLICT")
        check(is_abstain(a.resolve("Past Player", "evtP"), "EVENT_PAST"), "EVENT_PAST")
        check(is_abstain(a.resolve("Ghost Player", "evtG"), "NAME_UNRESOLVED"), "NAME_UNRESOLVED")
        check(is_abstain(a.resolve("Mike Williams", "evtM"), "NAME_AMBIGUOUS"), "NAME_AMBIGUOUS")
        check(is_abstain(a.resolve("Robert Griffin", "evtA"), "PLAYER_ID_ALIAS_CONFLICT"),
              "PLAYER_ID_ALIAS_CONFLICT")
    with tmp() as d:                                   # SEASON_UNAVAILABLE (unlisted calendar year)
        a, _, _ = setup(d, clock=lambda: datetime(2030, 11, 1, 18, 0, tzinfo=UTC))
        check(is_abstain(a.resolve("Josh Allen", "evt1"), "SEASON_UNAVAILABLE"), "SEASON_UNAVAILABLE")
    with tmp() as d:                                   # PROPS_UNAVAILABLE
        a = ad.NflIdentityEventAdapter(os.path.join(d, "missing.csv"),
                                       os.path.join(d, "r.parquet"), clock=CLOCK)
        std_roster_df().to_parquet(os.path.join(d, "r.parquet"))
        check(is_abstain(a.resolve("Josh Allen", "evt1"), "PROPS_UNAVAILABLE"), "PROPS_UNAVAILABLE")
    with tmp() as d:                                   # PROPS_STALE
        a, _, _ = setup(d, props_age_h=40.0)
        check(is_abstain(a.resolve("Josh Allen", "evt1"), "PROPS_STALE"), "PROPS_STALE (CLOCK B contract)")
    with tmp() as d:                                   # PROPS_SCHEMA_INVALID (missing column)
        bad = std_props_df().drop(columns=["SourceUpdatedAtUTC"])
        a, _, _ = setup(d, props_df=bad)
        check(is_abstain(a.resolve("Josh Allen", "evt1"), "PROPS_SCHEMA_INVALID"),
              "PROPS_SCHEMA_INVALID (missing column)")
    with tmp() as d:                                   # ROSTER_UNAVAILABLE
        pp = os.path.join(d, "p.csv")
        _csv(pp, std_props_df())
        a = ad.NflIdentityEventAdapter(pp, os.path.join(d, "missing.parquet"), clock=CLOCK)
        check(is_abstain(a.resolve("Josh Allen", "evt1"), "ROSTER_UNAVAILABLE"), "ROSTER_UNAVAILABLE")
    with tmp() as d:                                   # ROSTER_SCHEMA_INVALID (no season column)
        a, _, _ = setup(d, roster_df=std_roster_df().drop(columns=["season"]))
        check(is_abstain(a.resolve("Josh Allen", "evt1"), "ROSTER_SCHEMA_INVALID"),
              "ROSTER_SCHEMA_INVALID (missing season)")
    with tmp() as d:                                   # ROSTER_SEASON_MISMATCH
        a, _, _ = setup(d, roster_df=std_roster_df(season=2025))
        check(is_abstain(a.resolve("Josh Allen", "evt1"), "ROSTER_SEASON_MISMATCH"),
              "ROSTER_SEASON_MISMATCH (roster is a different season)")


# =========================================================================== single-snapshot / TOCTOU
def test_single_snapshot_no_toctou():
    print("\n[C] each artifact is read ONCE: bytes + sha + mtime are one consistent snapshot")
    with tmp() as d:
        pp = os.path.join(d, "p.csv")
        _csv(pp, std_props_df())
        data1, sha1, mt1 = ad._read_artifact(pp)
        check(hashlib.sha256(data1).hexdigest() == sha1, "sha is of the exact bytes read from this fd")
        # replace the file AFTER the snapshot; the captured snapshot is unaffected, and a NEW read differs
        _csv(pp, std_props_df().iloc[:1])
        data2, sha2, mt2 = ad._read_artifact(pp)
        check(sha1 != sha2 and len(data2) < len(data1),
              "a later read reflects the replacement (each call is its own single snapshot)")
        check(hashlib.sha256(data1).hexdigest() == sha1,
              "the first snapshot's sha still matches its own bytes (not split from a replacement)")


# =========================================================================== cache invalidation by fingerprint
def test_cache_keyed_by_fingerprint():
    print("\n[D] indexes cache by (props_sha, roster_sha, season, resolver_version); change invalidates")
    with tmp() as d:
        a, pp, rp = setup(d)
        a.resolve("Josh Allen", "evt1")
        a.resolve("Mike Williams", "evtM")
        check(a.build_count == 1, "repeated resolves on unchanged artifacts reuse ONE built index")
        std_roster_df().iloc[:4].to_parquet(rp)        # change roster bytes -> new sha
        a.resolve("Josh Allen", "evt1")
        check(a.build_count == 2, "a changed artifact fingerprint invalidates the cache and rebuilds")


# =========================================================================== collision appears on refresh
def test_collision_change_on_refresh():
    print("\n[E] a name that was unique becomes AMBIGUOUS when the roster gains a colliding id")
    with tmp() as d:
        only_josh = pd.DataFrame([("00-001", "Josh Allen", 2026)],
                                 columns=["player_id", "player_display_name", "season"])
        a, pp, rp = setup(d, roster_df=only_josh)
        r1 = a.resolve("Josh Allen", "evt1")
        check(isinstance(r1, ad.ResolvedObservationInput), "unique name resolves under the first roster")
        two = pd.DataFrame([("00-001", "Josh Allen", 2026), ("00-999", "Josh Allen", 2026)],
                           columns=["player_id", "player_display_name", "season"])
        two.to_parquet(rp)                              # refresh adds a colliding id for the same name
        r2 = a.resolve("Josh Allen", "evt1")
        check(is_abstain(r2, "NAME_AMBIGUOUS"), "after refresh the collision is re-audited -> NAME_AMBIGUOUS")


# =========================================================================== one governed reason, never a guess
def test_exactly_one_reason_type():
    print("\n[F] a resolve returns either a ResolvedObservationInput OR exactly one valid Abstention")
    with tmp() as d:
        a, _, _ = setup(d)
        for args in [("Josh Allen", "evt1"), ("Ghost Player", "evtG"), ("Stefon Diggs", "evt1")]:
            r = a.resolve(*args)
            ok = isinstance(r, ad.ResolvedObservationInput) or (
                isinstance(r, ad.Abstention) and r.reason_code in ad.REASONS)
            check(ok, f"resolve{args} -> a governed result ({type(r).__name__})")


# =========================================================================== end-to-end capture + provenance
def test_end_to_end_capture_and_provenance():
    print("\n[G] a resolved input captures through the v4 store and retains its provenance; retry no-ops")
    with tmp() as d:
        a, _, _ = setup(d)
        r = a.resolve("Josh Allen", "evt1")
        check(isinstance(r, ad.ResolvedObservationInput), "resolved for capture")
        store = rcs.ResearchCandidateStore(os.path.join(d, "store.db"))
        res = store.capture_observation(observer_id="owner", entity=r.entity, event=r.event,
                                        thesis="usage may rise", sources=("https://x/bio",),
                                        evidence=r.evidence, idempotency_key="K")
        check(res["status"] == "recorded", "the resolved input + evidence records in the store")
        store.close()
        s2 = rcs.ResearchCandidateStore(os.path.join(d, "store.db"))   # reopen validates evidence + fp parity
        obs = s2.load_observation(res["id"])
        check(len([s for s in obs.sources if s.startswith("bkres:v1:")]) == 7,
              "the stored observation retains all 7 reserved evidence references")
        check(("bkres:v1:player=00-001" in obs.sources) and ("bkres:v1:event=evt1" in obs.sources)
              and ("bkres:v1:roster-season=2026" in obs.sources),
              "provenance encodes the bound player_id, event id, and roster season")
        check(s2.replay_validate()["observations"] == 1, "the store replays + reconciles after reopen")
        # a retry re-resolves (fresh evidence) under the same key + intent -> no-op
        r2 = a.resolve("Josh Allen", "evt1")
        again = s2.capture_observation(observer_id="owner", entity=r2.entity, event=r2.event,
                                       thesis="usage may rise", sources=("https://x/bio",),
                                       evidence=r2.evidence, idempotency_key="K")
        check(again["status"] == "noop" and again["id"] == res["id"], "an exact re-resolve + retry no-ops")
        s2.close()


if __name__ == "__main__":
    print("=" * 80)
    print("NFL IDENTITY + EVENT ADAPTER — STEP 3 QC (governed resolve/abstain, synthetic fixtures)")
    print("=" * 80)
    for t in (test_success_and_utc_kickoff, test_all_abstention_codes, test_single_snapshot_no_toctou,
              test_cache_keyed_by_fingerprint, test_collision_change_on_refresh,
              test_exactly_one_reason_type, test_end_to_end_capture_and_provenance):
        t()
    print("\n" + "=" * 80)
    print("Clean:", not fails)
    if fails:
        print("FAILURES:")
        for f in fails:
            print("  -", f)
    sys.exit(1 if fails else 0)
