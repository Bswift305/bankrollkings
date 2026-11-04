"""QC: Elite alert HISTORY rule (v5 owner decision 6) -- /elite, grade/persist path, /elite/alerts/export.

A persisted line-move alert is a record of what a book showed at capture time, never a current executable
quote. It may show player + recorded line + recorded book ONLY with a trustworthy tz-aware UTC capture time
AND recorded source provenance, always labelled exactly
  "Historical alert — not a current executable quote"
with no price styling, no action and no path into a ticket/parlay. Without provenance, book and line are
WITHHELD. The CSV export obeys the same rule.

Proves (synthetic data in a temp DATA_DIR; services.qc_auth isolated owner; runtime snapshots stubbed; no
user-store writes):
  (1) row helper: provenance row keeps book/line + label + ET capture display; naive / non-UTC / future /
      unparseable / missing capture, or missing / unrecognised source -> book + line withheld.
  (2) /elite renders every history row with the exact label; the provenance row shows its recorded book +
      line + capture time; every withheld row's book and line appear NOWHERE on the page; the history block
      has no link, button, form, ticket/parlay path, action label or accent price styling.
  (3) /elite/alerts/export: HistoryLabel + ProvenanceStatus columns; book/line(-move) columns blank for every
      row without provenance; Urgency (action) never exported; the provenance row keeps its book + line.
  (4) persist records CapturedAtUTC (aware UTC) + SourceProvenance from the scanner; the scanner stamps its
      props-feed source; such a freshly persisted row passes the rule.
  (5) the Elite runtime snapshot key moved off the pre-rule v3 payloads.
Exit 0 on pass, 1 otherwise.
"""
from __future__ import annotations

import contextlib
import csv
import io
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("SECRET_KEY", "qc-elite-alert-history")

import pandas as pd  # noqa: E402

import app  # noqa: E402
from services import qc_auth  # noqa: E402

FAILS: list[str] = []
NOTES: list[str] = []
LABEL = "Historical alert — not a current executable quote"
NOW = datetime.now(timezone.utc)


def check(cond, msg):
    (NOTES if cond else FAILS).append(msg)


def _row(aid, player, book, line, captured, source, urgency="ACT"):
    return {"AlertId": aid, "FirstSeen": "2026-11-01 10:00:00", "LastSeen": f"2026-11-0{aid[-1]} 10:00:00",
            "Sport": "NBA", "Player": player, "Stat": "PTS", "Book": book, "Game": "Away Q @ Home Q",
            "OpenLine": line - 1.0, "CurrentLine": line, "SharpSide": "OVER", "ModelSide": "OVER",
            "Alignment": "ALIGNED", "Urgency": urgency, "OverMove": 4.0, "UnderMove": -4.0, "LineMove": 1.0,
            "Reliability": "ANCHOR", "TrueProb": 55, "Score": 10, "OutcomeState": "Pending", "ActualValue": "",
            "GameDate": "", "ResolvedAt": "", "CapturedAtUTC": captured, "SourceProvenance": source}


GOOD_SRC = "props_feed:NBA:data/props/NBA_Props.csv"
ROWS = [
    _row("a1", "Qcalert Provenanced", "QCBOOKPROV", 31.5, (NOW - timedelta(hours=30)).isoformat(timespec="seconds"), GOOD_SRC),
    _row("a2", "Qcalert Naive", "QCBOOKNAIVE", 41.5, "2026-11-01T10:00:00", GOOD_SRC),
    _row("a3", "Qcalert Nosource", "QCBOOKNOSRC", 42.5, NOW.isoformat(timespec="seconds"), ""),
    _row("a4", "Qcalert Offset", "QCBOOKOFFSET", 43.5, "2026-11-01T10:00:00+05:00", GOOD_SRC),
    _row("a5", "Qcalert Future", "QCBOOKFUTURE", 44.5, (NOW + timedelta(days=2)).isoformat(timespec="seconds"), GOOD_SRC),
    _row("a6", "Qcalert Garbage", "QCBOOKGARB", 45.5, "not-a-time", GOOD_SRC),
    _row("a7", "Qcalert Legacy", "QCBOOKLEGACY", 46.5, "", ""),
    _row("a8", "Qcalert Badsrc", "QCBOOKBADSRC", 47.5, NOW.isoformat(timespec="seconds"), "somewhere"),
]
WITHHELD = [r for r in ROWS if r["Book"] != "QCBOOKPROV"]


def qc_row_helper():
    good = app.elite_alert_history_row(ROWS[0])
    check(good["provenance_ok"] and good["book"] == "QCBOOKPROV" and good["line"] == "31.5"
          and good["history_label"] == LABEL and good["captured_at_utc"].endswith("+00:00")
          and good["captured_display"].endswith("ET") and good["source"] == GOOD_SRC,
          "(1) provenance row keeps recorded book + line, exact label, ET capture display, source")
    for r in WITHHELD:
        h = app.elite_alert_history_row(r)
        check(not h["provenance_ok"] and h["book"] is None and h["line"] is None and h["player"] == r["Player"]
              and h["history_label"] == LABEL and "provenance unavailable" in (h["provenance_note"] or ""),
              f"(1) {r['Player']}: book + line withheld, player kept, labelled, 'provenance unavailable'")
    check(app.ELITE_ALERT_HISTORY_LABEL == LABEL, "(1) the label constant is exactly the owner's wording")


@contextlib.contextmanager
def _sandbox():
    with tempfile.TemporaryDirectory(prefix="qc_elite_alerts_") as td:
        data = Path(td) / "data"
        (data / "tracking").mkdir(parents=True)
        pd.DataFrame(ROWS)[app.ELITE_ALERT_COLUMNS].to_csv(data / "tracking" / "Elite_LineMove_Alerts.csv", index=False)
        saved = {n: getattr(app, n) for n in ("DATA_DIR", "load_runtime_snapshot", "write_runtime_snapshot",
                                              "build_elite_cross_sport_candidates", "build_streak_heat_chart_service",
                                              "grade_manual_bet_logs")}
        app.DATA_DIR = data
        app.load_runtime_snapshot = lambda *a, **k: None
        app.write_runtime_snapshot = lambda *a, **k: None
        app.build_elite_cross_sport_candidates = lambda *a, **k: []
        app.build_streak_heat_chart_service = lambda *a, **k: []
        app.grade_manual_bet_logs = lambda *a, **k: 0
        try:
            yield data
        finally:
            for n, v in saved.items():
                setattr(app, n, v)


def _history_block(html: str) -> str:
    start = html.find("Recent Alerts")
    end = html.find("Best-Book Shopping Board", start)
    return html[start:end] if start >= 0 and end > start else ""


def qc_route_and_export():
    with _sandbox():
        with qc_auth.isolated_owner_client() as client:
            resp = client.get("/elite")
            html = resp.get_data(as_text=True)
            exp = client.get("/elite/alerts/export")
            csv_text = exp.get_data(as_text=True)
    check(resp.status_code == 200, f"(2) /elite renders for the isolated owner (status {resp.status_code})")
    block = _history_block(html)
    check(block.count(LABEL) == len(ROWS), f"(2) every history row carries the exact label ({block.count(LABEL)}/{len(ROWS)})")
    check("QCBOOKPROV" in block and "31.5" in block and "captured" in block and GOOD_SRC in block,
          "(2) provenance row shows recorded line + book + capture time + source")
    leaked = [r["Book"] for r in WITHHELD if r["Book"] in html] + \
             [str(r["CurrentLine"]) for r in WITHHELD if str(r["CurrentLine"]) in html]
    check(not leaked, f"(2) no withheld book or line appears anywhere on /elite ({leaked})")
    check(block.count("provenance unavailable") == len(WITHHELD), "(2) every withheld row says provenance unavailable")
    bad = [tok for tok in ("<a ", "<button", "<form", "href=", "onclick", "/parlay", "ticket", "badge-accent",
                           "var(--accent", "WINDOW CLOSING", ">ACT<", "Add to") if tok.lower() in block.lower()]
    check(block and not bad, f"(2) history block has no link/button/form/ticket path, action label or price styling ({bad})")

    rows = list(csv.DictReader(io.StringIO(csv_text)))
    check(exp.status_code == 200 and len(rows) == len(ROWS) and rows and list(rows[0])[:2] == ["HistoryLabel", "ProvenanceStatus"],
          f"(3) export: one row per alert with HistoryLabel + ProvenanceStatus first (status {exp.status_code})")
    by_player = {r["Player"]: r for r in rows}
    check(all(r["HistoryLabel"] == LABEL for r in rows), "(3) every exported row carries the exact label")
    good = by_player.get("Qcalert Provenanced", {})
    check(good.get("Book") == "QCBOOKPROV" and float(good.get("CurrentLine") or 0) == 31.5
          and good.get("ProvenanceStatus") == "RECORDED", "(3) provenance row keeps recorded book + line in the export")
    quote_cols = ("Book", "OpenLine", "CurrentLine", "LineMove", "OverMove", "UnderMove")
    blank = all(all(by_player[r["Player"]][c] == "" for c in quote_cols)
                and by_player[r["Player"]]["ProvenanceStatus"].startswith("UNAVAILABLE") for r in WITHHELD)
    check(blank, "(3) export blanks book + line(-move) columns for every row without provenance")
    check(all(r["Urgency"] == "" for r in rows) and "QCBOOKNAIVE" not in csv_text,
          "(3) no action label exported; withheld books absent from the CSV text")


def qc_persist_and_scanner():
    saved = (app.load_props, app.load_wnba_props, app.load_mlb_props)
    app.load_props = lambda *a, **k: pd.DataFrame([{
        "Player": "Qcscan Mover", "Stat": "PTS", "Book": "QCBOOKSCAN", "Game": "A @ H", "OpenLine": 20.5,
        "CurrentLine": 22.5, "Line": 22.5, "OpenOverOdds": -110, "OverOdds": -110, "OpenUnderOdds": -110,
        "UnderOdds": -110}])
    app.load_wnba_props = app.load_mlb_props = lambda *a, **k: pd.DataFrame()
    try:
        scans = app.build_elite_sharp_money_scanner([])
    finally:
        app.load_props, app.load_wnba_props, app.load_mlb_props = saved
    check(scans and scans[0].get("source_provenance") == "props_feed:NBA:data/props/NBA_Props.csv",
          "(4) scanner stamps each move with its props-feed source")
    with tempfile.TemporaryDirectory(prefix="qc_elite_persist_") as td:
        saved_dir = app.DATA_DIR
        app.DATA_DIR = Path(td)
        try:
            out = app.persist_elite_line_move_alerts(scans)
        finally:
            app.DATA_DIR = saved_dir
    rec = out.to_dict("records")[0] if len(out) else {}
    cap = app._elite_alert_capture_utc(rec.get("CapturedAtUTC"))
    check(cap is not None and abs((cap - datetime.now(timezone.utc)).total_seconds()) < 120
          and rec.get("SourceProvenance") == "props_feed:NBA:data/props/NBA_Props.csv"
          and app.elite_alert_history_row(rec)["provenance_ok"],
          "(4) persist records an aware-UTC CapturedAtUTC + SourceProvenance; the fresh row passes the rule")
    check({"CapturedAtUTC", "SourceProvenance"} <= set(app.ELITE_ALERT_COLUMNS),
          "(4) provenance columns are in ELITE_ALERT_COLUMNS (not silently dropped on read)")


def qc_snapshot_key():
    src = (HERE / "app.py").read_text(encoding="utf-8")
    check('snapshot_key = f"elite_dashboard_v4_' in src and 'snapshot_key = f"elite_dashboard_v3_' not in src,
          "(5) Elite snapshot key bumped to v4 (pre-rule v3 payloads are never served)")
    tpl = (HERE / "templates" / "elite_dashboard.html").read_text(encoding="utf-8")
    hist = tpl[tpl.find("Recent Alerts"):tpl.find("Best-Book Shopping Board")]
    check("row.Book" not in hist and "row.CurrentLine" not in hist and "entity_anchor" not in hist
          and not re.search(r"<a\s", hist), "(5) template history block reads only the display-safe fields, no links")


def main() -> int:
    for fn in (qc_row_helper, qc_route_and_export, qc_persist_and_scanner, qc_snapshot_key):
        try:
            fn()
        except Exception as exc:  # a crash is a failure, never a pass
            import traceback
            FAILS.append(f"{fn.__name__} crashed: {exc!r}\n{traceback.format_exc()}")
    print("=" * 64)
    print("QC: ELITE ALERT HISTORY (historical, provenance-gated, never executable)")
    print("=" * 64)
    for n in NOTES:
        print(f"[OK]   {n}")
    for f in FAILS:
        print(f"[FAIL] {f}")
    print(f"\n{len(NOTES)} passed, {len(FAILS)} failed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
