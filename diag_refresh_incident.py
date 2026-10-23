"""Daily-refresh incident diagnostic — reads the production operator logs + feed artifacts and prints a
structured incident report (chronology, first failure per provider, provider failure table, artifact
preservation, customer-impact). Read-only; stdlib only; prints NO credential values (API keys in command
lines and error messages are redacted).

Run on production (where the logs + data live), e.g.:

    cd /opt/bankrollkings && venv/bin/python3 diag_refresh_incident.py            # latest log
    cd /opt/bankrollkings && venv/bin/python3 diag_refresh_incident.py --log logs/daily_operator_20261023_130000.log

It does NOT hit the network or touch secrets, so it is safe to run anytime. The network / credential /
quota / disk probes are intentionally left to the shell block in docs/refresh_incident_2026-10-23.md
(those need the service environment and are better run as shell).
"""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
DATA_DIR = BASE_DIR / "data"
ENV_PATH = BASE_DIR / ".env"
COOLDOWN_PATH = LOG_DIR / ".diag_probe_cooldown.json"
DEFAULT_COOLDOWN = 600  # seconds; one health call per provider at most this often (unless --force)

# Redact anything that looks like a secret so the report is safe to paste.
_REDACTIONS = [
    (re.compile(r'(--api[-_]?key[=\s]+)\S+', re.I), r'\1<REDACTED>'),
    (re.compile(r'((?:api[_-]?key|apikey|key|token|secret|authorization|bearer)["\']?\s*[:=]\s*["\']?)[A-Za-z0-9._\-]{6,}', re.I), r'\1<REDACTED>'),
    # response identifiers (request/correlation/trace ids) in JSON or headers
    (re.compile(r'("(?:requestId|request_id|requestID|correlationId|correlation_id|traceId|trace_id|id)"\s*:\s*")[^"]+', re.I), r'\1<REDACTED_ID>'),
    (re.compile(r'\b[0-9a-fA-F]{16,}\b'), '<REDACTED_HEX>'),
    (re.compile(r'(apiKey=)[^&\s"\']+', re.I), r'\1<REDACTED>'),
    (re.compile(r'([?&](?:api[_-]?key|apikey|key|token)=)[^&\s"\']+', re.I), r'\1<REDACTED>'),
]


def _sanitize(text: str) -> str:
    out = text or ""
    for pat, repl in _REDACTIONS:
        out = pat.sub(repl, out)
    return out


# Provider family + the public surface each step feeds (for the failure table + customer impact).
def _provider_for(label: str, command: str) -> str:
    l, c = (label or "").lower(), (command or "").lower()
    if "odds feed health" in l or "qc_odds_feed" in c:
        return "Odds API (health guard)"
    if "preseason" in l:
        return "Odds API game lines (NFL preseason)"
    if "first-half" in l or "first_half" in c:
        return "Odds API per-event (1H)"
    if "player props" in l or "refresh_football_props" in c or "player_props" in c:
        return "Odds API player props"
    if "line movement" in l or "game lines" in l or "fetch_game_lines" in c:
        return "Odds API game lines"
    if "futures" in l:
        return "Odds API futures"
    if "season-long" in l or "season_markets" in c:
        return "Season-long markets (provider-neutral)"
    if "cfb" in l or "ncaaf" in l or "cfbd" in c or "cfb_data" in c:
        return "CFBD (results/lines/coaches/ATS)"
    if "weather" in l:
        return "Open-Meteo weather"
    if "final scores" in l or "fetch_final_scores" in c:
        return "ESPN scoreboard"
    if "nflverse" in c or "player_week" in c or "ngs" in c or "gamelogs" in c:
        return "nflverse"
    if "injur" in l:
        return "Injury feeds"
    return "internal / cross-sport"


STEP_RE = re.compile(r'^\[([A-Z][A-Za-z ()/\-]*)\]\s+(.*)$')


def parse_log(path: Path) -> dict:
    """Parse one daily_operator log into {started, finished, sports, steps:[{status,label,command,output}]}."""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    started = finished = sports = ""
    steps = []
    cur = None
    for ln in lines:
        if ln.startswith("Started:"):
            started = ln.split(":", 1)[1].strip()
            continue
        if ln.startswith("Finished:"):
            finished = ln.split(":", 1)[1].strip()
            continue
        if ln.startswith("Sports:"):
            sports = ln.split(":", 1)[1].strip()
            continue
        m = STEP_RE.match(ln)
        if m and ("PASS" in m.group(1) or "FAIL" in m.group(1) or "SKIP" in m.group(1) or "TIMEOUT" in m.group(1)):
            cur = {"status": m.group(1).strip(), "label": m.group(2).strip(), "command": "", "output": []}
            steps.append(cur)
            continue
        if cur is not None:
            if ln.startswith("Command:"):
                cur["command"] = ln.split(":", 1)[1].strip()
            else:
                cur["output"].append(ln)
    for s in steps:
        s["output"] = "\n".join(s["output"]).strip()
    return {"path": path, "started": started, "finished": finished, "sports": sports, "steps": steps}


def _counts(parsed):
    c = {"PASS": 0, "FAIL": 0, "SKIP": 0, "TIMEOUT": 0, "other": 0}
    for s in parsed["steps"]:
        st = s["status"]
        key = "PASS" if "PASS" in st else "FAIL" if "FAIL" in st else "SKIP" if "SKIP" in st else "TIMEOUT" if "TIMEOUT" in st else "other"
        c[key] += 1
    return c


def _first_fail(parsed):
    for s in parsed["steps"]:
        if "FAIL" in s["status"]:
            return s
    return None


def _first_error_line(output: str) -> str:
    for ln in (output or "").splitlines():
        s = ln.strip()
        if re.search(r'error|exception|traceback|http|401|403|429|timeout|refused|ssl|quota|missing|invalid', s, re.I):
            return _sanitize(s)[:300]
    # fall back to the last non-empty line
    nonempty = [l for l in (output or "").splitlines() if l.strip()]
    return _sanitize(nonempty[-1])[:300] if nonempty else "(no output captured)"


def _age(path: Path):
    try:
        st = path.stat()
        hrs = (time.time() - st.st_mtime) / 3600.0
        return st.st_size, hrs
    except OSError:
        return None, None


# Curated feed -> (provider, public surface) map for the age / artifact table.
FEEDS = [
    ("odds/NBA_Odds.csv", "Odds API game lines", "NBA board / lines"),
    ("odds/WNBA_Odds.csv", "Odds API game lines", "WNBA board / lines"),
    ("odds/NFL_Odds.csv", "Odds API game lines", "NFL game-lines board"),
    ("schedules/NCAAF_Odds.csv", "Odds API / CFBD lines", "CFB game-lines board"),
    ("props/NFL_Props.csv", "Odds API player props", "NFL props board"),
    ("props/NCAAF_Props.csv", "Odds API player props", "CFB props"),
    ("props/NBA_Props.csv", "Odds API player props", "NBA props board"),
    ("props/WNBA_Props.csv", "Odds API player props", "WNBA props board"),
    ("props/MLB_Props.csv", "Odds API player props", "MLB props board"),
    ("tracking/NFL_AllPropResults.csv", "graded record (nflverse)", "Riding-the-Wave / Heating Up / milestones"),
    ("tracking/NFL_PropLines_Graded.csv", "graded record (nflverse)", "prop-line scoreboard"),
]


# --------------------------------------------------------------------------------------------------
# Secret-safe provider health probes. Each makes EXACTLY ONE request per provider, loads credentials
# internally (env -> .env), prints HTTP status + nonsecret quota headers + a sanitized error, and
# NEVER prints or persists the key, the query string, the Authorization header, or response ids.
# Cooldown-guarded so it cannot be hammered. --probe runs these; the default run makes no network call.
# --------------------------------------------------------------------------------------------------
def _load_env_file(path: Path) -> dict:
    vals = {}
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return vals


def _get_key(names):
    """Return (var_name, key) from the process env, else from .env. Never logged."""
    import os
    for n in names:
        v = os.environ.get(n)
        if v and v.strip():
            return n, v.strip()
    envf = _load_env_file(ENV_PATH)
    for n in names:
        if envf.get(n):
            return n, envf[n].strip()
    return None, None


def _cooldown(provider: str, cooldown: int, force: bool):
    data = {}
    try:
        data = json.loads(COOLDOWN_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    last = int(data.get(provider, 0) or 0)
    remaining = cooldown - int(time.time() - last)
    if (not force) and remaining > 0:
        return False, remaining
    data[provider] = int(time.time())
    try:
        COOLDOWN_PATH.parent.mkdir(parents=True, exist_ok=True)
        COOLDOWN_PATH.write_text(json.dumps(data), encoding="utf-8")   # timestamps only, never keys
    except OSError:
        pass
    return True, 0


def _http_once(req, timeout=15):
    """One request. Returns (status, headers_lower, body_text). Network errors raise."""
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read(2000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        hdrs = {k.lower(): v for k, v in (e.headers.items() if e.headers else [])}
        return e.code, hdrs, (e.read(2000).decode("utf-8", "replace") if hasattr(e, "read") else "")


def probe_odds(cooldown: int, force: bool):
    print("\n  [Odds API] one free /v4/sports health call (reports account quota; consumes no credits)")
    name, key = _get_key(("ODDS_API_KEY", "THE_ODDS_API_KEY"))
    if not key:
        print("    no Odds key in env or .env (ODDS_API_KEY / THE_ODDS_API_KEY) — run where .env is readable")
        return
    ok, rem = _cooldown("odds", cooldown, force)
    if not ok:
        print(f"    SKIPPED — cooldown {rem}s remaining (pass --force to override)")
        return
    from urllib.parse import quote
    req = urllib.request.Request("https://api.the-odds-api.com/v4/sports?apiKey=" + quote(key, safe=""),
                                 headers={"User-Agent": "bk-diag/1.0"})
    try:
        status, hdr, body = _http_once(req)
    except Exception as e:
        print(f"    NETWORK/DNS/TLS error: {type(e).__name__}: {_sanitize(str(e))[:160]}  -> infra/availability")
        return
    remaining, used = hdr.get("x-requests-remaining"), hdr.get("x-requests-used")
    print(f"    HTTP {status}  (key var {name}, value redacted; query string redacted)")
    print(f"    quota headers: x-requests-remaining={remaining}  x-requests-used={used}")
    if status != 200 or (remaining is not None and str(remaining).strip() in ("0", "0.0")):
        print(f"    body: {_sanitize(body)[:200]}")
    # classification
    if remaining is not None and str(remaining).strip() in ("0", "0.0"):
        print("    => CONFIRMED: Odds credits EXHAUSTED (x-requests-remaining=0).")
    elif status in (401, 403):
        print(f"    => CONFIRMED: Odds AUTH failure (HTTP {status}).")
    elif status == 200:
        print("    => Odds key valid AND has quota. If paid fetches still fail, it is NOT exhaustion — "
              "capture a paid-fetch error body separately.")


def probe_cfbd(cooldown: int, force: bool):
    print("\n  [CFBD] one authenticated /conferences health call")
    name, key = _get_key(("CFBD_API_KEY",))
    if not key:
        print("    no CFBD_API_KEY in env or .env — run where .env is readable")
        return
    ok, rem = _cooldown("cfbd", cooldown, force)
    if not ok:
        print(f"    SKIPPED — cooldown {rem}s remaining (pass --force to override)")
        return
    req = urllib.request.Request("https://api.collegefootballdata.com/conferences",
                                 headers={"Authorization": "Bearer " + key, "User-Agent": "bk-diag/1.0",
                                          "Accept": "application/json"})
    try:
        status, hdr, body = _http_once(req)
    except Exception as e:
        print(f"    NETWORK/DNS/TLS error: {type(e).__name__}: {_sanitize(str(e))[:160]}  -> infra/availability")
        return
    print(f"    HTTP {status}  (Authorization: Bearer <redacted>)")
    if status != 200:
        print(f"    body: {_sanitize(body)[:200]}")
    # classification
    if status in (401, 403):
        print(f"    => CONFIRMED: CFBD AUTH failure (HTTP {status}) — key invalid/expired/forbidden.")
    elif status == 200:
        print("    => CFBD auth OK — the CFB refresh failure is elsewhere (schema/endpoint/rate), NOT the key.")
    elif status == 429:
        print("    => CFBD rate-limited (HTTP 429).")


def run_probes(cooldown: int, force: bool):
    print("=" * 78)
    print("BANKROLL KINGS — PROVIDER HEALTH PROBE (one request per provider; no secrets printed)")
    print("=" * 78)
    probe_odds(cooldown, force)
    probe_cfbd(cooldown, force)
    print("\nClassification: 429 OUT_OF_USAGE_CREDITS or x-requests-remaining=0 => Odds exhaustion; "
          "401/403 => auth; HTTP 200 + schema/validation error => provider-contract change; "
          "DNS/TLS/timeout => infrastructure.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Daily-refresh incident diagnostic (read-only, no secrets).")
    ap.add_argument("--log", help="Specific daily_operator log to analyze (default: the most recent).")
    ap.add_argument("--history", type=int, default=12, help="How many recent logs to include in the chronology.")
    ap.add_argument("--probe", action="store_true",
                    help="Make ONE secret-safe health request per provider (Odds, CFBD) and classify it. "
                         "No log analysis. Credentials loaded internally and never printed.")
    ap.add_argument("--force", action="store_true", help="Override the per-provider probe cooldown.")
    ap.add_argument("--cooldown", type=int, default=DEFAULT_COOLDOWN,
                    help=f"Minimum seconds between probes of the same provider (default {DEFAULT_COOLDOWN}).")
    args = ap.parse_args()

    if args.probe:
        return run_probes(args.cooldown, args.force)

    if args.log:
        target = Path(args.log)
        if not target.is_absolute() and not target.exists():
            target = BASE_DIR / target
        if not target.exists():
            print(f"Log not found: {target}")
            return 2
        log_dir = target.parent
    else:
        log_dir = LOG_DIR
        logs0 = sorted(log_dir.glob("daily_operator_*.log"))
        if not logs0:
            print(f"No daily_operator logs under {log_dir}")
            return 2
        target = logs0[-1]
    logs = sorted(log_dir.glob("daily_operator_*.log")) or [target]

    print("=" * 78)
    print("BANKROLL KINGS — DAILY-REFRESH INCIDENT DIAGNOSTIC")
    print("=" * 78)

    # ---- 1. Chronology across recent runs ----
    print("\n## 1. Incident chronology (recent daily_operator runs)")
    recent = logs[-args.history:]
    last_all_pass = None
    first_degraded = None
    for lp in recent:
        p = parse_log(lp)
        c = _counts(p)
        ff = _first_fail(p)
        tag = "ALL-PASS" if c["FAIL"] == 0 else f"DEGRADED (first FAIL: {ff['label'] if ff else '?'})"
        if c["FAIL"] == 0:
            last_all_pass = lp.name
        elif first_degraded is None:
            first_degraded = lp.name
        print(f"  {lp.name}  start={p['started'] or '?'}  "
              f"PASS={c['PASS']} FAIL={c['FAIL']} SKIP={c['SKIP']} steps={len(p['steps'])}  -> {tag}")
    print(f"\n  Last fully-successful run : {last_all_pass or '(none in window)'}")
    print(f"  First degraded run        : {first_degraded or '(none in window)'}")

    # ---- Target run detail + execution mode ----
    p = parse_log(target)
    c = _counts(p)
    completed = bool(p["finished"])
    many_after_fail = c["PASS"] > 0 and c["FAIL"] > 1 and len(p["steps"]) > 20
    mode = ("continue-on-error (ran every step; FAILs are INDEPENDENT, not a cascade)"
            if completed and many_after_fail else
            "abort-on-first-FAIL (steps after the first FAIL did NOT run)")
    print(f"\n## Target run: {target.name}")
    print(f"  started={p['started']}  finished={p['finished'] or '(no Finished line -> run did not complete)'}")
    print(f"  sports={p['sports']}  PASS={c['PASS']} FAIL={c['FAIL']} SKIP={c['SKIP']} steps={len(p['steps'])}")
    print(f"  execution mode: {mode}")

    # ---- 2. First actual failure (overall) ----
    print("\n## 2. First failure (sanitized exception / HTTP status)")
    ff = _first_fail(p)
    if ff is None:
        print("  No FAIL in this run.")
    else:
        print(f"  Step    : {ff['label']}")
        print(f"  Provider: {_provider_for(ff['label'], ff['command'])}")
        print(f"  Command : {_sanitize(ff['command'])}")
        print(f"  First error line: {_first_error_line(ff['output'])}")
        print("  --- sanitized tail of step output ---")
        tail = "\n".join(_sanitize(ff['output']).splitlines()[-18:])
        print("  " + tail.replace("\n", "\n  "))

    # ---- 2b. First failure PER PROVIDER FAMILY (item 2) -- from the log, no new API calls ----
    # Real operator steps carry a "Command:" line; nested '[FAIL] foo exited with code 1' summaries
    # inside a step's captured stdout do NOT. Aggregate each real step with its nested children so the
    # actual HTTP body / exception (which lands under a child) is surfaced.
    def _full_body(steps, i):
        parts = [steps[i]["output"]]
        j = i + 1
        while j < len(steps) and not steps[j]["command"]:
            child = steps[j]
            parts.append(f"[{child['status']}] {child['label']}")
            if child["output"]:
                parts.append(child["output"])
            j += 1
        return "\n".join(x for x in parts if x).strip()

    print("\n## 2b. First failure per provider family (sanitized; from this log only)")
    families = ["Odds API (health guard)", "Odds API game lines", "Odds API player props",
                "Odds API futures", "Odds API per-event (1H)", "Odds API game lines (NFL preseason)",
                "CFBD (results/lines/coaches/ATS)", "ESPN scoreboard", "nflverse"]
    real_fail_idx = [i for i, s in enumerate(p["steps"]) if "FAIL" in s["status"] and s["command"]]
    seen = set()
    for fam in families:
        idx = next((i for i in real_fail_idx
                    if _provider_for(p["steps"][i]["label"], p["steps"][i]["command"]) == fam), None)
        if idx is None:
            continue
        seen.add(fam)
        step = p["steps"][idx]
        body = _sanitize(_full_body(p["steps"], idx))
        print(f"\n  [{fam}]  first failing step: {step['label']}")
        print(f"    error: {_first_error_line(body)}")
        if body:
            tail = "\n".join(body.splitlines()[-12:])
            print("    --- aggregated output tail (step + nested children) ---")
            print("    " + tail.replace("\n", "\n    "))
        else:
            print("    (no output body in the daily log -- summary only; use a targeted probe)")
    if not seen:
        print("  (no provider-family failures in this run)")
    print("\n  NOTE: the daily operator log stores step SUMMARIES; a sub-script's raw HTTP body (e.g. a 429")
    print("  OUT_OF_USAGE_CREDITS payload) may live only in that sub-runner's own log. If a family shows")
    print("  only 'exited with code 1', get the raw error with ONE targeted probe (see the incident doc)")
    print("  -- that is a single call, not a job re-run.")

    # ---- 3. Provider failure / status table ----
    print("\n## 3. Provider-level step table (this run)")
    print(f"  {'STATUS':<24} {'PROVIDER':<34} STEP")
    for s in p["steps"]:
        print(f"  {s['status']:<24} {_provider_for(s['label'], s['command']):<34} {s['label']}")
    # steps that never appeared (aborted before them) are the stale-cause set:
    print("\n  Steps AFTER the first FAIL never ran this run (their feeds did not refresh) — see the")
    print("  feed-age table below for which artifacts are consequently stale.")

    # ---- 6 + 7. Feed artifact ages + preservation + customer impact ----
    print("\n## 6-7. Feed artifact age / preservation / customer impact")
    print(f"  {'FEED':<42} {'AGE(h)':>8} {'SIZE':>10}  PROVIDER / SURFACE")
    for rel, provider, surface in FEEDS:
        size, hrs = _age(DATA_DIR / rel)
        if size is None:
            age_s, size_s, flag = "MISSING", "-", "  <- absent"
        else:
            age_s = f"{hrs:.0f}"
            size_s = str(size)
            flag = "  <- ZERO-BYTE" if size == 0 else ("  <- STALE(>36h)" if hrs and hrs > 36 else "")
        print(f"  {rel:<42} {age_s:>8} {size_s:>10}  {provider} / {surface}{flag}")
    print("\n  A STALE/MISSING/ZERO-BYTE feed whose refresh step is AFTER the abort point is stale BECAUSE")
    print("  the run aborted (fetchers preserve last-known-good on failure; they never write empties on")
    print("  an exception — see fetch_game_lines.main). A fresh feed whose surface still reads 'stale' is")
    print("  a separate issue. Surfaces bound to a stale feed should fail closed (show unavailable).")

    print("\n" + "=" * 78)
    print("Paste this whole report back. Then run the shell infra/network/quota probes in")
    print("docs/refresh_incident_2026-10-23.md (they need the service env + network).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
