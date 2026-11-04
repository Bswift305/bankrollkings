"""
QC (D11, 2026-11-04): Run Status must report the CURRENT operator run -- identified by an immutable run id
-- and never the previous run's result as current.

Prod evidence (11-03): the nested Run Status call at the end of the Edge Engine pipeline step ran while
the 11-03 operator log and summary did not exist yet, so it read 11-02's log (newest by mtime, 23.8h ->
FRESH) and 11-02's summary (football_props:ncaaf_player_props=VALIDATION_FAILED) as the current state.

Offline, temp tree, synthetic files, no network. Covers:
  1  exact 11-03 replay (run active, its log unwritten, yesterday's VALIDATION_FAILED summary, yesterday's
     log newest)                                   -> PENDING / IN PROGRESS, previous run separate
  2  same + today's child outcome UPDATED            -> interim only, not overridden, not final
  3  finished run, matching ids                      -> normal fold, current log by id (not by mtime)
  4  missing summary and/or missing log              -> PENDING / MISSING, never an older artifact
  5  killed run (deadline / process gone)            -> INCOMPLETE; persisted PENDING expires to INCOMPLETE
  6  two logs on the same UTC day                    -> identity by run id
  7  UTC-midnight and Eastern-midnight crossings     -> identity unaffected by dates/filenames
  8  stale child-outcome file (mlb_daily from 10-28) -> ignored for the current run
  9  every generate_run_status invocation site mid-run (nested Edge call + top-level run_daily step)
 10  marker writes atomic (failed replace keeps the old file; concurrent reader never sees a torn file)
 11  run id immutable across real child processes (env inheritance), sidecars + summary + marker agree
Then MUTATION checks: each key piece is reverted in-process and the suite must FAIL.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
os.environ.pop("BK_OPERATOR_RUN_ID", None)   # never inherit a real operator run's id

import generate_run_status as grs                      # noqa: E402
import run_bk_edge_engine_pipeline as edge             # noqa: E402
import run_daily                                       # noqa: E402
from services import operator_run                      # noqa: E402
from services import run_outcomes                      # noqa: E402

HOST = "qc-host"
UTC = timezone.utc
VF = "football_props:ncaaf_player_props=VALIDATION_FAILED"


def T(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)


# ------------------------------------------------------------------------------------------- tree
class Tree:
    """A temp base dir with every generate_run_status path redirected into it."""

    _ATTRS = ("BASE_DIR", "LOG_DIR", "TRACKING_DIR", "JSON_PATH", "CSV_PATH", "OPERATOR_SUMMARY_PATH",
              "OPERATOR_MARKER_PATH", "_PID_ALIVE", "_HOSTNAME")

    def __init__(self, alive=True):
        self.alive = alive

    def __enter__(self):
        self._td = tempfile.TemporaryDirectory()
        self.base = Path(self._td.name)
        self.logs = self.base / "logs"
        self.tracking = self.base / "data" / "tracking"
        self.logs.mkdir(parents=True)
        self.tracking.mkdir(parents=True)
        self._saved = {a: getattr(grs, a) for a in self._ATTRS}
        grs.BASE_DIR = self.base
        grs.LOG_DIR = self.logs
        grs.TRACKING_DIR = self.tracking
        grs.JSON_PATH = self.tracking / "Run_Status.json"
        grs.CSV_PATH = self.tracking / "Run_Status.csv"
        grs.OPERATOR_SUMMARY_PATH = self.tracking / "Last_Operator_Summary.json"
        grs.OPERATOR_MARKER_PATH = self.tracking / operator_run.MARKER_FILENAME
        grs._PID_ALIVE = lambda pid: self.alive
        grs._HOSTNAME = HOST
        return self

    def __exit__(self, *exc):
        for a, v in self._saved.items():
            setattr(grs, a, v)
        self._td.cleanup()
        return False

    # writers
    def marker(self, run_id, started, state="RUNNING", cap_h=8.0, host=HOST, pid=424242, finished=None):
        m = {"schema": operator_run.SCHEMA, "run_id": run_id, "state": state,
             "started_at": operator_run.utc_iso(started), "max_runtime_seconds": int(cap_h * 3600),
             "deadline_at": operator_run.utc_iso(started + timedelta(hours=cap_h)),
             "finished_at": operator_run.utc_iso(finished) if finished else None,
             "pid": pid, "host": host, "log": "", "sports": ["wnba"], "summary_written": None}
        operator_run.atomic_write_json(grs.OPERATOR_MARKER_PATH, m)
        return m

    def summary(self, run_id, started, finished, degraded=(), state=None, legacy=False):
        s = {"finished_at": (finished.isoformat(timespec="seconds") if legacy else operator_run.utc_iso(finished)),
             "log": "", "sports": ["wnba"], "blocking_failure": False, "failed_steps": [],
             "provider_exhausted_steps": [], "child_outcomes": {}, "degraded_child_outcomes": list(degraded),
             "steps": []}
        if not legacy:
            s.update({"run_id": run_id, "started_at": operator_run.utc_iso(started),
                      "state": state or "COMPLETE"})
        grs.OPERATOR_SUMMARY_PATH.write_text(json.dumps(s), encoding="utf-8")

    def log(self, name, run_id, mtime):
        p = self.logs / name
        p.write_text("\n".join(["Header", "=" * 10, "Started: x", *operator_run.log_tag_line(run_id), "", "body"]),
                     encoding="utf-8")
        ts = mtime.timestamp()
        os.utime(p, (ts, ts))
        return p

    def sidecar(self, parent, run_id, at, outcomes):
        payload = {"parent": parent, "at": operator_run.utc_iso(at), "outcomes": outcomes,
                   "degraded": any(run_outcomes.is_alerting(o) for o in outcomes.values())}
        if run_id is not None:
            payload["run_id"] = run_id
        (self.tracking / f"_child_outcomes_{parent}.json").write_text(json.dumps(payload), encoding="utf-8")


def row(payload, name):
    return next((r for r in payload["rows"] if r["Name"] == name), None)


def reasons_text(payload) -> str:
    return " | ".join(payload.get("degraded_reasons") or [])


# ------------------------------------------------------------------------------------------ cases
def _replay_setup(t: Tree, *, identified_prev: bool):
    y_start, y_end = T("2026-11-02T13:00:00Z"), T("2026-11-02T13:24:16Z")
    run_t = operator_run.new_run_id(T("2026-11-03T13:00:00Z"))
    run_y = operator_run.new_run_id(y_start) if identified_prev else None
    t.log("daily_operator_20261102_130000.log", run_y, T("2026-11-02T13:19:12Z"))
    t.log("all_scorecards_20261102_131358.log", run_y, T("2026-11-02T13:19:00Z"))
    t.log("bk_edge_engine_pipeline_20261102_130711.log", run_y, T("2026-11-02T13:13:00Z"))
    t.summary(run_y, y_start, y_end, degraded=[VF], legacy=not identified_prev)
    t.marker(run_t, T("2026-11-03T13:00:00Z"))
    # the current run's Edge log was written just before the nested Run Status call
    t.log("bk_edge_engine_pipeline_20261103_130711.log", run_t, T("2026-11-03T13:07:11Z"))
    return run_t, run_y


def case_replay_1103(f):
    for identified_prev in (False, True):
        tag = f"[1 replay prev={'id' if identified_prev else 'legacy'}]"
        with Tree() as t:
            run_t, run_y = _replay_setup(t, identified_prev=identified_prev)
            p = grs.build_run_status(now=T("2026-11-03T13:07:12Z"))
            op = p["operator"]
            if op.get("state") != "PENDING" or op.get("status_label") != "IN PROGRESS":
                f.append(f"{tag} operator must be PENDING/IN PROGRESS; got {op.get('state')}/{op.get('status_label')}")
            cur = op.get("current_run") or {}
            if cur.get("run_id") != run_t or cur.get("started_at") != "2026-11-03T13:00:00Z":
                f.append(f"{tag} current run id/start must be named; got {cur}")
            if "VALIDATION_FAILED" in reasons_text(p):
                f.append(f"{tag} yesterday's VALIDATION_FAILED leaked into current reasons: {p['degraded_reasons']}")
            d = row(p, "Daily Operator")
            if d["Status"] != "IN_PROGRESS" or d["Artifact"] or run_t not in d["StatusNote"]:
                f.append(f"{tag} Daily Operator row must be IN_PROGRESS for {run_t}, not yesterday's log; got {d}")
            if d.get("PreviousArtifact") != str(Path("logs") / "daily_operator_20261102_130000.log") \
                    or d.get("PreviousRunLabel") != "previous run":
                f.append(f"{tag} yesterday's log must appear only as the labelled previous run; got {d}")
            e = row(p, "Edge Engine")
            if e["Status"] != "FRESH" or "20261103" not in e["Artifact"]:
                f.append(f"{tag} Edge row must be the current run's own log; got {e}")
            sc = row(p, "Scorecards")
            if sc["Status"] != "PENDING" or sc["Artifact"]:
                f.append(f"{tag} Scorecards (not reached yet) must be PENDING, not yesterday FRESH; got {sc}")
            prev = op.get("previous_run") or {}
            if prev.get("label") != "previous run" or not any("VALIDATION_FAILED" in r for r in prev.get("reasons", [])) \
                    or prev.get("run_id") != run_y:
                f.append(f"{tag} previous run must be separate + labelled with its own id/reasons; got {prev}")
            # through main() (wall clock): the persisted file + console say IN PROGRESS and label the
            # previous run. Same run id, started 7 minutes before the real now.
            t.marker(run_t, datetime.now(UTC) - timedelta(minutes=7))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                grs.main()
            text = out.getvalue()
            disk = json.loads(grs.JSON_PATH.read_text(encoding="utf-8"))
            if disk["operator"].get("state") != "PENDING" or "IN PROGRESS" not in text or run_t not in text:
                f.append(f"{tag} main() must persist/print PENDING naming {run_t}")
            if "Previous run (not current)" not in text or re.search(r"DEGRADED: .*VALIDATION_FAILED", text):
                f.append(f"{tag} console must label the previous run and not print its reason as DEGRADED")


def case_replay_child_updated(f):
    with Tree() as t:
        run_t, _ = _replay_setup(t, identified_prev=False)
        t.sidecar("football_props", run_t, T("2026-11-03T13:03:00Z"), {"nfl": "UPDATED", "ncaaf_player_props": "UPDATED"})
        p = grs.build_run_status(now=T("2026-11-03T13:07:12Z"))
        op = p["operator"]
        if op.get("state") != "PENDING":
            f.append(f"[2] still PENDING while the run is active; got {op.get('state')}")
        interim = op.get("in_progress_child_outcomes") or {}
        if interim.get("football_props", {}).get("ncaaf_player_props") != "UPDATED":
            f.append(f"[2] today's UPDATED must be the interim outcome; got {interim}")
        if "VALIDATION_FAILED" in reasons_text(p) or "UPDATED" in reasons_text(p):
            f.append(f"[2] neither yesterday's VF nor today's interim outcome may be a current reason: {p['degraded_reasons']}")
        if op.get("state") in ("COMPLETE", "FAILED"):
            f.append("[2] interim outcome must not be presented as final")


def case_finished(f):
    with Tree() as t:
        s, e = T("2026-11-03T13:00:00Z"), T("2026-11-03T13:24:00Z")
        run_t = operator_run.new_run_id(s)
        t.log("daily_operator_20261102_130000.log", None, T("2026-11-03T13:30:00Z"))   # decoy NEWER mtime
        t.log("daily_operator_20261103_130000.log", run_t, T("2026-11-03T13:20:29Z"))
        t.summary(run_t, s, e, degraded=["football_props:nfl=VALIDATION_FAILED"], state="COMPLETE")
        t.marker(run_t, s, state="COMPLETE", finished=e)
        p = grs.build_run_status(now=T("2026-11-03T14:00:00Z"))
        op = p["operator"]
        if op.get("state") != "COMPLETE" or (op.get("current_run") or {}).get("run_id") != run_t:
            f.append(f"[3] finished run must be COMPLETE and identified; got {op.get('state')}")
        if "football_props:nfl=VALIDATION_FAILED" not in reasons_text(p):
            f.append(f"[3] the CURRENT run's alerting child outcome must fold in as before; got {p['degraded_reasons']}")
        if op.get("previous_run"):
            f.append("[3] a finished current run has no separate previous-run block")
        d = row(p, "Daily Operator")
        if d["Status"] != "FRESH" or "20261103" not in d["Artifact"]:
            f.append(f"[3] Daily Operator must be the run's own log by id, not the newer-mtime decoy; got {d}")
        for key in ("finished_at", "blocking_failure", "failed_steps", "provider_exhausted_steps", "degraded_child_outcomes"):
            if key not in op:
                f.append(f"[3] legacy operator key {key} must be preserved")
    # legacy tree (no marker at all): unchanged pre-D11 behaviour
    with Tree() as t:
        t.summary(None, None, T("2026-11-03T13:24:00Z"), degraded=[VF], legacy=True)
        t.log("daily_operator_20261103_130000.log", None, T("2026-11-03T13:20:00Z"))
        p = grs.build_run_status(now=T("2026-11-03T14:00:00Z"))
        if "VALIDATION_FAILED" not in reasons_text(p) or p["operator"].get("state") != "LEGACY":
            f.append(f"[3L] no marker -> legacy fold unchanged; got {p['operator'].get('state')} {p['degraded_reasons']}")
        if row(p, "Daily Operator")["Status"] != "FRESH":
            f.append("[3L] legacy Daily Operator row must stay newest-by-mtime")


def case_missing(f):
    with Tree() as t:   # active run, nothing else on disk
        run_t = operator_run.new_run_id(T("2026-11-03T13:00:00Z"))
        t.marker(run_t, T("2026-11-03T13:00:00Z"))
        p = grs.build_run_status(now=T("2026-11-03T13:05:00Z"))
        d = row(p, "Daily Operator")
        if p["operator"].get("state") != "PENDING" or d["Status"] != "IN_PROGRESS" or d.get("PreviousArtifact"):
            f.append(f"[4a] no summary/no log -> PENDING with no substituted artifact; got {p['operator'].get('state')} {d}")
        if p["operator"].get("previous_run") is not None:
            f.append("[4a] no previous summary -> no previous run block")
    with Tree() as t:   # closed run whose summary and log are missing, older artifacts present
        s = T("2026-11-03T13:00:00Z")
        run_t = operator_run.new_run_id(s)
        t.log("daily_operator_20261102_130000.log", None, T("2026-11-02T13:19:00Z"))
        t.summary(None, None, T("2026-11-02T13:24:00Z"), degraded=[VF], legacy=True)
        t.marker(run_t, s, state="FAILED", finished=T("2026-11-03T13:30:00Z"))
        p = grs.build_run_status(now=T("2026-11-03T14:00:00Z"))
        d = row(p, "Daily Operator")
        if d["Status"] != "MISSING" or d["Artifact"]:
            f.append(f"[4b] closed run without its own log -> MISSING, never yesterday's log; got {d}")
        if "VALIDATION_FAILED" in reasons_text(p) or "final summary is missing" not in reasons_text(p):
            f.append(f"[4b] missing summary must be a reason and the older summary never current; got {p['degraded_reasons']}")


def case_killed(f):
    s = T("2026-11-03T13:00:00Z")
    for tag, alive, now, host, expect in (
            ("deadline", True, T("2026-11-03T21:00:01Z"), HOST, "INCOMPLETE"),
            ("pid-gone", False, T("2026-11-03T13:40:00Z"), HOST, "INCOMPLETE"),
            ("foreign-host-not-probed", False, T("2026-11-03T13:40:00Z"), "other-box", "PENDING")):
        with Tree(alive=alive) as t:
            run_t, _ = _replay_setup(t, identified_prev=False)
            t.marker(run_t, s, host=host)
            p = grs.build_run_status(now=now)
            st = p["operator"].get("state")
            if st != expect:
                f.append(f"[5 {tag}] expected {expect}; got {st}")
            if "VALIDATION_FAILED" in reasons_text(p):
                f.append(f"[5 {tag}] yesterday's reason must never be current: {p['degraded_reasons']}")
            if expect == "INCOMPLETE":
                if run_t not in reasons_text(p) or row(p, "Daily Operator")["Status"] != "INCOMPLETE" \
                        or p["overall"] not in ("DEGRADED", "RED"):
                    f.append(f"[5 {tag}] INCOMPLETE must name {run_t}, mark the row, and degrade; got {p['degraded_reasons']}")
                if (p["operator"].get("previous_run") or {}).get("label") != "previous run":
                    f.append(f"[5 {tag}] previous run must stay separately labelled")
    # a Run_Status.json persisted mid-run by a run that then died expires to INCOMPLETE in the reader
    with Tree() as t:
        run_t, _ = _replay_setup(t, identified_prev=False)
        p = grs.build_run_status(now=T("2026-11-03T13:07:12Z"))
        early = operator_run.expire_pending_payload(p, now=T("2026-11-03T15:00:00Z"))
        late = operator_run.expire_pending_payload(p, now=T("2026-11-03T21:00:01Z"))
        if early["operator"]["state"] != "PENDING":
            f.append("[5d] a PENDING payload before its deadline must stay PENDING")
        if late["operator"]["state"] != "INCOMPLETE" or row(late, "Daily Operator")["Status"] != "INCOMPLETE" \
                or late["overall"] != "DEGRADED" or run_t not in reasons_text(late):
            f.append(f"[5d] a persisted PENDING past its deadline must read INCOMPLETE; got {late['operator']['state']}")


def case_two_logs_same_day(f):
    with Tree() as t:
        a_s, a_e = T("2026-11-03T13:00:00Z"), T("2026-11-03T13:24:00Z")
        b_s = T("2026-11-03T15:30:00Z")
        run_a, run_b = operator_run.new_run_id(a_s), operator_run.new_run_id(b_s)
        t.log("daily_operator_20261103_130000.log", run_a, T("2026-11-03T13:20:00Z"))
        t.summary(run_a, a_s, a_e, degraded=[VF])
        t.marker(run_b, b_s)
        p = grs.build_run_status(now=T("2026-11-03T15:35:00Z"))
        d = row(p, "Daily Operator")
        if p["operator"].get("current_run", {}).get("run_id") != run_b or d["Status"] != "IN_PROGRESS":
            f.append(f"[6] the manual 15:30 run is current by its own id; got {d}")
        if d.get("PreviousRunId") != run_a or (p["operator"].get("previous_run") or {}).get("run_id") != run_a:
            f.append(f"[6] the 13:00 run must be labelled previous with its own id; got {d}")
        if "VALIDATION_FAILED" in reasons_text(p):
            f.append("[6] run A's reason must not be current while run B is in progress")
        # B finishes; A's log is then touched NEWER -- identity still wins
        b_e = T("2026-11-03T15:50:00Z")
        t.log("daily_operator_20261103_153000.log", run_b, T("2026-11-03T15:49:00Z"))
        os.utime(t.logs / "daily_operator_20261103_130000.log", (T("2026-11-03T15:55:00Z").timestamp(),) * 2)
        t.summary(run_b, b_s, b_e)
        t.marker(run_b, b_s, state="COMPLETE", finished=b_e)
        p = grs.build_run_status(now=T("2026-11-03T16:00:00Z"))
        if "20261103_153000" not in row(p, "Daily Operator")["Artifact"] or "VALIDATION_FAILED" in reasons_text(p):
            f.append(f"[6] finished run B must use its own log by id; got {row(p, 'Daily Operator')}")


def case_midnight(f):
    for tag, start, now, end in (
            ("utc-midnight", T("2026-11-03T23:58:00Z"), T("2026-11-04T00:05:00Z"), T("2026-11-04T00:20:00Z")),
            ("eastern-midnight", T("2026-11-04T04:58:00Z"), T("2026-11-04T05:05:00Z"), T("2026-11-04T05:20:00Z"))):
        with Tree() as t:
            run_t = operator_run.new_run_id(start)
            prev_s = start - timedelta(hours=11)
            t.log(f"daily_operator_{prev_s:%Y%m%d_%H%M%S}.log", None, prev_s + timedelta(minutes=20))
            # decoy whose FILENAME date is the newest (Eastern-vs-UTC naming) but which is not this run
            t.log(f"daily_operator_{(start + timedelta(days=1)):%Y%m%d}_000000.log", None, prev_s + timedelta(minutes=21))
            t.summary(None, None, prev_s + timedelta(minutes=24), degraded=[VF], legacy=True)
            t.marker(run_t, start)
            p = grs.build_run_status(now=now)
            if p["operator"].get("state") != "PENDING" or p["operator"]["current_run"]["run_id"] != run_t:
                f.append(f"[7 {tag}] run must stay identified as {run_t} across midnight; got {p['operator'].get('state')}")
            if row(p, "Daily Operator")["Artifact"] or "VALIDATION_FAILED" in reasons_text(p):
                f.append(f"[7 {tag}] no dated/older log may stand in for the current run")
            # the run's own log is named with ITS start stamp (local-time naming), finished after midnight
            t.log(f"daily_operator_{start:%Y%m%d_%H%M%S}.log", run_t, end - timedelta(minutes=1))
            t.summary(run_t, start, end)
            t.marker(run_t, start, state="COMPLETE", finished=end)
            p = grs.build_run_status(now=end + timedelta(minutes=5))
            d = row(p, "Daily Operator")
            if p["operator"].get("state") != "COMPLETE" or f"{start:%Y%m%d_%H%M%S}" not in d["Artifact"]:
                f.append(f"[7 {tag}] finished run must resolve to its own log by id; got {d}")


def case_stale_sidecar(f):
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        tr = base / "data" / "tracking"
        tr.mkdir(parents=True)
        run_t = operator_run.new_run_id(T("2026-11-03T13:00:00Z"))
        old = operator_run.new_run_id(T("2026-10-28T13:00:00Z"))
        (tr / "_child_outcomes_mlb_daily.json").write_text(json.dumps(
            {"parent": "mlb_daily", "at": "2026-10-28T13:10:00+00:00", "outcomes": {"player_props": "VALIDATION_FAILED"},
             "degraded": True}), encoding="utf-8")   # pre-D11 sidecar: no run id at all
        (tr / "_child_outcomes_nba_daily.json").write_text(json.dumps(
            {"parent": "nba_daily", "run_id": old, "at": "2026-10-28T13:10:00+00:00",
             "outcomes": {"player_props": "PROVIDER_ERROR"}}), encoding="utf-8")
        (tr / "_child_outcomes_football_props.json").write_text(json.dumps(
            {"parent": "football_props", "run_id": run_t, "at": "2026-11-03T13:03:00+00:00",
             "outcomes": {"nfl": "UPDATED"}}), encoding="utf-8")
        cur = run_outcomes.load_all_child_outcomes(base, run_t)
        if set(cur) != {"football_props"}:
            f.append(f"[8] only the current run's sidecars may load; got {sorted(cur)}")
        _, other = run_outcomes.partition_child_outcomes(base, run_t)
        if set(other) != {"mlb_daily", "nba_daily"}:
            f.append(f"[8] stale sidecars must be reported not-this-run; got {sorted(other)}")
        if run_outcomes.load_all_child_outcomes(base, None):
            f.append("[8] no run id -> nothing is current")


# ---------------------------------------------------------------- real run_daily drives (9, 11)
@contextlib.contextmanager
def daily_tree(prev_summary=True):
    with Tree() as t:
        saved = (run_daily.BASE_DIR, run_daily.LOG_DIR, run_daily._run_step, edge.BASE_DIR, edge.LOG_DIR,
                 edge.STEPS, edge.run_step, sys.argv, os.environ.get("BK_OPERATOR_RUN_ID"))
        run_daily.BASE_DIR, run_daily.LOG_DIR = t.base, t.logs
        edge.BASE_DIR, edge.LOG_DIR, edge.STEPS = t.base, t.logs, []
        grs._PID_ALIVE = operator_run.pid_alive     # the real (in-process) operator pid
        grs._HOSTNAME = None
        if prev_summary:
            y = T("2026-11-02T13:00:00Z")
            t.log("daily_operator_20261102_130000.log", None, y + timedelta(minutes=19))
            t.log("all_scorecards_20261102_131358.log", None, y + timedelta(minutes=19))
            t.summary(None, None, y + timedelta(minutes=24), degraded=[VF], legacy=True)
            # stale sidecar from a step that will not run this time (mlb not in --sports wnba)
            t.sidecar("mlb_daily", None, T("2026-10-28T13:10:00Z"), {"player_props": "VALIDATION_FAILED"})
        try:
            yield t
        finally:
            (run_daily.BASE_DIR, run_daily.LOG_DIR, run_daily._run_step, edge.BASE_DIR, edge.LOG_DIR,
             edge.STEPS, edge.run_step, sys.argv, env) = saved
            if env is None:
                os.environ.pop("BK_OPERATOR_RUN_ID", None)
            else:
                os.environ["BK_OPERATOR_RUN_ID"] = env


def _grs_main_inprocess() -> tuple[bool, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = grs.main()
    return rc == 0, out.getvalue()


def case_invocation_sites(f):
    # static: every script invocation of generate_run_status.py must be one of the two handled sites
    sites = set()
    for py in REPO.glob("*.py"):
        if py.name.startswith("qc_"):
            continue
        if re.search(r"""["']generate_run_status\.py["']""", py.read_text(encoding="utf-8", errors="replace")):
            sites.add(py.name)
    if sites != {"run_daily.py", "run_bk_edge_engine_pipeline.py"}:
        f.append(f"[9] generate_run_status invocation sites changed -- cover them here: {sorted(sites)}")

    with daily_tree() as t:
        snaps = {}

        def edge_step(label, script):
            if script == "generate_run_status.py":
                ok, out = _grs_main_inprocess()
                snaps["nested"] = json.loads(grs.JSON_PATH.read_text(encoding="utf-8"))
                snaps["nested_out"] = out
                return ok, out
            return True, ""

        def fake(label, command, timeout):
            if label == "Edge Engine pipeline":
                edge.run_step = edge_step
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    rc = edge.main()
                return rc == 0, out.getvalue()
            if label == "All scorecards":
                snaps["after_edge_before_scorecards"] = grs.build_run_status()
                return True, ""
            if label == "Run status":
                ok, out = _grs_main_inprocess()
                snaps["final"] = json.loads(grs.JSON_PATH.read_text(encoding="utf-8"))
                return ok, out
            return True, ""

        run_daily._run_step = fake
        sys.argv = ["run_daily.py", "--sports", "wnba", "--skip-refresh"]
        with contextlib.redirect_stdout(io.StringIO()):
            run_daily.main()
        marker = json.loads(grs.OPERATOR_MARKER_PATH.read_text(encoding="utf-8"))
        rid = marker["run_id"]
        n = snaps.get("nested") or {}
        if (n.get("operator") or {}).get("state") != "PENDING" or n["operator"]["current_run"]["run_id"] != rid:
            f.append(f"[9 nested Edge call] mid-run Run Status must be PENDING for {rid}; got {(n.get('operator') or {}).get('state')}")
        else:
            if "VALIDATION_FAILED" in reasons_text(n) or row(n, "Daily Operator")["Status"] != "IN_PROGRESS":
                f.append(f"[9 nested Edge call] previous run leaked into the mid-run status: {n['degraded_reasons']}")
            if row(n, "Edge Engine")["Status"] != "FRESH" or row(n, "Scorecards")["Status"] != "PENDING":
                f.append(f"[9 nested Edge call] Edge=current run's log, Scorecards=PENDING expected; got "
                         f"{row(n, 'Edge Engine')['Status']}/{row(n, 'Scorecards')['Status']}")
        mid = snaps.get("after_edge_before_scorecards") or {}
        if (mid.get("operator") or {}).get("state") != "PENDING":
            f.append("[9 mid-run read between steps] must be PENDING")
        fin = snaps.get("final") or {}
        if (fin.get("operator") or {}).get("state") != "COMPLETE" or fin["operator"]["current_run"]["run_id"] != rid:
            f.append(f"[9 top-level Run status step] final read must be COMPLETE for {rid}; got {(fin.get('operator') or {}).get('state')}")
        elif "VALIDATION_FAILED" in reasons_text(fin) or "20261102" in row(fin, "Daily Operator")["Artifact"]:
            f.append(f"[9 top-level] final must use this run's log/summary only; got {row(fin, 'Daily Operator')}")
        if marker["state"] != "COMPLETE" or not marker.get("finished_at"):
            f.append(f"[9] final summary must close the marker atomically; got {marker['state']}")
        summ = json.loads(grs.OPERATOR_SUMMARY_PATH.read_text(encoding="utf-8"))
        if summ.get("run_id") != rid or summ.get("started_at") != marker["started_at"] or not summ.get("finished_at"):
            f.append(f"[9] summary must carry run_id/started_at/finished_at of the run; got {summ.get('run_id')}")


CHILD_CODE = (
    "import os, sys; sys.path.insert(0, {repo!r});"
    "rid = os.environ.get('BK_OPERATOR_RUN_ID', '');"
    "print('RID=' + rid);"
    "lbl = {label!r};"
    "from services.run_outcomes import record_child_outcomes;"
    "record_child_outcomes({base!r}, 'football_props', {{'nfl': 'UPDATED'}}) if lbl == 'Football player props' else None"
)


# Steps spread across the whole run (first, middle, the props parent, late, post-refresh) that spawn a real
# child; the rest return PASS in-process to keep the QC fast.
SPAWN_LABELS = {"Odds feed health", "All-sport injuries", "Football player props", "WNBA player props",
                "All prop results grading", "Dashboard prewarm", "Odds feed health (post-refresh)"}


def case_run_id_immutable(f):
    with daily_tree() as t:
        seen = []
        real_step = run_daily._run_step

        def fake(label, command, timeout):
            if label not in SPAWN_LABELS:
                return True, ""
            # a REAL child process with the inherited environment, exactly like the real _run_step
            code = CHILD_CODE.format(repo=str(REPO), label=label, base=str(t.base))
            ok, out = real_step(label, [sys.executable, "-c", code], 60)
            m = re.search(r"RID=(\S*)", out or "")
            seen.append((label, m.group(1) if m else None))
            return ok, out

        run_daily._run_step = fake
        sys.argv = ["run_daily.py", "--sports", "wnba", "--skip-edge", "--skip-scorecards", "--continue-on-error"]
        with contextlib.redirect_stdout(io.StringIO()):
            run_daily.main()
        marker = json.loads(grs.OPERATOR_MARKER_PATH.read_text(encoding="utf-8"))
        rid = marker["run_id"]
        if not operator_run.valid_run_id(rid):
            f.append(f"[11] marker run id must be a valid unguessable id; got {rid!r}")
        ids = {r for _, r in seen}
        if len(seen) < 5 or ids != {rid}:
            bad = [(lbl, r) for lbl, r in seen if r != rid][:5]
            f.append(f"[11] every child must inherit the SAME run id {rid}; mismatches={bad} (n={len(seen)})")
        sc = json.loads((t.tracking / "_child_outcomes_football_props.json").read_text(encoding="utf-8"))
        if sc.get("run_id") != rid:
            f.append(f"[11] child sidecar must be stamped with the run id; got {sc.get('run_id')}")
        summ = json.loads(grs.OPERATOR_SUMMARY_PATH.read_text(encoding="utf-8"))
        if summ.get("run_id") != rid or "football_props" not in summ.get("child_outcomes", {}):
            f.append("[11] summary must carry the run id and this run's child outcomes")
        if "mlb_daily" in summ.get("child_outcomes", {}) or any("mlb_daily" in x for x in summ.get("degraded_child_outcomes", [])):
            f.append(f"[8/11] stale mlb_daily sidecar (10-28) leaked into the current summary: {summ.get('degraded_child_outcomes')}")
        if "mlb_daily" not in (summ.get("not_run_this_run") or {}):
            f.append("[8/11] the stale mlb_daily sidecar must be listed as not_run_this_run")
        if marker["state"] not in ("COMPLETE", "FAILED") or os.environ.get("BK_OPERATOR_RUN_ID") != rid:
            f.append("[11] marker must be closed and the run id unchanged at the end of the run")
        log = next(t.logs.glob("daily_operator_2*.log"), None)
        logs = [p for p in t.logs.glob("daily_operator_*.log") if operator_run.read_log_tag(p) == rid]
        if len(logs) != 1:
            f.append(f"[11] the run's own log must carry its run id (found {len(logs)}; any={log})")


def case_atomic(f):
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        path = operator_run.marker_path(base)
        first = {"run_id": operator_run.new_run_id(), "state": "RUNNING", "started_at": "2026-11-03T13:00:00Z"}
        operator_run.atomic_write_json(path, first)
        real_replace = os.replace

        def boom(*a, **k):
            raise OSError("simulated crash before rename")
        os.replace = boom
        try:
            operator_run.atomic_write_json(path, {"run_id": "x" * 5000})
            f.append("[10] a failed replace must raise")
        except OSError:
            pass
        finally:
            os.replace = real_replace
        st, got = operator_run.read_json_status(path)
        if st != "ok" or got != first:
            f.append(f"[10] a failed write must leave the prior marker intact; got {st}")
        if [p.name for p in path.parent.iterdir() if p.name != path.name]:
            f.append("[10] a failed write must not leave temp files behind")

        # concurrent reader vs writer: no torn / missing read, ever
        stop = threading.Event()
        bad = []

        def reader():
            while not stop.is_set():
                s, _ = operator_run.read_json_status(path)
                if s != "ok":
                    bad.append(s)

        th = threading.Thread(target=reader)
        th.start()
        try:
            for i in range(300):
                operator_run.atomic_write_json(path, {"run_id": first["run_id"], "state": "RUNNING",
                                                      "started_at": "2026-11-03T13:00:00Z",
                                                      "pad": ("ab" * (2000 + (i % 7) * 900))})
        finally:
            stop.set()
            th.join()
        if bad:
            f.append(f"[10] concurrent reader saw {len(bad)} torn/missing marker read(s): {bad[:3]}")
    # path containment
    try:
        operator_run.marker_path(Path(tempfile.gettempdir()))
    except ValueError:
        f.append("[10] marker path for a normal base must be accepted")
    real_name = operator_run.MARKER_FILENAME
    operator_run.MARKER_FILENAME = "../escape.json"
    try:
        operator_run.marker_path(Path(tempfile.gettempdir()))
        f.append("[10] a marker path that escapes data/tracking must be refused")
    except ValueError:
        pass
    finally:
        operator_run.MARKER_FILENAME = real_name


CASES = [case_replay_1103, case_replay_child_updated, case_finished, case_missing, case_killed,
         case_two_logs_same_day, case_midnight, case_stale_sidecar, case_invocation_sites,
         case_run_id_immutable, case_atomic]


def run_suite() -> list[str]:
    failures: list[str] = []
    for case in CASES:
        try:
            case(failures)
        except Exception as exc:   # a crash is a failure, never a silent pass
            failures.append(f"[{case.__name__}] raised {type(exc).__name__}: {exc}")
    return failures


# ------------------------------------------------------------------------------------- mutations
@contextlib.contextmanager
def _patch(obj, name, value):
    old = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, old)


def _mut_ignore_marker():
    real = operator_run.read_json_status

    def fake(path):
        if Path(path).name == operator_run.MARKER_FILENAME:
            return "absent", None
        return real(path)
    return _patch(operator_run, "read_json_status", fake)


def _mut_merge_all_sidecars():
    real = run_outcomes.partition_child_outcomes

    def fake(base_dir, run_id):
        cur, other = real(base_dir, run_id)
        tracking = Path(base_dir) / "data" / "tracking"
        for p in tracking.glob("_child_outcomes_*.json"):
            d = json.loads(p.read_text(encoding="utf-8"))
            cur[d.get("parent") or p.stem] = d
        return cur, {}
    stack = contextlib.ExitStack()
    stack.enter_context(_patch(run_outcomes, "partition_child_outcomes", fake))
    stack.enter_context(_patch(grs, "partition_child_outcomes", fake))
    return stack


def _mut_never_incomplete():
    return _patch(operator_run, "assess_running", lambda *a, **k: ("RUNNING", "in progress"))


def _mut_newest_mtime_log():
    return _patch(grs, "_find_tagged_log", lambda patterns, rid: grs._latest_file(patterns, grs.LOG_DIR))


def _mut_no_env_export():
    real = operator_run.begin_run

    def fake(base_dir, **kw):
        kw["environ"] = {}
        return real(base_dir, **kw)
    return _patch(operator_run, "begin_run", fake)


def _mut_non_atomic_write():
    import time as _t

    def fake(path, obj):
        data = json.dumps(obj, indent=2)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(data[: len(data) // 2])
            fh.flush()
            _t.sleep(0.002)
            fh.write(data[len(data) // 2:])
    return _patch(operator_run, "atomic_write_json", fake)


def _mut_no_close():
    return _patch(operator_run, "close_run", lambda *a, **k: True)


def _mut_no_expiry():
    return _patch(operator_run, "expire_pending_payload", lambda payload, now=None: payload)


def _mut_fold_previous_when_pending():
    real = grs._operator_context

    def fake(now=None):
        reasons, info = real(now)
        prev = info.get("previous_run") or {}
        return reasons + list(prev.get("reasons") or []), info
    return _patch(grs, "_operator_context", fake)


MUTATIONS = [
    ("ignore the current-run marker (pre-D11 read)", _mut_ignore_marker),
    ("merge every child-outcome sidecar regardless of run id", _mut_merge_all_sidecars),
    ("never classify a dead/overdue run INCOMPLETE", _mut_never_incomplete),
    ("pick the operator log by newest mtime, not run id", _mut_newest_mtime_log),
    ("do not export BK_OPERATOR_RUN_ID to children", _mut_no_env_export),
    ("non-atomic marker write", _mut_non_atomic_write),
    ("final summary does not close the marker", _mut_no_close),
    ("persisted PENDING never expires", _mut_no_expiry),
    ("fold the previous run's reasons into the current status", _mut_fold_previous_when_pending),
]


def main() -> int:
    print("=" * 64)
    print("QC: RUN STATUS = CURRENT OPERATOR RUN (D11)")
    print("=" * 64)
    failures = run_suite()
    if failures:
        for x in failures:
            print(f"[FAIL] {x}")
        print(f"[FAIL] baseline: {len(failures)} failure(s) across {len(CASES)} case groups")
        return 1
    print(f"[OK] baseline: {len(CASES)} case groups pass")
    survived = []
    for name, mut in MUTATIONS:
        with mut():
            mf = run_suite()
        if mf:
            print(f"[OK] mutation caught ({len(mf)} failure(s)): {name}")
        else:
            survived.append(name)
            print(f"[FAIL] mutation SURVIVED: {name}")
    if survived:
        return 1
    print(f"[OK] all {len(MUTATIONS)} mutations caught")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
