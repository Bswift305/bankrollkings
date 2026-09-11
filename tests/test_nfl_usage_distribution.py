"""Smoke test for services/nfl_usage_distribution (stdlib only).

Run:  python3 tests/test_nfl_usage_distribution.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.nfl_usage_distribution import (  # noqa: E402
    build_team_usage,
    classify_backfield,
    classify_receiver_room,
    usage_signal,
)

_fails = 0


def check(cond: bool, msg: str) -> None:
    global _fails
    if not cond:
        _fails += 1
    print(f"[{'  ok  ' if cond else ' FAIL '}] {msg}")


# ── classification unit checks ───────────────────────────────────────────────
check(classify_backfield([0.75, 0.18, 0.07]) == "bell_cow", "bell-cow backfield")
check(classify_backfield([0.55, 0.38, 0.07]) == "dual_back", "dual-back backfield (Detroit look)")
check(classify_backfield([0.42, 0.33, 0.25]) == "committee", "three-way committee")
check(classify_receiver_room([0.34, 0.20, 0.16]) == "wr_alpha", "alpha WR room")
check(classify_receiver_room([0.28, 0.26, 0.18]) == "wr_two_headed", "two-headed WR room")
check(classify_receiver_room([0.24, 0.22, 0.20, 0.18]) == "wr_spread", "spread WR room")

# ── end-to-end aggregation + signal ──────────────────────────────────────────
rows = [
    # DET dual backfield, Gibbs surging recently (development)
    {"player": "Jahmyr Gibbs", "team": "DET", "carries": 150, "targets": 55, "receptions": 44,
     "recent_carries": 78, "recent_targets": 26},
    {"player": "David Montgomery", "team": "DET", "carries": 140, "targets": 25, "receptions": 19,
     "recent_carries": 55, "recent_targets": 8},
    {"player": "Amon-Ra St. Brown", "team": "DET", "carries": 0, "targets": 110, "receptions": 82},
    {"player": "Jameson Williams", "team": "DET", "carries": 0, "targets": 58, "receptions": 34},
    {"player": "Tim Patrick", "team": "DET", "carries": 0, "targets": 40, "receptions": 26},
    # BUF bell-cow back
    {"player": "James Cook", "team": "BUF", "carries": 190, "targets": 45, "receptions": 36},
    {"player": "Ray Davis", "team": "BUF", "carries": 55, "targets": 12, "receptions": 9},
]

teams = build_team_usage(rows)
det = teams["DET"]
buf = teams["BUF"]
check(det.rb_scheme == "dual_back", f"DET detected dual_back (got {det.rb_scheme})")
check(det.wr_scheme == "wr_alpha", f"DET detected wr_alpha (got {det.wr_scheme})")
check(buf.rb_scheme == "bell_cow", f"BUF detected bell_cow (got {buf.rb_scheme})")

gibbs = next(p for p in det.players if p.player == "Jahmyr Gibbs")
monty = next(p for p in det.players if p.player == "David Montgomery")
check(gibbs.trend > 0, f"Gibbs shows positive development trend ({gibbs.trend})")

# Montgomery is RB2 here (fewer carries) — his rushing OVER should be supported.
monty_over = usage_signal(monty, det.rb_scheme, "RUSH_YDS", "OVER")
gibbs_over = usage_signal(gibbs, det.rb_scheme, "RUSH_YDS", "OVER")
print(f"   Gibbs RUSH OVER delta = {gibbs_over['score_delta']} {gibbs_over['tags']}")
print(f"   Monty RUSH OVER delta = {monty_over['score_delta']} {monty_over['tags']}")
check(gibbs_over["score_delta"] < 0, "committee lead-back rushing OVER is faded")
check(monty_over["score_delta"] > 0, "committee RB2 rushing OVER is supported")

# BUF bell-cow: Cook's rushing OVER supported, Ray Davis faded.
cook = next(p for p in buf.players if p.player == "James Cook")
ray = next(p for p in buf.players if p.player == "Ray Davis")
check(usage_signal(cook, buf.rb_scheme, "RUSH_YDS", "OVER")["score_delta"] > 0, "bell-cow lead rushing OVER supported")
check(usage_signal(ray, buf.rb_scheme, "RUSH_YDS", "OVER")["score_delta"] < 0, "bell-cow backup rushing OVER faded")

# DET alpha WR: St. Brown receiving OVER supported; WR2 faded.
arsb = next(p for p in det.players if p.player == "Amon-Ra St. Brown")
jw = next(p for p in det.players if p.player == "Jameson Williams")
check(usage_signal(arsb, det.wr_scheme, "REC_YDS", "OVER")["score_delta"] > 0, "alpha WR1 receiving OVER supported")
check(usage_signal(jw, det.wr_scheme, "REC_YDS", "OVER")["score_delta"] < 0, "secondary WR receiving OVER faded")

print(f"\n{'ALL CHECKS PASSED' if _fails == 0 else str(_fails) + ' CHECK(S) FAILED'}")
sys.exit(1 if _fails else 0)
