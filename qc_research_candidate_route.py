"""QC: Research Candidate 2D1 observation-only dark route + boundary (LOCAL ONLY).

Proves the owner-only, flag-gated dark capture route and its dependency-free boundary:
  * OFF (default) in a FRESH interpreter -> importing app pulls in NO research-candidate store/adapter/
    boundary, and hitting the route (even with a valid CSRF token) 404s and STILL imports nothing;
  * ON: owner-only (is_admin alone -> 404); unauthorized -> 404 (dark); CSRF enforced; input/size limits;
    server-derived observer id; success records; exact retry no-ops; changed intent -> 409; a governed
    adapter abstention -> 422; a misconfigured (out-of-root) DB path -> calm 503.

Temp artifacts only; no production enablement, deployment, UI, or schema change. The ON tests set the flag
+ paths BEFORE importing app (the flag is read at import); the OFF zero-import proof runs in a subprocess.
"""
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

fails = []


def check(cond, msg):
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        fails.append(msg)


UTC = timezone.utc
NOW = datetime.now(UTC)
FUTURE = (NOW + timedelta(days=30)).isoformat()
SU_OK = (NOW - timedelta(hours=1)).isoformat()

# current NFL season from the SAME pure contract the adapter/store use
from services.nfl_season_contract import expected_completed_week   # noqa: E402
from services.timeutils import DISPLAY_TZ                          # noqa: E402
_week, SEASON = expected_completed_week(NOW.astimezone(DISPLAY_TZ).date() if DISPLAY_TZ else NOW.date())

# One persistent temp workspace for the whole run (approved root + artifacts).
TD = tempfile.mkdtemp(prefix="rc2d1_")
ROOT = os.path.realpath(TD)
DB = os.path.join(ROOT, "store.db")
PROPS = os.path.join(ROOT, "NFL_Props.csv")
ROSTER = os.path.join(ROOT, "roster.parquet")


def _write_artifacts():
    pd.DataFrame([("Josh Allen", "evt1", FUTURE, SU_OK)],
                 columns=["Player", "EventId", "EventCommenceAtUTC", "SourceUpdatedAtUTC"]).to_csv(PROPS, index=False)
    ts = NOW.timestamp() - 3600.0
    os.utime(PROPS, (ts, ts))
    pd.DataFrame([("00-001", "Josh Allen", SEASON)],
                 columns=["player_id", "player_display_name", "season"]).to_parquet(ROSTER)


OWNER = {"user_id": "owner-uuid-0001", "email": "nobody@example.test", "role": "owner"}
ADMIN_NOT_OWNER = {"user_id": "admin-uuid", "email": "admin@example.test", "role": "member", "is_admin": "1"}


def _body(**over):
    b = {"player_ref": "Josh Allen", "event_id": "evt1", "thesis": "usage may rise",
         "sources": ["https://x/bio"], "acted": False, "idempotency_key": "K"}
    b.update(over)
    return b


def _post(client, body, csrf="tok", user=OWNER):
    import app as appmod
    appmod.get_current_user = lambda: user
    headers = {}
    if csrf is not None:
        headers["X-CSRFToken"] = csrf
    return client.post("/research-candidate/observe", data=json.dumps(body),
                       content_type="application/json", headers=headers)


# =========================================================================== OFF: zero import + 404 (subprocess)
def test_off_zero_import_and_404():
    print("\n[A] OFF (fresh interpreter): import app pulls in NO rc modules; the route 404s, still nothing")
    code = r"""
import os, sys, json
os.environ.pop('BK_RESEARCH_CANDIDATE_ENABLED', None)
os.environ.setdefault('SECRET_KEY', 'qc-off')
import app as a
MODS = ('services.research_candidate_store', 'services.nfl_identity_event_adapter',
        'services.research_candidate_boundary')
at_load = [m for m in MODS if m in sys.modules]
c = a.app.test_client()
with c.session_transaction() as s:
    s['_csrf_token'] = 't'
r = c.post('/research-candidate/observe', data=json.dumps({'player_ref':'x'}),
           content_type='application/json', headers={'X-CSRFToken': 't'})
after = [m for m in MODS if m in sys.modules]
print('RESULT', json.dumps({'at_load': at_load, 'status': r.status_code, 'after': after}))
"""
    env = dict(os.environ)
    env.pop("BK_RESEARCH_CANDIDATE_ENABLED", None)
    env.setdefault("SECRET_KEY", "qc-off")
    out = subprocess.run([sys.executable, "-c", code], cwd=HERE, env=env,
                         capture_output=True, text=True, timeout=300)
    line = next((ln for ln in out.stdout.splitlines() if ln.startswith("RESULT ")), None)
    if line is None:
        check(False, f"subprocess produced a RESULT line (stderr tail: {out.stderr[-400:]})")
        return
    data = json.loads(line[len("RESULT "):])
    check(data["at_load"] == [], "importing app with the flag OFF imports NO research-candidate module")
    check(data["status"] == 404, "the dark route 404s when OFF (even with a valid CSRF token)")
    check(data["after"] == [], "hitting the OFF route still imports no store/adapter/boundary")


# =========================================================================== ON: owner/CSRF/tiers
def _on_client():
    os.environ["BK_RESEARCH_CANDIDATE_ENABLED"] = "1"
    os.environ["BK_RESEARCH_CANDIDATE_ROOT"] = ROOT
    os.environ["BK_RESEARCH_CANDIDATE_DB_PATH"] = DB
    os.environ["BK_RESEARCH_CANDIDATE_PROPS"] = PROPS
    os.environ["BK_RESEARCH_CANDIDATE_ROSTER"] = ROSTER
    os.environ.setdefault("SECRET_KEY", "qc-on")
    import app as appmod
    appmod.RESEARCH_CANDIDATE_ENABLED = True   # ensure ON even if import order varied
    c = appmod.app.test_client()
    with c.session_transaction() as s:
        s["_csrf_token"] = "tok"
    return appmod, c


def test_on_success_idempotency_conflict():
    print("\n[B] ON: owner capture records; exact retry no-ops; changed intent conflicts")
    _write_artifacts()
    appmod, c = _on_client()
    r1 = _post(c, _body())
    check(r1.status_code == 200 and r1.get_json().get("status") == "recorded",
          f"owner success records (got {r1.status_code} {r1.get_json()})")
    rid = r1.get_json().get("id")
    r2 = _post(c, _body())
    check(r2.status_code == 200 and r2.get_json().get("status") == "noop" and r2.get_json().get("id") == rid,
          "an exact retry (same key + intent) no-ops to the same record")
    r3 = _post(c, _body(thesis="a different thesis"))
    check(r3.status_code == 409, "same key + different intent -> 409 conflict")


def test_on_authz_and_csrf():
    print("\n[C] ON: owner-only (is_admin alone -> 404), unauthorized -> 404, CSRF enforced, OFF flag -> 404")
    _write_artifacts()
    appmod, c = _on_client()
    r_admin = _post(c, _body(idempotency_key="K2"), user=ADMIN_NOT_OWNER)
    check(r_admin.status_code == 404, "an is_admin-only (non-owner) caller -> 404 (admin alone insufficient)")
    r_anon = _post(c, _body(idempotency_key="K3"), user=None)
    check(r_anon.status_code == 404, "an unauthenticated caller -> 404 (dark)")
    r_nocsrf = _post(c, _body(idempotency_key="K4"), csrf=None)
    check(r_nocsrf.status_code == 400, "a POST without a CSRF token -> 400 (global CSRF hook)")
    appmod.RESEARCH_CANDIDATE_ENABLED = False
    try:
        r_off = _post(c, _body(idempotency_key="K5"))
        check(r_off.status_code == 404, "flag OFF -> 404 even for an owner with a valid CSRF token")
    finally:
        appmod.RESEARCH_CANDIDATE_ENABLED = True


def test_on_input_and_abstain_tiers():
    print("\n[D] ON: input/size limits -> 422; a governed adapter abstention -> 422 with a reason code")
    _write_artifacts()
    appmod, c = _on_client()
    check(_post(c, _body(acted="true", idempotency_key="I1")).status_code == 422,
          "acted as a string (not bool) -> 422 (no coercion)")
    check(_post(c, _body(thesis="", idempotency_key="I2")).status_code == 422, "missing thesis -> 422")
    check(_post(c, _body(sources="http://x", idempotency_key="I3")).status_code == 422,
          "sources as a bare string -> 422")
    check(_post(c, _body(thesis="x" * 5000, idempotency_key="I4")).status_code == 422,
          "oversized thesis -> 422")
    r_ab = _post(c, _body(event_id="not-on-board", idempotency_key="I5"))
    jb = r_ab.get_json()
    check(r_ab.status_code == 422 and "EVENT_NOT_FOUND" in str(jb.get("reason", "")),
          "an off-board event -> 422 with the governed abstention reason (EVENT_NOT_FOUND)")
    r_mis = _post(c, _body(player_ref="Nobody Here", idempotency_key="I6"))
    check(r_mis.status_code == 422 and "PLAYER_EVENT_MISMATCH" in str(r_mis.get_json().get("reason", "")),
          "a valid event with an unpaired player -> 422 PLAYER_EVENT_MISMATCH")


def test_on_misconfig_503():
    print("\n[E] ON: a DB path outside the approved root fails closed as a calm 503")
    _write_artifacts()
    appmod, c = _on_client()
    outside = os.path.join(tempfile.mkdtemp(prefix="rc2d1_out_"), "escape.db")
    saved = os.environ.get("BK_RESEARCH_CANDIDATE_DB_PATH")
    os.environ["BK_RESEARCH_CANDIDATE_DB_PATH"] = outside
    try:
        r = _post(c, _body(idempotency_key="M1"))
        check(r.status_code == 503, "an out-of-root DB path -> 503 (containment fails closed)")
        check("escape" not in json.dumps(r.get_json()), "the 503 body is sanitized (no path leaked)")
    finally:
        os.environ["BK_RESEARCH_CANDIDATE_DB_PATH"] = saved


if __name__ == "__main__":
    print("=" * 80)
    print("RESEARCH CANDIDATE — 2D1 OBSERVATION ROUTE + BOUNDARY QC (dark, local)")
    print("=" * 80)
    for t in (test_off_zero_import_and_404, test_on_success_idempotency_conflict, test_on_authz_and_csrf,
              test_on_input_and_abstain_tiers, test_on_misconfig_503):
        t()
    print("\n" + "=" * 80)
    print("Clean:", not fails)
    if fails:
        print("FAILURES:")
        for f in fails:
            print("  -", f)
    sys.exit(1 if fails else 0)
