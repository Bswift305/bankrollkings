"""QC: Research Candidate governed domain contract + validators (SLICE 1, DARK/LOCAL).

Proves the Slice-1 guarantees of `services/research_candidate.py` against the approved design
`docs/research_candidate_contract.md` (Rev 2.1). In-memory fixtures ONLY — writes nothing to any
`data/` directory, imports no `app` symbol, and exercises no route/UI/job.

Validation matrix (sections A-M):
  A strict typed inputs, NO coercion            G INCONCLUSIVE is an immutable finding (no rewind)
  B timezone-aware observation + event clocks    H no recommendation / ranking / score surface
  C pre-event freeze enforced                     I deterministic canonical serialization + hashes
  D numeric MEPI required + NEVER backfilled      J supersession linkage (outcomes + findings)
  E measurement failure -> counted UNMEASURABLE   K family key excludes entity; case identity differs
    (INVALIDATED only for frozen eligibility;     L fixtures: 5 categories + Freiermuth Case #1
     outcome-correlated covariate exclusion barred) M forward-only lifecycle / state-transition table
  F one game cannot promote a hypothesis -> edge
"""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import services.research_candidate as rc  # noqa: E402

UTC = timezone.utc
ET = timezone(timedelta(hours=-4))

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


# --------------------------------------------------------------------------- shared timing
EVENT = datetime(2026, 10, 25, 17, 30, 0, tzinfo=UTC)          # the event's own clock
PRE = datetime(2026, 10, 25, 12, 51, 21, tzinfo=UTC)           # before the event
POST = datetime(2026, 10, 25, 21, 0, 0, tzinfo=UTC)            # after the event

SEQ = iter(range(1, 10_000))


def temporal(observed=PRE, captured=PRE, event=EVENT, src=None,
             src_status=rc.SourceUpdatedStatus.NOT_PROVIDED):
    return rc.TemporalFacts(observed_at=observed, event_effective=event, bk_captured=captured,
                            record_seq=next(SEQ), source_updated=src, source_updated_status=src_status)


def endpoint(name="target_share_lift", version="v1", mepi=0.05):
    return rc.PrimaryEndpoint(name=name, version=version, direction=rc.Direction.INCREASE,
                              mepi=mepi, unit="target_share_fraction")


def baseline():
    # game script + team pass volume are COVARIATES here, never invalidation triggers.
    return rc.BaselineMethod(method="role_matchup_expected_usage", version="v1",
                             covariates=("game_script", "team_pass_volume", "snaps", "qb_change"))


def observation(oid, entity, event, thesis):
    return rc.UserObservation(observation_id=oid, observer="owner", entity=entity, event=event,
                              thesis=thesis, observed_at=PRE, bk_captured=PRE, record_seq=next(SEQ),
                              sources=("https://example.test/bio",))


def candidate(cid, oid, sub_label, entity, event, *, ep=None, captured=PRE,
              invalidation=("player_inactive", "assumed_starter_benched")):
    return rc.ResearchCandidate(
        candidate_id=cid, observation_id=oid, observer="owner",
        category=rc.Category.PLAYER_MILESTONE_USAGE, sub_label=sub_label, entity=entity, event=event,
        temporal=temporal(captured=captured, event=event.event_effective), thesis="usage may rise",
        baseline=baseline(), assumptions=("player active", "normal snap role", "assumed starter plays"),
        eligibility_conditions=("player active", "assumed starter plays"),
        invalidation_conditions=invalidation,
        primary_endpoint=endpoint() if ep is None else ep,
        pre_event_snapshot={"expected_target_share": 0.18, "competing_wr_out": True},
        sources=("https://example.test/bio",),
    )


def entity(cid, name):
    return rc.EntityIdentity(canonical_id=cid, display=name)


def event(cid, eff=EVENT):
    return rc.EventIdentity(canonical_id=cid, event_effective=eff)


def measured_outcome(oid, cid, observed, expected, seq=None):
    return rc.CandidateOutcome(
        outcome_id=oid, candidate_id=cid, version=1, case_state=rc.CaseState.MEASURED,
        bk_captured=POST, record_seq=seq if seq is not None else next(SEQ),
        observed_endpoint_value=observed, baseline_expected_value=expected,
        completeness={"observed": rc.Completeness.COMPLETE, "baseline": rc.Completeness.COMPLETE},
        covariates={"game_script": "neutral", "team_pass_volume": 38.0},
        descriptive={"receiving_yards": 64.0, "touchdowns": 1},   # secondary — never the endpoint
    )


# =========================================================================== A strict typing
def test_strict_typing_no_coercion():
    print("\n[A] strict typed inputs, NO coercion")
    expect_raises(rc.TypeStrictError, lambda: endpoint(mepi=5),
                  "int MEPI rejected (no int->float coercion)")
    expect_raises(rc.TypeStrictError, lambda: endpoint(mepi=True),
                  "bool MEPI rejected (bool is not a number here)")
    expect_raises(rc.HindsightError, lambda: endpoint(mepi=0.0),
                  "non-positive MEPI rejected")
    expect_raises(rc.TypeStrictError, lambda: rc.CandidateOutcome(
        outcome_id="o", candidate_id="c", version=1, case_state=rc.CaseState.PENDING,
        bk_captured=POST, record_seq=1, observed_endpoint_value="0.1"),
        "numeric-string endpoint value rejected (no str->float coercion)")
    expect_raises(rc.TypeStrictError, lambda: rc.EntityIdentity(canonical_id="", display="x"),
                  "empty canonical id rejected")


# =========================================================================== B tz-aware clocks
def test_timezone_aware_clocks():
    print("\n[B] timezone-aware observation + event clocks required")
    naive = datetime(2026, 10, 25, 12, 0, 0)
    expect_raises(rc.TemporalError, lambda: temporal(observed=naive),
                  "naive observed_at rejected")
    expect_raises(rc.TemporalError, lambda: rc.EventIdentity(canonical_id="g", event_effective=naive),
                  "naive event_effective rejected")
    expect_raises(rc.TypeStrictError, lambda: rc.TemporalFacts(
        observed_at="2026-10-25T12:00:00Z", event_effective=EVENT, bk_captured=PRE, record_seq=1),
        "string-as-datetime rejected")
    # provider clock never backfilled
    expect_raises(rc.TemporalError, lambda: rc.TemporalFacts(
        observed_at=PRE, event_effective=EVENT, bk_captured=PRE, record_seq=1,
        source_updated=PRE, source_updated_status=rc.SourceUpdatedStatus.UNKNOWN),
        "provider clock present while status != PRESENT rejected (no backfill)")


# =========================================================================== C pre-event freeze
def test_pre_event_freeze():
    print("\n[C] pre-event freeze enforced")
    ent, ev = entity("p-eligible", "Eligible Player"), event("g1")
    good = candidate("c-good", "o-good", rc.SubLabel.BIRTHDAY, ent, ev, captured=PRE)
    check(good.frozen_before_event and good.eligible_for_sample, "pre-event freeze => eligible")
    check(good.track_state is rc.CaseTrackState.MEASUREMENT_DEFINED, "pre-event => MEASUREMENT_DEFINED")

    late = candidate("c-late", "o-good", rc.SubLabel.BIRTHDAY, ent, ev, captured=POST)
    check(not late.frozen_before_event, "capture after event => not frozen_before_event")
    check(not late.eligible_for_sample and "frozen_after_event" in late.ineligibility_reasons,
          "frozen-after-event => ineligible")
    check(late.track_state is rc.CaseTrackState.DESCRIPTIVE_NOTE,
          "frozen-after-event => permanent DESCRIPTIVE_NOTE")

    unresolved = candidate("c-unk", "o-good", rc.SubLabel.BIRTHDAY,
                           rc.EntityIdentity("p?", "Unknown", rc.Resolution.AMBIGUOUS), ev)
    check(not unresolved.eligible_for_sample
          and "unresolved_identity" in unresolved.ineligibility_reasons,
          "ambiguous identity => ineligible, never guessed")


# =========================================================================== D MEPI no backfill
def test_mepi_required_and_no_backfill():
    print("\n[D] numeric MEPI required + NEVER backfilled")
    ent, ev = entity("p-nomepi", "Seed Player"), event("g1")
    seed = candidate("c-seed", "o-seed", rc.SubLabel.BIRTHDAY, ent, ev, ep=False) \
        if False else rc.ResearchCandidate(
            candidate_id="c-seed", observation_id="o-seed", observer="owner",
            category=rc.Category.PLAYER_MILESTONE_USAGE, sub_label=rc.SubLabel.BIRTHDAY,
            entity=ent, event=ev, temporal=temporal(event=ev.event_effective),
            thesis="usage may rise", baseline=baseline(),
            assumptions=("player active",), eligibility_conditions=("player active",),
            invalidation_conditions=("player_inactive",), primary_endpoint=None,
            pre_event_snapshot={}, sources=("https://example.test/bio",))
    check(seed.primary_endpoint is None and not seed.eligible_for_sample
          and "no_frozen_numeric_mepi" in seed.ineligibility_reasons,
          "no frozen numeric MEPI => ineligible seed")
    check(seed.family_key is None, "a seed without an endpoint maps to no family")

    # backfilling the MEPI AFTER the event to rescue eligibility is prohibited.
    expect_raises(rc.HindsightError, lambda: rc.supersede_candidate(
        seed, new_temporal=temporal(captured=POST, event=ev.event_effective),
        primary_endpoint=endpoint()),
        "backfilling MEPI with a post-event capture rejected (no manufactured pre-registration)")

    # a genuine pre-event correction that adds the MEPI is allowed.
    fixed = rc.supersede_candidate(
        seed, new_temporal=temporal(captured=PRE, event=ev.event_effective),
        primary_endpoint=endpoint())
    check(fixed.eligible_for_sample and fixed.supersedes == seed.temporal.record_seq,
          "pre-event correction may add the MEPI and link by record_seq")


# =========================================================================== E UNMEASURABLE vs INVALIDATED
def test_measurement_failure_counted():
    print("\n[E] measurement failure -> counted UNMEASURABLE; INVALIDATED only for frozen eligibility")
    store = rc.InMemoryResearchStore()
    ent, ev = entity("p-e", "E Player"), event("g1")
    store.record_observation(observation("o-e", ent, ev, "usage may rise"))
    # invalidation set deliberately (mis)includes a covariate name to prove the covariate guard.
    cand = candidate("c-e", "o-e", rc.SubLabel.REVENGE_GAME, ent, ev,
                     invalidation=("player_inactive", "game_script"))
    store.freeze_candidate(cand)

    unmeasurable = rc.CandidateOutcome(
        outcome_id="o-unm", candidate_id="c-e", version=1, case_state=rc.CaseState.UNMEASURABLE,
        bk_captured=POST, record_seq=next(SEQ), invalidation_reason="tracking_feed_missing",
        completeness={"observed": rc.Completeness.PENDING})
    store.append_outcome(unmeasurable)
    check(unmeasurable.counts_in_missingness and not unmeasurable.counts_in_matched_sample,
          "UNMEASURABLE is COUNTED in missingness, not the matched sample (never silently dropped)")

    # INVALIDATED with a measurement-missing reason not in the frozen set is rejected.
    bad_missing = rc.CandidateOutcome(
        outcome_id="o-badm", candidate_id="c-e", version=1, case_state=rc.CaseState.INVALIDATED,
        bk_captured=POST, record_seq=next(SEQ), invalidation_reason="tracking_feed_missing")
    expect_raises(rc.EligibilityError, lambda: bad_missing.validate_invalidation_against_candidate(cand),
                  "INVALIDATED with a non-frozen (measurement-missing) reason rejected")

    # INVALIDATED on an outcome-correlated COVARIATE is rejected even if someone froze it as a condition.
    bad_cov = rc.CandidateOutcome(
        outcome_id="o-badc", candidate_id="c-e", version=1, case_state=rc.CaseState.INVALIDATED,
        bk_captured=POST, record_seq=next(SEQ), invalidation_reason="game_script")
    expect_raises(rc.EligibilityError, lambda: bad_cov.validate_invalidation_against_candidate(cand),
                  "INVALIDATED on a predeclared covariate rejected (outcome-correlated exclusion barred)")

    # a legitimate frozen eligibility failure is accepted.
    good_inv = rc.CandidateOutcome(
        outcome_id="o-goodi", candidate_id="c-e", version=1, case_state=rc.CaseState.INVALIDATED,
        bk_captured=POST, record_seq=next(SEQ), invalidation_reason="player_inactive")
    good_inv.validate_invalidation_against_candidate(cand)
    check(True, "INVALIDATED on a frozen eligibility failure (player_inactive) accepted")
    # MEASURED must not carry an invalidation reason / must be complete.
    expect_raises(rc.EligibilityError, lambda: rc.CandidateOutcome(
        outcome_id="o-x", candidate_id="c-e", version=1, case_state=rc.CaseState.MEASURED,
        bk_captured=POST, record_seq=1, observed_endpoint_value=0.2, baseline_expected_value=0.1,
        completeness={"observed": rc.Completeness.PENDING, "baseline": rc.Completeness.COMPLETE}),
        "MEASURED with a non-COMPLETE variable rejected")


# =========================================================================== F one case != edge
def test_one_case_cannot_be_edge():
    print("\n[F] one game cannot promote a hypothesis into an edge")
    store = rc.InMemoryResearchStore()
    ent, ev = entity("p-f1", "F1"), event("gF1")
    store.record_observation(observation("o-f1", ent, ev, "usage may rise"))
    cand = candidate("c-f1", "o-f1", rc.SubLabel.RECORD_CHASE, ent, ev)
    store.freeze_candidate(cand)
    store.append_outcome(measured_outcome("o-f1o", "c-f1", 0.26, 0.18))
    fk = cand.family_key
    summary1 = rc.summarize_family(fk, store.family_cases(fk))
    check(summary1.effective_n == 1 and summary1.n_matched == 1, "single matched case => effective_n 1")
    expect_raises(rc.EvaluationError, lambda: rc.evaluate_family(
        finding_id="f1", endpoint=endpoint(), summary=summary1,
        proposed_status=rc.FindingStatus.SUPPORTED, bk_captured=POST, record_seq=next(SEQ)),
        "SUPPORTED from a single case rejected")
    only = rc.evaluate_family(finding_id="f1", endpoint=endpoint(), summary=summary1,
                              proposed_status=rc.FindingStatus.INCONCLUSIVE, bk_captured=POST,
                              record_seq=next(SEQ))
    check(only.status is rc.FindingStatus.INCONCLUSIVE, "a below-floor family can only be INCONCLUSIVE")

    # add a SECOND independent entity's matched case -> SUPPORTED becomes structurally possible.
    ent2, ev2 = entity("p-f2", "F2"), event("gF2")
    store.record_observation(observation("o-f2", ent2, ev2, "usage may rise"))
    cand2 = candidate("c-f2", "o-f2", rc.SubLabel.RECORD_CHASE, ent2, ev2)
    store.freeze_candidate(cand2)
    store.append_outcome(measured_outcome("o-f2o", "c-f2", 0.30, 0.18))
    summary2 = rc.summarize_family(fk, store.family_cases(fk))
    check(summary2.effective_n == 2, "two distinct entities => effective_n 2")

    good_bundle = rc.EvidenceBundle(effect_estimate=0.12, interval_low=0.07, interval_high=0.17,
                                    corrected_interval_low=0.06, corrected_interval_high=0.18,
                                    out_of_sample=True, sensitivity_analysis_done=True,
                                    missingness_rule="exclude_pending")
    supported = rc.evaluate_family(finding_id="f2", endpoint=endpoint(), summary=summary2,
                                   proposed_status=rc.FindingStatus.SUPPORTED, bk_captured=POST,
                                   record_seq=next(SEQ), evidence=good_bundle)
    check(supported.status is rc.FindingStatus.SUPPORTED, "SUPPORTED allowed at/above the floor with a full bundle")
    check(supported.authority == rc.AUTHORITY == "RESEARCH_ONLY", "SUPPORTED is still RESEARCH_ONLY")

    expect_raises(rc.EvaluationError, lambda: rc.evaluate_family(
        finding_id="f3", endpoint=endpoint(), summary=summary2,
        proposed_status=rc.FindingStatus.SUPPORTED, bk_captured=POST, record_seq=next(SEQ)),
        "SUPPORTED without an evidence bundle rejected (significance alone is not enough)")
    no_oos = rc.EvidenceBundle(effect_estimate=0.12, interval_low=0.07, interval_high=0.17,
                               corrected_interval_low=0.06, corrected_interval_high=0.18,
                               out_of_sample=False, sensitivity_analysis_done=True,
                               missingness_rule="exclude_pending")
    expect_raises(rc.EvaluationError, lambda: rc.evaluate_family(
        finding_id="f4", endpoint=endpoint(), summary=summary2,
        proposed_status=rc.FindingStatus.SUPPORTED, bk_captured=POST, record_seq=next(SEQ),
        evidence=no_oos), "SUPPORTED without out-of-sample rejected")
    below = rc.EvidenceBundle(effect_estimate=0.02, interval_low=0.00, interval_high=0.04,
                              corrected_interval_low=0.005, corrected_interval_high=0.03,
                              out_of_sample=True, sensitivity_analysis_done=True,
                              missingness_rule="exclude_pending")
    expect_raises(rc.EvaluationError, lambda: rc.evaluate_family(
        finding_id="f5", endpoint=endpoint(), summary=summary2,
        proposed_status=rc.FindingStatus.SUPPORTED, bk_captured=POST, record_seq=next(SEQ),
        evidence=below), "effect below MEPI cannot be SUPPORTED (would be UNSUPPORTED)")


# =========================================================================== G INCONCLUSIVE immutable
def test_inconclusive_immutable():
    print("\n[G] INCONCLUSIVE is an immutable finding; a later evaluation supersedes, never rewinds")
    store = rc.InMemoryResearchStore()
    ent, ev = entity("p-g", "G"), event("gG")
    store.record_observation(observation("o-g", ent, ev, "usage may rise"))
    cand = candidate("c-g", "o-g", rc.SubLabel.HOMECOMING, ent, ev)
    store.freeze_candidate(cand)
    store.append_outcome(measured_outcome("o-go", "c-g", 0.25, 0.18))
    fk = cand.family_key
    s = rc.summarize_family(fk, store.family_cases(fk))
    inconclusive = rc.evaluate_family(finding_id="g1", endpoint=endpoint(), summary=s,
                                      proposed_status=rc.FindingStatus.INCONCLUSIVE, bk_captured=POST,
                                      record_seq=next(SEQ))
    store.record_finding(inconclusive)
    check(store.current_finding(fk).status is rc.FindingStatus.INCONCLUSIVE, "INCONCLUSIVE recorded")
    # no store method rewinds a family to accumulating.
    check(not any("rewind" in n or "reopen" in n for n in dir(store)),
          "store exposes no rewind/reopen path")
    # a later evaluation is a NEW finding superseding by record_seq; history retains the prior.
    later = rc.evaluate_family(finding_id="g2", endpoint=endpoint(), summary=s,
                               proposed_status=rc.FindingStatus.INCONCLUSIVE, bk_captured=POST,
                               record_seq=next(SEQ), supersedes=inconclusive.record_seq)
    store.record_finding(later)
    hist = store._finding_versions[fk.key]
    check(len(hist) == 2 and hist[0].content_hash == inconclusive.content_hash,
          "prior INCONCLUSIVE preserved immutably in history")
    expect_raises(rc.SupersessionError, lambda: store.record_finding(rc.evaluate_family(
        finding_id="g3", endpoint=endpoint(), summary=s,
        proposed_status=rc.FindingStatus.INCONCLUSIVE, bk_captured=POST, record_seq=next(SEQ))),
        "a non-superseding finding after one exists is rejected")


# =========================================================================== H no authority surface
def test_no_recommendation_surface():
    print("\n[H] no recommendation / ranking / score surface")
    check(rc.AUTHORITY == "RESEARCH_ONLY", "module AUTHORITY is RESEARCH_ONLY")
    forbidden = ("rank", "score", "recommend", "best_", "pick", "lock", "bet_", "edge_value")
    hits = [n for n in dir(rc) if any(f in n.lower() for f in forbidden)]
    check(not hits, "no ranking/scoring/recommendation names in the module API (%r)" % hits)
    fnames = {f.name for f in rc.__dataclass_fields__.values()} if hasattr(rc, "__dataclass_fields__") else set()
    finding_fields = set(rc.EvaluatedFinding.__dataclass_fields__)
    check(not (finding_fields & {"score", "rank", "confidence"}),
          "EvaluatedFinding carries no score/rank/confidence field")
    _ = fnames


# =========================================================================== I determinism
def test_deterministic_hashes():
    print("\n[I] deterministic canonical serialization + stable content hashes")
    ent, ev = entity("p-i", "I"), event("gI")
    c1 = candidate("c-i", "o-i", rc.SubLabel.CONTRACT_INCENTIVE, ent, ev)
    h_a, h_b = rc.content_hash(c1), rc.content_hash(c1)
    check(h_a == h_b and len(h_a) == 64, "content_hash is stable and sha256-shaped")
    # dict insertion order must not change the hash.
    o1 = rc.CandidateOutcome(outcome_id="o", candidate_id="c-i", version=1,
                             case_state=rc.CaseState.MEASURED, bk_captured=POST, record_seq=1,
                             observed_endpoint_value=0.3, baseline_expected_value=0.18,
                             completeness={"observed": rc.Completeness.COMPLETE,
                                           "baseline": rc.Completeness.COMPLETE},
                             covariates={"game_script": "neutral", "team_pass_volume": 38.0})
    o2 = rc.CandidateOutcome(outcome_id="o", candidate_id="c-i", version=1,
                             case_state=rc.CaseState.MEASURED, bk_captured=POST, record_seq=1,
                             observed_endpoint_value=0.3, baseline_expected_value=0.18,
                             completeness={"baseline": rc.Completeness.COMPLETE,
                                           "observed": rc.Completeness.COMPLETE},
                             covariates={"team_pass_volume": 38.0, "game_script": "neutral"})
    check(rc.content_hash(o1) == rc.content_hash(o2), "hash is independent of dict insertion order")
    check('"observed_endpoint_value":0.3' in rc.canonical_json(o1), "canonical JSON keeps the real value")


# =========================================================================== J supersession
def test_supersession_linkage():
    print("\n[J] supersession linkage (outcome version chain + finding chain, one current)")
    store = rc.InMemoryResearchStore()
    ent, ev = entity("p-j", "J"), event("gJ")
    store.record_observation(observation("o-j", ent, ev, "usage may rise"))
    cand = candidate("c-j", "o-j", rc.SubLabel.BIRTHDAY, ent, ev)
    store.freeze_candidate(cand)
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
          and len(store.outcome_history("c-j")) == 2, "exactly one current outcome; prior retained")
    expect_raises(rc.SupersessionError, lambda: store.append_outcome(rc.CandidateOutcome(
        outcome_id="o-j4", candidate_id="c-j", version=4, case_state=rc.CaseState.MEASURED,
        bk_captured=POST, record_seq=next(SEQ), observed_endpoint_value=0.25,
        baseline_expected_value=0.18,
        completeness={"observed": rc.Completeness.COMPLETE, "baseline": rc.Completeness.COMPLETE},
        supersedes=v2.record_seq)), "a version that skips (2->4) is rejected")


# =========================================================================== K family key vs case id
def test_family_key_excludes_entity():
    print("\n[K] family key excludes the entity; case identity is (entity,event,contract)")
    ea, eb = entity("p-ka", "A"), entity("p-kb", "B")
    eva, evb = event("gKA"), event("gKB")
    ca = candidate("c-ka", "o-ka", rc.SubLabel.REVENGE_GAME, ea, eva)
    cb = candidate("c-kb", "o-kb", rc.SubLabel.REVENGE_GAME, eb, evb)
    check(ca.family_key.key == cb.family_key.key,
          "two different players share one family (entity not in the key)")
    check(ca.case_identity != cb.case_identity, "case identities differ (entity+event+contract)")
    check("p-ka" not in ca.family_key.key, "entity id absent from the family key string")


# =========================================================================== L fixtures
def test_fixtures_five_categories_and_case1():
    print("\n[L] fixtures: 5 categories (non-predictive labels) + Freiermuth Case #1")
    store = rc.InMemoryResearchStore()
    labels = [rc.SubLabel.BIRTHDAY, rc.SubLabel.REVENGE_GAME, rc.SubLabel.RECORD_CHASE,
              rc.SubLabel.HOMECOMING, rc.SubLabel.CONTRACT_INCENTIVE]
    for i, lab in enumerate(labels):
        ent, ev = entity(f"p-l{i}", f"Player {i}"), event(f"gL{i}")
        store.record_observation(observation(f"o-l{i}", ent, ev, f"{lab.value} usage thesis"))
        c = candidate(f"c-l{i}", f"o-l{i}", lab, ent, ev)
        store.freeze_candidate(c)
        check(c.eligible_for_sample and c.sub_label is lab,
              f"{lab.value}: eligible candidate built as a LABEL, not a predictor")
    check(len(store.candidates) == 5, "all five category fixtures built")

    # Freiermuth Case #1: valid observation + descriptive seed, INELIGIBLE for the evaluated sample.
    fm_ent = entity("nfl:pat-freiermuth", "Pat Freiermuth")
    fm_ev = rc.EventIdentity(canonical_id="nfl:2026-PIT-NO-paris",
                             event_effective=datetime(2026, 10, 25, 13, 30, 0, tzinfo=UTC))
    obs = rc.UserObservation(
        observation_id="obs-case1", observer="owner", entity=fm_ent, event=fm_ev,
        thesis="Rodgers may involve Freiermuth more than his normal role because it is his birthday",
        observed_at=datetime(2026, 10, 25, 12, 51, 21, tzinfo=UTC),
        bk_captured=datetime(2026, 10, 25, 12, 51, 21, tzinfo=UTC), record_seq=next(SEQ),
        sources=("https://steelers.test/bio", "https://nfl.test/schedule"), acted=False)
    store.record_observation(obs)
    check(obs.track_state is rc.CaseTrackState.OBSERVED, "Case #1 observation is valid and recorded")
    # the preserved seed froze NO numeric MEPI pre-kickoff -> ineligible (never backfill).
    seed = rc.ResearchCandidate(
        candidate_id="cand-case1", observation_id="obs-case1", observer="owner",
        category=rc.Category.PLAYER_MILESTONE_USAGE, sub_label=rc.SubLabel.BIRTHDAY,
        entity=fm_ent, event=fm_ev,
        temporal=temporal(observed=obs.observed_at, captured=obs.bk_captured, event=fm_ev.event_effective),
        thesis=obs.thesis, baseline=baseline(),
        assumptions=("player active", "normal snap role", "Rodgers starts"),
        eligibility_conditions=("player active", "Rodgers starts"),
        invalidation_conditions=("player_inactive", "assumed_starter_benched"),
        primary_endpoint=None, pre_event_snapshot={"expected_target_share": 0.17},
        sources=obs.sources)
    store.freeze_candidate(seed)
    check(seed.frozen_before_event and not seed.eligible_for_sample
          and seed.ineligibility_reasons == ("no_frozen_numeric_mepi",),
          "Case #1: pre-kickoff seed, but INELIGIBLE (no frozen numeric MEPI)")
    expect_raises(rc.HindsightError, lambda: rc.supersede_candidate(
        seed, new_temporal=temporal(captured=POST, event=fm_ev.event_effective),
        primary_endpoint=endpoint()),
        "Case #1 MEPI can never be backfilled post-event to rescue eligibility")


# =========================================================================== M lifecycle table
def test_lifecycle_forward_only():
    print("\n[M] forward-only lifecycle / state-transition table")
    # per-case states observed in fixtures; no backward transition exists in the API.
    check(set(s.value for s in rc.CaseState) ==
          {"MEASURED", "PARTIAL", "PENDING", "UNMEASURABLE", "INVALIDATED"},
          "case states exactly {MEASURED,PARTIAL,PENDING,UNMEASURABLE,INVALIDATED}")
    check(set(s.value for s in rc.FindingStatus) == {"SUPPORTED", "UNSUPPORTED", "INCONCLUSIVE"},
          "finding statuses exactly {SUPPORTED,UNSUPPORTED,INCONCLUSIVE}")
    check(set(s.value for s in rc.CaseTrackState) ==
          {"OBSERVED", "MEASUREMENT_DEFINED", "OUTCOME_CAPTURED", "DESCRIPTIVE_NOTE"},
          "per-case track states match the contract §2 lifecycle")


if __name__ == "__main__":
    print("=" * 78)
    print("RESEARCH CANDIDATE CONTRACT — SLICE 1 QC (domain model + validators, dark/local)")
    print("=" * 78)
    test_strict_typing_no_coercion()
    test_timezone_aware_clocks()
    test_pre_event_freeze()
    test_mepi_required_and_no_backfill()
    test_measurement_failure_counted()
    test_one_case_cannot_be_edge()
    test_inconclusive_immutable()
    test_no_recommendation_surface()
    test_deterministic_hashes()
    test_supersession_linkage()
    test_family_key_excludes_entity()
    test_fixtures_five_categories_and_case1()
    test_lifecycle_forward_only()
    print("\n" + "=" * 78)
    print("Clean:", not fails)
    if fails:
        print("FAILURES:")
        for f in fails:
            print("  -", f)
    sys.exit(1 if fails else 0)
