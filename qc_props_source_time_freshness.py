#!/usr/bin/env python3
"""QC: NBA/WNBA executable-props freshness is governed ONLY by the zone-explicit SourceUpdatedAtUTC.

b12eec3 remediation (2026-11-08). The central NBA/WNBA props gate (props_executable_meta / props_feed_status /
_executable_props_frame) read the zone-less `LastUpdated` fetch stamp as an Eastern wall clock. On prod that
stamp is written in UTC, so a fresh feed published at 13:08Z looked like 18:08Z -- ~5h in the future -- and
every NBA prop price was withheld (unavailable_reason='future_timestamp') until ~18:03Z, after each publication.

The contract proven here (synthetic fixtures; no data files, no network):
  * freshness, age, label and skew come ONLY from SourceUpdatedAtUTC with an explicit offset;
  * a zone-less, malformed or missing source time is unknown -> 'no_timestamp' (prices withheld, fail closed);
  * a misleading LastUpdated never changes the verdict, in any process zone (UTC / New York / Los Angeles),
    on DST and non-DST dates;
  * a genuinely future source time beyond the 5-minute allowance -> 'future_timestamp'; within it -> executable
    and labelled clock_skew_tolerated;
  * older than 6h -> 'stale' (never future-dated); the 6h rule is never loosened;
  * row level: rows without a valid source time, or beyond the allowance, are dropped from the executable frame;
  * the gate makes no network access even with an API key present.
Exits 0 when every check holds, 1 otherwise.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
os.environ.setdefault("SECRET_KEY", "qc-props-source-time")

PASSED: list[str] = []
FAILED: list[str] = []


def check(cond, msg):
    (PASSED if cond else FAILED).append(msg)


# ---- the probe: evaluated in a child process per process zone ---------------------------------------------
PROBE = r'''
import json, os, socket, sys, urllib.request
os.environ.setdefault("SECRET_KEY", "qc-props-source-time")
os.environ["ODDS_API_KEY"] = "qc-dummy-key-not-real"
ATTEMPTS = []
def _deny(*a, **k):
    ATTEMPTS.append(1)
    raise OSError("QC: network blocked")
socket.create_connection = _deny
socket.socket.connect = _deny
socket.getaddrinfo = _deny
urllib.request.urlopen = _deny
sys.path.insert(0, sys.argv[1])
import pandas as pd
import app

def frame(src, lu, n=3):
    return pd.DataFrame([{"Player": f"P{i}", "Stat": "Points", "Line": 20.5, "OverOdds": -110, "UnderOdds": -110,
                          "Book": "DraftKings", "Game": "A@B", "EventId": "ev", "EventCommenceAtUTC": "2026-11-09T02:00:00Z",
                          "LastUpdated": lu, "SourceUpdatedAtUTC": (src[i] if isinstance(src, list) else src)}
                         for i in range(n)])

def verdict(df, now):
    m = app.props_executable_meta(df, now=now)
    fr, mm = app._executable_props_frame("nba", df, now=now)
    return {k: m.get(k) for k in ("executable", "unavailable_reason", "prices_withheld", "last_updated_utc",
                                  "age_hours", "clock_skew_tolerated", "freshness_source")} | {"rows": len(fr),
            "dropped": mm.get("future_rows_dropped", 0), "warning": m.get("warning", "")}

C = {}
# prod shape 2026-11-08: zone-less UTC LastUpdated 13:08, explicit sources 13:06:41..13:08:05
prod = frame(["2026-11-08T13:06:41Z", "2026-11-08T13:07:30Z", "2026-11-08T13:08:05Z"], "2026-11-08 13:08")
C["prod_fresh_1310"] = verdict(prod, "2026-11-08T13:10:00Z")
C["prod_fresh_1400"] = verdict(prod, "2026-11-08T14:00:00Z")
C["prod_stale_1920"] = verdict(prod, "2026-11-08T19:20:00Z")
# DST (EDT, July) and non-DST (EST, January) with a misleading zone-less LastUpdated equal to the UTC wall clock
C["dst_fresh"] = verdict(frame("2026-07-15T17:00:00Z", "2026-07-15 17:00"), "2026-07-15T17:30:00Z")
C["nodst_fresh"] = verdict(frame("2026-01-15T17:00:00Z", "2026-01-15 17:00"), "2026-01-15T17:30:00Z")
# misleading LastUpdated far in the past must not make a fresh source stale
C["lu_past_src_fresh"] = verdict(frame("2026-11-08T13:08:00Z", "2026-11-01 08:00"), "2026-11-08T13:20:00Z")
# explicit offsets other than Z resolve to the same instant
C["offset_equivalent"] = verdict(frame("2026-11-08T08:08:00-05:00", "x"), "2026-11-08T13:20:00Z")
# unknown source times -> no_timestamp
C["src_missing"] = verdict(frame("", "2026-11-08 13:08"), "2026-11-08T13:20:00Z")
C["src_zoneless"] = verdict(frame("2026-11-08 13:08:00", "2026-11-08 13:08"), "2026-11-08T13:20:00Z")
C["src_malformed"] = verdict(frame("not-a-time", "2026-11-08 13:08"), "2026-11-08T13:20:00Z")
nocol = frame("2026-11-08T13:08:00Z", "2026-11-08 13:08").drop(columns=["SourceUpdatedAtUTC"])
C["src_column_absent"] = verdict(nocol, "2026-11-08T13:20:00Z")
# genuinely future vs clock-skew allowance
C["future_30m"] = verdict(frame("2026-11-08T13:50:00Z", "2026-11-08 13:08"), "2026-11-08T13:20:00Z")
C["skew_3m"] = verdict(frame("2026-11-08T13:23:00Z", "2026-11-08 13:08"), "2026-11-08T13:20:00Z")
# row level: 1 valid, 1 missing, 1 future -> only the valid row is executable
C["rows_mixed"] = verdict(frame(["2026-11-08T13:08:00Z", "", "2026-11-08T15:00:00Z"], "2026-11-08 13:08"),
                          "2026-11-08T13:20:00Z")
# WNBA-shaped stale feed with blank source times (prod 2026-11-08) -> withheld truthfully
C["wnba_blank_sources"] = verdict(frame("", "2026-10-31 13:05"), "2026-11-08T13:20:00Z")
C["stale_7h"] = verdict(frame("2026-11-08T06:00:00Z", "2026-11-08 13:08"), "2026-11-08T13:20:00Z")
C["_network_attempts"] = len(ATTEMPTS)
print("QCJSON" + json.dumps(C, sort_keys=True))
'''


def run_probe(tz: str) -> dict:
    env = dict(os.environ)
    env["TZ"] = tz
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run([sys.executable, "-c", PROBE, str(REPO)], capture_output=True, text=True, env=env,
                       timeout=600, cwd=str(REPO))
    line = next((l for l in p.stdout.splitlines() if l.startswith("QCJSON")), None)
    if line is None:
        return {"_error": (p.stderr or p.stdout)[-800:]}
    return json.loads(line[len("QCJSON"):])


def main() -> int:
    zones = ["UTC", "America/New_York", "America/Los_Angeles"]
    results = {z: run_probe(z) for z in zones}
    for z, r in results.items():
        check("_error" not in r, f"probe ran under TZ={z} ({r.get('_error', 'ok')[:200] if '_error' in r else 'ok'})")
    base = results["UTC"]
    if "_error" in base:
        return report()
    for z in zones[1:]:
        if "_error" not in results[z]:
            check(results[z] == base, f"identical verdicts under TZ={z} as under UTC (no process-zone dependence)")

    c = base
    f = c["prod_fresh_1310"]
    check(f["executable"] and f["rows"] == 3 and f["last_updated_utc"] == "2026-11-08T13:08:05Z"
          and f["freshness_source"] == "SourceUpdatedAtUTC",
          f"fresh NBA feed is executable immediately after publication, aged from its source time ({f})")
    check(c["prod_fresh_1400"]["executable"] and c["prod_fresh_1400"]["age_hours"] == 0.87,
          f"same feed at 14:00Z: executable, age 0.87h from 13:08:05Z ({c['prod_fresh_1400']})")
    s = c["prod_stale_1920"]
    check(not s["executable"] and s["unavailable_reason"] == "stale" and s["prices_withheld"] and s["rows"] == 0,
          f"same feed at 19:20Z becomes STALE normally, never future-dated ({s})")
    for k in ("dst_fresh", "nodst_fresh", "lu_past_src_fresh", "offset_equivalent"):
        check(c[k]["executable"] and c[k]["rows"] == 3 and c[k]["warning"] == "",
              f"{k}: explicit source time governs; misleading LastUpdated ignored; no stale warning ({c[k]})")
    check(c["offset_equivalent"]["last_updated_utc"] == "2026-11-08T13:08:00Z",
          "an explicit -05:00 offset canonicalizes to the same UTC instant")
    for k in ("src_missing", "src_zoneless", "src_malformed", "src_column_absent", "wnba_blank_sources"):
        v = c[k]
        check(not v["executable"] and v["unavailable_reason"] == "no_timestamp" and v["prices_withheld"]
              and v["rows"] == 0 and v["last_updated_utc"] is None,
              f"{k}: unknown source time -> no_timestamp, prices withheld, no zone guessed ({v})")
    fu = c["future_30m"]
    check(not fu["executable"] and fu["unavailable_reason"] == "future_timestamp" and fu["prices_withheld"],
          f"a genuinely future source time (+30 min) fails closed as future_timestamp ({fu})")
    sk = c["skew_3m"]
    check(sk["executable"] and sk["clock_skew_tolerated"] is True and sk["rows"] == 3,
          f"+3 min is within the 5-minute allowance: executable and labelled ({sk})")
    rm = c["rows_mixed"]
    check(rm["executable"] and rm["rows"] == 1 and rm["dropped"] == 2,
          f"row level: missing-source and future-source rows are dropped, the valid row stays ({rm})")
    st = c["stale_7h"]
    check(not st["executable"] and st["unavailable_reason"] == "stale" and "7.3h ago" in st["warning"]
          and "ET" in st["warning"], f"7h-old source -> stale, withheld, warning shows the real source time ({st})")
    check(c["_network_attempts"] == 0, "the gate attempted no network access with an API key present")
    return report()


def report() -> int:
    print("=" * 72)
    print("QC: PROPS FRESHNESS = SourceUpdatedAtUTC ONLY (no zone guessed for LastUpdated)")
    print("=" * 72)
    for m in PASSED:
        print(f"[OK]   {m}")
    for m in FAILED:
        print(f"[FAIL] {m}")
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
