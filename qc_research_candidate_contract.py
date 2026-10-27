"""QC: Research Candidate governed domain contract + validators (SLICE 1, DARK/LOCAL).

Proves the Slice-1 guarantees of `services/research_candidate.py` against the approved design
`docs/research_candidate_contract.md` (Rev 2.1) INCLUDING the nine reviewer blockers that gate
Slice-1 close. In-memory fixtures ONLY — writes nothing to any `data/` directory, imports no
`app` symbol, exercises no route/UI/job.

Validation matrix:
  A strict typed inputs, NO coercion           I deterministic canonical serialization + hashes
  B tz-aware observation + event clocks          J supersession linkage (outcomes + findings)
  C pre-event freeze enforced                     K family key excludes entity; case identity differs
  D numeric MEPI required + NEVER backfilled      L fixtures: 5 categories + Freiermuth Case #1
  E measurement failure -> counted UNMEASURABLE   M forward-only lifecycle / state-transition table
  F one game cannot promote a hypothesis -> edge  --- reviewer blockers 1-9 ---
  G INCONCLUSIVE immutable (no rewind)            N frozen records truly immutable (no caller mutation)
  H no recommendation / ranking / score surface   O pre-event ordering complete (capture/outcome)
                                                  P candidate<->observation subject binding
                                                  Q supersession allow-list + append-only chain
                                                  R PARTIAL does NOT enter matched sample / effective-n
                                                  S evaluation bound to the frozen family contract
                                                  T direction-aware SUPPORTED (INCREASE + DECREASE)
                                                  U canonical numeric safety (NaN/inf, key coercion)
"""
import operator
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import services.research_candidate as rc  # noqa: E402

UTC = timezone.utc
fails = []


def check(cond, msg):
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        fails.append(msg)


def expect_raises(exc, fn, msg):
    try:
        fn()
    except exc:
        check(True, msg)
    except Exception as e:  # noqa: BLE001
        check(False, msg + f"  (raised {type(e).__name__}: {e}, expected {exc.__name__})")
    else:
        check(False, msg + f"  (no exception, expected {exc.__name__})")


# --------------------------------------------------------------------------- shared timing + consts
OBSERVED = datetime(2026, 10, 25, 11, 0, 0, tzinfo=UTC)
PRE = datetime(2026, 10, 25, 12, 51, 21, tzinfo=UTC)          # observed <= captured < event
EVENT = datetime(2026, 10, 25, 17, 30, 0, tzinfo=UTC)
POST = datetime(2026, 10, 25, 21, 0, 0, tzinfo=UTC)
BEFORE_OBS = datetime(2026, 10, 25, 9, 0, 0, tzinfo=UTC)

THESIS = "usage may rise"
SOURCES = ("https://example.test/bio",)
SEQ = iter(range(1, 10_000_000))


def temporal(observed=OBSERVED, captured=PRE, event=EVENT, seq=None,
             src=None, src_status=rc.SourceUpdatedStatus.NOT_PROVIDED):
    return rc.TemporalFacts(observed_at=observed, event_effective=event, bk_captured=captured,
                            record_seq=next(SEQ) if seq is None else seq,
                            source_updated=src, source_updated_status=src_status)


def endpoint(name="target_share_lift", version="v1", direction=rc.Direction.INCREASE, mepi=0.05):
    return rc.PrimaryEndpoint(name=name, version=version, direction=direction, mepi=mepi,
                              unit="target_share_fraction")


def baseline():
    return rc.BaselineMethod(method="role_matchup_expected_usage", version="v1",
                             covariates=("game_script", "team_pass_volume", "snaps", "qb_change"))


def entity(cid, name):
    return rc.EntityIdentity(canonical_id=cid, display=name)


def event(cid, eff=EVENT):
    return rc.EventIdentity(canonical_id=cid, event_effective=eff)


def observation(oid, ent, ev, thesis=THESIS, sources=SOURCES, acted=False):
    return rc.UserObservation(observation_id=oid, observer="owner", entity=ent, event=ev,
                              thesis=thesis, observed_at=OBSERVED, bk_captured=PRE,
                              record_seq=next(SEQ), sources=sources, acted=acted)


def candidate(cid, oid, sub_label, ent, ev, *, ep=None, captured=PRE,
              invalidation=("player_inactive", "assumed_starter_benched"), snapshot=None):
    return rc.ResearchCandidate(
        candidate_id=cid, observation_id=oid, observer="owner",
        category=rc.Category.PLAYER_MILESTONE_USAGE, sub_label=sub_label, entity=ent, event=ev,
        temporal=temporal(captured=captured, event=ev.event_effective), thesis=THESIS,
        baseline=baseline(), assumptions=("player active", "normal snap role"),
        eligibility_conditions=("player active", "assumed starter plays"),
        invalidation_conditions=invalidation,
        primary_endpoint=endpoint() if ep is None else ep,
        pre_event_snapshot={"expected_target_share": 0.18} if snapshot is None else snapshot,
        sources=SOURCES)


def mk_candidate(cid, obs, *, seq, captured=PRE, supersedes=None, ep=None, ev=None,
                 sub_label=rc.SubLabel.BIRTHDAY):
    the_ev = ev or obs.event
    return rc.ResearchCandidate(
        candidate_id=cid, observation_id=obs.observation_id, observer=obs.observer,
        category=rc.Category.PLAYER_MILESTONE_USAGE, sub_label=sub_label, entity=obs.entity,
        event=the_ev, temporal=temporal(captured=captured, event=the_ev.event_effective, seq=seq),
        thesis=obs.thesis, baseline=baseline(), assumptions=("player active",),
        eligibility_conditions=("player active",), invalidation_conditions=("player_inactive",),
        primary_endpoint=endpoint() if ep is None else ep, pre_event_snapshot={},
        acted=obs.acted, sources=obs.sources, supersedes=supersedes)


def measured_outcome(oid, cid, observed, expected, seq=None, captured=POST):
    return rc.CandidateOutcome(
        outcome_id=oid, candidate_id=cid, version=1, case_state=rc.CaseState.MEASURED,
        bk_captured=captured, record_seq=next(SEQ) if seq is None else seq,
        observed_endpoint_value=observed, baseline_expected_value=expected,
        completeness={"observed": rc.Completeness.COMPLETE, "baseline": rc.Completeness.COMPLETE},
        covariates={"game_script": "neutral", "team_pass_volume": 38.0},
        descriptive={"receiving_yards": 64.0, "touchdowns": 1})


def full_bundle(effect=0.12, clo=0.06, chi=0.18, oos=True, sens=True):
    return rc.EvidenceBundle(effect_estimate=effect, interval_low=min(clo, 0.07),
                             interval_high=max(chi, 0.17), corrected_interval_low=clo,
                             corrected_interval_high=chi, out_of_sample=oos,
                             sensitivity_analysis_done=sens, missingness_rule="exclude_pending")


# =========================================================================== A strict typing
def test_strict_typing_no_coercion():
    print("\n[A] strict typed inputs, NO coercion")
    expect_raises(rc.TypeStrictError, lambda: endpoint(mepi=5), "int MEPI rejected")
    expect_raises(rc.TypeStrictError, lambda: endpoint(mepi=True), "bool MEPI rejected")
    expect_raises(rc.HindsightError, lambda: endpoint(mepi=0.0), "non-positive MEPI rejected")
    expect_raises(rc.TypeStrictError, lambda: rc.CandidateOutcome(
        outcome_id="o", candidate_id="c", version=1, case_state=rc.CaseState.PENDING,
        bk_captured=POST, record_seq=1, observed_endpoint_value="0.1"),
        "numeric-string endpoint value rejected")
    expect_raises(rc.TypeStrictError, lambda: rc.EntityIdentity(canonical_id="", display="x"),
                  "empty canonical id rejected")


# =========================================================================== B tz-aware
def test_timezone_aware_clocks():
    print("\n[B] timezone-aware observation + event clocks")
    naive = datetime(2026, 10, 25, 12, 0, 0)
    expect_raises(rc.TemporalError, lambda: temporal(observed=naive), "naive observed_at rejected")
    expect_raises(rc.TemporalError, lambda: rc.EventIdentity(canonical_id="g", event_effective=naive),
                  "naive event_effective rejected")
    expect_raises(rc.TypeStrictError, lambda: rc.TemporalFacts(
        observed_at="2026-10-25T12:00:00Z", event_effective=EVENT, bk_captured=PRE, record_seq=1),
        "string-as-datetime rejected")
    expect_raises(rc.TemporalError, lambda: rc.TemporalFacts(
        observed_at=OBSERVED, event_effective=EVENT, bk_captured=PRE, record_seq=1,
        source_updated=PRE, source_updated_status=rc.SourceUpdatedStatus.UNKNOWN),
        "provider clock present while status != PRESENT rejected (no backfill)")


# =========================================================================== C pre-event freeze
def test_pre_event_freeze():
    print("\n[C] pre-event freeze enforced")
    ent, ev = entity("p-eligible", "Eligible"), event("g1")
    good = candidate("c-good", "o", rc.SubLabel.BIRTHDAY, ent, ev, captured=PRE)
    check(good.frozen_before_event and good.eligible_for_sample, "pre-event => eligible")
    late = candidate("c-late", "o", rc.SubLabel.BIRTHDAY, ent, ev, captured=POST)
    check(not good.frozen_before_event is False and not late.eligible_for_sample
          and "frozen_after_event" in late.ineligibility_reasons, "frozen-after-event => ineligible")
    check(late.track_state is rc.CaseTrackState.DESCRIPTIVE_NOTE, "=> permanent DESCRIPTIVE_NOTE")
    unresolved = candidate("c-unk", "o", rc.SubLabel.BIRTHDAY,
                           rc.EntityIdentity("p?", "U", rc.Resolution.AMBIGUOUS), ev)
    check("unresolved_identity" in unresolved.ineligibility_reasons, "ambiguous identity => ineligible")


# =========================================================================== D MEPI no backfill
def test_mepi_required_and_no_backfill():
    print("\n[D] numeric MEPI required + NEVER backfilled")
    ent, ev = entity("p-nm", "Seed"), event("g1")
    seed = rc.ResearchCandidate(
        candidate_id="c-seed", observation_id="o", observer="owner",
        category=rc.Category.PLAYER_MILESTONE_USAGE, sub_label=rc.SubLabel.BIRTHDAY,
        entity=ent, event=ev, temporal=temporal(event=ev.event_effective), thesis=THESIS,
        baseline=baseline(), assumptions=("player active",), eligibility_conditions=("player active",),
        invalidation_conditions=("player_inactive",), primary_endpoint=None,
        pre_event_snapshot={}, sources=SOURCES)
    check(seed.primary_endpoint is None and "no_frozen_numeric_mepi" in seed.ineligibility_reasons,
          "no frozen numeric MEPI => ineligible seed")
    check(seed.family_key is None, "seed without endpoint maps to no family")
    expect_raises(rc.HindsightError, lambda: rc.supersede_candidate(
        seed, new_temporal=temporal(captured=POST, event=ev.event_effective), primary_endpoint=endpoint()),
        "backfilling MEPI post-event rejected")
    fixed = rc.supersede_candidate(seed, new_temporal=temporal(captured=PRE, event=ev.event_effective),
                                   primary_endpoint=endpoint())
    check(fixed.eligible_for_sample and fixed.supersedes == seed.temporal.record_seq,
          "pre-event correction may add the MEPI and link by record_seq")


# =========================================================================== E UNMEASURABLE
def test_measurement_failure_counted():
    print("\n[E] measurement failure -> counted UNMEASURABLE; INVALIDATED only for frozen eligibility")
    store = rc.InMemoryResearchStore()
    ent, ev = entity("p-e", "E"), event("g1")
    store.record_observation(observation("o-e", ent, ev))
    cand = candidate("c-e", "o-e", rc.SubLabel.REVENGE_GAME, ent, ev,
                     invalidation=("player_inactive", "game_script"))
    store.freeze_candidate(cand)
    unm = rc.CandidateOutcome(outcome_id="o-unm", candidate_id="c-e", version=1,
                              case_state=rc.CaseState.UNMEASURABLE, bk_captured=POST,
                              record_seq=next(SEQ), invalidation_reason="tracking_feed_missing",
                              completeness={"observed": rc.Completeness.PENDING})
    store.append_outcome(unm)
    check(unm.counts_in_missingness and not unm.counts_in_matched_sample,
          "UNMEASURABLE counted in missingness, not matched sample")
    bad_missing = rc.CandidateOutcome(outcome_id="o-bm", candidate_id="c-e", version=1,
                                      case_state=rc.CaseState.INVALIDATED, bk_captured=POST,
                                      record_seq=1, invalidation_reason="tracking_feed_missing")
    expect_raises(rc.EligibilityError, lambda: bad_missing.validate_invalidation_against_candidate(cand),
                  "INVALIDATED with a non-frozen (missing-data) reason rejected")
    bad_cov = rc.CandidateOutcome(outcome_id="o-bc", candidate_id="c-e", version=1,
                                  case_state=rc.CaseState.INVALIDATED, bk_captured=POST,
                                  record_seq=1, invalidation_reason="game_script")
    expect_raises(rc.EligibilityError, lambda: bad_cov.validate_invalidation_against_candidate(cand),
                  "INVALIDATED on a predeclared covariate rejected (outcome-correlated exclusion barred)")
    good = rc.CandidateOutcome(outcome_id="o-gi", candidate_id="c-e", version=1,
                               case_state=rc.CaseState.INVALIDATED, bk_captured=POST, record_seq=1,
                               invalidation_reason="player_inactive")
    good.validate_invalidation_against_candidate(cand)
    check(True, "INVALIDATED on a frozen eligibility failure accepted")


# =========================================================================== F one case != edge
def test_one_case_cannot_be_edge():
    print("\n[F] one game cannot promote a hypothesis into an edge")
    store = rc.InMemoryResearchStore()
    ent, ev = entity("p-f1", "F1"), event("gF1")
    store.record_observation(observation("o-f1", ent, ev))
    store.freeze_candidate(candidate("c-f1", "o-f1", rc.SubLabel.RECORD_CHASE, ent, ev))
    store.append_outcome(measured_outcome("o-f1o", "c-f1", 0.26, 0.18))
    fk = store.candidates["c-f1"].family_key
    s1 = rc.summarize_family(fk, store.family_cases(fk))
    check(s1.effective_n == 1 and s1.n_matched == 1, "single matched case => effective_n 1")
    expect_raises(rc.EvaluationError, lambda: rc.evaluate_family(
        finding_id="f1", endpoint=endpoint(), summary=s1, proposed_status=rc.FindingStatus.SUPPORTED,
        bk_captured=POST, record_seq=next(SEQ)), "SUPPORTED from a single case rejected")
    only = rc.evaluate_family(finding_id="f1", endpoint=endpoint(), summary=s1,
                              proposed_status=rc.FindingStatus.INCONCLUSIVE, bk_captured=POST,
                              record_seq=next(SEQ))
    check(only.status is rc.FindingStatus.INCONCLUSIVE, "below floor => only INCONCLUSIVE")
    ent2, ev2 = entity("p-f2", "F2"), event("gF2")
    store.record_observation(observation("o-f2", ent2, ev2))
    store.freeze_candidate(candidate("c-f2", "o-f2", rc.SubLabel.RECORD_CHASE, ent2, ev2))
    store.append_outcome(measured_outcome("o-f2o", "c-f2", 0.30, 0.18))
    s2 = rc.summarize_family(fk, store.family_cases(fk))
    check(s2.effective_n == 2, "two distinct entities => effective_n 2")
    sup = rc.evaluate_family(finding_id="f2", endpoint=endpoint(), summary=s2,
                             proposed_status=rc.FindingStatus.SUPPORTED, bk_captured=POST,
                             record_seq=next(SEQ), evidence=full_bundle())
    check(sup.status is rc.FindingStatus.SUPPORTED and sup.authority == "RESEARCH_ONLY",
          "SUPPORTED allowed at floor with a full bundle, still RESEARCH_ONLY")
    expect_raises(rc.EvaluationError, lambda: rc.evaluate_family(
        finding_id="f3", endpoint=endpoint(), summary=s2, proposed_status=rc.FindingStatus.SUPPORTED,
        bk_captured=POST, record_seq=next(SEQ)), "SUPPORTED without a bundle rejected")


# =========================================================================== G INCONCLUSIVE immutable
def test_inconclusive_immutable():
    print("\n[G] INCONCLUSIVE is an immutable finding; a later evaluation supersedes, never rewinds")
    store = rc.InMemoryResearchStore()
    ent, ev = entity("p-g", "G"), event("gG")
    store.record_observation(observation("o-g", ent, ev))
    store.freeze_candidate(candidate("c-g", "o-g", rc.SubLabel.HOMECOMING, ent, ev))
    store.append_outcome(measured_outcome("o-go", "c-g", 0.25, 0.18))
    fk = store.candidates["c-g"].family_key
    s = rc.summarize_family(fk, store.family_cases(fk))
    inc = rc.evaluate_family(finding_id="g1", endpoint=endpoint(), summary=s,
                             proposed_status=rc.FindingStatus.INCONCLUSIVE, bk_captured=POST,
                             record_seq=next(SEQ))
    store.record_finding(inc)
    check(not any("rewind" in n or "reopen" in n for n in dir(store)), "store exposes no rewind/reopen")
    later = rc.evaluate_family(finding_id="g2", endpoint=endpoint(), summary=s,
                               proposed_status=rc.FindingStatus.INCONCLUSIVE, bk_captured=POST,
                               record_seq=next(SEQ), supersedes=inc.record_seq)
    store.record_finding(later)
    hist = store._finding_versions[fk.key]
    check(len(hist) == 2 and hist[0].content_hash == inc.content_hash,
          "prior INCONCLUSIVE preserved immutably in history")
    expect_raises(rc.SupersessionError, lambda: store.record_finding(rc.evaluate_family(
        finding_id="g3", endpoint=endpoint(), summary=s, proposed_status=rc.FindingStatus.INCONCLUSIVE,
        bk_captured=POST, record_seq=next(SEQ))), "a non-superseding finding after one exists rejected")


# =========================================================================== H no authority surface
def test_no_recommendation_surface():
    print("\n[H] no recommendation / ranking / score surface")
    check(rc.AUTHORITY == "RESEARCH_ONLY", "module AUTHORITY is RESEARCH_ONLY")
    forbidden = ("rank", "score", "recommend", "best_", "pick", "lock", "bet_", "edge_value")
    hits = [n for n in dir(rc) if any(f in n.lower() for f in forbidden)]
    check(not hits, "no ranking/scoring/recommendation names in the API (%r)" % hits)
    check(not (set(rc.EvaluatedFinding.__dataclass_fields__) & {"score", "rank", "confidence"}),
          "EvaluatedFinding carries no score/rank/confidence field")


# =========================================================================== I determinism
def test_deterministic_hashes():
    print("\n[I] deterministic canonical serialization + stable content hashes")
    ent, ev = entity("p-i", "I"), event("gI")
    c1 = candidate("c-i", "o", rc.SubLabel.CONTRACT_INCENTIVE, ent, ev)
    check(rc.content_hash(c1) == rc.content_hash(c1) and len(c1.content_hash) == 64,
          "content_hash stable and sha256-shaped")
    o1 = measured_outcome("o", "c-i", 0.3, 0.18, seq=1)
    o2 = rc.CandidateOutcome(outcome_id="o", candidate_id="c-i", version=1,
                             case_state=rc.CaseState.MEASURED, bk_captured=POST, record_seq=1,
                             observed_endpoint_value=0.3, baseline_expected_value=0.18,
                             completeness={"baseline": rc.Completeness.COMPLETE,
                                           "observed": rc.Completeness.COMPLETE},
                             covariates={"team_pass_volume": 38.0, "game_script": "neutral"},
                             descriptive={"touchdowns": 1, "receiving_yards": 64.0})
    check(rc.content_hash(o1) == rc.content_hash(o2), "hash independent of dict insertion order")


# =========================================================================== J supersession
def test_supersession_linkage():
    print("\n[J] supersession linkage (outcome version chain, one current)")
    store = rc.InMemoryResearchStore()
    ent, ev = entity("p-j", "J"), event("gJ")
    store.record_observation(observation("o-j", ent, ev))
    store.freeze_candidate(candidate("c-j", "o-j", rc.SubLabel.BIRTHDAY, ent, ev))
    v1 = measured_outcome("o-j1", "c-j", 0.22, 0.18)
    store.append_outcome(v1)
    v2 = rc.CandidateOutcome(outcome_id="o-j2", candidate_id="c-j", version=2,
                             case_state=rc.CaseState.MEASURED, bk_captured=POST, record_seq=next(SEQ),
                             observed_endpoint_value=0.24, baseline_expected_value=0.18,
                             completeness={"observed": rc.Completeness.COMPLETE,
                                           "baseline": rc.Completeness.COMPLETE},
                             supersedes=v1.record_seq)
    store.append_outcome(v2)
    check(store.current_outcome("c-j").outcome_id == "o-j2"
          and len(store.outcome_history("c-j")) == 2, "one current outcome; prior retained")
    expect_raises(rc.SupersessionError, lambda: store.append_outcome(rc.CandidateOutcome(
        outcome_id="o-j4", candidate_id="c-j", version=4, case_state=rc.CaseState.MEASURED,
        bk_captured=POST, record_seq=next(SEQ), observed_endpoint_value=0.25,
        baseline_expected_value=0.18,
        completeness={"observed": rc.Completeness.COMPLETE, "baseline": rc.Completeness.COMPLETE},
        supersedes=v2.record_seq)), "a version that skips (2->4) is rejected")


# =========================================================================== K family key
def test_family_key_excludes_entity():
    print("\n[K] family key excludes entity; case identity is (entity,event,contract)")
    ca = candidate("c-ka", "o", rc.SubLabel.REVENGE_GAME, entity("p-ka", "A"), event("gKA"))
    cb = candidate("c-kb", "o", rc.SubLabel.REVENGE_GAME, entity("p-kb", "B"), event("gKB"))
    check(ca.family_key.key == cb.family_key.key, "two players share one family (entity not in key)")
    check(ca.case_identity != cb.case_identity, "case identities differ")
    check("p-ka" not in ca.family_key.key, "entity id absent from the family key string")


# =========================================================================== L fixtures
def test_fixtures_five_categories_and_case1():
    print("\n[L] fixtures: 5 categories (non-predictive labels) + Freiermuth Case #1")
    store = rc.InMemoryResearchStore()
    labels = [rc.SubLabel.BIRTHDAY, rc.SubLabel.REVENGE_GAME, rc.SubLabel.RECORD_CHASE,
              rc.SubLabel.HOMECOMING, rc.SubLabel.CONTRACT_INCENTIVE]
    for i, lab in enumerate(labels):
        ent, ev = entity(f"p-l{i}", f"Player {i}"), event(f"gL{i}")
        store.record_observation(observation(f"o-l{i}", ent, ev))
        c = candidate(f"c-l{i}", f"o-l{i}", lab, ent, ev)
        store.freeze_candidate(c)
        check(c.eligible_for_sample and c.sub_label is lab,
              f"{lab.value}: eligible candidate built as a LABEL, not a predictor")
    check(len(store.candidates) == 5, "all five category fixtures built")

    fm_ent = entity("nfl:pat-freiermuth", "Pat Freiermuth")
    fm_ev = rc.EventIdentity("nfl:2026-PIT-NO-paris", datetime(2026, 10, 25, 13, 30, 0, tzinfo=UTC))
    obs = rc.UserObservation(
        observation_id="obs-case1", observer="owner", entity=fm_ent, event=fm_ev,
        thesis="Rodgers may involve Freiermuth more than his normal role because it is his birthday",
        observed_at=datetime(2026, 10, 25, 12, 51, 21, tzinfo=UTC),
        bk_captured=datetime(2026, 10, 25, 12, 51, 21, tzinfo=UTC), record_seq=next(SEQ),
        sources=("https://steelers.test/bio", "https://nfl.test/schedule"), acted=False)
    store.record_observation(obs)
    seed = rc.ResearchCandidate(
        candidate_id="cand-case1", observation_id="obs-case1", observer="owner",
        category=rc.Category.PLAYER_MILESTONE_USAGE, sub_label=rc.SubLabel.BIRTHDAY,
        entity=fm_ent, event=fm_ev,
        temporal=rc.TemporalFacts(observed_at=obs.observed_at, event_effective=fm_ev.event_effective,
                                  bk_captured=obs.bk_captured, record_seq=next(SEQ)),
        thesis=obs.thesis, baseline=baseline(),
        assumptions=("player active", "Rodgers starts"),
        eligibility_conditions=("player active", "Rodgers starts"),
        invalidation_conditions=("player_inactive",), primary_endpoint=None,
        pre_event_snapshot={"expected_target_share": 0.17}, sources=obs.sources)
    store.freeze_candidate(seed)
    check(seed.frozen_before_event and not seed.eligible_for_sample
          and seed.ineligibility_reasons == ("no_frozen_numeric_mepi",),
          "Case #1: pre-kickoff seed, INELIGIBLE (no frozen numeric MEPI)")
    expect_raises(rc.HindsightError, lambda: rc.supersede_candidate(
        seed, new_temporal=temporal(captured=POST, event=fm_ev.event_effective), primary_endpoint=endpoint()),
        "Case #1 MEPI can never be backfilled post-event")


# =========================================================================== M lifecycle table
def test_lifecycle_forward_only():
    print("\n[M] forward-only lifecycle / state-transition table")
    check(set(s.value for s in rc.CaseState) ==
          {"MEASURED", "PARTIAL", "PENDING", "UNMEASURABLE", "INVALIDATED"}, "case states exact")
    check(set(s.value for s in rc.FindingStatus) == {"SUPPORTED", "UNSUPPORTED", "INCONCLUSIVE"},
          "finding statuses exact")
    check(set(s.value for s in rc.CaseTrackState) ==
          {"OBSERVED", "MEASUREMENT_DEFINED", "OUTCOME_CAPTURED", "DESCRIPTIVE_NOTE"},
          "track states match contract §2")


# ===== blocker 1 ==========================================================  N immutability
def test_frozen_records_immutable():
    print("\n[N] frozen records are truly immutable (caller mutation cannot change content)")
    ent, ev = entity("p-n", "N"), event("gN")
    snap = {"expected_target_share": 0.18, "nested": {"x": [1, 2]}}
    c = candidate("c-n", "o", rc.SubLabel.BIRTHDAY, ent, ev, snapshot=snap)
    h0 = c.content_hash
    snap["expected_target_share"] = 999.0          # mutate the caller's object AFTER construction
    snap["nested"]["x"].append(3)
    check(c.content_hash == h0 and rc.content_hash(c) == h0,
          "mutating the caller's snapshot does not change the record's content/hash")
    expect_raises(TypeError, lambda: operator.setitem(c.pre_event_snapshot, "expected_target_share", 1.0),
                  "the stored snapshot mapping is read-only (MappingProxyType)")
    check(isinstance(c.pre_event_snapshot["nested"]["x"], tuple),
          "nested lists are frozen into tuples")
    out = measured_outcome("o-n", "c-n", 0.3, 0.18)
    expect_raises(TypeError, lambda: operator.setitem(out.covariates, "game_script", "evil"),
                  "outcome covariates mapping is read-only")


# ===== blocker 2 ==========================================================  O ordering
def test_pre_event_ordering_complete():
    print("\n[O] pre-event ordering complete (capture >= observation; outcome >= event)")
    expect_raises(rc.TemporalError, lambda: rc.TemporalFacts(
        observed_at=OBSERVED, event_effective=EVENT, bk_captured=BEFORE_OBS, record_seq=1),
        "capture-before-observation rejected")
    expect_raises(rc.TemporalError, lambda: rc.UserObservation(
        observation_id="o", observer="owner", entity=entity("p", "P"), event=event("g"),
        thesis=THESIS, observed_at=OBSERVED, bk_captured=BEFORE_OBS, record_seq=1),
        "observation capture-before-observation rejected")
    store = rc.InMemoryResearchStore()
    ent, ev = entity("p-o", "O"), event("gO")
    store.record_observation(observation("o-o", ent, ev))
    store.freeze_candidate(candidate("c-o", "o-o", rc.SubLabel.BIRTHDAY, ent, ev))
    early = rc.CandidateOutcome(outcome_id="o-oe", candidate_id="c-o", version=1,
                                case_state=rc.CaseState.PENDING, bk_captured=PRE, record_seq=next(SEQ))
    expect_raises(rc.TemporalError, lambda: store.append_outcome(early),
                  "an outcome captured before its event is rejected")


# ===== blocker 3 ==========================================================  P binding
def test_candidate_observation_binding():
    print("\n[P] candidate is bound to its observation's subject")
    store = rc.InMemoryResearchStore()
    ent, ev = entity("p-p", "P"), event("gP")
    store.record_observation(observation("o-p", ent, ev))
    wrong_entity = candidate("c-pe", "o-p", rc.SubLabel.BIRTHDAY, entity("p-OTHER", "Other"), ev)
    expect_raises(rc.BindingError, lambda: store.freeze_candidate(wrong_entity),
                  "candidate with a different entity than its observation rejected")
    wrong_thesis = rc.ResearchCandidate(
        candidate_id="c-pt", observation_id="o-p", observer="owner",
        category=rc.Category.PLAYER_MILESTONE_USAGE, sub_label=rc.SubLabel.BIRTHDAY, entity=ent,
        event=ev, temporal=temporal(event=ev.event_effective), thesis="a DIFFERENT thesis",
        baseline=baseline(), assumptions=("x",), eligibility_conditions=("x",),
        invalidation_conditions=("player_inactive",), primary_endpoint=endpoint(),
        pre_event_snapshot={}, sources=SOURCES)
    expect_raises(rc.BindingError, lambda: store.freeze_candidate(wrong_thesis),
                  "candidate with a different thesis than its observation rejected")
    drop_sources = candidate("c-ps", "o-p", rc.SubLabel.BIRTHDAY, ent, ev)
    object.__setattr__(drop_sources, "sources", ("https://unrelated.test/x",))
    expect_raises(rc.BindingError, lambda: store.freeze_candidate(drop_sources),
                  "candidate dropping the observation's source lineage rejected")


# ===== blocker 4+5 ========================================================  Q supersession guard
def test_supersession_allowlist_and_chain():
    print("\n[Q] supersession allow-list + append-only candidate chain")
    ent, ev = entity("p-q", "Q"), event("gQ")
    seed = candidate("c-q", "o", rc.SubLabel.BIRTHDAY, ent, ev)
    expect_raises(rc.SupersessionError, lambda: rc.supersede_candidate(
        seed, new_temporal=temporal(event=ev.event_effective), category=rc.Category.PLAYER_MILESTONE_USAGE),
        "override of a non-allowlisted field (category) rejected")
    expect_raises(rc.SupersessionError, lambda: rc.supersede_candidate(
        seed, new_temporal=temporal(event=ev.event_effective), supersedes=None),
        "caller-supplied supersedes rejected")
    # append-only candidate storage + superseding chain.
    store = rc.InMemoryResearchStore()
    store.record_observation(observation("o-q", ent, ev))
    prior = mk_candidate("c-q0", store.observations["o-q"], seq=1000)
    store.freeze_candidate(prior)
    expect_raises(rc.SupersessionError, lambda: store.freeze_candidate(
        mk_candidate("c-q0", store.observations["o-q"], seq=1001)),
        "duplicate candidate_id rejected (append-only storage)")
    corr = rc.supersede_candidate(prior, new_temporal=temporal(event=ev.event_effective, seq=1002),
                                  candidate_id="c-q1")
    store.freeze_candidate(corr)
    check(not store.is_current_candidate(prior) and store.is_current_candidate(corr),
          "superseding candidate becomes current; prior is superseded")
    fk = corr.family_key
    check(len(store.family_cases(fk)) == 1, "family_cases returns only the current candidate")
    bad_seq = mk_candidate("c-q2", store.observations["o-q"], seq=999, supersedes=1002)
    expect_raises(rc.SupersessionError, lambda: store.freeze_candidate(bad_seq),
                  "a superseding candidate with a non-increasing record_seq rejected")
    primary_via_override_post = rc.supersede_candidate  # adversarial: endpoint via override post-event
    expect_raises(rc.HindsightError, lambda: primary_via_override_post(
        prior, new_temporal=temporal(captured=POST, event=ev.event_effective, seq=1003),
        primary_endpoint=endpoint(name="target_share_lift", version="v2")),
        "primary_endpoint supplied through supersede post-event rejected (MEPI backfill)")


# ===== blocker 6 ==========================================================  R PARTIAL separate
def test_partial_not_in_matched_sample():
    print("\n[R] PARTIAL does NOT enter the matched sample / effective-n")
    store = rc.InMemoryResearchStore()
    for i in range(2):
        ent, ev = entity(f"p-r{i}", f"R{i}"), event(f"gR{i}")
        store.record_observation(observation(f"o-r{i}", ent, ev))
        store.freeze_candidate(candidate(f"c-r{i}", f"o-r{i}", rc.SubLabel.BIRTHDAY, ent, ev))
        store.append_outcome(rc.CandidateOutcome(
            outcome_id=f"o-r{i}o", candidate_id=f"c-r{i}", version=1, case_state=rc.CaseState.PARTIAL,
            bk_captured=POST, record_seq=next(SEQ), observed_endpoint_value=0.22,
            completeness={"observed": rc.Completeness.COMPLETE, "baseline": rc.Completeness.PENDING}))
    fk = store.candidates["c-r0"].family_key
    s = rc.summarize_family(fk, store.family_cases(fk))
    check(s.n_partial == 2 and s.n_matched == 0 and s.effective_n == 0,
          "two PARTIAL cases => n_partial 2, n_matched 0, effective_n 0")
    expect_raises(rc.EvaluationError, lambda: rc.evaluate_family(
        finding_id="r1", endpoint=endpoint(), summary=s, proposed_status=rc.FindingStatus.SUPPORTED,
        bk_captured=POST, record_seq=next(SEQ), evidence=full_bundle()),
        "PARTIAL cases cannot reach the floor to permit SUPPORTED")


# ===== blocker 7 ==========================================================  S evaluation binding
def test_evaluation_bound_to_family():
    print("\n[S] evaluation is bound to the frozen family contract")
    store = rc.InMemoryResearchStore()
    for i in range(2):
        ent, ev = entity(f"p-s{i}", f"S{i}"), event(f"gS{i}")
        store.record_observation(observation(f"o-s{i}", ent, ev))
        store.freeze_candidate(candidate(f"c-s{i}", f"o-s{i}", rc.SubLabel.BIRTHDAY, ent, ev))
        store.append_outcome(measured_outcome(f"o-s{i}o", f"c-s{i}", 0.30, 0.18))
    fk = store.candidates["c-s0"].family_key
    s = rc.summarize_family(fk, store.family_cases(fk))
    expect_raises(rc.EvaluationError, lambda: rc.evaluate_family(
        finding_id="s1", endpoint=endpoint(name="SOMETHING_ELSE"), summary=s,
        proposed_status=rc.FindingStatus.SUPPORTED, bk_captured=POST, record_seq=next(SEQ),
        evidence=full_bundle()), "endpoint whose name != family key rejected")
    expect_raises(rc.EvaluationError, lambda: rc.evaluate_family(
        finding_id="s2", endpoint=endpoint(version="v2"), summary=s,
        proposed_status=rc.FindingStatus.SUPPORTED, bk_captured=POST, record_seq=next(SEQ),
        evidence=full_bundle()), "endpoint whose version != family key rejected")


# ===== blocker 8 ==========================================================  T direction-aware
def test_direction_aware_support():
    print("\n[T] direction-aware SUPPORTED (INCREASE + DECREASE)")

    def family(direction, prefix):
        store = rc.InMemoryResearchStore()
        ep = endpoint(direction=direction)
        for i in range(2):
            ent, ev = entity(f"{prefix}{i}", f"{prefix}{i}"), event(f"g{prefix}{i}")
            store.record_observation(observation(f"o{prefix}{i}", ent, ev))
            store.freeze_candidate(candidate(f"c{prefix}{i}", f"o{prefix}{i}",
                                             rc.SubLabel.BIRTHDAY, ent, ev, ep=ep))
            store.append_outcome(measured_outcome(f"m{prefix}{i}", f"c{prefix}{i}", 0.30, 0.18))
        fk = store.candidates[f"c{prefix}0"].family_key
        return ep, rc.summarize_family(fk, store.family_cases(fk))

    ep_i, s_i = family(rc.Direction.INCREASE, "ti")
    pos = rc.EvidenceBundle(effect_estimate=0.12, interval_low=0.07, interval_high=0.17,
                            corrected_interval_low=0.06, corrected_interval_high=0.18,
                            out_of_sample=True, sensitivity_analysis_done=True, missingness_rule="x")
    check(rc.evaluate_family(finding_id="ti", endpoint=ep_i, summary=s_i,
                             proposed_status=rc.FindingStatus.SUPPORTED, bk_captured=POST,
                             record_seq=next(SEQ), evidence=pos).status is rc.FindingStatus.SUPPORTED,
          "INCREASE: positive effect clearing zero+MEPI => SUPPORTED")
    neg_for_increase = rc.EvidenceBundle(effect_estimate=-0.12, interval_low=-0.17, interval_high=-0.07,
                                         corrected_interval_low=-0.18, corrected_interval_high=-0.06,
                                         out_of_sample=True, sensitivity_analysis_done=True,
                                         missingness_rule="x")
    expect_raises(rc.EvaluationError, lambda: rc.evaluate_family(
        finding_id="ti2", endpoint=ep_i, summary=s_i, proposed_status=rc.FindingStatus.SUPPORTED,
        bk_captured=POST, record_seq=next(SEQ), evidence=neg_for_increase),
        "INCREASE: a negative effect cannot be SUPPORTED")

    ep_d, s_d = family(rc.Direction.DECREASE, "td")
    neg = rc.EvidenceBundle(effect_estimate=-0.12, interval_low=-0.17, interval_high=-0.07,
                            corrected_interval_low=-0.18, corrected_interval_high=-0.06,
                            out_of_sample=True, sensitivity_analysis_done=True, missingness_rule="x")
    check(rc.evaluate_family(finding_id="td", endpoint=ep_d, summary=s_d,
                             proposed_status=rc.FindingStatus.SUPPORTED, bk_captured=POST,
                             record_seq=next(SEQ), evidence=neg).status is rc.FindingStatus.SUPPORTED,
          "DECREASE: negative effect clearing zero+MEPI (directionally) => SUPPORTED")
    expect_raises(rc.EvaluationError, lambda: rc.evaluate_family(
        finding_id="td2", endpoint=ep_d, summary=s_d, proposed_status=rc.FindingStatus.SUPPORTED,
        bk_captured=POST, record_seq=next(SEQ), evidence=pos),
        "DECREASE: a positive effect cannot be SUPPORTED")


# ===== blocker 9 ==========================================================  U numeric safety
def test_canonical_numeric_safety():
    print("\n[U] canonical numeric safety (NaN/inf rejected; no mapping-key coercion)")
    nan, inf = float("nan"), float("inf")
    expect_raises(rc.TypeStrictError, lambda: endpoint(mepi=nan), "NaN MEPI rejected")
    expect_raises(rc.TypeStrictError, lambda: rc.CandidateOutcome(
        outcome_id="o", candidate_id="c", version=1, case_state=rc.CaseState.MEASURED,
        bk_captured=POST, record_seq=1, observed_endpoint_value=inf, baseline_expected_value=0.1,
        completeness={"observed": rc.Completeness.COMPLETE, "baseline": rc.Completeness.COMPLETE}),
        "inf endpoint value rejected")
    expect_raises(rc.TypeStrictError, lambda: candidate(
        "c-u", "o", rc.SubLabel.BIRTHDAY, entity("p-u", "U"), event("gU"), snapshot={1: "x"}),
        "non-string mapping key rejected (no 1 vs '1' collision)")
    expect_raises(rc.TypeStrictError, lambda: candidate(
        "c-u2", "o", rc.SubLabel.BIRTHDAY, entity("p-u2", "U2"), event("gU2"),
        snapshot={"bad": nan}), "NaN nested in a snapshot rejected")
    c = candidate("c-u3", "o", rc.SubLabel.BIRTHDAY, entity("p-u3", "U3"), event("gU3"))
    js = rc.canonical_json(c)
    check("NaN" not in js and "Infinity" not in js, "canonical JSON emits no NaN/Infinity tokens")


if __name__ == "__main__":
    print("=" * 80)
    print("RESEARCH CANDIDATE CONTRACT — SLICE 1 QC (domain model + validators, dark/local)")
    print("=" * 80)
    for t in (test_strict_typing_no_coercion, test_timezone_aware_clocks, test_pre_event_freeze,
              test_mepi_required_and_no_backfill, test_measurement_failure_counted,
              test_one_case_cannot_be_edge, test_inconclusive_immutable, test_no_recommendation_surface,
              test_deterministic_hashes, test_supersession_linkage, test_family_key_excludes_entity,
              test_fixtures_five_categories_and_case1, test_lifecycle_forward_only,
              test_frozen_records_immutable, test_pre_event_ordering_complete,
              test_candidate_observation_binding, test_supersession_allowlist_and_chain,
              test_partial_not_in_matched_sample, test_evaluation_bound_to_family,
              test_direction_aware_support, test_canonical_numeric_safety):
        t()
    print("\n" + "=" * 80)
    print("Clean:", not fails)
    if fails:
        print("FAILURES:")
        for f in fails:
            print("  -", f)
    sys.exit(1 if fails else 0)
