"""Per-request quota accounting for The Odds API (incident 2026-10-23 recovery).

Every paid fetch must self-account: capture the usage headers each response carries and print a receipt
with the per-provider quota and the TOTAL fetch cost. The Odds API returns, on every response:
  x-requests-last       credits THAT request cost
  x-requests-used       cumulative account usage
  x-requests-remaining  credits left
Total fetch cost = sum of x-requests-last across the responses. If the provider omits the headers on a
paid call, the cost receipt FAILS (we never guess the cost).

Never logs the URL, key, Authorization, or any response identifier. Pure stdlib.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

# Append-only ledger of EVERY paid call's cumulative usage headers, across all fetch subprocesses. This
# is what makes true reconciliation possible (incident 2026-10-24 #4): the account's cumulative
# x-requests-used / -remaining advance by the real cost even when x-requests-last is absent or 0 (as it
# was for the NBA probe), so reconciliation works off cumulative DELTAS, never the per-request sum.
LEDGER_REL = "data/tracking/odds_quota_ledger.jsonl"

# Per-OPERATION attribution (NBA v5 credit precision, 2026-11). A caller that needs the exact cost of ONE
# operation (services/nba_market.ensure_stage) passes an unguessable token to its fetch child in this env var;
# write_ledger stamps it on every row that child appends ("attribution_id", additive field). The caller then
# sums x-requests-last over ITS token's rows only -- never a positional slice or a global before/after delta
# that another writer (a manual fetch, the other caller, a future process) could inflate. Only a 32-char
# lowercase hex token (uuid4().hex) is accepted; anything else is ignored (row written without the field).
ATTRIBUTION_ENV = "BK_ODDS_ATTRIBUTION_ID"


def current_attribution_id():
    """The validated attribution token from the environment, or None."""
    raw = os.environ.get(ATTRIBUTION_ENV, "")
    tok = str(raw).strip()
    if len(tok) == 32 and all(ch in "0123456789abcdef" for ch in tok):
        return tok
    return None


def odds_credit_cost(n_markets, n_regions, n_paid_calls=1):
    """The Odds API DOCUMENTED credit cost (https://the-odds-api.com/liveapi/guides/v4/#usage-quota-costs):
    each /v4/sports/{sport}/odds (bulk OR per-event) request costs (markets x regions) credits; /v4/sports
    and /events are FREE. Total = n_paid_calls x markets x regions.

    Use this to set --expected-cost from the provider's formula, NOT from observed consumption:
      game lines (h2h,spreads,totals x us, one bulk call) -> 3x1x1 = 3
      props      (per event, e.g. 1 market x us x N events) -> 1x1xN
      futures    (outrights x us, one call per sport)       -> 1x1x1
    """
    return int(max(0, int(n_markets)) * max(0, int(n_regions)) * max(0, int(n_paid_calls)))


def _to_int(v):
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return None


class QuotaRecorder:
    """Accumulates usage headers across the responses of one fetch."""

    def __init__(self):
        self.calls = []            # [{last, used, remaining}]
        self.paid_without_headers = 0

    def record(self, headers, paid=True):
        """Record one response's usage headers. `headers` is any case-insensitive mapping. A paid call
        with NO usage headers is counted as a cost-accounting failure."""
        low = {}
        try:
            items = headers.items()
        except AttributeError:
            items = []
        for k, v in items:
            low[str(k).lower()] = v
        last = _to_int(low.get("x-requests-last"))
        used = _to_int(low.get("x-requests-used"))
        remaining = _to_int(low.get("x-requests-remaining"))
        if paid and last is None and used is None and remaining is None:
            self.paid_without_headers += 1
        self.calls.append({"last": last, "used": used, "remaining": remaining})

    @property
    def total_cost(self):
        costs = [c["last"] for c in self.calls if c["last"] is not None]
        return sum(costs) if costs else None

    @property
    def final_used(self):
        for c in reversed(self.calls):
            if c["used"] is not None:
                return c["used"]
        return None

    @property
    def final_remaining(self):
        for c in reversed(self.calls):
            if c["remaining"] is not None:
                return c["remaining"]
        return None

    def receipt(self, endpoint_family, sport, markets=None, expected_cost=None):
        """Return (ok, dict). ok=False when a paid response lacked usage headers (cost unprovable) or the
        actual cost exceeded expected_cost. Contains NO secrets, URLs, or response ids."""
        ok = True
        reasons = []
        if self.paid_without_headers:
            ok = False
            reasons.append(f"{self.paid_without_headers} paid response(s) returned NO usage headers "
                           "-- cost cannot be proven (failing the receipt rather than guessing)")
        cost = self.total_cost
        if expected_cost is not None and cost is not None and cost > expected_cost:
            ok = False
            reasons.append(f"actual cost {cost} exceeds documented expected {expected_cost}")
        return ok, {
            "endpoint_family": endpoint_family,
            "sport": sport,
            "markets": list(markets) if markets else [],
            "responses": len(self.calls),
            "x_requests_last_sum": cost,
            "x_requests_used": self.final_used,
            "x_requests_remaining": self.final_remaining,
            "expected_cost": expected_cost,
            "ok": ok,
            "reasons": reasons,
        }

    def write_ledger(self, endpoint_family, sport, base_dir, markets=None) -> int:
        """Append one JSONL line per recorded call (cumulative headers + attribution) to the shared
        ledger. Append-only and best-effort: a write failure never breaks a fetch. Returns the number
        of lines appended. Records NO url/key/response id. When ATTRIBUTION_ENV holds a valid token, each row
        also carries "attribution_id" (additive; readers that do not know the field are unaffected)."""
        path = Path(base_dir) / LEDGER_REL
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        mk = ",".join(markets) if markets else ""
        token = current_attribution_id()
        lines = []
        for seq, c in enumerate(self.calls):
            row = {
                "ts": now,
                "sport": sport,
                "endpoint_family": endpoint_family,
                "markets": mk,
                "seq": seq,
                "last": c["last"],
                "used": c["used"],
                "remaining": c["remaining"],
            }
            if token:
                row["attribution_id"] = token
            lines.append(json.dumps(row) + "\n")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # The batch is joined and handed to ONE write() on an append-mode handle, which narrows the window
            # in which a concurrent writer could interleave with it (attribution does not depend on order).
            with path.open("a", encoding="utf-8") as fh:
                fh.write("".join(lines))
            return len(self.calls)
        except OSError:
            return 0

    def print_receipt(self, endpoint_family, sport, markets=None, expected_cost=None, status="HTTP 200",
                      ledger_base_dir=None):
        ok, r = self.receipt(endpoint_family, sport, markets, expected_cost)
        if ledger_base_dir is not None:
            self.write_ledger(endpoint_family, sport, ledger_base_dir, markets=markets)
        print("---- QUOTA RECEIPT ----")
        print(f"  provider       : The Odds API")
        print(f"  endpoint family: {r['endpoint_family']}")
        print(f"  sport          : {r['sport']}")
        print(f"  markets        : {', '.join(r['markets']) or '(default)'}")
        print(f"  http status    : {status}")
        print(f"  responses      : {r['responses']}")
        print(f"  x-requests-last (sum = fetch cost): {r['x_requests_last_sum']}")
        print(f"  x-requests-used                   : {r['x_requests_used']}")
        print(f"  x-requests-remaining              : {r['x_requests_remaining']}")
        if r["expected_cost"] is not None:
            print(f"  expected cost  : {r['expected_cost']}")
        # A failed fetch must never print "OK" (2026-11): the cost line then says the accounting held, not
        # that anything succeeded.
        label = 'FAILED' if not ok else ('OK' if str(status).startswith('HTTP 2') else
                                         'ACCOUNTED (fetch failed -- not a success)')
        print(f"  COST RECEIPT   : {label}")
        for reason in r["reasons"]:
            print(f"    - {reason}")
        return ok, r
