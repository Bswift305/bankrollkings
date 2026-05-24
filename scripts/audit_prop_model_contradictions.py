from __future__ import annotations

from pathlib import Path
import sys
import csv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as appmod


CORE_STATS = {"PTS", "AST", "REB", "3PM", "STL", "BLK"}
OUTPUT_DIR = Path("data") / "debug"
CSV_PATH = OUTPUT_DIR / "prop_model_contradictions_latest.csv"
TXT_PATH = OUTPUT_DIR / "prop_model_contradictions_latest.txt"


def capture_route_context(path: str, fn):
    captured = {}
    original_render_template = appmod.render_template

    def fake_render_template(template_name, **context):
        captured["template"] = template_name
        captured["context"] = context
        return context

    appmod.render_template = fake_render_template
    try:
        with appmod.app.test_request_context(path):
            fn()
    finally:
        appmod.render_template = original_render_template

    return captured.get("context", {})


def recent_series_values(playoff_logs, player: str, team: str, stat: str, limit: int = 3):
    if playoff_logs.empty or stat not in playoff_logs.columns:
        return []
    pl = playoff_logs[(playoff_logs["Player"] == player) & (playoff_logs["Team"] == team)].copy()
    if pl.empty:
        return []
    if "Date" in pl.columns:
        pl["Date"] = appmod.pd.to_datetime(pl["Date"], errors="coerce")
        pl = pl.sort_values("Date", ascending=False)
    values = []
    for val in pl[stat].tolist():
        try:
            values.append(float(val))
        except Exception:
            continue
        if len(values) >= limit:
            break
    return values


def contradiction_reason(prop, recent_values):
    stat = str(prop.get("stat", "")).upper()
    if stat not in CORE_STATS:
        return None

    direction = str(prop.get("direction", "")).upper()
    line = prop.get("line")
    projected = prop.get("core_projected_value")
    over_prob = prop.get("core_baseline_over_prob")
    under_prob = prop.get("core_baseline_under_prob")
    if line is None:
        return None

    if recent_values and len(recent_values) >= 3:
        all_under = all(value < float(line) for value in recent_values[:3])
        all_over = all(value > float(line) for value in recent_values[:3])
        if direction == "OVER" and all_under and projected is not None and projected <= float(line):
            return "Final play is OVER despite three straight recent misses and projection below line."
        if direction == "UNDER" and all_over and projected is not None and projected >= float(line):
            return "Final play is UNDER despite three straight recent clears and projection above line."

    if direction == "OVER" and over_prob is not None and under_prob is not None:
        if float(over_prob) < 45 and float(under_prob) >= float(over_prob) + 10:
            return "Final play is OVER even though baseline under probability is materially stronger."
    if direction == "UNDER" and over_prob is not None and under_prob is not None:
        if float(under_prob) < 45 and float(over_prob) >= float(under_prob) + 10:
            return "Final play is UNDER even though baseline over probability is materially stronger."

    return None


def run_audit():
    props_context = capture_route_context("/props?postseason=1&sample=current&model_debug=1", appmod.props)
    props = props_context.get("props", [])
    playoff_logs = appmod.load_playoff_gamelogs()

    findings = []
    for prop in props:
        player = str(prop.get("player", "")).strip()
        team = str(prop.get("team", "")).strip()
        stat = str(prop.get("stat", "")).strip().upper()
        if not player or not team or stat not in CORE_STATS:
            continue

        recent_values = recent_series_values(playoff_logs, player, team, stat)
        reason = contradiction_reason(prop, recent_values)
        if not reason:
            continue

        findings.append(
            {
                "player": player,
                "team": team,
                "stat": stat,
                "line": prop.get("line"),
                "direction": prop.get("direction"),
                "projection": prop.get("core_projected_value"),
                "over_prob": prop.get("core_baseline_over_prob"),
                "under_prob": prop.get("core_baseline_under_prob"),
                "recent_values": ", ".join(f"{value:g}" for value in recent_values),
                "reason": reason,
            }
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with CSV_PATH.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "player",
                "team",
                "stat",
                "line",
                "direction",
                "projection",
                "over_prob",
                "under_prob",
                "recent_values",
                "reason",
            ],
        )
        writer.writeheader()
        writer.writerows(findings)

    summary_lines = [
        "Prop Model Contradiction Audit",
        f"Rows checked: {len(props)}",
        f"Contradictions found: {len(findings)}",
        "",
    ]
    for finding in findings[:25]:
        summary_lines.append(
            f"{finding['player']} {finding['stat']} {finding['line']} {finding['direction']} | "
            f"Proj {finding['projection']} | O {finding['over_prob']} / U {finding['under_prob']} | "
            f"Recent {finding['recent_values']} | {finding['reason']}"
        )
    TXT_PATH.write_text("\n".join(summary_lines), encoding="utf-8")

    print(f"rows_checked={len(props)}")
    print(f"contradictions={len(findings)}")
    print(f"csv={CSV_PATH}")
    print(f"txt={TXT_PATH}")
    if findings:
        print("top_issue=" + summary_lines[4])


if __name__ == "__main__":
    run_audit()
