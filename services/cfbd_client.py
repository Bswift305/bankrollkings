"""Shared CFBD (api.collegefootballdata.com) client — design-stage scaffolding, NOT wired into any CFB script.

Why: docs/cfbd_budget_audit_2026-11-01.md (program/ledger) found ~43 CFBD calls per CFB refresh, the identical
/lines?year=2026&seasonType=regular fetched by 6 scripts, no shared client and no call ledger, so the monthly
quota could not be governed because it could not be counted. This module provides the pieces; rewiring the
fetchers onto it waits for the owner to confirm the account contract.

CONFIGURED vs UNKNOWN — nothing about the provider account is hard-coded:
  * Monthly allowance (~1,000 is INFERRED, unproven) -> only from BK_CFBD_MONTHLY_ALLOWANCE. Unset => the budget
    guard reports "UNCONFIGURED", enforces NO invented limit, and still ledgers every call.
  * Reserve -> BK_CFBD_RESERVE_PCT (default 15, our own operating policy from audit §5.3, not a provider fact).
    DEFERRABLE requests are refused once month-to-date usage >= allowance - reserve; ESSENTIAL and PROBE
    requests may use the reserve until the allowance itself; at the allowance everything is refused.
  * Reset boundary (00:00 UTC on the 1st is ASSUMED, unproven) -> only from BK_CFBD_RESET_AT /
    BK_CFBD_RESET_POLICY (see services/cfbd_latch.py for the latch contract and the unconfigured behaviour).
    The month-to-date window is the configured policy's month; if no policy is configured it falls back to the
    UTC calendar month and says so (window_basis="calendar_month_utc_assumed").
  * Quota/reset response headers -> recorded ONLY if the provider actually sends them; never fabricated.

Per run: identical endpoint + sorted params are fetched once and served from memory afterwards (OK and AUTH
results are memoized; a memo hit is ledgered with memo=true, transport_call=false).

Ledger: append-only JSONL <BK_RUNTIME_DIR or data/tracking>/cfbd_call_ledger.jsonl. Secret-free: the API key
travels only in the Authorization header of the real transport and is never written, printed or put in params.

Outcomes: OK (200) | AUTH (401/403, never latches) | QUOTA (429, latches) | CLIENT_ERROR (other 4xx) |
SERVER_ERROR (5xx) | NETWORK_ERROR | MEMO | BLOCKED_LATCH | REFUSED_BUDGET | NO_KEY.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from services import cfbd_latch as latch_mod

CFBD_BASE_URL = "https://api.collegefootballdata.com"
LEDGER_FILENAME = "cfbd_call_ledger.jsonl"
DEFAULT_RESERVE_PCT = 15.0

ESSENTIAL = "ESSENTIAL"
DEFERRABLE = "DEFERRABLE"
PROBE = "PROBE"
REQUEST_CLASSES = (ESSENTIAL, DEFERRABLE, PROBE)

OK, AUTH, QUOTA = "OK", "AUTH", "QUOTA"
CLIENT_ERROR, SERVER_ERROR, NETWORK_ERROR = "CLIENT_ERROR", "SERVER_ERROR", "NETWORK_ERROR"
MEMO, BLOCKED_LATCH, REFUSED_BUDGET, NO_KEY = "MEMO", "BLOCKED_LATCH", "REFUSED_BUDGET", "NO_KEY"

# Response headers that MAY carry quota/reset information. Captured verbatim only when present.
_QUOTA_HEADER_PREFIXES = ("x-calllimit", "x-ratelimit", "ratelimit", "x-quota", "x-rate-limit")
_QUOTA_HEADER_NAMES = ("retry-after",)
_SECRET_PARAM_HINTS = ("key", "token", "secret", "auth", "password")


def classify_status(status: Optional[int]) -> str:
    if status is None:
        return NETWORK_ERROR
    if status == 200:
        return OK
    if status in (401, 403):
        return AUTH
    if status == 429:
        return QUOTA
    if 400 <= status < 500:
        return CLIENT_ERROR
    if status >= 500:
        return SERVER_ERROR
    return CLIENT_ERROR  # 1xx/2xx-other/3xx: not a usable CFBD answer


def extract_quota_headers(headers: Optional[Mapping[str, str]]) -> dict:
    out = {}
    for k, v in (headers or {}).items():
        lk = str(k).lower()
        if lk in _QUOTA_HEADER_NAMES or any(lk.startswith(p) for p in _QUOTA_HEADER_PREFIXES):
            out[lk] = str(v)
    return out


def _clean_params(params: Optional[Mapping[str, Any]]) -> dict:
    clean = {}
    for k, v in (params or {}).items():
        if v is None:
            continue
        if any(h in str(k).lower() for h in _SECRET_PARAM_HINTS):
            raise ValueError(f"refusing CFBD param {k!r}: credentials belong in the Authorization header")
        clean[str(k)] = str(v)
    return dict(sorted(clean.items()))


def memo_key(endpoint: str, params: Optional[Mapping[str, Any]]) -> str:
    ep = "/" + str(endpoint).strip().lstrip("/")
    return ep + "?" + urllib.parse.urlencode(_clean_params(params))


# ---- transport ---------------------------------------------------------------------------------------
@dataclass
class TransportResponse:
    status: int
    headers: dict = field(default_factory=dict)
    body: bytes = b""


class TransportError(Exception):
    """Network-level failure (no HTTP status). Message must never contain the key."""


Transport = Callable[[str, Mapping[str, str], float], TransportResponse]


def urllib_transport(url: str, headers: Mapping[str, str], timeout: float) -> TransportResponse:
    """Real transport. The only place the Authorization header is used; nothing here logs it."""
    req = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed https host)
            return TransportResponse(resp.status, dict(resp.headers.items()), resp.read())
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read()
        except Exception:
            body = b""
        return TransportResponse(exc.code, dict(exc.headers.items()) if exc.headers else {}, body)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise TransportError(type(exc).__name__) from None


# ---- results -----------------------------------------------------------------------------------------
@dataclass
class CfbdResult:
    outcome: str
    endpoint: str
    params: dict
    http_status: Optional[int] = None
    data: Any = None
    quota_headers: dict = field(default_factory=dict)
    memo: bool = False
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome == OK or (self.outcome == MEMO and self.data is not None)


# ---- ledger ------------------------------------------------------------------------------------------
class CallLedger:
    def __init__(self, path: Path):
        self.path = Path(path)

    def append(self, row: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")

    def rows(self) -> list[dict]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for ln in lines:
            try:
                out.append(json.loads(ln))
            except ValueError:
                continue  # a torn line never breaks accounting
        return out

    def transport_calls_since(self, start: datetime) -> int:
        n = 0
        for r in self.rows():
            if r.get("kind") != "call" or not r.get("transport_call"):
                continue
            ts = latch_mod._parse(r.get("ts"))
            if ts is not None and ts >= start:
                n += 1
        return n

    def last_latch_event(self) -> Optional[dict]:
        for r in reversed(self.rows()):
            if r.get("kind") == "latch":
                return r
        return None


# ---- budget guard ------------------------------------------------------------------------------------
def _month_window_start(now: datetime, env: Mapping[str, str]) -> tuple[datetime, str]:
    now = latch_mod._utc(now)
    policy = (env.get("BK_CFBD_RESET_POLICY") or "").strip().lower()
    start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    if policy == "monthly_utc_first":
        return start, "policy:monthly_utc_first"
    return start, "calendar_month_utc_assumed"


def budget_config(env: Mapping[str, str]) -> dict:
    raw = (env.get("BK_CFBD_MONTHLY_ALLOWANCE") or "").strip()
    allowance = None
    if raw:
        try:
            allowance = int(raw)
        except ValueError:
            allowance = None
        if allowance is not None and allowance <= 0:
            allowance = None
    rraw = (env.get("BK_CFBD_RESERVE_PCT") or "").strip()
    reserve_source = "configured" if rraw else "default"
    try:
        reserve_pct = float(rraw) if rraw else DEFAULT_RESERVE_PCT
    except ValueError:
        reserve_pct, reserve_source = DEFAULT_RESERVE_PCT, "default"
    reserve_pct = min(max(reserve_pct, 0.0), 100.0)
    return {"allowance": allowance, "reserve_pct": reserve_pct, "reserve_source": reserve_source}


def budget_status(ledger: CallLedger, now: datetime, env: Mapping[str, str]) -> dict:
    cfg = budget_config(env)
    start, basis = _month_window_start(now, env)
    used = ledger.transport_calls_since(start)
    st = {"month_to_date": used, "window_start": start.isoformat(), "window_basis": basis,
          "reserve_pct": cfg["reserve_pct"], "reserve_source": cfg["reserve_source"]}
    if cfg["allowance"] is None:
        st.update(state="UNCONFIGURED", allowance=None, reserve_calls=None, deferrable_limit=None,
                  note="BK_CFBD_MONTHLY_ALLOWANCE unset: no limit enforced, usage still ledgered")
        return st
    allowance = cfg["allowance"]
    reserve = int(round(allowance * cfg["reserve_pct"] / 100.0))
    limit = allowance - reserve
    state = "OK" if used < limit else ("RESERVE_ONLY" if used < allowance else "EXHAUSTED")
    st.update(state=state, allowance=allowance, reserve_calls=reserve, deferrable_limit=limit)
    return st


def budget_allows(status: dict, request_class: str) -> tuple[bool, str]:
    state = status["state"]
    if state == "UNCONFIGURED":
        return True, "allowance unconfigured: no limit enforced"
    if state == "EXHAUSTED":
        return False, f"month-to-date {status['month_to_date']} >= allowance {status['allowance']}"
    if state == "RESERVE_ONLY" and request_class == DEFERRABLE:
        return False, (f"month-to-date {status['month_to_date']} >= allowance-reserve "
                       f"{status['deferrable_limit']}: deferrable refused, reserve held for essential/probe")
    return True, state


# ---- client ------------------------------------------------------------------------------------------
class CfbdClient:
    def __init__(self, *, api_key: Optional[str] = None, transport: Optional[Transport] = None,
                 env: Optional[Mapping[str, str]] = None, runtime_dir: Optional[Path] = None,
                 run_id: Optional[str] = None, caller: str = "unknown",
                 clock: Optional[Callable[[], datetime]] = None, base_url: str = CFBD_BASE_URL,
                 timeout: float = 30.0):
        self.env = os.environ if env is None else env
        self._api_key = api_key if api_key is not None else (self.env.get("CFBD_API_KEY") or "").strip()
        self.transport = transport or urllib_transport
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        root = Path(runtime_dir) if runtime_dir else latch_mod.runtime_dir(self.env)
        self.ledger = CallLedger(root / LEDGER_FILENAME)
        self.latch = latch_mod.CfbdLatch(root / latch_mod.LATCH_FILENAME, env=self.env, clock=self.clock)
        self.run_id = run_id or self.env.get("BK_RUN_ID") or f"cfbd-{uuid.uuid4().hex[:12]}"
        self.caller = caller
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._memo: dict[str, CfbdResult] = {}
        self._force_ledgered = False
        self._checked_removed_latch = False

    def __repr__(self) -> str:  # never expose the key
        return f"<CfbdClient run_id={self.run_id} caller={self.caller}>"

    # -- ledger helpers
    def _now(self) -> datetime:
        return latch_mod._utc(self.clock())

    def _ledger_latch(self, event: str, **extra) -> None:
        row = {"ts": self._now().isoformat(), "run_id": self.run_id, "caller": self.caller,
               "kind": "latch", "event": event}
        row.update({k: v for k, v in extra.items() if v is not None})
        self.ledger.append(row)

    def _ledger_call(self, res: CfbdResult, caller: str, request_class: str, transport_call: bool,
                     latch_mode: str) -> None:
        row = {"ts": self._now().isoformat(), "run_id": self.run_id, "caller": caller, "kind": "call",
               "endpoint": res.endpoint, "params": res.params, "request_class": request_class,
               "transport_call": transport_call, "http_status": res.http_status, "outcome": res.outcome,
               "memo": res.memo, "latch_mode": latch_mode}
        if res.quota_headers:
            row["quota_headers"] = res.quota_headers
        if res.reason:
            row["reason"] = res.reason
        self.ledger.append(row)

    def _note_operator_overrides(self) -> None:
        if not self._checked_removed_latch:
            self._checked_removed_latch = True
            last = self.ledger.last_latch_event()
            if last and last.get("event") in ("LATCHED", "RELATCHED") and not self.latch.exists():
                self._ledger_latch("LATCH_FILE_REMOVED", note="operator cleared the latch by deleting the file")
        if latch_mod.force_enabled(self.env) and not self._force_ledgered and self.latch.read().get("exhausted"):
            self._force_ledgered = True
            self._ledger_latch("FORCE_OVERRIDE", note="BK_CFBD_FORCE set: latch bypassed")

    def budget_status(self) -> dict:
        return budget_status(self.ledger, self._now(), self.env)

    # -- main entry
    def get(self, endpoint: str, params: Optional[Mapping[str, Any]] = None, *,
            request_class: str = ESSENTIAL, caller: Optional[str] = None) -> CfbdResult:
        if request_class not in REQUEST_CLASSES:
            raise ValueError(f"unknown request_class {request_class!r}")
        caller = caller or self.caller
        clean = _clean_params(params)
        ep = "/" + str(endpoint).strip().lstrip("/")
        key = memo_key(ep, clean)

        if not self._api_key:
            res = CfbdResult(NO_KEY, ep, clean, reason="CFBD_API_KEY not set")
            self._ledger_call(res, caller, request_class, False, "n/a")
            return res

        if key in self._memo:
            src = self._memo[key]
            res = CfbdResult(MEMO, ep, clean, http_status=src.http_status, data=src.data, memo=True,
                             reason=f"memo of {src.outcome}")
            self._ledger_call(res, caller, request_class, False, "memo")
            return res

        self._note_operator_overrides()
        now = self._now()
        decision = self.latch.decide(now)
        if not decision.allowed:
            res = CfbdResult(BLOCKED_LATCH, ep, clean, reason=decision.reason)
            self._ledger_call(res, caller, request_class, False, decision.mode)
            return res
        effective_class = PROBE if decision.mode == latch_mod.PROBE else request_class

        status = budget_status(self.ledger, now, self.env)
        allowed, why = budget_allows(status, effective_class)
        if not allowed:
            res = CfbdResult(REFUSED_BUDGET, ep, clean, reason=why)
            self._ledger_call(res, caller, effective_class, False, decision.mode)
            return res

        was_probe = decision.mode == latch_mod.PROBE
        if was_probe:
            self.latch.record_probe_attempt(now)
            self._ledger_latch("PROBE_ATTEMPT", endpoint=ep)

        url = self.base_url + ep + (("?" + urllib.parse.urlencode(clean)) if clean else "")
        headers = {"Authorization": f"Bearer {self._api_key}", "Accept": "application/json"}
        try:
            resp = self.transport(url, headers, self.timeout)
        except TransportError as exc:
            res = CfbdResult(NETWORK_ERROR, ep, clean, reason=str(exc)[:120])
            self._ledger_call(res, caller, effective_class, True, decision.mode)
            return res

        outcome = classify_status(resp.status)
        res = CfbdResult(outcome, ep, clean, http_status=resp.status,
                         quota_headers=extract_quota_headers(resp.headers))
        if outcome == OK:
            try:
                res.data = json.loads(resp.body.decode("utf-8")) if resp.body else None
            except (ValueError, UnicodeDecodeError):
                res.outcome, res.reason = CLIENT_ERROR, "200 with unparseable JSON body"
        if res.outcome == OK and (was_probe or decision.mode == latch_mod.FORCED):
            self.latch.clear()
            self._ledger_latch("CLEARED", via=decision.mode)
        elif res.outcome == QUOTA:
            st = self.latch.on_quota(now, was_probe=was_probe, reason=f"HTTP 429 on {ep}")
            self._ledger_latch("RELATCHED" if was_probe else "LATCHED", reset_at=st.get("reset_at"),
                               reset_source=st.get("reset_source"))
        if res.outcome in (OK, AUTH):
            self._memo[key] = res
        self._ledger_call(res, caller, effective_class, True, decision.mode)
        return res
