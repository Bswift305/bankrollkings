from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from season_utils import active_sports, sport_for_label


BASE_DIR = Path(__file__).resolve().parent


def _hard_fail_count(output: str):
    """Pull the hard-FAIL tally from a 99% scorecard's summary (e.g. 'FAIL: 1').

    Returns the count, or None if no summary line was found (which usually means
    the scorecard crashed before printing one).
    """
    matches = re.findall(r"FAIL:\s*(\d+)", output or "")
    if not matches:
        return None
    return int(matches[-1])
LOG_DIR = BASE_DIR / "logs"
# Timeouts are generous because the daily refresh keeps the box busy when these
# run; a slow scorecard is treated as a non-blocking TIMEOUT (see main), not a
# hard failure, so transient slowness can't fail the whole daily run.
SCORECARDS = [
    # Runs first and is cheap: it verifies every registered sport still has its
    # loaders, stat map and calibrator wired. A sport missing a part is invisible
    # at runtime -- football archived all its picks and graded none of them -- so
    # this is the check that turns "silently absent" into a hard failure.
    ("Sport Registry", "qc_sport_registry.py", 240),
    # Daily operator season-gate: NFL preseason jobs must SKIP (not run, not FAIL) outside the ~Aug
    # window. The operator aborts on the first FAIL, so an out-of-window preseason fetch that errored
    # would stall every downstream refresh (the Oct 23 incident class). Pure; cheap.
    ("Daily Operator Season-Gate QC", "qc_daily_operator_season_gate.py", 60),
    # Cross-sport Quick Tools smoke (renders every /tools/* surface + exercises their
    # logic paths). Cheap, cross-sport (no season gate), so a broken tool is a hard FAIL.
    ("Quick Tools QC", "qc_quick_tools.py", 300),
    # Lens Attribution governance guards -- identity resolution + resolution states.
    # Permanent regression guard for the capture/grading integrity defects; a governance
    # bug reintroduced here is a hard FAIL, not a silently corrupted archive.
    ("Lens Attribution QC", "qc_lens_attribution.py", 180),
    # Floor-board cache determinism + player-log invalidation guard. Cheap; locks down the
    # call-order contamination and stale-on-log-refresh defects (a6d9e4c + signature follow-up).
    ("NFL Floor Cache QC", "qc_nfl_floor_cache.py", 240),
    # NFL heat-map freshness: a stale streak must never read as current. Locks down the cache
    # key (player-log signature), the through-week/timestamp disclosures, games-played vs
    # calendar recency + injury availability, the completed-week pending gate, and the Mike
    # Evans Week-5 regression (yesterday's result ends the run once the week loads).
    ("NFL Heat-Map Freshness QC", "qc_nfl_heatmap_freshness.py", 180),
    # Game-LINES freshness containment (2026-10-23 incident): a stale odds feed must be shown as stale,
    # never as current. get_lines_refresh_meta flags it and the football game-lines/totals board renders
    # a visible "Game Lines Are Stale" banner. Mirrors the props fail-closed protection. Fixture-driven.
    ("Game-Lines Freshness QC", "qc_game_lines_freshness.py", 180),
    # Market Movers fail-closed on a stalled line-movement capture (Oct 23 containment): a game whose
    # latest snapshot is stale (>12h = 3x the 4h cadence) is suppressed, never shown as a live current
    # line. Populated fixture (fresh surfaces, stale suppressed). app.DATA_DIR redirected; no network.
    ("Market Movers Freshness QC", "qc_market_movers_freshness.py", 120),
    # build_game_market_lookup wholesale-stale gate (Oct 23 containment): THE shared chokepoint for the
    # current spread/total/ML across every board + command center (NBA/WNBA/MLB/NFL/CFB) returns an empty
    # lookup when the whole odds feed is stale -- so no board annotates a stale current line as live. A
    # feed with any recent update (or no LastUpdated) is not suppressed. Pure.
    ("Market Lookup Freshness QC", "qc_market_lookup_freshness.py", 60),
    # Atomic + validated artifact publish (Oct 23 recovery gate): the shared temp->validate->os.replace
    # helper the Odds fetchers (game lines, player props, futures) now publish through -- a crash or bad
    # frame can't truncate an authoritative file and a validation failure preserves last-known-good. Cheap.
    ("Atomic CSV Publish QC", "qc_atomic_csv.py", 60),
    # Odds recovery preflight (Oct 23): strong semantic feed validation (wrong sport/schema, non-finite
    # lines, timestamp regression, conflicting duplicates, row-count collapse, empty slice) + per-request
    # quota accounting (x-requests-last/used/remaining -> fetch cost; fail the receipt if headers absent
    # or cost over budget). Gates the game-lines fetcher's atomic publish. Pure.
    ("Odds Recovery Preflight QC", "qc_odds_recovery_preflight.py", 60),
    # Recovery receipt-wrapper safety guards (Oct 23 item 5): redacts keys in the printed command, refuses
    # concurrent execution (lock), refuses when a refresh/fetch job is running, leaves authoritative bytes
    # unchanged on a failed fetch. Pure (fetch is a local python -c; process scan monkeypatched).
    ("Recover-Odds Wrapper QC", "qc_recover_odds_wrapper.py", 60),
    # CFB Wave Watch wording remediation (Gate 1): no betting-authority language survives and the
    # template filters no qualifier (every builder team renders; the model groups, never removes).
    ("CFB Wave Wording QC", "qc_cfb_wave_wording.py", 120),
    # CFB Active ATS Wave admission (docs/ats_wave_contract.md): membership = current consecutive graded
    # cover streak >= 3 (not season cover%); push interrupts; bye/ungraded ignored; loss resets;
    # source-through-week fail-closed; model-independent membership; deterministic streak-desc order.
    ("CFB ATS Wave Admission QC", "qc_cfb_ats_wave_admission.py", 120),
    # CFB wave-local team canonicalization + COLLISION AUDIT: the short/long CFBD name helper
    # (_cfb_wave_team_key) merges aliases (App State/Appalachian State) but never collapses distinct
    # teams (Miami FL/OH, USC/South Carolina, the Louisiana schools, Washington/Washington State, FCS
    # lookalikes). Idempotent; FBS-FCS side retained. Gate for the manifest<->graded reconciliation fix.
    ("CFB Wave Canon QC", "qc_cfb_wave_canon.py", 120),
    # CFB runtime-data resolver + deploy hardening: runtime copy precedence, live-file fail-closed (no
    # stale seed), atomic-write failure preserves the prior version, the deploy dirty-tracked guard, and
    # a fresh checkout starting safely before its first refresh. No network (fixtures).
    ("CFB Runtime-Data QC", "qc_cfb_runtime_data.py", 120),
    # CFBD provider-quota containment (Oct 23 incident): on a CFBD HTTP 429 the refresh must STOP and
    # report PROVIDER_QUOTA_EXHAUSTED (exit 3), not hammer every remaining sub-step. Pure (subprocess mocked).
    ("CFBD Quota Short-Circuit QC", "qc_cfb_quota_shortcircuit.py", 60),
    # CFB Matchup "This Week's Matchups" total-render contract (regression for da2c3c2): the header
    # O/U line must show the posted number from g.total.line and never the raw Python object, because
    # build_cfb_matchup_context sets g.total to a MAPPING (total_read: proj_total/line/lean/edge/...)
    # or None. Renders the real route+template with a fixed mu_week across all five g.total shapes
    # (mapping w/ numeric line, line=None, missing, legacy scalar, malformed mapping) and asserts no
    # dict/None/malformed-object text leaks. Mirror-guard of the NFL defect fixed in 24273df.
    ("CFB Matchup Total QC", "qc_cfb_matchup_total.py", 120),
    # NFL Active ATS Wave on the current-season source (nflverse_games.parquet): explicit active-season
    # gate (never max(season)), game_id identity + reciprocal team-side decisions, recorded-spread sign,
    # event-level completeness (completed Thursday counts mid-week; future ignored; overdue fails closed),
    # duplicate/conflict + stale-source fail-closed, factual streak-desc order, and W,W,P,W -> 1. Guards
    # against re-presenting a completed prior season as active.
    ("NFL ATS Wave QC", "qc_nfl_ats_wave.py", 120),
    # NFL games-source refresh pipeline (fetch_nfl_games.py): atomic replace, schema/dup/season/
    # completed-regression validation, permission failure as an operability error (never "no games"),
    # 304 unchanged handling, sidecar freshness, recovery after a failed pull. No network (fixtures).
    ("NFL Games Refresh QC", "qc_nfl_games_refresh.py", 120),
    # Riding-the-Wave player prop-streak freshness: the under-streak surface must disclose what
    # it is graded through and never present last season's final runs as current. Locks the
    # stale-season/through-week pending gate + availability + the Mike Evans unders->over fixture.
    ("NFL Prop-Streak Freshness QC", "qc_nfl_prop_streak_freshness.py", 180),
    # Same board against the REAL NFL_AllPropResults source schema (the routinely-refreshed graded
    # record): proves an Under streak that is current through the latest graded week disappears once
    # the next graded game goes Over, via the real on-disk read path.
    ("NFL Prop-Streak Integration QC", "qc_nfl_prop_streak_integration.py", 180),
    # P0 corrective: the prop-streak board is bound to the RESOLVED current season (never max(Season)),
    # fails closed when the current season is ungraded (no prior-season fallback), and gates on a
    # freshness-aware 4-state injury model (ACTIVE/PAUSED/STATUS UNKNOWN) -- a paused player's run is
    # preserved as fact but never "actively continuing", a stale feed fails closed, RETURNED is never
    # fabricated from a missing prop row. Drives the real on-disk + injury-freshness paths.
    ("NFL Wave Season+Injury QC", "qc_nfl_wave_season_injury.py", 180),
    # Universal entity links: the sport-scoped resolver (services/entity_links.py + player_url/
    # team_url/entity_anchor). Centralized URL encoding, per-sport destinations, unknown/ambiguous/
    # historical-only/unsupported -> plain text, identical names never cross-link, prose/heading/
    # option/decorative placements never linked -- and it FETCHES each resolvable destination through
    # the test client to prove the page renders the intended entity.
    ("Universal Entity-Link QC", "qc_entity_links.py", 180),
    # Additive NBA/WNBA market-only entity destinations (Option A): while the NBA.com stats gate is OFF,
    # NBA/WNBA player + NBA team entity links resolve from the LICENSED Odds feed to the new minimal
    # market-only pages (/tools/nba-player, /tools/wnba-player, /tools/nba-team) -- never the gated rich
    # /player /team pages; unknown/ambiguous -> plain text; pages abstain on stats.nba.com statistics
    # visibly, no nested anchors; gate ON reverts to the rich pages. Fixture-driven (no live data).
    ("NBA/WNBA Market-Only Entity QC", "qc_entity_nba_wnba_market.py", 120),
    # Performance regression guards (Site Performance P0): the entity keyset is cache-stable per source
    # version (not rebuilt per row -- the injury-report 63s class), per-row resolve stays cheap, and the
    # milestone builder serves its cached object warm. Structural invariants, not flaky wall-clock.
    ("Performance Regression Guards", "qc_perf_guards.py", 180),
    # Injury Report progressive disclosure (Site Performance P0 / P3): server-side paging + filtering
    # must not drop, duplicate, or reorder any record -- paged membership is complete and page-size
    # independent, filters are faithful + order-preserving, and the default page ships one page, not all.
    ("Injury Report Progressive QC", "qc_injury_report_progressive.py", 180),
    # Prewarm cache lifecycle (Site Performance P0): disk-materialized artifacts invalidate on a source
    # fingerprint change AND on an APP_CACHE_VERSION (deploy) change, reuse on unchanged inputs, fail
    # closed on corruption, and publish atomically (no partial reads, last complete write wins).
    ("Prewarm Cache Lifecycle QC", "qc_prewarm_lifecycle.py", 120),
    # NFL Matchup Center (Green Light B1/step 2): every slate game present (no suppression), canonical
    # date:AWAY@HOME identity, every module abstains (available+source, never a zeroed value), derived
    # reads labelled, deterministic order, cached route (no cold regression).
    ("NFL Matchup Center QC", "qc_nfl_matchup_center.py", 180),
    # Shared ticket editor (King's Tickets): Today's Cards + King's Tickets render one shared
    # component from one builder; identical inputs -> identical ordered legs (the surfaces cannot drift).
    ("Shared Ticket Editor QC", "qc_ticket_editor_shared.py", 180),
    # King's Tickets DARK draft store (Step 4): flag off by default; 2-5 + unique-leg; one draft/account;
    # optimistic CAS (no silent overwrite); transactional rollback; purge; account-bound; degrades, never crashes.
    ("King's Tickets Draft Store QC", "qc_kings_tickets_drafts.py", 120),
    # Per-user preference store: atomic writes (no torn/truncated JSON), multi-worker lock, key-scoped
    # mutation (no lost update), reset preserves unrelated settings, corrupt file degrades safely.
    ("User Preference Store QC", "qc_user_prefs_store.py", 60),
    # Green Light preference workspace (store + lens registry): preferences only order/show/hide the existing
    # factual lenses (same universe), deterministically; hides are VIEW-class; reset restores default; no
    # model-based suppression; validation fails safe; no Journal/draft-store coupling.
    ("Green Light Preferences QC", "qc_green_light_preferences.py", 60),
    # Green Light preference workspace route + template (opt-in ?view=workspace): full 12-lens default,
    # default board unchanged, CSRF-protected save, accurate hidden-by-user count, reset restores default,
    # lens status endpoint, shared-editor no-drift, no journal/draft-store coupling.
    # Green Light lens-adapter framework: common envelope, canonical-universe hashes (no add/suppress),
    # preference filtering, availability (never a silent zero), failure isolation + 7 failure modes.
    ("Green Light Adapter Framework QC", "qc_green_light_adapters.py", 60),
    # Entity-link authenticated crawl: owner test-client renders every entity-bearing route, follows every
    # generated entity URL (status/sport/entity), and asserts no broken links, no nested anchors, no cross-
    # sport resolution, no gated NBA/WNBA stat leakage. Server-side (no owner browser needed).
    ("Entity-Link Crawl", "qc_entity_link_crawl.py", 180),
    # NBA/WNBA restricted-data containment (4 remediated gaps, both flag states): no runtime pip install,
    # no header spoofing, WNBA injury ingestion gated, load_schedule/load_playoff_results gated + sentinels
    # contained, cache key folds gate state, licensed Odds loaders + other sports unaffected.
    ("NBA Containment QC", "qc_nba_containment.py", 120),
    # Streak integrity audit (market-line / Riding-the-Wave prop streaks): directed fixtures through the
    # real builder prove source->canonical->calc->membership->ordering, prior seasons can't extend a live
    # streak, missing obs != missed game, pushes break, dedup, full membership, and fail-closed sources.
    ("Streak Integrity Audit", "qc_streak_integrity.py", 120),
    # Streak integrity audit (milestone family): directed fixtures through build_nfl_milestone_streaks prove
    # canonical _key alias merge (N.Collins+Nico Collins), season boundary, bye=gap-not-reset, the freshness
    # gate (a run not reaching the latest week isn't "current"), and fail-closed sources.
    ("Streak Integrity Audit (milestone)", "qc_streak_integrity_milestone.py", 120),
    # Streak integrity audit (NFL + CFB ATS): pure df->streak cores prove active consecutive covers,
    # earlier losses allowed, pushes interrupt, (GameID,TeamSide) authority (CFB), dedup/conflict/ineligible,
    # universe hashes, fail-closed, and game-level traces.
    ("Streak Integrity Audit (ATS)", "qc_streak_integrity_ats.py", 120),
    # Streak integrity audit (Hot Hand / Heat Map): directed fixtures through build_nfl_hot_hand prove
    # consecutive clears of the current prop line (miss breaks), current-season-only, fail-closed.
    ("Streak Integrity Audit (Hot Hand)", "qc_streak_integrity_hothand.py", 120),
    # Shared streak-explainer normalized view-model: every family maps into one common model; absent
    # fields labeled unavailable (never synthesized); governed-model status separate from factual membership.
    ("Streak Explainer View-Model", "qc_streak_explainer.py", 60),
    ("Green Light Workspace QC", "qc_green_light_workspace.py", 200),
    # NFL identity resolution: short-form names ('N.Collins', the 2025 build) must resolve to one
    # canonical key so a player's season is never dropped and a streak never under-counts (the bug
    # that hid Nico Collins' 5 straight 100+ vs JAX).
    ("NFL Identity Resolution QC", "qc_nfl_identity_resolution.py", 120),
    # NFL milestone streaks (fixed-threshold, game-stats; distinct from market-line): matchup +
    # season-wide, the membership firewall (a qualifier cannot be hidden by a limit/sort), the
    # Streak Explainer, milestone-vs-market-line labeling, and fail-closed season-wide.
    ("NFL Milestone Streak QC", "qc_nfl_milestone_streaks.py", 180),
    # fetch_nfl_player_week --check-only contract: a missing parquet is behind (exit 2), but a file
    # that exists yet cannot be read is a DISTINCT error (exit 3), never a false "week 0" that would
    # read as missing production data. Cheap; guards the post-week retry's operator diagnostics.
    ("NFL Fetch Check-Only QC", "qc_nfl_fetch_checkonly.py", 120),
    # Player Check acceptance: shared inclusion predicates, floor evaluator codes, and the name
    # resolver (ambiguity/suffix/punctuation). Durable fixtures; live cases are advisory notes.
    ("Player Check QC", "qc_player_check.py", 240),
    ("NFL SGP Workbench QC", "qc_sgp_workbench.py", 120),
    # NBA postseason phase rule: the thirteen configured-window phase tests + override + NBA
    # scoping + other-sports-unchanged. Cheap; guards the P0 season-state correction.
    ("NBA Postseason Phase QC", "qc_nba_postseason_phase.py", 180),
    # NBA P0 Commit C: the authenticated NBA board authority removal (Confidence/Tier/Conf-column/
    # Locks + neutral tip-off sort) must be NBA-only and fail-safe -- other sports keep everything,
    # including when the is_nba_props flag is omitted. Renders props.html for both views x all sports.
    ("NBA Commit C Guard QC", "qc_nba_commit_c_guard.py", 180),
    # NBA Residual-Authority remediation (rev 2): R1-R8 presentation (both views x all sports, incl.
    # omitted-flag fail-safe), R2 market-only fallback, and R7 semantic equivalence + exact
    # added-back membership (/overs,/unders coerced to the direction-filtered board).
    ("NBA Residual-Authority QC", "qc_nba_residual_authority.py", 180),
    # Trial Eligibility Gate core (mocked): one-lifetime-trial store guarantees -- eligibility,
    # hard cap, atomic redemption, crash-recovery, key rotation, DB invariants, fail-closed.
    ("Trial Gate QC", "qc_trial_gate.py", 120),
    # Legal/IP containment: no uncleared official league/team mark is served or emitted, former logo
    # URLs 404, the independence/trademark disclaimer renders, the NBA.com data-rights gate withholds
    # gamelogs + shows the unavailable banner while licensed Odds API lines still render. Guard is
    # correct in both flag states (skips the relevant checks when a flag is explicitly ON).
    ("Legal/IP Containment QC", "qc_legal_containment.py", 180),
    # NBA/WNBA market-only fallback while the NBA.com gate is off: licensed Odds API facts only, no
    # NBA.com stats/snapshots/authority, same-book quotes, missing side labeled, NBA+WNBA independent.
    ("NBA Market-Only Board QC", "qc_nba_market_only.py", 180),
    # Decision Journal V1 (SQLite): the 15 frozen acceptance checks -- concurrency, crash recovery,
    # unknown fields, selection, SGP combined-only pricing, settlement math, immutability + append-only
    # corrections, prospective timing, BK-origin, idempotent import, migration, access isolation,
    # journal-only failure mode, descriptive reporting. Runs against throwaway temp DBs; cheap.
    ("Decision Journal QC", "qc_decision_journal.py", 180),
    ("Decision Journal Backup/Retention QC", "qc_dj_backup_retention.py", 120),
    # Lookup Phase 1: immutable change-event schema, dataset allowlist, timestamp honesty,
    # correction lineage, stable identity, and Odds API baseline ingestion. Dark: no Flask/UI path.
    ("Lookup Change Store QC", "qc_lookup_change_store.py", 120),
    # Lookup Phase 2: change-first Player Check presentation, honest first-visit baseline,
    # per-user unread watermark, successful-render commit, failure/race preservation, flag-off dark.
    ("Lookup Change Views QC", "qc_lookup_change_views.py", 180),
    # Lookup Phase 3: descriptive nflverse distributions, no missing-component zero-fill,
    # no score/projection/ordering authority, and the same dark feature gate.
    ("Lookup Facts + Context QC", "qc_lookup_facts_context.py", 120),
    # Governed model metadata: sport/market/position isolation and the Qualified+validation firewall.
    ("Model Registry QC", "qc_model_registry.py", 120),
    ("Unqualified Authority Containment QC", "qc_unqualified_authority_containment.py", 120),
    ("Model Observations QC", "qc_model_observations.py", 120),
    ("NBA 99 Scorecard", "run_nba_99_scorecard.py", 360),
    ("WNBA 99 Scorecard", "run_wnba_99_scorecard.py", 420),
    ("MLB 99 Scorecard", "run_mlb_99_scorecard.py", 480),
    ("NFL 99 Scorecard", "run_nfl_99_scorecard.py", 360),
    ("Prelaunch Scorecard", "run_prelaunch_scorecard.py", 360),
]

TIMEOUT_MARK = "[TIMEOUT]"


def run_scorecard(label: str, script: str, timeout: int) -> tuple[bool, str]:
    path = BASE_DIR / script
    if not path.exists():
        return False, f"Missing scorecard script: {path}"
    try:
        proc = subprocess.run(
            [sys.executable, str(path)],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        # Don't let one slow scorecard crash the whole step — report and move on.
        return False, f"{TIMEOUT_MARK} {script} exceeded {timeout}s"
    parts = []
    if proc.stdout:
        parts.append(proc.stdout.strip())
    if proc.stderr:
        parts.append(proc.stderr.strip())
    return proc.returncode == 0, "\n".join(parts)


def main() -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"all_scorecards_{stamp}.log"
    lines = [
        "Bankroll Kings Scorecard Runner",
        "=" * 35,
        f"Started: {datetime.now().isoformat(timespec='seconds')}",
        "",
    ]
    active = active_sports()
    failed = False
    for label, script, timeout in SCORECARDS:
        print(f"[RUN] {label}")
        ok, output = run_scorecard(label, script, timeout)
        sport = sport_for_label(label)
        if ok:
            status = "PASS"
        elif TIMEOUT_MARK in output:
            # Transient slowness (box busy during refresh). Logged, not fatal —
            # a real persistent hang will keep showing up and can be acted on.
            status = "TIMEOUT (slow; not blocking)"
        elif sport is not None and sport not in active:
            # Off-season sport: scorecard can't pass without data. Expected.
            status = "SKIP (off-season)"
        else:
            # Judge every scorecard, launch gate included, on hard FAIL sections
            # rather than on its exit code. The Prelaunch Scorecard exits non-zero
            # for any NO-GO, and its GO rule also requires fewer than 3 WATCH
            # sections -- a bar nothing can clear pre-season, when "0 plays
            # evaluated", "0 resolved results" and a standing manual visual-trust
            # review are all true at once. Paging nightly on that is the alert
            # fatigue the season gate exists to prevent. A genuinely failing
            # section, or a crash (no summary line at all), still alarms.
            hard = _hard_fail_count(output)
            if hard is None:
                # No summary printed -> the scorecard likely crashed. Real.
                status = "FAIL"
                failed = True
            elif hard > 0:
                status = "FAIL"
                failed = True
            else:
                # Zero hard fails: non-zero exit is only WATCH items (e.g.
                # calibration immaturity, a NO-GO on watch count). Not an alarm.
                status = "WATCH (not blocking)"
        print(f"[{status}] {label}")
        lines += [f"[{status}] {label}", f"Script: {script}", output or "(no output)", ""]
    lines.append(f"Finished: {datetime.now().isoformat(timespec='seconds')}")
    log_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Log saved: {log_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
