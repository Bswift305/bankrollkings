"""QC: NBA market credit attribution is OPERATION-SCOPED (v5 credit-precision fix, 2026-11).

services/nba_market.ensure_stage gives each stage run an unguessable token (uuid4().hex) passed to its child
ONLY via BK_ODDS_ATTRIBUTION_ID; services/odds_quota.write_ledger stamps it as `attribution_id` on each quota
ledger row; _ledger_credits sums x-requests-last over THAT token's rows only. This QC proves:

  (1) write_ledger stamps a valid token; no env / malformed token -> row written WITHOUT the field (additive).
  (2) synthetic ledger: unrelated sports, untokened NBA rows, NBA rows with ANOTHER token, before/after/among
      this stage's rows -> credits == exactly this token's x-requests-last sum (not the sport-only sum).
  (3) an attributed row missing x-requests-last (or a non-int) -> x_requests_last_sum None, UNAVAILABLE.
  (4) zero attributed rows -> 0 with explicit NO_ATTRIBUTED_ENTRIES status; pre-existing untokened rows ignored.
  (5) remaining quota is a SEPARATE account-global snapshot (scope ACCOUNT_GLOBAL, labelled not-this-cost),
      from this operation's own last attributed row, never added to the credits; no ambiguous top-level
      `x_requests_remaining` key survives in `credits`.
  (6) REAL concurrency through ensure_stage: a stub stage child (real subprocess) writes its attributed rows
      in batches and waits (handshake) until foreign rows have landed between its batches, while a THREAD
      appends untokened NBA + other-sport rows and a separate PROCESS appends NBA rows via write_ledger under
      a DIFFERENT token -> reported credits == exactly the child's rows; foreign rows provably interleaved.
  (7) ledger rotation/truncation DURING the stage cannot shift attribution (no positional slice).
  (8) the parent's environment is never modified; a stale token in the parent env is overridden for the child.
  (9) props_not_attempted() credits use the same schema (account snapshot separate, NOT_RUN).
Offline: temp base_dir only, no network, no provider, no real data file touched. Exit 0 on pass, 1 otherwise.
"""
from __future__ import annotations

import sys as _qc_sys  # noqa: E402
from pathlib import Path as _QcPath  # noqa: E402
_qc_sys.path.insert(0, str(_QcPath(__file__).resolve().parent))  # noqa: E402
from services.qc_runtime import isolate_runtime as _isolate_runtime  # noqa: E402
_isolate_runtime()  # per-run temp BK_RUNTIME_DIR: a QC never resolves the production runtime

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

FAILS: list[str] = []
NOTES: list[str] = []
LEDGER_REL = Path("data") / "tracking" / "odds_quota_ledger.jsonl"
NBA = "basketball_nba"


def check(cond, msg):
    (NOTES if cond else FAILS).append(msg)


def _ledger(base) -> Path:
    return Path(base) / LEDGER_REL


def _append_raw(base, rows):
    p = _ledger(base)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write("".join(json.dumps(r) + "\n" for r in rows))


def _read_rows(base):
    out = []
    try:
        for line in _ledger(base).read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                out.append({"_corrupt": line})
    except OSError:
        pass
    return out


def _row(sport, last, remaining, token=None):
    r = {"ts": "2026-11-04T00:00:00+00:00", "sport": sport, "endpoint_family": "qc", "markets": "",
         "seq": 0, "last": last, "used": None, "remaining": remaining}
    if token:
        r["attribution_id"] = token
    return r


# ------------------------------------------------------------------------------------------------ children
def stub_stage_child(argv) -> int:
    """A stage child: writes attributed rows via the REAL write_ledger (token from its env), in batches, and
    after each batch waits until >= 2 NEW foreign rows land (proves interleaving). Optional mode 'truncate'
    rewrites the ledger first (rotation). Optional 'missing' makes the second batch's response headerless."""
    base, lasts, mode = Path(argv[0]), [int(x) for x in argv[1].split(",")], argv[2]
    from services.odds_quota import QuotaRecorder, current_attribution_id
    token = current_attribution_id()
    if not token:
        print("stub child: no attribution token in env", flush=True)
        return 9
    if mode == "truncate":
        p = _ledger(base)
        p.write_text(json.dumps(_row("americanfootball_nfl", 1, 500)) + "\n", encoding="utf-8")   # rotated
    remaining = 90000
    for i, last in enumerate(lasts):
        q = QuotaRecorder()
        if mode == "missing" and i == 1:
            q.record({"x-requests-remaining": remaining})            # paid response lacking x-requests-last
        else:
            remaining -= last
            q.record({"x-requests-last": last, "x-requests-used": 100000 - remaining,
                      "x-requests-remaining": remaining})
        q.write_ledger("player_props per-event", NBA, base, markets=["player_points"])
        if i < len(lasts) - 1:
            foreign0 = sum(1 for r in _read_rows(base) if r.get("attribution_id") != token)
            deadline = time.monotonic() + 30
            while sum(1 for r in _read_rows(base) if r.get("attribution_id") != token) < foreign0 + 2:
                if time.monotonic() > deadline:
                    print("stub child: no foreign rows arrived (handshake timeout)", flush=True)
                    return 8
                time.sleep(0.02)
    return 0


def other_writer_child(argv) -> int:
    """Another NBA writer (e.g. a manual fetch_player_props run / the other caller) appending through the
    REAL write_ledger under ITS OWN token (from env) until the stop file exists."""
    from services.odds_quota import QuotaRecorder
    base, stop = Path(argv[0]), Path(argv[1])
    n = 0
    while not stop.exists() and n < 2000:
        q = QuotaRecorder()
        q.record({"x-requests-last": 40, "x-requests-used": 1, "x-requests-remaining": 12345})
        q.write_ledger("player_props per-event", NBA, base, markets=["player_points"])
        n += 1
        time.sleep(0.03)
    return 0


# ------------------------------------------------------------------------------------------------ tests
def t_write_ledger_stamp(tmp):
    from services import odds_quota as oq
    base = Path(tmp) / "stamp"
    saved = os.environ.pop(oq.ATTRIBUTION_ENV, None)
    try:
        tok = "0123456789abcdef0123456789abcdef"
        cases = [(None, False), (tok, True), ("XYZ", False), (tok.upper(), False), (tok[:-1], False),
                 (tok + "0", False), ("", False)]
        for val, expect in cases:
            if val is None:
                os.environ.pop(oq.ATTRIBUTION_ENV, None)
            else:
                os.environ[oq.ATTRIBUTION_ENV] = val
            before = len(_read_rows(base))
            q = oq.QuotaRecorder()
            q.record({"x-requests-last": 2, "x-requests-used": 3, "x-requests-remaining": 4})
            n = q.write_ledger("qc", NBA, base)
            new = _read_rows(base)[before:]
            ok = n == 1 and len(new) == 1 and (("attribution_id" in new[0]) == expect)
            if expect:
                ok = ok and new[0].get("attribution_id") == tok
            check(ok, f"(1) write_ledger env={val!r}: attribution_id {'stamped' if expect else 'absent'}")
            check(all(k in new[0] for k in ("ts", "sport", "endpoint_family", "markets", "seq", "last", "used",
                                            "remaining")) if new else False,
                  f"(1) write_ledger env={val!r}: legacy fields unchanged (additive only)")
    finally:
        os.environ.pop(oq.ATTRIBUTION_ENV, None)
        if saved is not None:
            os.environ[oq.ATTRIBUTION_ENV] = saved


def t_synthetic(tmp):
    from services import nba_market as nm
    base = Path(tmp) / "synthetic"
    me, other = "a" * 32, "b" * 32
    _append_raw(base, [_row(NBA, 30, 99000), _row("baseball_mlb", 5, 98995), _row(NBA, 7, 98988, other)])
    _append_raw(base, [_row(NBA, 3, 98985, me)])
    _append_raw(base, [_row(NBA, 50, 98935), _row("americanfootball_nfl", 9, 98926)])
    _append_raw(base, [_row(NBA, 4, 98922, me), _row(NBA, 11, 98911, other)])
    p = _ledger(base)
    with p.open("a", encoding="utf-8") as fh:
        fh.write("not json at all\n")                                     # garbage without this token: ignored
        fh.write('{"sport": "basketball_nba", "last": 999, "attribution_id": "' + other + '"\n')  # other's torn
    _append_raw(base, [_row(NBA, 5, 98906, me), _row(NBA, 60, 98846)])
    c = nm._ledger_credits(base, me)
    sport_only = sum(r["last"] for r in _read_rows(base) if r.get("sport") == NBA and isinstance(r.get("last"), int))
    check(c["x_requests_last_sum"] == 12 and c["ledger_entries"] == 3 and c["status"] == "RECORDED",
          f"(2) interleaved foreign rows: credits == this token's 3+4+5=12 exactly (got {c['x_requests_last_sum']}, "
          f"sport-only sum would be {sport_only})")
    check(sport_only != 12, "(2) the sport-only (old) sum differs -- the fixture would have inflated the receipt")
    check(c.get("attribution_id") == me and c.get("attribution") == "per_operation_token"
          and c.get("sports") == [NBA], "(2) credits record the token + attribution method + sports")
    snap = c.get("account_remaining_snapshot") or {}
    check(snap.get("value") == 98906 and snap.get("scope") == "ACCOUNT_GLOBAL"
          and "NOT this operation's cost" in str(snap.get("label")),
          "(5) remaining = this operation's LAST attributed row, labelled account-global, not this cost")
    check("x_requests_remaining" not in c, "(5) no ambiguous top-level x_requests_remaining in credits")
    check(c["x_requests_last_sum"] != snap.get("value") and c["x_requests_last_sum"] == 12,
          "(5) remaining snapshot never added to/merged with the credit sum")
    o = nm._ledger_credits(base, other)
    check(o["x_requests_last_sum"] is None and o["status"].startswith("UNAVAILABLE") and o.get("torn_attributed_lines") == 1,
          "(3) a TORN ledger line carrying an operation's token makes that operation's sum UNAVAILABLE (never "
          "silently dropped from the sum)")
    # (3) missing / non-int header on an attributed row
    base3 = Path(tmp) / "missing"
    _append_raw(base3, [_row(NBA, 3, 100, me), _row(NBA, None, 97, me), _row(NBA, 2, 95, me)])
    c3 = nm._ledger_credits(base3, me)
    check(c3["x_requests_last_sum"] is None and c3["status"].startswith("UNAVAILABLE") and c3["ledger_entries"] == 3,
          "(3) attributed row without x-requests-last -> sum None, UNAVAILABLE (never guessed)")
    base3b = Path(tmp) / "nonint"
    _append_raw(base3b, [_row(NBA, 3, 100, me), _row(NBA, "4", 96, me)])
    _append_raw(base3b, [_row(NBA, True, 95, me)])
    c3b = nm._ledger_credits(base3b, me)
    check(c3b["x_requests_last_sum"] is None and c3b["status"].startswith("UNAVAILABLE"),
          "(3) string/bool x-requests-last -> UNAVAILABLE")
    # (4) zero attributed rows
    base4 = Path(tmp) / "none"
    _append_raw(base4, [_row(NBA, 30, 99000), _row(NBA, 7, 98988, other), _row("baseball_mlb", 5, 1)])
    c4 = nm._ledger_credits(base4, me)
    check(c4["x_requests_last_sum"] == 0 and c4["ledger_entries"] == 0
          and c4["status"].startswith("NO_ATTRIBUTED_ENTRIES")
          and (c4.get("account_remaining_snapshot") or {}).get("value") is None,
          "(4) zero attributed rows -> 0, NO_ATTRIBUTED_ENTRIES, no remaining snapshot borrowed from others")
    c4b = nm._ledger_credits(Path(tmp) / "absent", me)
    check(c4b["x_requests_last_sum"] == 0 and c4b["status"].startswith("NO_ATTRIBUTED_ENTRIES"),
          "(4) no ledger file -> 0, NO_ATTRIBUTED_ENTRIES")
    c4c = nm._ledger_credits(base4, None)
    check(c4c["ledger_entries"] == 0, "(4) a None token never matches untokened rows")
    # (9)
    pna = nm.props_not_attempted({"caller": "qc", "outcome": "VALIDATION_FAILED"})["credits"]
    check(pna["status"] == "NOT_RUN" and pna["x_requests_last_sum"] == 0 and "x_requests_remaining" not in pna
          and (pna.get("account_remaining_snapshot") or {}).get("scope") == "ACCOUNT_GLOBAL",
          "(9) props_not_attempted credits: same schema, NOT_RUN, account snapshot separate")


def _foreign_thread(base, stop: threading.Event, counter: list):
    i = 0
    while not stop.is_set() and i < 4000:
        sport = NBA if i % 2 == 0 else "baseball_mlb"
        from services.odds_quota import append_ledger_lines   # every real writer appends under the ledger lock
        append_ledger_lines(base, json.dumps(_row(sport, 25, 50000 - i)) + "\n")   # untokened writer
        counter[0] += 1
        i += 1
        time.sleep(0.015)


def _run_concurrent(tmp, name, lasts, mode, expect_sum, expect_status):
    from services import nba_market as nm
    from services.odds_quota import ATTRIBUTION_ENV
    base = Path(tmp) / name
    _append_raw(base, [_row(NBA, 77, 99999), _row(NBA, 6, 99993, "c" * 32)])   # pre-existing rows
    stop_file = Path(tmp) / f"{name}.stop"
    other_tok = "d" * 32
    env = dict(os.environ)
    env[ATTRIBUTION_ENV] = other_tok
    other = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--other-writer", str(base),
                              str(stop_file)], env=env, cwd=str(HERE))
    stop, counter = threading.Event(), [0]
    th = threading.Thread(target=_foreign_thread, args=(base, stop, counter), daemon=True)
    th.start()
    stale_parent = "e" * 32
    os.environ[ATTRIBUTION_ENV] = stale_parent        # (8) a stale token in the parent env must be overridden
    try:
        rec = nm.ensure_stage("lines", "qc_credit", base_dir=base, timeout=120,
                              command=[sys.executable, str(Path(__file__).resolve()), "--stub-child", str(base),
                                       ",".join(str(x) for x in lasts), mode])
    finally:
        parent_after = os.environ.get(ATTRIBUTION_ENV)
        os.environ.pop(ATTRIBUTION_ENV, None)
        stop.set()
        stop_file.write_text("stop", encoding="utf-8")
        th.join(10)
        try:
            other.wait(30)
        except subprocess.TimeoutExpired:
            other.kill()
    check(parent_after == stale_parent, f"(8) {name}: parent env untouched by ensure_stage")
    check(rec["exit_code"] == 0, f"(6) {name}: stub stage child exit 0 (handshake satisfied) -- got {rec['exit_code']}")
    cr = rec["credits"]
    tok = cr.get("attribution_id")
    rows = _read_rows(base)
    mine_idx = [i for i, r in enumerate(rows) if r.get("attribution_id") == tok]
    check(bool(tok) and tok not in (stale_parent, other_tok, "c" * 32) and len(tok) == 32,
          f"(8) {name}: the child ran under a fresh per-stage token, not the parent's stale one")
    check(not any(r.get("attribution_id") == stale_parent for r in rows),
          f"(8) {name}: no row carries the parent's stale token")
    check(len(mine_idx) == len(lasts), f"(6) {name}: child's {len(lasts)} attributed rows present "
                                       f"(found {len(mine_idx)})")
    between = [r for r in rows[mine_idx[0]:mine_idx[-1]] if r.get("attribution_id") != tok] if mine_idx else []
    nba_foreign = [r for r in between if r.get("sport") == NBA]
    check(len(nba_foreign) >= 2 and any(r.get("attribution_id") == other_tok for r in between)
          and any("attribution_id" not in r for r in between if r.get("sport") == NBA),
          f"(6) {name}: foreign NBA rows (untokened AND other-token) provably landed DURING the stage "
          f"({len(between)} foreign rows between this stage's rows)")
    check(not any("_corrupt" in r for r in rows), f"(6) {name}: no torn ledger line under concurrent append")
    check(cr["x_requests_last_sum"] == expect_sum and cr["status"].startswith(expect_status)
          and cr["ledger_entries"] == len(lasts),
          f"(6) {name}: credits == exactly this stage's rows ({expect_sum}, {expect_status}) -- got "
          f"{cr['x_requests_last_sum']} / {cr['status']}")
    foreign_nba_sum = sum(r["last"] for r in rows if r.get("sport") == NBA and r.get("attribution_id") != tok
                          and isinstance(r.get("last"), int))
    check(foreign_nba_sum > 0, f"(6) {name}: {foreign_nba_sum} foreign NBA credits were in the ledger and excluded")
    snap = cr.get("account_remaining_snapshot") or {}
    own_last = rows[mine_idx[-1]].get("remaining") if mine_idx else None
    check(snap.get("value") == own_last and snap.get("scope") == "ACCOUNT_GLOBAL",
          f"(5) {name}: remaining snapshot is from THIS operation's last row ({own_last}), not another writer's")
    return rec


def main(argv) -> int:
    if argv and argv[0] == "--stub-child":
        return stub_stage_child(argv[1:])
    if argv and argv[0] == "--other-writer":
        return other_writer_child(argv[1:])
    with tempfile.TemporaryDirectory(prefix="qc_nba_credit_") as tmp:
        t_write_ledger_stamp(tmp)
        t_synthetic(tmp)
        _run_concurrent(tmp, "interleave", [3, 3, 9, 1], "interleave", 16, "RECORDED")
        _run_concurrent(tmp, "truncate", [2, 5, 4], "truncate", 11, "RECORDED")
        _run_concurrent(tmp, "missing_hdr", [3, 3, 3], "missing", None, "UNAVAILABLE")
    for n in NOTES:
        print(f"  ok   {n}")
    for f in FAILS:
        print(f"  FAIL {f}")
    print(f"qc_nba_credit_attribution: {len(NOTES)} passed, {len(FAILS)} failed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
