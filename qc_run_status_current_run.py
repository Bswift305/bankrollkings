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
  3  finished run, matching ids                      -> normal fold, current log by id (not by mtime);
     no marker (legacy)                              -> tokenless child outcomes are legacy history only
  4  missing summary and/or missing log              -> PENDING / MISSING, never an older artifact
  5  killed run (lease free / deadline / foreign host) -> INCOMPLETE, PERSISTED when the owner is gone;
     persisted PENDING Run_Status expires to INCOMPLETE in the reader
  6  two logs on the same UTC day                    -> identity by run id
  7  UTC-midnight and Eastern-midnight crossings     -> identity unaffected by dates/filenames
  8  stale + tokenless child-outcome files (mlb_daily from 10-28) -> never current
  9  every generate_run_status invocation site mid-run (nested Edge call + top-level run_daily step)
 10  marker writes atomic (failed replace keeps the old file; concurrent reader never sees a torn file)
 11  run id immutable across real child processes (env inheritance), sidecars + summary + marker agree
 12  REAL concurrent processes: a second run (and run_daily) is refused while a live run holds the lease;
     N simultaneous starters -> exactly one; a killed run is converted to INCOMPLETE atomically by Run
     Status or by the next run start; a finalizer can never close a newer run
 13  hygiene: UTC ISO-Z timestamps, 0600 modes (POSIX), no symlinks, bounded per-run retention
Then MUTATION checks: each key piece is reverted in-process and the suite must FAIL.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
# Never inherit a real operator run's id. When launched INSIDE an operator run (the nightly scorecards
# step, whose whole budget is 1200s), run the baseline only; the ~3 min mutation sweep is a dev gate.
_UNDER_OPERATOR = bool(os.environ.pop("BK_OPERATOR_RUN_ID", None))

import generate_run_status as grs                      # noqa: E402
import run_bk_edge_engine_pipeline as edge             # noqa: E402
import run_daily                                       # noqa: E402
from services import operator_run                      # noqa: E402
from services import run_outcomes                      # noqa: E402

HOST = "qc-host"
UTC = timezone.utc
VF = "football_props:ncaaf_player_props=VALIDATION_FAILED"
Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
NOTES: list[str] = []


def T(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)


# ------------------------------------------------------------------------------------------- tree
class Tree:
    """A temp base dir with every generate_run_status path redirected into it. alive=True holds the
    REAL operator lease for the tree (a live owner); alive=False leaves it free (owner gone)."""

    _ATTRS = ("BASE_DIR", "LOG_DIR", "TRACKING_DIR", "JSON_PATH", "CSV_PATH", "OPERATOR_SUMMARY_PATH",
              "OPERATOR_MARKER_PATH", "_HOSTNAME")

    def __init__(self, alive=True):
        self.alive = alive
        self.lease = None

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
        grs._HOSTNAME = HOST
        if self.alive:
            self.lease = operator_run.acquire_lease(self.base, 0)
        return self

    def __exit__(self, *exc):
        if self.lease is not None:
            self.lease.release()
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
        operator_run.atomic_write_json(operator_run.run_marker_path(self.base, run_id), m)
        operator_run.atomic_write_json(grs.OPERATOR_MARKER_PATH, m)
        return m

    def pointer(self) -> dict:
        return json.loads(grs.OPERATOR_MARKER_PATH.read_text(encoding="utf-8"))

    def summary(self, run_id, started, finished, degraded=(), state=None, legacy=False, blocking=None):
        s = {"finished_at": (finished.isoformat(timespec="seconds") if legacy else operator_run.utc_iso(finished)),
             "log": "", "sports": ["wnba"], "blocking_failure": bool(blocking), "failed_steps": list(blocking or []),
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
def _replay_setup(t: Tree, *, identified_prev: bool, host=HOST):
    y_start, y_end = T("2026-11-02T13:00:00Z"), T("2026-11-02T13:24:16Z")
    run_t = operator_run.new_run_id(T("2026-11-03T13:00:00Z"))
    run_y = operator_run.new_run_id(y_start) if identified_prev else None
    t.log("daily_operator_20261102_130000.log", run_y, T("2026-11-02T13:19:12Z"))
    t.log("all_scorecards_20261102_131358.log", run_y, T("2026-11-02T13:19:00Z"))
    t.log("bk_edge_engine_pipeline_20261102_130711.log", run_y, T("2026-11-02T13:13:00Z"))
    t.summary(run_y, y_start, y_end, degraded=[VF], legacy=not identified_prev)
    t.marker(run_t, T("2026-11-03T13:00:00Z"), host=host)
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
            if t.pointer().get("state") != "RUNNING":
                f.append(f"{tag} a live run (lease held) must never be converted")
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
        t.sidecar("nba_daily", None, T("2026-11-02T13:03:00Z"), {"player_props": "VALIDATION_FAILED"})   # tokenless
        p = grs.build_run_status(now=T("2026-11-03T13:07:12Z"))
        op = p["operator"]
        if op.get("state") != "PENDING":
            f.append(f"[2] still PENDING while the run is active; got {op.get('state')}")
        interim = op.get("in_progress_child_outcomes") or {}
        if interim.get("football_props", {}).get("ncaaf_player_props") != "UPDATED":
            f.append(f"[2] today's UPDATED must be the interim outcome; got {interim}")
        if "nba_daily" in interim:
            f.append("[2] a tokenless sidecar must never be an interim (current) outcome")
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
    # legacy tree (no marker at all): blocking failure still folds; tokenless child outcomes do NOT
    with Tree() as t:
        t.summary(None, None, T("2026-11-03T13:24:00Z"), degraded=[VF], legacy=True, blocking=["NBA daily refresh"])
        t.log("daily_operator_20261103_130000.log", None, T("2026-11-03T13:20:00Z"))
        p = grs.build_run_status(now=T("2026-11-03T14:00:00Z"))
        op = p["operator"]
        if op.get("state") != "LEGACY" or "NBA daily refresh" not in reasons_text(p):
            f.append(f"[3L] no marker -> legacy fold of blocking failure unchanged; got {op.get('state')} {p['degraded_reasons']}")
        if "VALIDATION_FAILED" in reasons_text(p) or VF not in ((op.get("legacy_history") or {}).get("degraded_child_outcomes") or []):
            f.append(f"[3L] tokenless child outcomes must be legacy history only, never current; got {p['degraded_reasons']}")
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
    for tag, alive, now, host, expect, persisted in (
            ("hung-past-deadline", True, T("2026-11-03T21:00:01Z"), HOST, "INCOMPLETE", False),
            ("owner-gone", False, T("2026-11-03T13:40:00Z"), HOST, "INCOMPLETE", True),
            ("foreign-host-in-deadline", False, T("2026-11-03T13:40:00Z"), "other-box", "PENDING", False),
            ("foreign-host-past-deadline", False, T("2026-11-03T21:00:01Z"), "other-box", "INCOMPLETE", True)):
        with Tree(alive=alive) as t:
            run_t, _ = _replay_setup(t, identified_prev=False, host=host)
            p = grs.build_run_status(now=now)
            st = p["operator"].get("state")
            if st != expect:
                f.append(f"[5 {tag}] expected {expect}; got {st}")
            if "VALIDATION_FAILED" in reasons_text(p):
                f.append(f"[5 {tag}] yesterday's reason must never be current: {p['degraded_reasons']}")
            ptr = t.pointer()
            rec = json.loads(operator_run.run_marker_path(t.base, run_t).read_text(encoding="utf-8"))
            if persisted:
                if ptr.get("state") != "INCOMPLETE" or rec.get("state") != "INCOMPLETE" \
                        or ptr.get("detected_by") != "run_status" or not Z_RE.match(ptr.get("detected_at") or ""):
                    f.append(f"[5 {tag}] killed run must be PERSISTED INCOMPLETE (pointer+record); got {ptr.get('state')}/{rec.get('state')}")
                p2 = grs.build_run_status(now=now)   # re-read: the persisted state is what is served
                if p2["operator"].get("state") != "INCOMPLETE" or not p2["operator"].get("incomplete_persisted"):
                    f.append(f"[5 {tag}] persisted INCOMPLETE must be read back as INCOMPLETE")
            elif ptr.get("state") != "RUNNING":
                f.append(f"[5 {tag}] must NOT persist a conversion (owner may be alive); got {ptr.get('state')}")
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
            t.log(f"daily_operator_{(start + timedelta(days=1)):%Y%m%d}_000000.log", None, prev_s + timedelta(minutes=21))
            t.summary(None, None, prev_s + timedelta(minutes=24), degraded=[VF], legacy=True)
            t.marker(run_t, start)
            p = grs.build_run_status(now=now)
            if p["operator"].get("state") != "PENDING" or p["operator"]["current_run"]["run_id"] != run_t:
                f.append(f"[7 {tag}] run must stay identified as {run_t} across midnight; got {p['operator'].get('state')}")
            if row(p, "Daily Operator")["Artifact"] or "VALIDATION_FAILED" in reasons_text(p):
                f.append(f"[7 {tag}] no dated/older log may stand in for the current run")
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
        (tr / "_child_outcomes_wnba_x.json").write_text(json.dumps(
            {"parent": "wnba_x", "run_id": "not-a-valid-id", "outcomes": {"p": "STALE"}}), encoding="utf-8")
        (tr / "_child_outcomes_nba_daily.json").write_text(json.dumps(
            {"parent": "nba_daily", "run_id": old, "at": "2026-10-28T13:10:00Z",
             "outcomes": {"player_props": "PROVIDER_ERROR"}}), encoding="utf-8")
        (tr / "_child_outcomes_football_props.json").write_text(json.dumps(
            {"parent": "football_props", "run_id": run_t, "at": "2026-11-03T13:03:00Z",
             "outcomes": {"nfl": "UPDATED"}}), encoding="utf-8")
        cur = run_outcomes.load_all_child_outcomes(base, run_t)
        if set(cur) != {"football_props"}:
            f.append(f"[8] only the current run's sidecars may load; got {sorted(cur)}")
        _, other, legacy = run_outcomes.partition_child_outcomes(base, run_t)
        if set(other) != {"nba_daily"} or set(legacy) != {"mlb_daily", "wnba_x"}:
            f.append(f"[8] other-run vs legacy split wrong; other={sorted(other)} legacy={sorted(legacy)}")
        if run_outcomes.load_all_child_outcomes(base, None) or run_outcomes.load_all_child_outcomes(base, "x"):
            f.append("[8] no valid run id -> nothing is current (tokenless never matches tokenless)")


# ---------------------------------------------------------------- real run_daily drives (9, 11)
@contextlib.contextmanager
def daily_tree(prev_summary=True):
    with Tree(alive=False) as t:
        saved = (run_daily.BASE_DIR, run_daily.LOG_DIR, run_daily._run_step, run_daily.LEASE_WAIT_SECONDS,
                 edge.BASE_DIR, edge.LOG_DIR, edge.STEPS, edge.run_step, sys.argv, os.environ.get("BK_OPERATOR_RUN_ID"))
        run_daily.BASE_DIR, run_daily.LOG_DIR = t.base, t.logs
        run_daily.LEASE_WAIT_SECONDS = 0.3
        edge.BASE_DIR, edge.LOG_DIR, edge.STEPS = t.base, t.logs, []
        grs._HOSTNAME = None
        if prev_summary:
            y = T("2026-11-02T13:00:00Z")
            t.log("daily_operator_20261102_130000.log", None, y + timedelta(minutes=19))
            t.log("all_scorecards_20261102_131358.log", None, y + timedelta(minutes=19))
            t.summary(None, None, y + timedelta(minutes=24), degraded=[VF], legacy=True)
            # tokenless sidecar from a step that will not run this time (mlb not in --sports wnba)
            t.sidecar("mlb_daily", None, T("2026-10-28T13:10:00Z"), {"player_props": "VALIDATION_FAILED"})
            # another run's sidecar
            t.sidecar("nba_daily", operator_run.new_run_id(T("2026-10-29T13:00:00Z")), T("2026-10-29T13:10:00Z"),
                      {"player_props": "PROVIDER_ERROR"})
        try:
            yield t
        finally:
            (run_daily.BASE_DIR, run_daily.LOG_DIR, run_daily._run_step, run_daily.LEASE_WAIT_SECONDS,
             edge.BASE_DIR, edge.LOG_DIR, edge.STEPS, edge.run_step, sys.argv, env) = saved
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
        marker = t.pointer()
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
            f.append("[9 mid-run read between steps] must be PENDING (live run never converted)")
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
        lease = operator_run.acquire_lease(t.base, 0)
        if lease is None:
            f.append("[9] run_daily must release the lease when it ends")
        else:
            lease.release()


CHILD_CODE = (
    "import os, sys; sys.path.insert(0, {repo!r});"
    "rid = os.environ.get('BK_OPERATOR_RUN_ID', '');"
    "print('RID=' + rid);"
    "lbl = {label!r};"
    "from services.run_outcomes import record_child_outcomes;"
    "record_child_outcomes({base!r}, 'football_props', {{'nfl': 'UPDATED'}}) if lbl == 'Football player props' else None"
)
SPAWN_LABELS = {"Odds feed health", "All-sport injuries", "Football player props", "WNBA player props",
                "All prop results grading", "Dashboard prewarm", "Odds feed health (post-refresh)"}


def case_run_id_immutable(f):
    with daily_tree() as t:
        seen = []
        real_step = run_daily._run_step

        def fake(label, command, timeout):
            if label not in SPAWN_LABELS:
                return True, ""
            code = CHILD_CODE.format(repo=str(REPO), label=label, base=str(t.base))
            ok, out = real_step(label, [sys.executable, "-c", code], 60)
            m = re.search(r"RID=(\S*)", out or "")
            seen.append((label, m.group(1) if m else None))
            return ok, out

        run_daily._run_step = fake
        sys.argv = ["run_daily.py", "--sports", "wnba", "--skip-edge", "--skip-scorecards", "--continue-on-error"]
        with contextlib.redirect_stdout(io.StringIO()):
            run_daily.main()
        marker = t.pointer()
        rid = marker["run_id"]
        if not operator_run.valid_run_id(rid):
            f.append(f"[11] marker run id must be a valid unguessable id; got {rid!r}")
        ids = {r for _, r in seen}
        if len(seen) < 5 or ids != {rid}:
            bad = [(lbl, r) for lbl, r in seen if r != rid][:5]
            f.append(f"[11] every child must inherit the SAME run id {rid}; mismatches={bad} (n={len(seen)})")
        sc = json.loads((t.tracking / "_child_outcomes_football_props.json").read_text(encoding="utf-8"))
        if sc.get("run_id") != rid or not Z_RE.match(sc.get("at") or ""):
            f.append(f"[11] child sidecar must be stamped with the run id + UTC ISO-Z; got {sc.get('run_id')} {sc.get('at')}")
        summ = json.loads(grs.OPERATOR_SUMMARY_PATH.read_text(encoding="utf-8"))
        if summ.get("run_id") != rid or "football_props" not in summ.get("child_outcomes", {}):
            f.append("[11] summary must carry the run id and this run's child outcomes")
        for parent in ("mlb_daily", "nba_daily"):
            if parent in summ.get("child_outcomes", {}) or any(parent in x for x in summ.get("degraded_child_outcomes", [])):
                f.append(f"[8/11] stale {parent} sidecar leaked into the current summary: {summ.get('degraded_child_outcomes')}")
        if "nba_daily" not in (summ.get("not_run_this_run") or {}) or "mlb_daily" not in (summ.get("legacy_child_outcomes") or {}):
            f.append("[8/11] other-run sidecar -> not_run_this_run; tokenless -> legacy_child_outcomes")
        for key in ("started_at", "finished_at"):
            if not Z_RE.match(summ.get(key) or ""):
                f.append(f"[11] summary {key} must be UTC ISO-Z; got {summ.get(key)}")
        if marker["state"] not in ("COMPLETE", "FAILED") or os.environ.get("BK_OPERATOR_RUN_ID") != rid:
            f.append("[11] marker must be closed and the run id unchanged at the end of the run")
        logs = [p for p in t.logs.glob("daily_operator_*.log") if operator_run.read_log_tag(p) == rid]
        if len(logs) != 1:
            f.append(f"[11] the run's own log must carry its run id (found {len(logs)})")


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
    real_name = operator_run.MARKER_FILENAME
    operator_run.MARKER_FILENAME = "../escape.json"
    try:
        operator_run.marker_path(Path(tempfile.gettempdir()))
        f.append("[10] a marker path that escapes data/tracking must be refused")
    except ValueError:
        pass
    finally:
        operator_run.MARKER_FILENAME = real_name


# ------------------------------------------------------------------- 12: real concurrent processes
HOLD_CODE = r"""
import os, sys, time
sys.path.insert(0, sys.argv[1])
from services import operator_run as o
base, mode = sys.argv[2], sys.argv[3]
if mode == "race":
    go = sys.argv[4]
    while not os.path.exists(go):
        time.sleep(0.002)
lease = o.acquire_lease(base, 0)
if lease is None:
    print("REFUSED", flush=True)
    sys.exit(o.REFUSED_EXIT_CODE)
try:
    m = o.begin_run(base, lease, log_name="x.log", sports=["wnba"], max_runtime_seconds=3600)
except o.OperatorRunConflict:
    print("CONFLICT", flush=True)
    sys.exit(o.REFUSED_EXIT_CODE)
print("READY " + m["run_id"], flush=True)
line = sys.stdin.readline().strip()
if line == "close":
    print("CLOSED " + str(o.close_run(base, lease, m, "COMPLETE", summary_written=True)), flush=True)
lease.release()
"""


def _spawn(base, mode, *extra):
    return subprocess.Popen([sys.executable, "-c", HOLD_CODE, str(REPO), str(base), mode, *extra],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _first_line(proc) -> str:
    return (proc.stdout.readline() or "").strip()


def _finish(proc, send=""):
    try:
        out, _ = proc.communicate(send, timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
    return out or ""


def _kill(proc, base):
    proc.kill()
    proc.wait(timeout=30)
    for _ in range(200):                    # the OS releases the lease when the process is gone
        lease = operator_run.acquire_lease(base, 0)
        if lease is not None:
            lease.release()
            return True
        time.sleep(0.05)
    return False


def case_concurrency(f):
    with Tree(alive=False) as t:
        base = t.base
        p1 = _spawn(base, "hold")
        l1 = _first_line(p1)
        if not l1.startswith("READY "):
            f.append(f"[12] first run must start; got {l1!r} {p1.stderr.read() if p1.poll() is not None else ''}")
            _finish(p1)
            return
        id1 = l1.split()[1]
        before = grs.OPERATOR_MARKER_PATH.read_bytes()
        # a second operator process is refused and writes nothing
        p2 = _spawn(base, "hold")
        out2 = _finish(p2)
        if p2.returncode != operator_run.REFUSED_EXIT_CODE or "REFUSED" not in out2:
            f.append(f"[12] a second run must be REFUSED while a live run holds the lease; rc={p2.returncode} {out2!r}")
        if grs.OPERATOR_MARKER_PATH.read_bytes() != before:
            f.append("[12] a refused run must not touch the active marker")
        # run_daily itself refuses (exit 75), writes no log, no marker change
        mp = grs.OPERATOR_MARKER_PATH
        with daily_tree(prev_summary=False):
            run_daily.BASE_DIR, run_daily.LOG_DIR = base, t.logs
            run_daily._run_step = lambda *a, **k: (True, "")
            sys.argv = ["run_daily.py", "--sports", "wnba", "--skip-refresh", "--skip-edge", "--skip-scorecards"]
            with contextlib.redirect_stdout(io.StringIO()):
                rc = run_daily.main()
            if rc != operator_run.REFUSED_EXIT_CODE or list(t.logs.glob("daily_operator_*.log")) \
                    or mp.read_bytes() != before or os.environ.get("BK_OPERATOR_RUN_ID"):
                f.append(f"[12] run_daily must refuse (75) without writing while another run is live; rc={rc}")
        # Run Status while the owner is alive: PENDING, never converted
        p = grs.build_run_status()
        if p["operator"].get("state") != "PENDING" or t.pointer()["state"] != "RUNNING":
            f.append(f"[12] live owner -> PENDING and untouched; got {p['operator'].get('state')}")
        # kill -9 the owner -> Run Status converts it atomically, persisted
        if not _kill(p1, base):
            f.append("[12] the OS must release the lease of a killed process")
        grs._HOSTNAME = None    # the child wrote this host's real name
        p = grs.build_run_status()
        ptr = t.pointer()
        rec = json.loads(operator_run.run_marker_path(base, id1).read_text(encoding="utf-8"))
        if p["operator"].get("state") != "INCOMPLETE" or ptr.get("state") != "INCOMPLETE" \
                or rec.get("state") != "INCOMPLETE" or ptr.get("detected_by") != "run_status":
            f.append(f"[12] killed run must be converted to INCOMPLETE by Run Status, persisted; got "
                     f"{p['operator'].get('state')}/{ptr.get('state')}/{rec.get('state')}")
        # a late finalizer for the killed run cannot resurrect it
        lease = operator_run.acquire_lease(base, 0)
        lease.run_id = id1
        if operator_run.close_run(base, lease, {"run_id": id1}, "COMPLETE", summary_written=True):
            f.append("[12] closing an INCOMPLETE run must fail the CAS")
        lease.release()
        try:
            operator_run.close_run(base, None, {"run_id": id1}, "COMPLETE", summary_written=True)
            f.append("[12] close without the lease must be refused")
        except operator_run.OperatorRunConflict:
            pass

        # kill path #2: the NEXT RUN START converts the killed run
        p3 = _spawn(base, "hold")
        id3 = _first_line(p3).split()[-1]
        _kill(p3, base)
        p4 = _spawn(base, "hold")
        l4 = _first_line(p4)
        id4 = l4.split()[-1]
        rec3 = json.loads(operator_run.run_marker_path(base, id3).read_text(encoding="utf-8"))
        if not l4.startswith("READY ") or rec3.get("state") != "INCOMPLETE" or rec3.get("detected_by") != "run_start" \
                or t.pointer().get("run_id") != id4:
            f.append(f"[12] next run start must convert the killed run (CAS) then start; got {l4!r} {rec3.get('state')}")
        # while run 4 is live nobody else can finalize anything
        if operator_run.acquire_lease(base, 0.2) is not None:
            f.append("[12] the lease must be exclusive across processes")
        before4 = grs.OPERATOR_MARKER_PATH.read_bytes()
        out4 = _finish(p4, "close\n")
        if "CLOSED True" not in out4 or t.pointer().get("state") != "COMPLETE" or t.pointer().get("run_id") != id4:
            f.append(f"[12] run 4 must close its own run; got {out4!r}")
        # a stale finalizer for run 3 (lease bound to id3) can never close the newer run 4
        after4 = grs.OPERATOR_MARKER_PATH.read_bytes()
        lease = operator_run.acquire_lease(base, 0)
        lease.run_id = id3
        r = operator_run.close_run(base, lease, {"run_id": id3}, "COMPLETE", summary_written=True)
        lease.run_id = id1
        r2 = operator_run.close_run(base, lease, {"run_id": id4}, "FAILED", summary_written=True)
        lease.release()
        if r or r2 or grs.OPERATOR_MARKER_PATH.read_bytes() != after4 or before4 == after4:
            f.append("[12] a finalizer must never close another/newer run")
        # an older run whose record is still RUNNING may close ITSELF but never touches a newer pointer
        old = operator_run.new_run_id()
        rec_old = {"schema": operator_run.SCHEMA, "run_id": old, "state": "RUNNING", "started_at": operator_run.utc_now_iso()}
        operator_run.atomic_write_json(operator_run.run_marker_path(base, old), rec_old)
        lease = operator_run.acquire_lease(base, 0)
        lease.run_id = old
        ok = operator_run.close_run(base, lease, rec_old, "COMPLETE", summary_written=True)
        lease.release()
        if not ok or grs.OPERATOR_MARKER_PATH.read_bytes() != after4:
            f.append("[12] closing an older run must leave the newer run's pointer byte-identical")

        # N simultaneous starters -> exactly one
        go = base / "go.flag"
        racers = [_spawn(base, "race", str(go)) for _ in range(6)]
        time.sleep(0.5)
        go.write_text("go", encoding="utf-8")
        firsts = [_first_line(p) for p in racers]
        winners = [x for x in firsts if x.startswith("READY ")]
        if len(winners) != 1 or sum(1 for x in firsts if x == "REFUSED") != 5:
            f.append(f"[12] 6 simultaneous starts must yield exactly one run; got {firsts}")
        elif t.pointer().get("run_id") != winners[0].split()[1] or t.pointer().get("state") != "RUNNING":
            f.append("[12] the pointer must name the single winner")
        for p in racers:
            _finish(p, "\n")


# ----------------------------------------------------------------------------------- 13: hygiene
def case_hygiene(f):
    with Tree(alive=False) as t:
        base = t.base
        with operator_run.acquire_lease(base, 0) as lease:
            m = operator_run.begin_run(base, lease, log_name="x.log", sports=["wnba"], max_runtime_seconds=600,
                                       environ={})
            for k in ("started_at", "deadline_at"):
                if not Z_RE.match(m.get(k) or ""):
                    f.append(f"[13] marker {k} must be UTC ISO-Z; got {m.get(k)}")
            operator_run.close_run(base, lease, m, "COMPLETE", summary_written=True)
        ptr = t.pointer()
        if not Z_RE.match(ptr.get("finished_at") or ""):
            f.append(f"[13] finished_at must be UTC ISO-Z; got {ptr.get('finished_at')}")
        if operator_run.parse_utc("2026-11-03T13:00:00") is not None:
            f.append("[13] a naive timestamp must be rejected")
        files = [grs.OPERATOR_MARKER_PATH, operator_run.run_marker_path(base, m["run_id"]),
                 operator_run.lock_path(base)]
        os.environ["BK_OPERATOR_RUN_ID"] = m["run_id"]
        try:
            run_outcomes.record_child_outcomes(base, "football_props", {"nfl": "UPDATED"})
        finally:
            os.environ.pop("BK_OPERATOR_RUN_ID", None)
        files.append(t.tracking / "_child_outcomes_football_props.json")
        if os.name == "posix":
            for p in files:
                mode = os.stat(p).st_mode & 0o777
                if mode != 0o600:
                    f.append(f"[13] {p.name} must be 0600; got {oct(mode)}")
        else:
            NOTES.append("POSIX 0600 mode check skipped on this OS (enforced via fchmod on Linux)")
        # symlinks: never written through, never followed
        target = base / "elsewhere.json"
        target.write_text("{}", encoding="utf-8")
        link = t.tracking / "_child_outcomes_evil.json"
        try:
            os.symlink(target, link)
            made = True
        except OSError:
            made = False
            NOTES.append("symlink checks skipped (symlink creation not permitted)")
        if made:
            try:
                operator_run.atomic_write_json(link, {"x": 1})
                f.append("[13] writing through a symlink must be refused")
            except ValueError:
                pass
            if target.read_text(encoding="utf-8") != "{}":
                f.append("[13] a symlink target must never be modified")
            if "evil" in str(run_outcomes.partition_child_outcomes(base, m["run_id"])):
                f.append("[13] a symlinked sidecar must be ignored")
            ptr_link_base = base / "b2"
            (ptr_link_base / "data" / "tracking").mkdir(parents=True)
            os.symlink(target, operator_run.marker_path(ptr_link_base))
            if operator_run.read_marker(ptr_link_base)[0] != "corrupt":
                f.append("[13] a symlinked marker must read as corrupt (never followed)")
        # bounded retention: age + count cap; current + pointer run never deleted; foreign names untouched
        rd = operator_run.runs_dir(base)
        now = datetime.now(UTC)
        made_ids = []
        for i in range(130):
            rid = operator_run.new_run_id(now - timedelta(days=i * 0.5 + 0.01))
            operator_run.atomic_write_json(rd / f"{rid}.json", {"run_id": rid})
            made_ids.append(rid)
        ancient_ptr = operator_run.new_run_id(now - timedelta(days=400))
        t.marker(ancient_ptr, now - timedelta(days=400), state="COMPLETE", finished=now - timedelta(days=400))
        (rd / "README.txt").write_text("keep", encoding="utf-8")
        with operator_run.acquire_lease(base, 0) as lease:
            cur = operator_run.begin_run(base, lease, log_name="y.log", sports=["wnba"], environ={})
            operator_run.close_run(base, lease, cur, "COMPLETE", summary_written=True)
        left = {p.name[:-5] for p in rd.glob("*.json")}
        if cur["run_id"] not in left or ancient_ptr not in left:
            f.append("[13] retention must never delete the current run or the pointer's run")
        if len(left) > operator_run.RETENTION_MAX_FILES:
            f.append(f"[13] retention count cap exceeded: {len(left)} > {operator_run.RETENTION_MAX_FILES}")
        too_old = [r for r in left if r not in (cur["run_id"], ancient_ptr)
                   and operator_run.run_id_time(r) < now - timedelta(days=operator_run.RETENTION_MAX_AGE_DAYS)]
        if too_old:
            f.append(f"[13] retention age cap exceeded: {len(too_old)} files older than {operator_run.RETENTION_MAX_AGE_DAYS}d")
        if not (rd / "README.txt").exists():
            f.append("[13] retention must only delete <run id>.json files")
        if made_ids[0] not in left:
            f.append("[13] retention must keep the newest runs")


CASES = [case_replay_1103, case_replay_child_updated, case_finished, case_missing, case_killed,
         case_two_logs_same_day, case_midnight, case_stale_sidecar, case_invocation_sites,
         case_run_id_immutable, case_atomic, case_concurrency, case_hygiene]


def run_suite() -> list[str]:
    failures: list[str] = []
    for case in CASES:
        try:
            case(failures)
        except Exception as exc:   # a crash is a failure, never a silent pass
            import traceback
            tb = traceback.extract_tb(exc.__traceback__)[-3:]
            where = " <- ".join(f"{Path(fr.filename).name}:{fr.lineno}" for fr in reversed(tb))
            failures.append(f"[{case.__name__}] raised {type(exc).__name__}: {exc} @ {where}")
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


def _mut_accept_any_sidecar():
    real = run_outcomes.partition_child_outcomes

    def fake(base_dir, run_id):
        cur, other, legacy = real(base_dir, run_id)
        tracking = Path(base_dir) / "data" / "tracking"
        for p in tracking.glob("_child_outcomes_*.json"):
            d = json.loads(p.read_text(encoding="utf-8"))
            cur[p.stem.replace("_child_outcomes_", "")] = d
        return cur, {}, {}
    stack = contextlib.ExitStack()
    stack.enter_context(_patch(run_outcomes, "partition_child_outcomes", fake))
    stack.enter_context(_patch(grs, "partition_child_outcomes", fake))
    return stack


def _mut_accept_tokenless():
    real = run_outcomes.partition_child_outcomes

    def fake(base_dir, run_id):
        cur, other, legacy = real(base_dir, run_id)
        tracking = Path(base_dir) / "data" / "tracking"
        for parent in legacy:
            cur[parent] = json.loads((tracking / f"_child_outcomes_{parent}.json").read_text(encoding="utf-8"))
        return cur, other, {}
    stack = contextlib.ExitStack()
    stack.enter_context(_patch(run_outcomes, "partition_child_outcomes", fake))
    stack.enter_context(_patch(grs, "partition_child_outcomes", fake))
    return stack


def _mut_legacy_children_current():
    return _patch(grs, "_is_child_outcome_reason", lambda r: False)


def _mut_never_incomplete():
    return _patch(operator_run, "settle_running", lambda *a, **k: ("RUNNING", "in progress", False))


def _mut_convert_not_persisted():
    return _patch(operator_run, "convert_incomplete", lambda *a, **k: True)


def _mut_newest_mtime_log():
    return _patch(grs, "_find_tagged_log", lambda patterns, rid: grs._latest_file(patterns, grs.LOG_DIR))


def _mut_no_env_export():
    real = operator_run.begin_run

    def fake(base_dir, lease, **kw):
        kw["environ"] = {}
        return real(base_dir, lease, **kw)
    return _patch(operator_run, "begin_run", fake)


def _mut_non_atomic_write():
    import time as _t

    def fake(path, obj, mode=0o600):
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


def _mut_no_lease_exclusion():
    # every lock attempt "succeeds": concurrent runs can clobber each other (env-propagated to children)
    return _patch(operator_run, "_try_lock", lambda fd: True)


def _mut_close_without_cas():
    def fake(base_dir, lease, marker, state, *, summary_written, finished_at=None):
        closed = dict(marker)
        closed.setdefault("started_at", operator_run.utc_now_iso())
        closed.update({"state": state, "finished_at": operator_run.utc_now_iso(), "summary_written": summary_written})
        operator_run.atomic_write_json(operator_run.marker_path(base_dir), closed)
        return True
    return _patch(operator_run, "close_run", fake)


def _mut_retention_deletes_current():
    real = operator_run.prune_run_markers
    return _patch(operator_run, "prune_run_markers", lambda base_dir, keep, now=None: real(base_dir, set(), now))


MUTATIONS = [
    ("ignore the current-run marker (pre-D11 read)", _mut_ignore_marker),
    ("accept every child-outcome sidecar regardless of run id", _mut_accept_any_sidecar),
    ("accept tokenless (legacy) sidecars as current", _mut_accept_tokenless),
    ("fold legacy summary child outcomes as current", _mut_legacy_children_current),
    ("never classify a dead/overdue run INCOMPLETE", _mut_never_incomplete),
    ("INCOMPLETE derived only, never persisted", _mut_convert_not_persisted),
    ("pick the operator log by newest mtime, not run id", _mut_newest_mtime_log),
    ("do not export BK_OPERATOR_RUN_ID to children", _mut_no_env_export),
    ("non-atomic marker write", _mut_non_atomic_write),
    ("final summary does not close the marker", _mut_no_close),
    ("close without run-id CAS", _mut_close_without_cas),
    ("no lease exclusion (concurrent runs)", _mut_no_lease_exclusion),
    ("retention may delete the current run", _mut_retention_deletes_current),
    ("persisted PENDING never expires", _mut_no_expiry),
    ("fold the previous run's reasons into the current status", _mut_fold_previous_when_pending),
]


def main() -> int:
    print("=" * 64)
    print("QC: RUN STATUS = CURRENT OPERATOR RUN (D11)")
    print("=" * 64)
    failures = run_suite()
    for n in sorted(set(NOTES)):
        print(f"[NOTE] {n}")
    if failures:
        for x in failures:
            print(f"[FAIL] {x}")
        print(f"[FAIL] baseline: {len(failures)} failure(s) across {len(CASES)} case groups")
        return 1
    print(f"[OK] baseline: {len(CASES)} case groups pass")
    if "--no-mutations" in sys.argv or (_UNDER_OPERATOR and "--mutations" not in sys.argv):
        print("[NOTE] mutation sweep skipped (inside an operator run / --no-mutations); run without flags to include it")
        return 0
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
