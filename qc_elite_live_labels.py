"""QC (adversarial): Elite LIVE line-movement scanner labels are FACTS, never directives (D14 / P1, 2026-11).

Contract: docs/elite_live_labels_d14.md. Proves (synthetic, offline; temp DATA_DIR; isolated owner client;
runtime snapshots stubbed; no network, no real data written):

  (1) no ACT / WINDOW CLOSING / HOLD / PASS / "sharp" / urgency / composite score in: scanner row payloads,
      the rendered /elite scanner block, the /elite/matchup-builder line-movement block, and the
      /elite/alerts/export CSV (even when legacy alert rows still hold ACT/HOLD/WINDOW CLOSING/PASS + Score).
  (2) the countdown ("Starts in N minutes") renders ONLY when the start time is verified (explicit UTC) AND the
      quote time is recorded AND fresh (<= 6h CLOCK A) AND the source is recorded (props-feed source + EventId +
      book) AND an executable quote exists (finite line + valid American price on the line-move side).
  (3) each missing/invalid input INDIVIDUALLY suppresses the label (naive / offset / garbage / missing start;
      missing / naive / future / stale quote time; missing source prefix / EventId / book; missing / NaN line;
      missing / sub-100 / wrong-side price) -- with a neutral note naming why, never a default label.
  (4) started / past events show no countdown.
  (5) historical alert rows never carry a live label (no "Starts in", no directive).
  (6) timezone edge: on a UTC clock after 8pm ET the countdown and the ET start display are correct (aware UTC
      arithmetic; the label module never calls datetime.now()).
  (7) render-time computation: a cached page snapshot cannot freeze a countdown (a snapshot built when the
      event was upcoming shows no label once it has started).
  (8) neutral order: soonest verified start first, then larger move; no score field drives it.
  (M) move states (owner decision 2026-11-04): exact vocabulary LINE_MOVED / PRICE_MOVED / LINE_AND_PRICE_MOVED /
      NO_QUALIFYING_MOVE / INSUFFICIENT_DATA; line (points) and price (American-odds cents) keep separate actual
      deltas + thresholds and are never combined; only moved states are listed.
  (5') no ANCHOR/WATCH/AVOID hit-rate tier, model probability or "edge" in the scanner, matchup line-move block or
      export; (6) every stale / missing-source / missing-kickoff / non-executable row carries no urgency or action
      language; (8) explicit ?moves_sort=line|price and ?moves_state= work, unknown values fall back to neutral.
  (9) templates + copy: no row.urgency / row.sharp_side / row.score; learning module + Elite preview copy carry
      no "sharp" / WINDOW CLOSING wording.
Exit 0 on pass, 1 otherwise.
"""
from __future__ import annotations

import contextlib
import csv
import inspect
import io
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("SECRET_KEY", "qc-elite-live-labels")

import pandas as pd  # noqa: E402

import app  # noqa: E402
from services import elite_live_labels as ell  # noqa: E402
from services import qc_auth  # noqa: E402

FAILS: list[str] = []
NOTES: list[str] = []
DIRECTIVE_RE = re.compile(r"\b(ACT|HOLD|PASS|WINDOW CLOSING)\b")
# Urgency / action language (case-insensitive) that a live row must never carry.
ACTION_RE = re.compile(r"\b(act now|bet now|bet this|take it|hammer|lock|window clos\w*|closing fast|hurry|urgent|"
                       r"don'?t miss|before it moves|act|hold|pass|play now)\b", re.I)
AUTHORITY_RE = re.compile(r"\b(ANCHOR|WATCH|AVOID|UNMATCHED|UNPROVEN|true prob|edge)\b", re.I)
SHARP_RE = re.compile(r"sharp", re.I)
SRC = "props_feed:NBA:data/props/NBA_Props.csv"
# Route tests run at a FIXED instant (13:00 ET) so the Eastern-slate countdown window is deterministic.
FIXED_NOW = datetime(2026, 11, 4, 18, 0, 0, tzinfo=timezone.utc)


def check(cond, msg):
    (NOTES if cond else FAILS).append(msg)


def _z(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _base(now, **over):
    row = {"sport": "NBA", "player": "Qclive Base", "stat": "PTS", "book": "DraftKings", "game": "Away L@Home L",
           "source_provenance": SRC, "event_id": "evt123", "current_line": 22.5, "open_line": 20.5,
           "move_side": "OVER", "model_side": "OVER", "alignment": "ALIGNED", "move_state": "LINE_MOVED",
           "line_move": 2.0, "line_delta": 2.0, "over_price_delta_cents": 0.0, "under_price_delta_cents": 0.0,
           "over_price": -115.0, "under_price": -105.0,
           "event_commence_utc": _z(now + timedelta(minutes=24, seconds=30)),
           "quote_updated_utc": _z(now - timedelta(minutes=10))}
    row.update(over)
    return row


# ------------------------------------------------------------------------------------------------ pure
def qc_pure():
    now = datetime(2026, 11, 4, 18, 0, 0, tzinfo=timezone.utc)
    label, disp, reasons = ell.start_facts(_base(now), now)
    check(label == "Starts in 24 minutes" and not reasons and disp and disp.endswith("ET"),
          f"(2) all inputs valid -> 'Starts in 24 minutes' + ET start display (got {label!r}, {disp!r})")
    cases = {
        "start missing": ({"event_commence_utc": ""}, ell.START_UNVERIFIED),
        "start naive": ({"event_commence_utc": "2026-11-04T18:24:30"}, ell.START_UNVERIFIED),
        "start +05:00 offset": ({"event_commence_utc": "2026-11-04T23:24:30+05:00"}, ell.START_UNVERIFIED),
        "start garbage": ({"event_commence_utc": "tonight"}, ell.START_UNVERIFIED),
        "start None": ({"event_commence_utc": None}, ell.START_UNVERIFIED),
        "quote time missing": ({"quote_updated_utc": ""}, ell.QUOTE_TIME_MISSING),
        "quote time naive": ({"quote_updated_utc": "2026-11-04T17:50:00"}, ell.QUOTE_TIME_MISSING),
        "quote time future": ({"quote_updated_utc": _z(now + timedelta(minutes=30))}, ell.QUOTE_TIME_MISSING),
        "quote stale (6h01m)": ({"quote_updated_utc": _z(now - timedelta(hours=6, minutes=1))}, ell.QUOTE_STALE),
        "source prefix missing": ({"source_provenance": ""}, ell.SOURCE_MISSING),
        "source unrecognised": ({"source_provenance": "somewhere"}, ell.SOURCE_MISSING),
        "event id missing": ({"event_id": ""}, ell.SOURCE_MISSING),
        "book missing": ({"book": ""}, ell.SOURCE_MISSING),
        "line missing": ({"current_line": None}, ell.NO_EXECUTABLE_QUOTE),
        "line NaN": ({"current_line": float("nan")}, ell.NO_EXECUTABLE_QUOTE),
        "side price missing": ({"over_price": None}, ell.NO_EXECUTABLE_QUOTE),
        "side price sub-100": ({"over_price": -50.0}, ell.NO_EXECUTABLE_QUOTE),
        "only other-side price": ({"over_price": None, "under_price": -110.0}, ell.NO_EXECUTABLE_QUOTE),  # synthetic-fixture
        "move side unknown": ({"move_side": ""}, ell.NO_EXECUTABLE_QUOTE),
    }
    for name, (over, code) in cases.items():
        label, _d, reasons = ell.start_facts(_base(now, **over), now)
        check(label is None and reasons == [code],
              f"(3) {name} ALONE suppresses the label with exactly [{code}] (got {label!r}, {reasons})")
    ok_edge = ell.start_facts(_base(now, quote_updated_utc=_z(now - timedelta(hours=5, minutes=59))), now)[0]
    check(ok_edge is not None, "(2) a 5h59m-old quote is still fresh (CLOCK A boundary)")
    for name, delta in (("at start", timedelta(0)), ("10 min after start", -timedelta(minutes=10)),
                        ("yesterday", -timedelta(days=1))):
        label, _d, reasons = ell.start_facts(_base(now, event_commence_utc=_z(now + delta)), now)
        check(label is None and ell.EVENT_STARTED in reasons, f"(4) {name}: no countdown (EVENT_STARTED)")
    ann = ell.annotate([_base(now, quote_updated_utc="")], now)[0]
    check(ann["start_label"] is None and ann["start_note"].startswith("No countdown:")
          and "quote update time not recorded" in ann["start_note"],
          "(3) annotated row without a label carries a neutral note naming why")
    for secs, want in ((30, "Starts in under 1 minute"), (60, "Starts in 1 minute"), (59 * 60 + 59, "Starts in 59 minutes"),
                       (3600, "Starts in 1 h 0 min"), (3 * 86400 + 7200, "Starts in 3 days 2 h")):
        check(ell.countdown_text(secs) == want, f"(2) countdown text {secs}s -> {want!r} (got {ell.countdown_text(secs)!r})")
    # (6) UTC prod clock after 8pm ET: 01:30Z on Nov 5 == 8:30 PM ET Nov 4 (EST, after the Nov 1 DST end).
    late = datetime(2026, 11, 5, 1, 30, tzinfo=timezone.utc)
    lab, disp, _r = ell.start_facts(_base(late, event_commence_utc="2026-11-05T02:00:00Z",
                                          quote_updated_utc="2026-11-05T01:20:00Z"), late)
    check(lab == "Starts in 30 minutes" and disp == "Wed Nov 04, 09:00 PM ET",
          f"(6) UTC clock after 8pm ET: 'Starts in 30 minutes', start shown as Nov 04 09:00 PM ET (got {lab!r}, {disp!r})")
    lab2, _d2, r2 = ell.start_facts(_base(late, event_commence_utc="2026-11-05T01:00:00Z",
                                          quote_updated_utc="2026-11-05T00:20:00Z"), late)
    check(lab2 is None and ell.EVENT_STARTED in r2, "(6) a game that started at 8pm ET is past on the UTC clock (no countdown)")
    src = inspect.getsource(ell)
    check("datetime.now(" not in src and ".astimezone()" not in src,
          "(6) label module never reads the ambient clock/zone (no datetime.now(), no bare astimezone())")
    # (Q4) countdown only inside the current Eastern slate day; a later slate shows its start time only
    noon = datetime(2026, 11, 4, 18, 0, tzinfo=timezone.utc)      # 13:00 ET
    for cz, want_label, name in (("2026-11-05T04:30:00Z", "Starts in 10 h 30 min", "23:30 ET same day"),
                                 ("2026-11-05T05:30:00Z", None, "00:30 ET next day"),
                                 ("2026-11-05T18:00:00Z", None, "tomorrow afternoon")):
        lab, disp, rs = ell.start_facts(_base(noon, event_commence_utc=cz, quote_updated_utc=_z(noon)), noon)
        ok = (lab == want_label) and (want_label is not None or (rs == [ell.OUTSIDE_SLATE] and disp))
        check(ok, f"(Q4) start {name}: {'countdown' if want_label else 'no countdown, start time shown'} ({lab!r}, {rs})")
    # (8) DEFAULT neutral order: start time, then most recent quote update -- never move size or a score
    q = lambda m: _z(now - timedelta(minutes=m))  # noqa: E731
    rows = [_base(now, player="Qc Unverified", event_commence_utc="", line_delta=5.0),
            _base(now, player="Qc Later", event_commence_utc=_z(now + timedelta(hours=3)), line_delta=9.0),
            _base(now, player="Qc Started", event_commence_utc=_z(now - timedelta(hours=1)), line_delta=30.0),
            _base(now, player="Qc Soon Older", event_commence_utc=_z(now + timedelta(hours=1)), quote_updated_utc=q(50),
                  line_delta=8.0, over_price_delta_cents=-90.0),
            _base(now, player="Qc Soon Newer", event_commence_utc=_z(now + timedelta(hours=1)), quote_updated_utc=q(5),
                  line_delta=0.5)]
    order = [r["player"] for r in ell.annotate(rows, now)]
    check(order == ["Qc Soon Newer", "Qc Soon Older", "Qc Later", "Qc Unverified", "Qc Started"],
          f"(8) default order: soonest verified start, then newest quote update; unverified, then started; move size "
          f"ignored ({order})")
    by_line = [r["player"] for r in ell.annotate(rows, now, sort="line")]
    check(by_line == ["Qc Started", "Qc Later", "Qc Soon Older", "Qc Unverified", "Qc Soon Newer"],
          f"(8) explicit sort=line orders by |line delta| (points) only ({by_line})")
    prow = [_base(now, player="Qc P small", over_price_delta_cents=-15.0, under_price_delta_cents=None),
            _base(now, player="Qc P big", over_price_delta_cents=None, under_price_delta_cents=60.0, line_delta=0.0),
            _base(now, player="Qc P none", over_price_delta_cents=None, under_price_delta_cents=None, line_delta=99.0)]
    by_price = [r["player"] for r in ell.annotate(prow, now, sort="price")]
    check(by_price == ["Qc P big", "Qc P small", "Qc P none"],
          f"(8) explicit sort=price orders by |price delta| (cents) only; a big LINE move does not rank by price ({by_price})")
    filt = ell.annotate([_base(now, player="a", move_state="LINE_MOVED"), _base(now, player="b", move_state="PRICE_MOVED")],
                        now, state="PRICE_MOVED")
    check([r["player"] for r in filt] == ["b"], "(8) explicit filter by move state")


def qc_move_states():
    """Owner decision 2/3: separate units, exact state vocabulary, documented thresholds."""
    c = ell.classify_move
    check(ell.LINE_MOVE_MIN_POINTS == 0.5 and ell.PRICE_MOVE_MIN_CENTS == 10,
          "(M) thresholds are per unit: line 0.5 points, price 10 American-odds cents")
    check(ell.MOVE_STATES == ("LINE_MOVED", "PRICE_MOVED", "LINE_AND_PRICE_MOVED", "NO_QUALIFYING_MOVE", "INSUFFICIENT_DATA"),
          "(M) exact factual state vocabulary")
    check([ell.american_cents(x) for x in (-110, -150, 105, 120, -100, 100, 50, None)] == [-10.0, -50.0, 5.0, 20.0, 0.0, 0.0, None, None],  # synthetic-fixture
          "(M) American-odds cents scale (-105 -> +105 is 10 cents; |odds|<100 invalid)")
    m = c(20.5, 22.5, -110, -110, -110, -110)  # synthetic-fixture
    check(m["move_state"] == "LINE_MOVED" and m["line_delta"] == 2.0 and m["over_price_delta_cents"] == 0.0
          and m["move_side"] == "OVER", "(M) line 20.5 -> 22.5, prices flat: LINE_MOVED, line_delta +2.0, side OVER")
    m = c(20.5, 20.5, -110, -125, -110, 105)  # synthetic-fixture
    check(m["move_state"] == "PRICE_MOVED" and m["line_delta"] == 0.0 and m["over_price_delta_cents"] == -15.0
          and m["under_price_delta_cents"] == 15.0 and m["move_side"] == "OVER",
          "(M) line flat, over -110 -> -125 (-15c), under -110 -> +105 (+15c): PRICE_MOVED, side OVER (over got pricier)")
    m = c(20.5, 20.0, -110, -150, -110, 120)  # synthetic-fixture
    check(m["move_state"] == "LINE_AND_PRICE_MOVED" and m["line_delta"] == -0.5 and m["move_side"] == "UNDER",
          "(M) both qualify: LINE_AND_PRICE_MOVED; side follows the line (down -> UNDER), each delta kept in its own unit")
    m = c(20.5, 20.5, -110, -115, -110, -105)  # synthetic-fixture
    check(m["move_state"] == "NO_QUALIFYING_MOVE" and m["move_side"] is None,
          "(M) 5-cent price change, flat line: NO_QUALIFYING_MOVE")
    m = c(20.5, 20.9, -110, -119, None, None)  # synthetic-fixture
    check(m["move_state"] == "NO_QUALIFYING_MOVE", "(M) 0.4 pt + 9 cents never combine into a qualifying move")
    m = c(None, 21.5, None, -110, "", None)  # synthetic-fixture
    check(m["move_state"] == "INSUFFICIENT_DATA" and m["line_delta"] is None and m["over_price_delta_cents"] is None,
          "(M) no open line and no open prices: INSUFFICIENT_DATA (never zero-filled)")
    m = c(20.5, 20.5, -110, -125, -110, -125)  # synthetic-fixture
    check(m["move_state"] == "PRICE_MOVED" and m["move_side"] is None,
          "(M) both sides got pricier equally: PRICE_MOVED with no single side (never guessed)")
    lab = ell.start_facts(dict(_base(datetime(2026, 11, 4, 18, tzinfo=timezone.utc)), move_side=""),
                          datetime(2026, 11, 4, 18, tzinfo=timezone.utc))
    check(lab[0] is None and ell.NO_EXECUTABLE_QUOTE in lab[2], "(M) no single move side -> no countdown")


# ------------------------------------------------------------------------------------------------ app
def _props_frame(now):
    def r(player, **over):
        base = {"Player": player, "Stat": "PTS", "Book": "DraftKings", "Game": "Away L@Home L", "OpenLine": 20.5,
                "CurrentLine": 22.5, "Line": 22.5, "OpenOverOdds": -110, "OverOdds": -150, "OpenUnderOdds": -110,  # synthetic-fixture
                "UnderOdds": 120, "EventId": "evtlive",
                "EventCommenceAtUTC": _z(now + timedelta(minutes=24, seconds=50)),
                "SourceUpdatedAtUTC": _z(now - timedelta(minutes=5))}
        base.update(over)
        return base
    return pd.DataFrame([
        r("Qclive Ready"),
        r("Qclive Nostart", EventCommenceAtUTC=""),
        r("Qclive Naivestart", EventCommenceAtUTC=(now + timedelta(minutes=40)).strftime("%Y-%m-%d %H:%M")),
        r("Qclive Stale", SourceUpdatedAtUTC=_z(now - timedelta(hours=7))),
        r("Qclive Noquotetime", SourceUpdatedAtUTC=""),
        r("Qclive Noevent", EventId=""),
        r("Qclive Noprice", OverOdds=None),
        r("Qclive Started", EventCommenceAtUTC=_z(now - timedelta(minutes=15))),
        r("Qclive Conflict", OpenOverOdds=-150, OverOdds=-110, OpenUnderOdds=120, UnderOdds=-130),  # synthetic-fixture
        r("Qclive Priceonly", OpenLine=22.5, CurrentLine=22.5, OpenOverOdds=-110, OverOdds=-125, OpenUnderOdds=-110,  # synthetic-fixture
          UnderOdds=-105),
        r("Qclive Flat", OpenLine=22.5, CurrentLine=22.5, OpenOverOdds=-110, OverOdds=-115, OpenUnderOdds=-110,  # synthetic-fixture
          UnderOdds=-105),
        r("Qclive Nodata", OpenLine=None, OpenOverOdds=None, OpenUnderOdds=None),
    ])


LEGACY_ALERTS = [
    {"AlertId": f"l{i}", "FirstSeen": "2026-11-01 10:00:00", "LastSeen": f"2026-11-0{i} 10:00:00", "Sport": "NBA",
     "Player": f"Qchist Legacy{i}", "Stat": "PTS", "Book": "QCHISTBOOK", "Game": "A@H", "OpenLine": 1, "CurrentLine": 2,
     "SharpSide": "OVER", "ModelSide": "OVER", "Alignment": "ALIGNED", "Urgency": urg, "OverMove": 4, "UnderMove": -4,
     "LineMove": 1, "Reliability": "WATCH", "TrueProb": 55, "Score": 17.5, "OutcomeState": "Pending", "ActualValue": "",
     "GameDate": "", "ResolvedAt": "", "CapturedAtUTC": "2026-11-01T10:00:00+00:00", "SourceProvenance": SRC}
    for i, urg in enumerate(("ACT", "HOLD", "WINDOW CLOSING", "PASS"), start=1)
]


@contextlib.contextmanager
def _sandbox(now, candidates=None, snapshot=None):
    with tempfile.TemporaryDirectory(prefix="qc_elite_live_") as td:
        data = Path(td) / "data"
        (data / "tracking").mkdir(parents=True)
        # a PRE-D14 archive (retired columns present): it must be read as history in the current schema
        pd.DataFrame(LEGACY_ALERTS).to_csv(data / "tracking" / "Elite_LineMove_Alerts.csv",
                                                                     index=False)
        names = ("DATA_DIR", "load_runtime_snapshot", "write_runtime_snapshot", "build_elite_cross_sport_candidates",
                 "build_streak_heat_chart_service", "grade_manual_bet_logs", "load_props", "load_wnba_props",
                 "load_mlb_props", "build_elite_line_move_scanner")
        saved = {n: getattr(app, n) for n in names}
        frame = _props_frame(now)
        real_scanner = saved["build_elite_line_move_scanner"]
        saved_clock = ell.utc_now
        ell.utc_now = lambda: now          # render-time labels use the fixed instant
        app.DATA_DIR = data
        app.load_runtime_snapshot = (lambda *a, **k: snapshot) if snapshot is not None else (lambda *a, **k: None)
        app.write_runtime_snapshot = lambda *a, **k: None
        # The other cockpit builders get no candidates (they need full candidate rows); the REAL scanner gets
        # the synthetic model sides so model-vs-move is exercised.
        app.build_elite_cross_sport_candidates = lambda *a, **k: []
        app.build_elite_line_move_scanner = lambda _c: real_scanner(list(candidates or []))
        app.build_streak_heat_chart_service = lambda *a, **k: []
        app.grade_manual_bet_logs = lambda *a, **k: 0
        app.load_props = lambda *a, **k: frame.copy()
        app.load_wnba_props = app.load_mlb_props = lambda *a, **k: pd.DataFrame()
        try:
            yield data
        finally:
            for n, v in saved.items():
                setattr(app, n, v)
            ell.utc_now = saved_clock


def _block(html, start_marker, end_marker):
    s = html.find(start_marker)
    e = html.find(end_marker, s + 1) if s >= 0 else -1
    return html[s:e] if s >= 0 and e > s else ""


def _row_html(block, player):
    i = block.find(player)
    if i < 0:
        return ""
    s = block.rfind("<tr", 0, i)
    e = block.find("</tr>", i)
    return block[s:e]


CANDS = [{"sport": "NBA", "player": "Qclive Ready", "stat": "PTS", "direction": "OVER", "reliability": "WATCH",
          "matchup": "Away L@Home L", "score": 1, "true_prob": 55},
         {"sport": "NBA", "player": "Qclive Conflict", "stat": "PTS", "direction": "UNDER", "reliability": "AVOID",
          "matchup": "Away L@Home L", "score": 1, "true_prob": 40}]


def qc_scanner_and_routes():
    now = FIXED_NOW
    with _sandbox(now, candidates=CANDS):
        scans = app.build_elite_line_move_scanner(CANDS)
        with qc_auth.isolated_owner_client() as client:
            resp = client.get("/elite")
            html = resp.get_data(as_text=True)
            exp = client.get("/elite/alerts/export")
            csv_text = exp.get_data(as_text=True)
            mb = client.get("/elite/matchup-builder?sport=NBA&matchup=Away%20L%40Home%20L")
            mb_html = mb.get_data(as_text=True)
            by_line = client.get("/elite?moves_sort=line").get_data(as_text=True)
            only_price = client.get("/elite?moves_state=PRICE_MOVED").get_data(as_text=True)
            bogus = client.get("/elite?moves_sort=score&moves_state=ACT")
        persisted = pd.read_csv(app.DATA_DIR / "tracking" / "Elite_LineMove_Alerts.csv", keep_default_na=False)
        migrated = app.load_elite_line_move_alerts()
        hist_rows = [app.elite_alert_history_row(r) for r in migrated.to_dict("records")]
    # (1) payload
    bad_keys = [k for r in scans for k in r if k in {"urgency", "sharp_side", "score", "confidence"}]
    bad_vals = [v for r in scans for v in r.values() if isinstance(v, str) and (DIRECTIVE_RE.search(v) or SHARP_RE.search(v))]
    check(scans and not bad_keys and not bad_vals,
          f"(1) scanner payload: no urgency/sharp_side/score/confidence keys, no directive or 'sharp' values "
          f"({len(scans)} rows; keys {bad_keys}; values {bad_vals})")
    check(all(r.get("move_side") in {"OVER", "UNDER"} for r in scans), "(1) each row states its line-move side")
    states = {r["player"]: r.get("move_state") for r in scans}
    check(states.get("Qclive Ready") == "LINE_AND_PRICE_MOVED" and states.get("Qclive Priceonly") == "PRICE_MOVED"
          and "Qclive Flat" not in states and "Qclive Nodata" not in states
          and all(v in ("LINE_MOVED", "PRICE_MOVED", "LINE_AND_PRICE_MOVED") for v in states.values()),
          f"(M) scanner: listed rows carry LINE_MOVED/PRICE_MOVED/LINE_AND_PRICE_MOVED; NO_QUALIFYING_MOVE and "
          f"INSUFFICIENT_DATA rows are not listed as moves ({states})")
    ready_row = next((r for r in scans if r["player"] == "Qclive Ready"), {})
    check(ready_row.get("line_delta") == 2.0 and ready_row.get("over_price_delta_cents") == -40.0
          and ready_row.get("under_price_delta_cents") == 30.0,
          "(M) actual deltas kept per unit: line +2.0 pts, over -40 cents, under +30 cents")
    check(not any(k in r for r in scans for k in ("reliability", "true_prob", "over_move", "under_move")),
          "(5') scanner rows carry no hit-rate tier, model probability or implied-point move")
    check(not hasattr(app, "build_elite_sharp" + "_money_scanner"),
          "(1) the scanner exists only under its neutral name (retired internal name removed)")
    # /elite scanner block
    check(resp.status_code == 200, f"(1) /elite renders ({resp.status_code})")
    scan_block = _block(html, 'data-live-line-moves="1"', "</table>")
    check(bool(scan_block), "(1) live scanner block found on /elite")
    check(not DIRECTIVE_RE.search(scan_block) and not SHARP_RE.search(scan_block)
          and not re.search(r"\bscore\b|confidence", scan_block, re.I),
          f"(1) /elite scanner block: no ACT/HOLD/PASS/WINDOW CLOSING, no 'sharp', no score/confidence "
          f"({DIRECTIVE_RE.findall(scan_block)[:3]} {SHARP_RE.findall(scan_block)[:3]})")
    check("WINDOW CLOSING" not in html and ">ACT<" not in html, "(1) whole /elite page: no WINDOW CLOSING / ACT badge")
    ready = _row_html(scan_block, "Qclive Ready")
    check(re.search(r"Starts in 2[34] minutes", ready) is not None and 'data-start-label="1"' in ready,
          "(2) the fully-evidenced row shows 'Starts in 24 minutes' on /elite")
    n_labels = scan_block.count('data-start-label="1"')
    check(n_labels == 3, f"(3) only the fully-evidenced rows carry a countdown ({n_labels} labels; Ready + Conflict + "
                         "Priceonly)")
    check(not AUTHORITY_RE.search(scan_block),
          f"(5') /elite scanner block: no ANCHOR/WATCH/AVOID tier, model probability or 'edge' "
          f"({AUTHORITY_RE.findall(scan_block)[:4]})")
    check("Line and price moved" in ready and "Line +2.0 pts" in ready and "(-40¢)" in ready and "(+30¢)" in ready,
          "(M) /elite shows the state and each actual delta in its own unit")
    for player, why in (("Qclive Nostart", "start time not verified"), ("Qclive Naivestart", "start time not verified"),
                        ("Qclive Stale", "quote older than 6h"), ("Qclive Noquotetime", "quote update time not recorded"),
                        ("Qclive Noevent", "quote source not recorded"),
                        ("Qclive Noprice", "no complete price on the line-move side"),
                        ("Qclive Started", "Historical -- event started; not a current executable quote")):
        rh = _row_html(scan_block, player)
        check(rh and "Starts in" not in rh and why in rh and 'data-start-note="1"' in rh,
              f"(3) {player}: no countdown, neutral note says '{why}'")
        stripped = re.sub(r"<[^>]+>", " ", rh)
        check(not ACTION_RE.search(stripped) and not DIRECTIVE_RE.search(stripped),
              f"(6) {player}: no urgency or action language at all ({ACTION_RE.findall(stripped)[:3]})")
    conflict = _row_html(scan_block, "Qclive Conflict")
    check("Model side differs from the line-move side" in conflict and not DIRECTIVE_RE.search(conflict),
          "(1) model conflict is stated as a fact (no HOLD); AVOID reliability shows as data (no PASS)")
    # (5) history block
    hist = _block(html, "Recent Alerts", "Best-Book Shopping Board")
    check(hist and "Starts in" not in hist and not DIRECTIVE_RE.search(hist) and not SHARP_RE.search(hist),
          "(5) historical alert rows: no countdown, no directive, no 'sharp' (legacy ACT/HOLD/WINDOW CLOSING/PASS rows)")
    # matchup builder
    mb_block = _block(mb_html, 'data-live-line-moves="1"', "Best-Book Edges")
    check(mb.status_code == 200 and "Qclive Ready" in mb_block, f"(1) matchup builder renders its line-move block ({mb.status_code})")
    check(not DIRECTIVE_RE.search(mb_block) and not SHARP_RE.search(mb_block) and not re.search(r"\bscore\b", mb_block, re.I),
          "(1) matchup builder line-move block: no directive, no 'sharp', no score")
    check(re.search(r"Starts in 2[34] minutes", mb_block) is not None and "No countdown:" in mb_block,
          "(2)(3) matchup builder: countdown for the evidenced row, neutral notes for the others")
    check("hold or pass" not in mb_html.lower(), "(1) matchup notes no longer call conflicts 'hold or pass signals'")
    check(not AUTHORITY_RE.search(mb_block) and not ACTION_RE.search(re.sub(r"<[^>]+>", " ", mb_block)),
          "(5')(6) matchup builder line-move block: no tier/probability/edge, no action language")
    lb = _block(by_line, 'data-live-line-moves="1"', "</table>")
    check(lb.find("Qclive Ready") >= 0 and lb.find("Qclive Priceonly") > lb.find("Qclive Ready"),
          "(8) /elite?moves_sort=line: a 2.0-pt line move lists before a price-only move (explicit user sort)")
    pb = _block(only_price, 'data-live-line-moves="1"', "</table>")
    check("Qclive Priceonly" in pb and "Qclive Ready" not in pb, "(8) /elite?moves_state=PRICE_MOVED filters to price-only moves")
    check(bogus.status_code == 200, "(8) unknown sort/state values are ignored (neutral default), never an error")
    # (1) export
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    header = list(rows[0]) if rows else []
    check(exp.status_code == 200 and rows and not {"Urgency", "Score", "Sharp" "Side", "Reliability", "TrueProb", "OverMove",
                                                    "UnderMove"} & set(header)
          and {"LineMoveSide", "MoveState", "OverPriceDeltaCents", "UnderPriceDeltaCents"} <= set(header),
          "(1) export: no Urgency/Score/SharpSide/Reliability/TrueProb; LineMoveSide + MoveState + cent deltas present")
    check(not re.search(r"\b(ANCHOR|WATCH|AVOID)\b", csv_text), "(5') export text: no ANCHOR/WATCH/AVOID tier")
    check(not DIRECTIVE_RE.search(csv_text) and not SHARP_RE.search(csv_text) and "17.5" not in csv_text,
          "(1) export text: no ACT/HOLD/PASS/WINDOW CLOSING, no 'sharp', no legacy score value")
    # persisted new rows carry no directive/score
    new = persisted[persisted["Player"].astype(str).str.startswith("Qclive")]
    retired = {"Urgency", "Score", "Sharp" "Side", "Reliability", "TrueProb", "OverMove", "UnderMove"}
    check(len(new) > 0 and not retired & set(persisted.columns) and list(persisted.columns) == app.ELITE_ALERT_COLUMNS
          and new["MoveState"].isin(["LINE_MOVED", "PRICE_MOVED", "LINE_AND_PRICE_MOVED"]).all(),
          f"(H) the archive is rewritten in the current schema: retired columns gone, MoveState recorded ({len(new)} rows)")
    legacy_hist = [h for h in hist_rows if h["player"].startswith("Qchist")]
    check(len(legacy_hist) == 4 and all(h["side"] == "OVER" for h in legacy_hist)
          and list(migrated.columns) == app.ELITE_ALERT_COLUMNS and not retired & set(migrated.columns),
          "(H) pre-D14 archive rows are read as history: old side migrated to LineMoveSide, ACT/HOLD/WINDOW CLOSING/"
          "PASS urgencies, scores, ANCHOR/WATCH tiers and implied-point moves dropped")
    check(all(h["history_label"] == app.ELITE_ALERT_HISTORY_LABEL for h in legacy_hist),
          "(H) legacy rows keep only the explicit historical / non-executable label")
    started = _row_html(scan_block, "Qclive Started")
    check("Last captured" in started and 'data-historical="1"' in started and "Now 22.5" not in started,
          "(5) a started event is shown as historical (last captured, not 'Now'), never live")
    check("as of " in ready and "capture time not recorded" in ready,
          "(T) the move shows its quote update time (ET) and discloses that the open capture time is not recorded")


def qc_render_time():
    """(7) a snapshot built while the event was upcoming must not keep its countdown once it has started."""
    now = FIXED_NOW
    upcoming = _base(now, player="Qcsnap Upcoming", event_commence_utc=_z(now + timedelta(minutes=90)))
    started = _base(now, player="Qcsnap Started", event_commence_utc=_z(now - timedelta(minutes=5)))
    with _sandbox(now):
        with app.app.test_request_context("/elite"):
            ctx = app.build_elite_dashboard_context(None, "")
    ctx["line_moves"] = [upcoming, started]          # as if frozen into a cached snapshot earlier
    payload = {"payload": ctx}
    with _sandbox(now, snapshot=payload):
        try:
            with qc_auth.isolated_owner_client() as client:
                html = client.get("/elite").get_data(as_text=True)
        except Exception as exc:
            html = f"render error {exc!r}"
    block = _block(html, 'data-live-line-moves="1"', "</table>")
    up = _row_html(block, "Qcsnap Upcoming")
    st = _row_html(block, "Qcsnap Started")
    check(re.search(r"Starts in 1 h (29|30) min", up) is not None,
          "(7) snapshot row with a future start: countdown computed now ('Starts in 1 h 29/30 min')")
    check(st and "Starts in" not in st and "Historical" in st,
          "(7) snapshot row whose start has passed: no countdown even though it came from a cached payload")
    check(block.find("Qcsnap Upcoming") < block.find("Qcsnap Started"), "(8) render-time order: upcoming before started")


def qc_static():
    for tpl, start, end in (("elite_dashboard.html", "Line Movement Scanner", "clv-report-card"),
                            ("elite_matchup_builder.html", "Line Movement In This Game", "Best-Book Edges")):
        full = (HERE / "templates" / tpl).read_text(encoding="utf-8")
        src = full[full.find(start):full.find(end)]
        check(src and not any(t in src for t in ("row.urgency", "row.sharp_side", "row.score", "WINDOW CLOSING",
                                                 "Sharp Side", "Sharp Money")),
              f"(9) {tpl} line-movement section: no row.urgency/row.sharp_side/row.score/WINDOW CLOSING/Sharp wording")
        check("row.urgency" not in full and "row.sharp_side" not in full, f"(9) {tpl}: no urgency/sharp_side anywhere")
    mod = next((m for m in app.build_elite_learning_modules() if m.get("slug") == "line-movement"), {})
    txt = " ".join(str(v) for v in mod.values())
    check(mod and not SHARP_RE.search(txt) and "WINDOW CLOSING" not in txt,
          "(9) Elite learning module 'Reading Line Movement': no 'sharp' / WINDOW CLOSING wording")
    prev = app.GLOBAL_FEATURE_PREVIEWS.get("elite", {})
    ptxt = " ".join([str(prev.get("preview_copy")), str(prev.get("subtitle"))] +
                    [" ".join(s) for s in prev.get("steps", [])])
    check(prev and not SHARP_RE.search(ptxt), "(9) Elite preview copy: no 'sharp-money' / 'sharp side' wording")
    scan_src = inspect.getsource(app.build_elite_line_move_scanner)
    check(not DIRECTIVE_RE.search(scan_src.replace("ACT/HOLD/WINDOW CLOSING/PASS", "")) and "'score'" not in scan_src,
          "(9) scanner source assigns no directive and no composite score")
    hist = app.elite_alert_history_row(LEGACY_ALERTS[2])
    check(not any(k.startswith("start_") for k in hist) and "Urgency" not in str(hist.keys()),
          "(5) history row helper exposes no live start/urgency fields")


def main() -> int:
    for fn in (qc_pure, qc_move_states, qc_scanner_and_routes, qc_render_time, qc_static):
        try:
            fn()
        except Exception as exc:  # a crash is a failure, never a pass
            import traceback
            FAILS.append(f"{fn.__name__} crashed: {exc!r}\n{traceback.format_exc()}")
    print("=" * 64)
    print("QC: ELITE LIVE LABELS (facts only; countdown fail-closed)")
    print("=" * 64)
    for n in NOTES:
        print(f"[OK]   {n}")
    for f in FAILS:
        print(f"[FAIL] {f}")
    print(f"\n{len(NOTES)} passed, {len(FAILS)} failed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
