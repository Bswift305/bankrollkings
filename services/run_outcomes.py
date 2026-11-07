"""
Bankroll Kings - per-sport refresh OUTCOME vocabulary + receipt-based classifier.
=================================================================================

Incident 2026-10-24 directives #2/#3: a parent refresh step must derive its result from its children's
actual outcomes, and a props child that fetched zero rows must be treated as VALIDATION_FAILED (an
alerting state) UNTIL a sanitized response-shape receipt proves every response lacked all requested
markets -- only then is it the benign NO_MARKETS_POSTED. Zero output rows, or zero reported cost, never
prove "no markets" by themselves.

The vocabulary (one honest state per child):
  UPDATED            artifact advanced with freshly fetched rows            benign
  NO_ACTIVE_EVENTS   the provider returned zero events in the fetch window   ALERTING (2026-11-04; frozen 2026-11-07)
  NO_MARKETS_POSTED  events exist, PROVEN no requested market on any event   benign
  VALIDATION_FAILED  rows failed validation / 0 rows not proven benign       ALERTING
  PROVIDER_ERROR     the provider errored on one or more events              ALERTING
  STALE              artifact did not advance and nothing benign explains it ALERTING
  SKIP               deliberately not run (season gate, missing key)         benign
  SKIPPED_BLOCKED_BY_LINES  not run: it needs fresh game lines and the lines
                     step failed this run (honest skip, never success)       ALERTING

Game-lines governance (2026-11, docs/game_lines_event_contract.md "Governed no-game result" and
"Single publisher + lock"):
  NO_GAMES_SCHEDULED a FRESH, AUTHORITATIVE, INDEPENDENT schedule affirmatively
                     says zero games for the governed Eastern service date;
                     decided BEFORE any paid call (zero credits)             benign
  SCHEDULE_UNAVAILABLE the provider returned zero events and no fresh
                     authoritative independent schedule can confirm a no-game
                     day (missing / stale / ambiguous / circular source):
                     fail closed, never an invented no-game result           ALERTING
  SKIPPED_LOCKED     another process holds the shared NBA game-lines publisher
                     lock; this run made no paid request and wrote nothing   ALERTING
  REUSED_FRESH       the other lines job published a receipt-verified lines
                     file inside the reuse window; reused, no paid request   benign
  REUSED_FRESH_AFTER_LOCK  this run WAITED for another holder of the lock,
                     then re-read the receipt + file hashes UNDER the lock and
                     found a valid publish inside the reuse window; reused,
                     no paid request (the collision is visible)               benign
  NO_FRESH_AFTER_LOCK  this run waited for another holder, re-read under the
                     lock, found NO valid fresh publish, and was told not to
                     fetch after contention: nothing published               ALERTING
  (The 90-min reuse window is duplicate-fetch suppression only; the executable
  boundary for customers stays the 6h CLOCK-A rule.)
  SKIPPED_OFF_SEASON a GOVERNED season calendar says the sport is outside   benign
                     its active window; decided BEFORE any provider call,
                     zero credits

OFF-SEASON / NO-GAME OWNER DECISION (2026-11-04, Safeguard A follow-up). An empty or failed fetch is NEVER an
off-season skip and never OK:
  * SKIPPED_OFF_SEASON only from a calendar listed in GOVERNED_SEASON_CALENDARS, decided before any provider
    call (the claim must carry provider_calls=0).
  * NO_GAMES_SCHEDULED only from a contract listed in GOVERNED_SCHEDULE_CONTRACTS.
  * UNCONFIGURED_SPORT is a hard failure.
  * Empty rows, a provider error, or any non-zero exit without one of those governed reasons is a FAILURE
    (degraded), never SKIP / OK. NO_ACTIVE_EVENTS (the provider listed zero events) is therefore ALERTING: a
    zero-event provider answer is not a schedule contract.
  * is_alerting fails closed: any outcome not explicitly BENIGN is alerting.
Governed claims are printed by the child as ONE line, e.g.
  OUTCOME: SKIPPED_OFF_SEASON calendar=<governed id> provider_calls=0
  OUTCOME: NO_GAMES_SCHEDULED contract=<governed id>
and are honoured ONLY with exit 0/1 (a claim never launders an exit >=2) and only when the id is governed.
An outcome in NEITHER set is unknown and is treated as alerting by is_alerting (fail closed).

Pure: stdlib only, no pandas, no app import -- safe to import from any refresh script.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

UPDATED = "UPDATED"
NO_ACTIVE_EVENTS = "NO_ACTIVE_EVENTS"
NO_MARKETS_POSTED = "NO_MARKETS_POSTED"
VALIDATION_FAILED = "VALIDATION_FAILED"
PROVIDER_ERROR = "PROVIDER_ERROR"
STALE = "STALE"
SKIP = "SKIP"
SKIPPED_BLOCKED_BY_LINES = "SKIPPED_BLOCKED_BY_LINES"
NO_GAMES_SCHEDULED = "NO_GAMES_SCHEDULED"
SCHEDULE_UNAVAILABLE = "SCHEDULE_UNAVAILABLE"
SKIPPED_LOCKED = "SKIPPED_LOCKED"
REUSED_FRESH = "REUSED_FRESH"
REUSED_FRESH_AFTER_LOCK = "REUSED_FRESH_AFTER_LOCK"
NO_FRESH_AFTER_LOCK = "NO_FRESH_AFTER_LOCK"
# Receipt-identity contract (2026-11-04): a governed NBA stage outcome comes ONLY from the stage's own per-run
# receipt (services/run_receipts). No receipt -> RUN_RECEIPT_MISSING; another run's token -> RUN_RECEIPT_MISMATCH.
RUN_RECEIPT_MISSING = "RUN_RECEIPT_MISSING"
RUN_RECEIPT_MISMATCH = "RUN_RECEIPT_MISMATCH"
# Frozen runner semantics (owner, 2026-11-07). Both are ALERTING, hard failures (exit >=2), never a skip:
#   CONFIG_MISSING  a required API key / config is absent: refused before any request (exit 2)
#   BLOCKED_QUOTA   a provider quota is exhausted; the latch prevents further calls but the step is a
#                   DEGRADED FAILURE, never converted into a skip or a pass
CONFIG_MISSING = "CONFIG_MISSING"
BLOCKED_QUOTA = "BLOCKED_QUOTA"

SKIPPED_OFF_SEASON = "SKIPPED_OFF_SEASON"

# NO_ACTIVE_EVENTS is ALERTING everywhere (Safeguard A + frozen semantics 2026-11-07): a zero-event provider
# answer is never a governed no-game / off-season result.
BENIGN = frozenset({UPDATED, NO_MARKETS_POSTED, SKIP, SKIPPED_OFF_SEASON, NO_GAMES_SCHEDULED, REUSED_FRESH,
                    REUSED_FRESH_AFTER_LOCK})
ALERTING = frozenset({VALIDATION_FAILED, PROVIDER_ERROR, STALE, NO_ACTIVE_EVENTS, SKIPPED_BLOCKED_BY_LINES,
                      SCHEDULE_UNAVAILABLE, SKIPPED_LOCKED, NO_FRESH_AFTER_LOCK, RUN_RECEIPT_MISSING,
                      RUN_RECEIPT_MISMATCH, CONFIG_MISSING, BLOCKED_QUOTA})

# Lines-step outcomes that mean "a verified, current lines file is in place" (dependents may run).
LINES_READY = frozenset({UPDATED, REUSED_FRESH, REUSED_FRESH_AFTER_LOCK})

# Game-lines receipt outcomes that can prove a benign NON-publish. Exit code alone can never prove one; a
# receipt written by THIS run must, AND (owner governed-only rule, 2026-11-04) the no-game claim must come
# from a GOVERNED schedule contract. NO_ACTIVE_EVENTS (the provider listed zero events) is deliberately
# absent: a zero-event provider answer is not a schedule contract, so for game lines it is a FAILURE.
# SCHEDULE_UNAVAILABLE is deliberately absent too.
BENIGN_LINES_NONPUBLISH = frozenset({NO_GAMES_SCHEDULED})

def governed_lines_nonpublish(receipt: dict | None) -> bool:
    """True only when a game-lines receipt claims a benign non-publish that is GOVERNED: outcome in
    BENIGN_LINES_NONPUBLISH and its `schedule_contract` id listed in GOVERNED_SCHEDULE_CONTRACTS. Never true
    for NO_ACTIVE_EVENTS; never true while no contract is governed."""
    if not isinstance(receipt, dict):
        return False
    return (receipt.get("outcome") in BENIGN_LINES_NONPUBLISH
            and str(receipt.get("schedule_contract") or "") in GOVERNED_SCHEDULE_CONTRACTS)


# ---- Governed benign non-publish sources (owner decision 2026-11-04) -------------------------------------
# A season calendar is GOVERNED only when it is listed here: it must decide "outside the active window" from
# the calendar alone, BEFORE any provider call. Today only the NFL PRESEASON window qualifies -- the daily
# operator season gate (season_utils.nfl_preseason_active, QC qc_daily_operator_season_gate.py), which skips
# the step without running it. There is NO governed MLB / WNBA / NBA / NCAAF / NFL-regular-season calendar:
# services/nfl_season_contract.NFL_SEASON_WEEK1_THURSDAY anchors Week-1 only (no season end / playoffs), so it
# cannot say "off-season". Those sports' empty fetches stay FAILURES until F2v2/F6 supply a governed contract.
GOVERNED_SEASON_CALENDARS: dict[str, str] = {
    "season_utils.nfl_preseason_active": "NFL preseason Odds key window (Jul 20 - Sep 12), operator pre-run gate",
}
# An authoritative schedule contract that can affirmatively say "no games" (game lines: the receipt's
# `schedule_contract`; runners: an `OUTCOME: NO_GAMES_SCHEDULED contract=<id>` claim). NONE is governed on
# this branch; a source is added only after owner review.
GOVERNED_SCHEDULE_CONTRACTS: dict[str, str] = {}

OUTCOME_PREFIX = "OUTCOME:"
# Statuses a RUNNER records for a step (run_daily / bk-linemove / chain runners).
STEP_PASS = "PASS"
STEP_FAIL = "FAIL"
# Failure reason codes (why a non-zero step is a FAILURE rather than a governed benign outcome).
REASON_HARD_FAILURE = "HARD_FAILURE"                  # exit >=2 / signal / timeout
REASON_NO_GOVERNED_REASON = "NO_GOVERNED_REASON"      # exit 1 (empty rows / provider error / validation) w/o claim
REASON_UNGOVERNED_CLAIM = "UNGOVERNED_CLAIM"          # a benign claim naming a calendar/contract nobody governs


def _claim_fields(line: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for tok in line.split()[1:]:
        if "=" in tok:
            k, v = tok.split("=", 1)
            out[k] = v
    return out


def governed_benign_claim(output: str | None) -> tuple[str | None, str]:
    """Scan child output for a governed benign claim. Returns (outcome, source) when a claim is GOVERNED,
    (None, REASON_UNGOVERNED_CLAIM + detail) when a benign claim is present but not governed, else (None, "")."""
    ungoverned = ""
    for raw in (output or "").splitlines():
        line = raw.strip()
        if not line.startswith(OUTCOME_PREFIX):
            continue
        body = line[len(OUTCOME_PREFIX):].strip()
        word = body.split()[0] if body.split() else ""
        fields = _claim_fields(body)
        if word == SKIPPED_OFF_SEASON:
            cal = fields.get("calendar", "")
            if cal in GOVERNED_SEASON_CALENDARS and fields.get("provider_calls") == "0":
                return SKIPPED_OFF_SEASON, f"calendar={cal}"
            ungoverned = f"{REASON_UNGOVERNED_CLAIM}: {SKIPPED_OFF_SEASON} calendar={cal or '(none)'} " \
                         f"provider_calls={fields.get('provider_calls', '(unproven)')}"
        elif word == NO_GAMES_SCHEDULED:
            con = fields.get("contract", "")
            if con in GOVERNED_SCHEDULE_CONTRACTS:
                return NO_GAMES_SCHEDULED, f"contract={con}"
            ungoverned = f"{REASON_UNGOVERNED_CLAIM}: {NO_GAMES_SCHEDULED} contract={con or '(none)'}"
    return None, ungoverned


def classify_step_exit(code: int, output: str | None) -> tuple[str, str]:
    """ONE classifier for every runner (run_daily, bk-linemove, chain runners): (status, reason).
      UNCONFIGURED_SPORT / CONFIG_MISSING / BLOCKED_QUOTA marker -> FAIL (hard failure, any exit code, any season)
      exit 0                               -> PASS
      exit 1 + GOVERNED benign claim       -> SKIPPED_OFF_SEASON / NO_GAMES_SCHEDULED (benign)
      exit 1 without one                   -> FAIL  (empty rows / provider error / validation / unclassified)
      exit >=2, negative (signal)          -> FAIL  (a benign claim never launders a hard failure)
    Never consults a props file, an artifact age, or the sport's "active" state."""
    text = output or ""
    typed = typed_hard_failure(text)   # UNCONFIGURED_SPORT / CONFIG_MISSING / BLOCKED_QUOTA: FAIL at any exit code
    if typed:
        return STEP_FAIL, typed
    if code == EXIT_OK:
        return STEP_PASS, ""
    if code == EXIT_NO_NEW_ROWS:
        outcome, source = governed_benign_claim(text)
        if outcome:
            return outcome, source
        return STEP_FAIL, source or REASON_NO_GOVERNED_REASON
    return STEP_FAIL, f"{REASON_HARD_FAILURE} (exit {code})"


def is_governed_benign_status(status: str) -> bool:
    return status in (SKIPPED_OFF_SEASON, NO_GAMES_SCHEDULED)

# A fetcher asked for a sport it has no declared paths for (services.fetch_sport_guard) refuses before any
# request or write, prints `OUTCOME: VALIDATION_FAILED reason_code=UNCONFIGURED_SPORT` and exits 2. That is
# a configuration error: ALERTING everywhere, never benign, never "no new rows", never off-season.
UNCONFIGURED_SPORT_REASON = "UNCONFIGURED_SPORT"
UNCONFIGURED_SPORT_MARKER = "reason_code=" + UNCONFIGURED_SPORT_REASON
EXIT_UNCONFIGURED_SPORT = 2

# Frozen 2026-11-07: a missing API key / config and an exhausted provider quota are typed HARD failures.
# Children print `OUTCOME: CONFIG_MISSING reason_code=CONFIG_MISSING ...` (exit 2) or
# `OUTCOME: BLOCKED_QUOTA reason_code=BLOCKED_QUOTA ...` (exit >=2). The legacy CFBD text
# PROVIDER_QUOTA_EXHAUSTED is read as BLOCKED_QUOTA too. Neither is ever a skip, a pass or a benign 1.
CONFIG_MISSING_MARKER = "reason_code=" + CONFIG_MISSING
BLOCKED_QUOTA_MARKER = "reason_code=" + BLOCKED_QUOTA
LEGACY_QUOTA_MARKER = "PROVIDER_QUOTA_EXHAUSTED"
EXIT_CONFIG_MISSING = 2


def is_exact_int(value, expected: int) -> bool:
    """Strict receipt integer check: an int (never a bool, float or numeric string) equal to `expected`.
    `True == 1` and `0.0 == 0` in Python, so a plain == would accept a malformed receipt."""
    return type(value) is int and value == expected


def typed_hard_failure(output: str | None) -> str | None:
    """The typed hard-failure reason carried by a child's output, if any (checked BEFORE the exit code, so it
    holds at any exit code and in any season): UNCONFIGURED_SPORT, CONFIG_MISSING or BLOCKED_QUOTA."""
    text = output or ""
    if UNCONFIGURED_SPORT_MARKER in text:
        return UNCONFIGURED_SPORT_REASON
    if CONFIG_MISSING_MARKER in text:
        return CONFIG_MISSING
    if BLOCKED_QUOTA_MARKER in text or LEGACY_QUOTA_MARKER in text:
        return BLOCKED_QUOTA
    return None

# Portable RUNNER exit semantics (owner decision, Safeguard A). Production units differ -- bk-linemove has
# SuccessExitStatus=1 -- so a runner must encode the verdict itself and the unit only propagates it:
#   0  success
#   1  ONLY the frozen benign "no new rows / last-known-good preserved" outcome -- and (2026-11-04) only
#      when that benign cause is GOVERNED (SKIPPED_OFF_SEASON / NO_GAMES_SCHEDULED, see above). A child's
#      exit 1 with no governed claim (empty rows, provider error, validation reject) is a hard failure.
#   >=2 hard failure / degraded (never mapped onto 0 or 1)
EXIT_OK = 0
EXIT_NO_NEW_ROWS = 1
EXIT_HARD_FAILURE = 2


def runner_exit_for_child(code: int, output: str | None = None) -> int:
    """Exit code for a runner stopping on a failed child. A child 1 stays 1 ONLY when the child's output
    carries a GOVERNED benign claim (classify_step_exit). Runners that stream their children uncaptured pass
    no output, so an unclassified child 1 becomes 2. Any other non-zero code (>=2, or a negative signal
    code such as earlyoom's SIGTERM) is a hard failure and stays >=2."""
    if code == EXIT_NO_NEW_ROWS:
        status, _ = classify_step_exit(code, output)
        return EXIT_NO_NEW_ROWS if is_governed_benign_status(status) else EXIT_HARD_FAILURE
    return code if code >= EXIT_HARD_FAILURE else EXIT_HARD_FAILURE


def is_alerting(outcome: str) -> bool:
    # Fail closed: only an outcome explicitly declared BENIGN is non-alerting (an unknown word is alerting).
    return outcome not in BENIGN


def load_shape_receipt(base_dir: Path, sport_slug: str) -> dict | None:
    """Read data/tracking/_last_props_fetch_<slug>.json written by fetch_player_props. None if absent
    or unreadable (treated conservatively by the classifier)."""
    path = Path(base_dir) / "data" / "tracking" / f"_last_props_fetch_{sport_slug.replace('/', '_')}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def classify_props_child(exit_code: int, artifact_advanced: bool, receipt: dict | None) -> tuple[str, str]:
    """Return (OUTCOME, one-line detail). The receipt carries FACTS (events_found, rows_fetched, whether
    any requested market was present, provider errors); exit_code + artifact_advanced say whether the
    child published. NO_MARKETS_POSTED requires the receipt to PROVE it; absent proof, zero rows is
    VALIDATION_FAILED (directive #2)."""
    if exit_code == EXIT_UNCONFIGURED_SPORT:
        # The child refused before fetching or writing anything, so any receipt on disk is from an EARLIER
        # run and proves nothing about this one (a stale events_found=0 would otherwise read as benign).
        return VALIDATION_FAILED, (f"child refused before fetching (exit {EXIT_UNCONFIGURED_SPORT}: "
                                   f"{UNCONFIGURED_SPORT_REASON} or {CONFIG_MISSING}); any shape receipt is from an "
                                   "earlier run")
    if receipt is None:
        # No evidence file. Do not invent a benign outcome.
        if exit_code == 0 and artifact_advanced:
            return UPDATED, "published new rows (no shape receipt present)"
        if exit_code == 0 and not artifact_advanced:
            return STALE, "child reported success but the artifact did not advance, and no receipt exists"
        return VALIDATION_FAILED, "child failed and no shape receipt exists to prove a benign cause"

    events = int(receipt.get("events_found") or 0)
    rows = int(receipt.get("rows_fetched") or 0)
    provider_errors = int(receipt.get("provider_error_count") or 0)
    proven_no_markets = bool(receipt.get("shape_proves_no_markets_posted"))
    present = receipt.get("markets_present_anywhere") or []

    if events == 0:
        # The provider listed zero events. That is EMPTY, not a governed no-game/off-season result
        # (owner decision 2026-11-04): NO_ACTIVE_EVENTS is ALERTING.
        return NO_ACTIVE_EVENTS, "provider listed zero events in the fetch window (not a governed no-game result)"
    if rows == 0 and provider_errors > 0:
        return PROVIDER_ERROR, f"{provider_errors} event(s) errored and zero rows were fetched"
    if rows > 0 and artifact_advanced:
        return UPDATED, f"{rows} rows fetched and published"
    if rows > 0 and not artifact_advanced:
        return VALIDATION_FAILED, (f"{rows} rows fetched but the artifact did not advance "
                                   "(validation/collapse preserved last-known-good)")
    # rows == 0, no provider errors
    if proven_no_markets:
        return NO_MARKETS_POSTED, f"{events} event(s) in window but no requested market posted on any (proven)"
    return VALIDATION_FAILED, (f"zero rows but requested markets WERE present ({', '.join(present) or 'see receipt'}) "
                               "-- not proven NO_MARKETS_POSTED; treat as validation/parse failure")


def _mtime(path) -> float:
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return 0.0


def props_step_outcome(base_dir, sport_slug: str, artifact_path, mtime_before: float,
                       exit_code: int, timed_out: bool) -> tuple[str, str, bool]:
    """Shared by every sport parent for its player-props child: classify from the shape receipt + whether
    the artifact advanced, so NBA / MLB / football all use the SAME vocabulary. Returns
    (outcome, detail, alerting)."""
    if timed_out:
        return PROVIDER_ERROR, "player-props fetch timed out", True
    advanced = _mtime(artifact_path) > mtime_before
    receipt = load_shape_receipt(base_dir, sport_slug)
    outcome, detail = classify_props_child(exit_code, advanced, receipt)
    return outcome, detail, is_alerting(outcome)


def record_child_outcomes(base_dir, parent: str, outcomes: dict[str, str]) -> None:
    """Write a structured per-parent child-outcome sidecar so the operator summary records the CHILD
    OUTCOME (the vocabulary) -- not merely the parent exit code (directive #3). Best-effort; one file per
    parent so parents never clobber each other."""
    path = Path(base_dir) / "data" / "tracking" / f"_child_outcomes_{parent}.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({
            "parent": parent,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "outcomes": outcomes,
            "degraded": any(is_alerting(o) for o in outcomes.values()),
        }, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def load_all_child_outcomes(base_dir) -> dict[str, dict]:
    """Merge every _child_outcomes_<parent>.json for the operator summary. Returns {parent: payload}."""
    out: dict[str, dict] = {}
    tracking = Path(base_dir) / "data" / "tracking"
    try:
        files = sorted(tracking.glob("_child_outcomes_*.json"))
    except OSError:
        return out
    for f in files:
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        parent = payload.get("parent") or f.stem.replace("_child_outcomes_", "")
        out[parent] = payload
    return out


def aggregate_parent(child_outcomes: dict[str, str]) -> tuple[str, bool]:
    """Aggregate children into a parent summary. Returns (summary, degraded). degraded is True when ANY
    child is alerting -- the parent must then NOT report a bare PASS. A parent with only benign children
    is clean (but still reports WHICH benign state each child reached)."""
    degraded = any(is_alerting(o) for o in child_outcomes.values())
    parts = ", ".join(f"{label}={outcome}" for label, outcome in child_outcomes.items())
    return parts, degraded
