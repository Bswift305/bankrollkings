"""Send an alert when the Bankroll Kings daily refresh fails.

Wired as systemd `OnFailure=bk-daily-alert.service`, so it only runs when
bk-daily.service exits non-zero. Since the daily exit code is now season-aware
(off-season + WATCH-only states are non-fatal), a failure here means a real,
in-season problem worth acting on.

Channels (configure in /opt/bankrollkings/.env):
  ALERT_WEBHOOK_URL   Slack or Discord incoming webhook (auto-detected). Easiest.
  ALERT_EMAIL_TO      Comma-separated recipients (requires SMTP_* below).
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM, SMTP_USE_TLS

Stdlib-only (urllib + smtplib) so it has no third-party dependencies and can
never itself be the reason the alert fails to send. Always exits 0.

Usage:
  python notify_failure.py            # build message from the latest daily log
  python notify_failure.py --test     # send a test message to confirm delivery
"""

from __future__ import annotations

import json
import os
import socket
import ssl
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
MAX_FAIL_LINES = 15
MAX_TAIL_LINES = 20


def _load_env_file():
    """Load KEY=VALUE pairs from .env into os.environ (without overriding values
    already set). Makes the notifier self-sufficient for SMTP config instead of
    relying on systemd's EnvironmentFile, which can mis-handle CRLF line endings.
    """
    path = BASE_DIR / ".env"
    if not path.exists():
        return
    try:
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'").strip()
            if key and key not in os.environ:
                os.environ[key] = val
    except Exception as exc:
        print(f"[notify] could not read .env: {exc}")


def _latest_daily_log() -> Path | None:
    logs = sorted(LOG_DIR.glob("daily_operator_*.log"))
    return logs[-1] if logs else None


def _build_message(test: bool) -> str:
    host = socket.gethostname()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if test:
        return (
            f"\U0001F7E2 Bankroll Kings alert test\n"
            f"Host: {host}\nTime: {now}\n"
            f"If you can read this, daily-failure alerts are wired correctly."
        )

    log_path = _latest_daily_log()
    header = f"\U0001F534 Bankroll Kings DAILY REFRESH FAILED\nHost: {host}\nTime: {now}"

    if not log_path or not log_path.exists():
        return header + "\n(No daily_operator log found to summarize.)"

    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # pragma: no cover - defensive
        return header + f"\nCould not read log {log_path.name}: {exc}"

    lines = text.splitlines()
    fails: list[str] = []
    for ln in lines:
        s = ln.strip()
        if s.startswith("[FAIL]"):
            label = s[len("[FAIL]"):].strip()
            if label and label not in fails:
                fails.append(label)

    parts = [header, f"Log: {log_path.name}"]
    if fails:
        shown = fails[:MAX_FAIL_LINES]
        parts.append("Failed steps:")
        parts.extend(f"  - {f}" for f in shown)
        if len(fails) > MAX_FAIL_LINES:
            parts.append(f"  ...and {len(fails) - MAX_FAIL_LINES} more")
    else:
        parts.append("(Service failed but no [FAIL] step lines were found.)")

    tail = [ln for ln in lines if ln.strip()][-MAX_TAIL_LINES:]
    if tail:
        parts.append("--- log tail ---")
        parts.extend(tail)

    return "\n".join(parts)


def _send_webhook(url: str, message: str) -> bool:
    if not (url.startswith("http://") or url.startswith("https://")):
        print(
            f"[notify] ALERT_WEBHOOK_URL is not a valid URL ({url!r}). "
            "Replace the placeholder in .env with your real Slack/Discord webhook URL."
        )
        return False
    low = url.lower()
    if "discord" in low:
        payload = {"content": message[:1900]}  # Discord 2000-char content cap
    elif "slack" in low or "hooks.slack" in low:
        payload = {"text": message}
    else:
        # Unknown provider: send both common keys; receivers ignore extras.
        payload = {"text": message, "content": message[:1900]}
    data = json.dumps(payload).encode("utf-8")
    ctx = ssl.create_default_context()
    try:
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
            ok = 200 <= resp.status < 300
            print(f"[notify] webhook status={resp.status}")
            return ok
    except Exception as exc:
        print(f"[notify] webhook send failed: {exc}")
        return False


def _send_email(message: str) -> bool:
    to_raw = os.environ.get("ALERT_EMAIL_TO", "").strip()
    host = os.environ.get("SMTP_HOST", "").strip()
    if not to_raw or not host:
        return False
    import smtplib
    from email.message import EmailMessage

    recipients = [a.strip() for a in to_raw.split(",") if a.strip()]
    port = int(os.environ.get("SMTP_PORT", "587") or "587")
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    sender = os.environ.get("SMTP_FROM", "").strip() or user or "alerts@bankrollkings.com"
    use_tls = str(os.environ.get("SMTP_USE_TLS", "1")).strip().lower() in ("1", "true", "yes", "on")

    msg = EmailMessage()
    msg["Subject"] = message.splitlines()[0][:120] if message else "Bankroll Kings alert"
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.set_content(message)

    try:
        with smtplib.SMTP(host, port, timeout=30) as server:
            if use_tls:
                server.starttls(context=ssl.create_default_context())
            if user and password:
                server.login(user, password)
            server.send_message(msg)
        print(f"[notify] email sent to {len(recipients)} recipient(s)")
        return True
    except Exception as exc:
        print(f"[notify] email send failed: {exc}")
        return False


def main() -> int:
    _load_env_file()
    test = "--test" in sys.argv[1:]
    message = _build_message(test)
    print(message)
    print("-" * 40)

    sent_any = False
    webhook = os.environ.get("ALERT_WEBHOOK_URL", "").strip()
    if webhook:
        sent_any = _send_webhook(webhook, message) or sent_any
    if _send_email(message):
        sent_any = True

    if not sent_any:
        print(
            "[notify] No alert channel delivered. Set ALERT_WEBHOOK_URL "
            "(Slack/Discord) or SMTP_* + ALERT_EMAIL_TO in .env."
        )
    # Always exit 0: the notifier must never itself enter a failed state.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
