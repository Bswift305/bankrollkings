"""QC: shared CFBD client scaffolding (services/cfbd_client.py + services/cfbd_latch.py).

Synthetic and offline: every case uses a fake transport and a temp runtime dir. NO network, NO CFBD call,
the real urllib transport is never invoked (a guard transport fails the run if it is). Exits 0 on pass,
1 on any failure. Prints one [ok]/[FAIL] line per check.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services import cfbd_client as cc
from services import cfbd_latch as cl

FAKE_KEY = "qc-FAKE-cfbd-key-7f3a9e0c1b2d"
RESULTS: list[tuple[bool, str]] = []


def check(cond: bool, msg: str) -> None:
    RESULTS.append((bool(cond), msg))
    print(f"[{'ok' if cond else 'FAIL'}] {msg}")


class FakeTransport:
    """Scripted responses; counts every call; records the headers it was given."""

    def __init__(self, script=None, default=(200, {}, b"[]")):
        self.script = list(script or [])
        self.default = default
        self.calls: list[str] = []
        self.auth_headers: list[str] = []

    def __call__(self, url, headers, timeout):
        self.calls.append(url)
        self.auth_headers.append(headers.get("Authorization", ""))
        item = self.script.pop(0) if self.script else self.default
        if isinstance(item, Exception):
            raise item
        status, hdrs, body = item
        return cc.TransportResponse(status, dict(hdrs), body)


class Clock:
    def __init__(self, t: datetime):
        self.t = t

    def __call__(self):
        return self.t


def _guard_real_transport(*_a, **_k):
    raise AssertionError("real urllib transport invoked in QC")


def make(tmp: Path, env: dict, transport, clock=None, run_id="qc-run"):
    full_env = {"CFBD_API_KEY": FAKE_KEY}
    full_env.update(env)
    return cc.CfbdClient(transport=transport, env=full_env, runtime_dir=tmp, run_id=run_id,
                         caller="qc_cfbd_client", clock=clock or Clock(T0))


T0 = datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc)
Q429 = (429, {}, b'{"message":"Monthly call quota exceeded"}')


def case(name):
    def deco(fn):
        def run():
            tmp = Path(tempfile.mkdtemp(prefix=f"qc_cfbd_{name}_"))
            try:
                fn(tmp)
            except Exception as exc:  # a crash is a failure, never a silent pass
                check(False, f"{name}: raised {type(exc).__name__}: {exc}")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        run.__name__ = name
        return run
    return deco


@case("ok200")
def t_ok(tmp):
    ft = FakeTransport([(200, {}, b'[{"id": 1}]')])
    c = make(tmp, {}, ft)
    r = c.get("/games", {"year": 2026, "seasonType": "regular"})
    rows = c.ledger.rows()
    check(r.outcome == cc.OK and r.data == [{"id": 1}], "200 -> OK with parsed data")
    check(len(ft.calls) == 1 and len(rows) == 1 and rows[0]["transport_call"] and rows[0]["http_status"] == 200,
          "200 counted once and ledgered (transport_call=true, http_status=200)")
    check(ft.auth_headers[0] == f"Bearer {FAKE_KEY}", "Authorization: Bearer header sent to the transport")
    check(set(rows[0]) >= {"ts", "run_id", "caller", "endpoint", "params", "http_status", "outcome"},
          "ledger row has ts/run_id/caller/endpoint/params/http_status/outcome")


@case("dedup")
def t_dedup(tmp):
    ft = FakeTransport([(200, {}, b'[{"line": 1}]')])
    c = make(tmp, {}, ft)
    res = [c.get("/lines", {"seasonType": "regular", "year": 2026} if i % 2 else {"year": 2026, "seasonType": "regular"},
                 caller=f"script{i}") for i in range(6)]
    rows = [r for r in c.ledger.rows() if r["kind"] == "call"]
    check(len(ft.calls) == 1, f"6 identical /lines calls (param order varied) -> 1 transport call (got {len(ft.calls)})")
    check(len(rows) == 6 and sum(1 for r in rows if r["memo"]) == 5 and sum(1 for r in rows if r["transport_call"]) == 1,
          "6 ledger rows: 1 transport + 5 marked memo=true")
    check(all(r.data == [{"line": 1}] for r in res), "memo hits serve the same data")
    check({r["caller"] for r in rows} == {f"script{i}" for i in range(6)}, "each memo row keeps its own caller")


@case("auth")
def t_auth(tmp):
    for code in (401, 403):
        sub = tmp / str(code)
        ft = FakeTransport([(code, {}, b"Unauthorized")])
        c = make(sub, {"BK_CFBD_RESET_POLICY": "monthly_utc_first"}, ft)
        r = c.get("/games", {"year": 2026})
        check(r.outcome == cc.AUTH, f"{code} -> AUTH")
        check(not c.latch.exists() and c.latch.decide().mode == cl.OPEN, f"{code} does NOT latch")
        check(not any(x.get("kind") == "latch" for x in c.ledger.rows()), f"{code}: no latch event ledgered")
        c.get("/games", {"year": 2026})
        check(len(ft.calls) == 1, f"{code}: repeat call served from memo, no retry storm")


@case("quota_configured")
def t_quota_cfg(tmp):
    ft = FakeTransport([Q429])
    c = make(tmp, {"BK_CFBD_RESET_POLICY": "monthly_utc_first"}, ft)
    r = c.get("/games", {"year": 2026})
    st = c.latch.read()
    check(r.outcome == cc.QUOTA, "429 -> QUOTA")
    check(st.get("exhausted") and st.get("reset_at") == "2026-12-01T00:00:00+00:00"
          and st.get("reset_source") == "policy:monthly_utc_first",
          f"latched with reset from configured policy ({st.get('reset_at')}, {st.get('reset_source')})")
    check(st.get("detected_at") == T0.isoformat(), "detected_at recorded")
    ev = [x for x in c.ledger.rows() if x.get("kind") == "latch"]
    check(len(ev) == 1 and ev[0]["event"] == "LATCHED", "LATCHED event ledgered")
    r2 = c.get("/teams", {"year": 2026})
    check(r2.outcome == cc.BLOCKED_LATCH and len(ft.calls) == 1, "next request BLOCKED with zero transport calls")

    # explicit instant wins over policy
    sub = tmp / "explicit"
    ft2 = FakeTransport([Q429])
    c2 = make(sub, {"BK_CFBD_RESET_AT": "2026-11-15T06:00:00+00:00",
                    "BK_CFBD_RESET_POLICY": "monthly_utc_first"}, ft2)
    c2.get("/games", {"year": 2026})
    st2 = c2.latch.read()
    check(st2.get("reset_at") == "2026-11-15T06:00:00+00:00" and st2.get("reset_source") == "configured_at",
          "explicit BK_CFBD_RESET_AT is used when configured and in the future")


@case("quota_unconfigured")
def t_quota_uncfg(tmp):
    clock = Clock(T0)
    ft = FakeTransport([Q429, Q429, (200, {}, b"[]")])
    c = make(tmp, {}, ft, clock)
    c.get("/games", {"year": 2026})
    st = c.latch.read()
    check(st.get("exhausted") and st.get("reset_at") is None and st.get("reset_source") == "unconfigured",
          "429 with no reset configured -> reset_at None, reset_source='unconfigured' (nothing invented)")
    check(st.get("probe_interval_hours") == 24.0, "unconfigured latch records the probe interval (default 24h)")
    clock.t = T0 + timedelta(hours=24) - timedelta(seconds=1)
    r = c.get("/teams", {"year": 2026})
    check(r.outcome == cc.BLOCKED_LATCH and len(ft.calls) == 1, "unconfigured: blocked until the probe interval")
    clock.t = T0 + timedelta(hours=24)
    r = c.get("/teams", {"year": 2026})
    check(len(ft.calls) == 2 and r.outcome == cc.QUOTA, "unconfigured: NOT indefinite -> exactly one probe after 24h")
    r = c.get("/venues")
    check(r.outcome == cc.BLOCKED_LATCH and len(ft.calls) == 2, "unconfigured: probe 429 re-latches (no 2nd probe)")
    st = c.latch.read()
    check(st.get("relatched") and st.get("reset_at") is None, "re-latch recorded, still unconfigured")
    clock.t = T0 + timedelta(hours=48)
    r = c.get("/venues")
    check(r.outcome == cc.OK and len(ft.calls) == 3 and not c.latch.exists(),
          "next interval: one probe -> 200 clears the latch")
    # a configured instant that is already in the past is stale -> treated as unconfigured, never 'open now'
    reset, src = cl.resolve_reset(T0, {"BK_CFBD_RESET_AT": "2026-11-01T00:00:00+00:00"})
    check(reset is None and src == "unconfigured", "stale BK_CFBD_RESET_AT (in the past) is not trusted")


@case("no_fabricated_headers")
def t_headers(tmp):
    ft = FakeTransport([(200, {"Content-Type": "application/json"}, b"[]"),
                        (200, {"X-CallLimit-Remaining": "512", "Content-Type": "x"}, b"[]")])
    c = make(tmp, {}, ft)
    r1 = c.get("/games", {"year": 2026})
    r2 = c.get("/teams")
    rows = [x for x in c.ledger.rows() if x["kind"] == "call"]
    check(r1.quota_headers == {} and "quota_headers" not in rows[0],
          "missing quota headers -> nothing recorded (no fabricated remaining/reset)")
    check(rows[1].get("quota_headers") == {"x-calllimit-remaining": "512"},
          "present quota header recorded verbatim, unrelated headers dropped")
    status = c.budget_status()
    check("remaining" not in json.dumps(status).lower(), "budget status never claims a provider 'remaining'")


@case("reset_rollover")
def t_rollover(tmp):
    clock = Clock(T0)
    ft = FakeTransport([Q429, Q429, (200, {}, b"[]")])
    c = make(tmp, {"BK_CFBD_RESET_POLICY": "monthly_utc_first"}, ft, clock)
    c.get("/games", {"year": 2026})
    boundary = datetime(2026, 12, 1, tzinfo=timezone.utc)
    clock.t = boundary - timedelta(seconds=1)
    r = c.get("/teams")
    check(r.outcome == cc.BLOCKED_LATCH and len(ft.calls) == 1, "1s before reset_at -> blocked, zero transport calls")
    clock.t = boundary
    r = c.get("/teams")
    r_again = c.get("/venues")
    check(len(ft.calls) == 2, f"at reset_at -> exactly one probe (transport calls {len(ft.calls)})")
    check(r.outcome == cc.QUOTA and r_again.outcome == cc.BLOCKED_LATCH,
          "probe 429 -> re-latched; following request blocked")
    st = c.latch.read()
    check(st.get("reset_at") == "2027-01-01T00:00:00+00:00" and st.get("relatched"),
          f"re-latched to the NEXT configured boundary ({st.get('reset_at')})")
    ev = [x["event"] for x in c.ledger.rows() if x.get("kind") == "latch"]
    check(ev == ["LATCHED", "PROBE_ATTEMPT", "RELATCHED"], f"latch events ledgered in order {ev}")
    clock.t = datetime(2027, 1, 1, tzinfo=timezone.utc)
    r = c.get("/teams")
    check(r.outcome == cc.OK and not c.latch.exists(), "next boundary probe 200 -> latch cleared")
    # single explicit instant that passes and the probe 429s -> not indefinite (falls to probe interval)
    sub = tmp / "explicit"
    clock2 = Clock(T0)
    ft2 = FakeTransport([Q429, Q429])
    c2 = make(sub, {"BK_CFBD_RESET_AT": "2026-11-11T00:00:00+00:00"}, ft2, clock2)
    c2.get("/games")
    clock2.t = datetime(2026, 11, 11, tzinfo=timezone.utc)
    c2.get("/games")
    d = c2.latch.decide(datetime(2026, 11, 12, 0, 0, 1, tzinfo=timezone.utc))
    check(c2.latch.read().get("reset_source") == "unconfigured" and d.mode == cl.PROBE,
          "explicit instant passed + probe 429 -> unconfigured probe-interval mode, not a permanent lock")


@case("reserve")
def t_reserve(tmp):
    # allowance 20, reserve 25% -> deferrable limit 15
    env = {"BK_CFBD_MONTHLY_ALLOWANCE": "20", "BK_CFBD_RESERVE_PCT": "25"}
    ft = FakeTransport()
    c = make(tmp, env, ft)
    for i in range(15):
        c.get("/games", {"week": i}, request_class=cc.DEFERRABLE)
    check(len(ft.calls) == 15, "deferrable allowed below allowance-reserve")
    r = c.get("/games", {"week": 99}, request_class=cc.DEFERRABLE)
    check(r.outcome == cc.REFUSED_BUDGET and len(ft.calls) == 15, "deferrable refused at allowance-reserve (15/20)")
    check(c.budget_status()["state"] == "RESERVE_ONLY", "guard reports RESERVE_ONLY")
    for i in range(4):
        c.get("/teams", {"i": i}, request_class=cc.ESSENTIAL)
    r = c.get("/conferences", request_class=cc.PROBE)
    check(r.outcome == cc.OK and len(ft.calls) == 20, "essential + probe still allowed inside the reserve up to allowance")
    r1 = c.get("/teams", {"i": 99}, request_class=cc.ESSENTIAL)
    r2 = c.get("/conferences", {"x": 1}, request_class=cc.PROBE)
    check(r1.outcome == cc.REFUSED_BUDGET and r2.outcome == cc.REFUSED_BUDGET and len(ft.calls) == 20,
          "at allowance -> essential and probe refused too (EXHAUSTED)")
    # prior-month rows do not count toward this month
    sub = tmp / "month"
    c3 = make(sub, env, FakeTransport(), Clock(datetime(2026, 10, 31, 23, 0, tzinfo=timezone.utc)))
    for i in range(20):
        c3.get("/games", {"w": i})
    c3.clock = Clock(datetime(2026, 11, 1, 0, 0, 1, tzinfo=timezone.utc))
    check(c3.budget_status()["month_to_date"] == 0, "month-to-date resets at the window start")


@case("unconfigured_allowance")
def t_unconfigured(tmp):
    ft = FakeTransport()
    c = make(tmp, {}, ft)
    for i in range(30):
        c.get("/games", {"w": i}, request_class=cc.DEFERRABLE)
    s = c.budget_status()
    check(s["state"] == "UNCONFIGURED" and s["allowance"] is None and s["deferrable_limit"] is None
          and s["reserve_calls"] is None, "allowance unset -> UNCONFIGURED, no invented allowance/limit/reserve")
    check(len(ft.calls) == 30 and s["month_to_date"] == 30, "no limit enforced, usage still counted (30)")
    check(s["window_basis"] == "calendar_month_utc_assumed", "window basis labelled as assumed when no reset policy")
    for bad in ("", "0", "-5", "abc"):
        cfg = cc.budget_config({"BK_CFBD_MONTHLY_ALLOWANCE": bad})
        if cfg["allowance"] is not None:
            check(False, f"invalid allowance {bad!r} was accepted")
            return
    check(True, "invalid/empty allowance values never become a limit")


@case("reconcile")
def t_reconcile(tmp):
    clock = Clock(T0)
    ft = FakeTransport([(200, {}, b"[]"), (500, {}, b""), (404, {}, b""), Q429],
                       default=(200, {}, b"[]"))
    c = make(tmp, {"BK_CFBD_RESET_POLICY": "monthly_utc_first"}, ft, clock)
    outs = [c.get("/a").outcome, c.get("/a").outcome, c.get("/b").outcome, c.get("/c").outcome,
            c.get("/d").outcome, c.get("/e").outcome]
    check(outs == [cc.OK, cc.MEMO, cc.SERVER_ERROR, cc.CLIENT_ERROR, cc.QUOTA, cc.BLOCKED_LATCH],
          f"status classification 200/memo/5xx/4xx/429/blocked ({outs})")
    ft_net = FakeTransport([cc.TransportError("URLError")])
    c_net = make(tmp / "net", {}, ft_net)
    check(c_net.get("/x").outcome == cc.NETWORK_ERROR, "transport error -> NETWORK_ERROR, ledgered")
    rows = [x for x in c.ledger.rows() if x["kind"] == "call"]
    check(sum(1 for x in rows if x["transport_call"]) == len(ft.calls) == 4,
          f"ledger transport_call count == fake transport calls ({len(ft.calls)})")
    check(c.budget_status()["month_to_date"] == len(ft.calls), "month-to-date from ledger == transport calls")


@case("no_secret")
def t_secret(tmp):
    ft = FakeTransport([(200, {}, b"[]"), (401, {}, b"bad key"), Q429])
    c = make(tmp, {"BK_CFBD_FORCE": "1"}, ft)
    c.get("/games", {"year": 2026})
    c.get("/teams")
    c.get("/venues")
    latch_text = c.latch.path.read_text(encoding="utf-8")  # written by the 429
    c.get("/venues2")
    text = c.ledger.path.read_text(encoding="utf-8") + latch_text
    check(FAKE_KEY not in text and "Bearer" not in text, "ledger + latch files never contain the key or Bearer")
    check(FAKE_KEY not in repr(c), "client repr does not expose the key")
    try:
        c.get("/games", {"api_key": "x"})
        check(False, "credential-like param accepted")
    except ValueError:
        check(True, "credential-like params refused (key never goes in params/ledger)")
    nokey = cc.CfbdClient(transport=ft, env={}, runtime_dir=tmp / "nk", run_id="r", clock=Clock(T0))
    n_before = len(ft.calls)
    check(nokey.get("/games").outcome == cc.NO_KEY and len(ft.calls) == n_before, "no key -> NO_KEY, no transport call")


@case("operator_overrides")
def t_overrides(tmp):
    clock = Clock(T0)
    ft = FakeTransport([Q429], default=(200, {}, b"[]"))
    c = make(tmp, {"BK_CFBD_RESET_POLICY": "monthly_utc_first"}, ft, clock)
    c.get("/games")
    # force override in a new run
    cf = make(tmp, {"BK_CFBD_RESET_POLICY": "monthly_utc_first", "BK_CFBD_FORCE": "1"}, ft, clock, run_id="r2")
    r = cf.get("/teams")
    ev = [x["event"] for x in cf.ledger.rows() if x.get("kind") == "latch"]
    check(r.outcome == cc.OK and "FORCE_OVERRIDE" in ev and ev[-1] == "CLEARED",
          f"BK_CFBD_FORCE bypasses latch, ledgered FORCE_OVERRIDE then CLEARED ({ev})")
    # delete-the-file override is detected and ledgered
    ft2 = FakeTransport([Q429], default=(200, {}, b"[]"))
    c2 = make(tmp / "del", {"BK_CFBD_RESET_POLICY": "monthly_utc_first"}, ft2, clock)
    c2.get("/games")
    c2.latch.path.unlink()
    c3 = make(tmp / "del", {"BK_CFBD_RESET_POLICY": "monthly_utc_first"}, ft2, clock, run_id="r3")
    r = c3.get("/teams")
    ev = [x["event"] for x in c3.ledger.rows() if x.get("kind") == "latch"]
    check(r.outcome == cc.OK and ev[-1] == "LATCH_FILE_REMOVED", f"deleted latch file -> request proceeds, ledgered ({ev})")


@case("legacy_untouched")
def t_legacy(tmp):
    check(cl.LATCH_FILENAME != "cfbd_quota_state.json",
          "scaffold latch uses its own file (legacy cfbd_quota_state.json untouched)")
    import refresh_cfb_data as r
    src = Path(r.__file__).read_text(encoding="utf-8")
    check("cfbd_client" not in src and "cfbd_latch" not in src, "refresh_cfb_data does not import the scaffold")


def main() -> int:
    orig = cc.urllib_transport
    cc.urllib_transport = _guard_real_transport  # any accidental default-transport use fails loudly
    try:
        for fn in (t_ok, t_dedup, t_auth, t_quota_cfg, t_quota_uncfg, t_headers, t_rollover, t_reserve,
                   t_unconfigured, t_reconcile, t_secret, t_overrides, t_legacy):
            fn()
    finally:
        cc.urllib_transport = orig
    fails = [m for ok, m in RESULTS if not ok]
    print("=" * 60)
    print(f"CFBD CLIENT QC: {len(RESULTS) - len(fails)} ok, {len(fails)} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
