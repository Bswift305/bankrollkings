"""Server-side resource + app watchdog for Bankroll Kings.

Runs every few minutes (systemd bk-health.timer). Checks memory, load, disk,
and that the local gunicorn answers /healthz, and emails/webhooks an alert when
something is wrong or trending bad. A per-condition cooldown prevents alert
spam, and a recovery notice is sent once a condition clears.

This is the EARLY-WARNING layer: it catches a box that is degrading (low RAM,
high load, full disk, app not responding locally) before users notice. It runs
ON the box, so it cannot alert if the whole host is down -- that gap is covered
by an EXTERNAL uptime monitor (e.g. UptimeRobot) hitting https://.../healthz.

Channels reuse notify_failure.py (.env: ALERT_WEBHOOK_URL and/or SMTP_* +
ALERT_EMAIL_TO). Stdlib-only. Always exits 0 so it can never enter a failed
state itself.

Usage:
  python monitor_health.py           # check + alert if needed
  python monitor_health.py --test    # force a test alert through the channels
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STATE_PATH = BASE_DIR / "logs" / "monitor_state.json"

# Reuse the notifier's env loader + channel senders (no duplicated SMTP code).
from notify_failure import _load_env_file, _send_email, _send_webhook  # noqa: E402

# --- thresholds (overridable via .env) ---------------------------------------
MEM_AVAIL_MIN_PCT = float(os.environ.get("HEALTH_MEM_MIN_PCT", "10"))      # alert if avail RAM < this %
DISK_MAX_PCT = float(os.environ.get("HEALTH_DISK_MAX_PCT", "90"))         # alert if any volume > this % used
LOAD_PER_CPU_MAX = float(os.environ.get("HEALTH_LOAD_PER_CPU", "4"))      # alert if 1-min load/cpu > this
HEALTHZ_URL = os.environ.get("HEALTH_LOCAL_URL", "http://127.0.0.1:8000/healthz")
COOLDOWN_SEC = int(os.environ.get("HEALTH_COOLDOWN_SEC", "1800"))         # min seconds between repeat alerts per condition
DISK_PATHS = ["/", "/opt/bankrollkings"]


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _mem_avail_pct() -> float | None:
    try:
        info = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, _, rest = line.partition(":")
            info[k.strip()] = float(rest.strip().split()[0])  # kB
        total = info.get("MemTotal")
        avail = info.get("MemAvailable")
        if total and avail:
            return round(100.0 * avail / total, 1)
    except Exception:
        pass
    return None


def _check() -> list[tuple[str, str]]:
    """Return list of (condition_key, human_message) for everything wrong now."""
    problems: list[tuple[str, str]] = []

    mem = _mem_avail_pct()
    if mem is not None and mem < MEM_AVAIL_MIN_PCT:
        problems.append(("memory", f"Low memory: {mem}% available (threshold {MEM_AVAIL_MIN_PCT}%)"))

    try:
        ncpu = os.cpu_count() or 1
        load1 = os.getloadavg()[0]
        per_cpu = load1 / ncpu
        if per_cpu > LOAD_PER_CPU_MAX:
            problems.append(("load", f"High load: {load1:.2f} over {ncpu} CPU ({per_cpu:.2f}/cpu, threshold {LOAD_PER_CPU_MAX})"))
    except Exception:
        pass

    for path in DISK_PATHS:
        try:
            usage = shutil.disk_usage(path)
            pct = round(100.0 * usage.used / usage.total, 1)
            if pct > DISK_MAX_PCT:
                problems.append((f"disk:{path}", f"Disk {path} {pct}% full (threshold {DISK_MAX_PCT}%)"))
        except Exception:
            pass

    # Local app responsiveness (gunicorn behind nginx). This catches the app
    # being wedged even when the box itself is fine.
    try:
        req = urllib.request.Request(HEALTHZ_URL, headers={"User-Agent": "bk-health"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            if not (200 <= resp.status < 300):
                problems.append(("app", f"Local /healthz returned HTTP {resp.status}"))
    except Exception as exc:
        problems.append(("app", f"Local /healthz unreachable: {exc}"))

    return problems


def _load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(state))
    except Exception as exc:
        print(f"[health] could not write state: {exc}")


def _deliver(message: str) -> None:
    print(message)
    print("-" * 40)
    sent = False
    webhook = os.environ.get("ALERT_WEBHOOK_URL", "").strip()
    if webhook:
        sent = _send_webhook(webhook, message) or sent
    if _send_email(message):
        sent = True
    if not sent:
        print("[health] No alert channel delivered (set ALERT_WEBHOOK_URL or SMTP_* + ALERT_EMAIL_TO in .env).")


def main() -> int:
    _load_env_file()
    host = socket.gethostname()
    now = time.time()

    if "--test" in sys.argv[1:]:
        _deliver(f"\U0001F7E2 Bankroll Kings health-watchdog test\nHost: {host}\nTime: {_now_utc()}\nChannels are wired correctly.")
        return 0

    problems = _check()
    state = _load_state()
    prev_active = set(state.get("active", []))
    last_alert = state.get("last_alert", {})
    now_active = {key for key, _ in problems}

    # New or cooled-down problems -> alert.
    to_alert = []
    for key, msg in problems:
        last = float(last_alert.get(key, 0))
        if key not in prev_active or (now - last) >= COOLDOWN_SEC:
            to_alert.append((key, msg))
            last_alert[key] = now

    if to_alert:
        body = "\n".join(
            [f"\U0001F534 Bankroll Kings HEALTH ALERT", f"Host: {host}", f"Time: {_now_utc()}", ""]
            + [f"  - {msg}" for _, msg in to_alert]
        )
        _deliver(body)

    # Conditions that were active and are now clear -> one recovery notice.
    recovered = prev_active - now_active
    if recovered:
        for key in list(recovered):
            last_alert.pop(key, None)
        body = "\n".join(
            [f"\U0001F7E2 Bankroll Kings RECOVERED", f"Host: {host}", f"Time: {_now_utc()}", ""]
            + [f"  - cleared: {key}" for key in sorted(recovered)]
        )
        _deliver(body)

    _save_state({"active": sorted(now_active), "last_alert": last_alert})

    if not problems:
        print(f"[health] OK ({_now_utc()}) mem_avail%={_mem_avail_pct()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
