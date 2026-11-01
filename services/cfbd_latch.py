"""CFBD quota latch contract (design-stage scaffolding — NOT wired into any CFB script yet).

What is KNOWN vs UNKNOWN (docs/cfbd_budget_audit_2026-11-01.md on program/ledger):
  * KNOWN: CFBD answers an exhausted monthly quota with HTTP 429 ("Monthly call quota exceeded").
  * UNKNOWN: the exact reset instant. "00:00 UTC on the 1st" is an ASSUMPTION the owner has not confirmed,
    so this module never uses it as a default. A reset boundary exists only when explicitly configured:
        BK_CFBD_RESET_AT       an explicit ISO-8601 instant (e.g. 2026-12-01T00:00:00+00:00)
        BK_CFBD_RESET_POLICY   "monthly_utc_first" -> next calendar-month 00:00 UTC after detection
    BK_CFBD_RESET_AT wins when both are set and it is still in the future at detection time.

The latch on QUOTA persists {exhausted, detected_at, reset_at, reset_source, ...}.

UNCONFIGURED RESET (reset_source == "unconfigured", reset_at == None) — the documented behaviour:
  Fail-closed but NOT indefinite. Ordinary traffic stays blocked; exactly ONE controlled probe is allowed per
  probe interval (BK_CFBD_PROBE_INTERVAL_HOURS, default 24h), anchored on the last probe (or detected_at).
  A probe 200 clears the latch; a probe 429 re-latches and restarts the interval. The 24h default is OUR
  operating cadence, not a provider fact: worst case ~31 probe calls/month, a bounded and visible cost, versus
  the legacy latch (refresh_cfb_data._cfbd_blocked) which blocks FOREVER when reset_at is absent.

CONFIGURED RESET: before reset_at -> no requests at all. At/after reset_at -> exactly one probe. Probe 429 ->
  re-latch to the next configured boundary (policy) — or, when only a single explicit instant was configured
  and it has now passed, fall back to the unconfigured probe-interval mode (never an indefinite lock).
  Any probe that ends without clearing or re-latching (AUTH, network error, 5xx) leaves the latch in place
  and the next probe waits one probe interval.

AUTH (401/403) NEVER latches — that is a key problem, not a quota problem.

Operator overrides (kept from the legacy latch): BK_CFBD_FORCE=1 bypasses the latch; deleting the state file
clears it. Both are ledgered by services.cfbd_client (FORCE_OVERRIDE / LATCH_FILE_REMOVED).

State file: <BK_RUNTIME_DIR or data/tracking>/cfbd_latch_state.json. DELIBERATELY a different file from the
legacy cfbd_quota_state.json so this scaffold cannot change refresh_cfb_data's current behaviour; unifying
the two is part of the wiring step after the account contract is confirmed.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
LATCH_FILENAME = "cfbd_latch_state.json"
DEFAULT_PROBE_INTERVAL_HOURS = 24.0
RESET_POLICIES = ("monthly_utc_first",)

# Latch decision modes
OPEN = "OPEN"          # not latched
BLOCKED = "BLOCKED"    # latched; no request may be made
PROBE = "PROBE"        # latched; exactly one probe request may be made now
FORCED = "FORCED"      # latched but operator override BK_CFBD_FORCE is set


def runtime_dir(env: Optional[Mapping[str, str]] = None) -> Path:
    env = os.environ if env is None else env
    root = env.get("BK_RUNTIME_DIR") or str(BASE_DIR / "data" / "tracking")
    return Path(root)


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _parse(ts) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return _utc(datetime.fromisoformat(str(ts)))
    except ValueError:
        return None


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return _utc(dt).isoformat() if dt else None


def force_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    env = os.environ if env is None else env
    return (env.get("BK_CFBD_FORCE", "") or "").strip().lower() in ("1", "true", "yes", "on")


def probe_interval(env: Optional[Mapping[str, str]] = None) -> timedelta:
    env = os.environ if env is None else env
    raw = (env.get("BK_CFBD_PROBE_INTERVAL_HOURS") or "").strip()
    try:
        hours = float(raw) if raw else DEFAULT_PROBE_INTERVAL_HOURS
    except ValueError:
        hours = DEFAULT_PROBE_INTERVAL_HOURS
    if hours <= 0:
        hours = DEFAULT_PROBE_INTERVAL_HOURS
    return timedelta(hours=hours)


def next_policy_boundary(policy: str, after: datetime) -> Optional[datetime]:
    """Next boundary STRICTLY after `after` for a configured policy; None for unknown policies."""
    after = _utc(after)
    if policy == "monthly_utc_first":
        y, m = (after.year + 1, 1) if after.month == 12 else (after.year, after.month + 1)
        return datetime(y, m, 1, tzinfo=timezone.utc)
    return None


def resolve_reset(now: datetime, env: Optional[Mapping[str, str]] = None) -> tuple[Optional[datetime], str]:
    """(reset_at, reset_source) from EXPLICIT configuration only. Never guesses a provider boundary."""
    env = os.environ if env is None else env
    now = _utc(now)
    explicit = _parse((env.get("BK_CFBD_RESET_AT") or "").strip())
    if explicit and explicit > now:
        return explicit, "configured_at"
    policy = (env.get("BK_CFBD_RESET_POLICY") or "").strip().lower()
    if policy in RESET_POLICIES:
        return next_policy_boundary(policy, now), f"policy:{policy}"
    if explicit:  # configured, but already in the past -> stale, cannot be trusted as the next boundary
        return None, "unconfigured"
    return None, "unconfigured"


@dataclass
class LatchDecision:
    mode: str
    reason: str
    next_probe_at: Optional[datetime] = None

    @property
    def allowed(self) -> bool:
        return self.mode in (OPEN, PROBE, FORCED)


class CfbdLatch:
    def __init__(self, path: Optional[Path] = None, env: Optional[Mapping[str, str]] = None,
                 clock: Optional[Callable[[], datetime]] = None):
        self.env = os.environ if env is None else env
        self.path = Path(path) if path else runtime_dir(self.env) / LATCH_FILENAME
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    # ---- persistence -------------------------------------------------------------------------------
    def read(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def exists(self) -> bool:
        return self.path.exists()

    def _write(self, state: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.path)

    def clear(self) -> None:
        try:
            self.path.unlink()
        except OSError:
            pass

    # ---- decision ----------------------------------------------------------------------------------
    def decide(self, now: Optional[datetime] = None) -> LatchDecision:
        now = _utc(now or self.clock())
        st = self.read()
        if not st.get("exhausted"):
            return LatchDecision(OPEN, "not latched")
        if force_enabled(self.env):
            return LatchDecision(FORCED, "BK_CFBD_FORCE operator override")
        interval = probe_interval(self.env)
        reset_at = _parse(st.get("reset_at"))
        last_probe = _parse(st.get("last_probe_at"))
        detected = _parse(st.get("detected_at")) or now
        if reset_at is not None:
            if now < reset_at:
                return LatchDecision(BLOCKED, f"quota latched until {_iso(reset_at)} ({st.get('reset_source')})",
                                     next_probe_at=reset_at)
            if last_probe is None or last_probe < reset_at:
                return LatchDecision(PROBE, "reset boundary reached: one probe allowed", next_probe_at=reset_at)
            nxt = last_probe + interval
        else:
            nxt = (last_probe or detected) + interval
        if now >= nxt:
            return LatchDecision(PROBE, f"probe interval elapsed ({st.get('reset_source')}): one probe allowed",
                                 next_probe_at=nxt)
        return LatchDecision(BLOCKED, f"quota latched ({st.get('reset_source')}); next probe at {_iso(nxt)}",
                             next_probe_at=nxt)

    # ---- transitions -------------------------------------------------------------------------------
    def record_probe_attempt(self, now: Optional[datetime] = None) -> dict:
        """Persist the probe BEFORE it is sent, so a second caller in the same window is BLOCKED."""
        now = _utc(now or self.clock())
        st = self.read()
        st["last_probe_at"] = _iso(now)
        st["probe_count"] = int(st.get("probe_count") or 0) + 1
        self._write(st)
        return st

    def on_quota(self, now: Optional[datetime] = None, *, was_probe: bool = False, reason: str = "") -> dict:
        """Latch (or re-latch after a failed probe). reset_at comes ONLY from explicit config."""
        now = _utc(now or self.clock())
        prev = self.read()
        reset_at, source = resolve_reset(now, self.env)
        st = {
            "exhausted": True,
            "provider": "cfbd",
            "detected_at": _iso(now),
            "reset_at": _iso(reset_at),
            "reset_source": source,
            "reason": reason or "HTTP 429 quota",
            "first_detected_at": prev.get("first_detected_at") or prev.get("detected_at") or _iso(now),
            "probe_count": int(prev.get("probe_count") or 0),
            "relatched": bool(was_probe and prev.get("exhausted")),
        }
        if was_probe:
            st["last_probe_at"] = prev.get("last_probe_at") or _iso(now)
        if source == "unconfigured":
            st["probe_interval_hours"] = probe_interval(self.env).total_seconds() / 3600.0
        self._write(st)
        return st
