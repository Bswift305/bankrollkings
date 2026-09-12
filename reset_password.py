"""Admin password reset — sets a user's password directly in NBA_Users.csv.

Use this when the self-service email reset (/password-reset) can't be used —
e.g. SMTP isn't configured on the host. Run it ON THE SERVER (or anywhere that
has the live data/tracking/NBA_Users.csv), where werkzeug is installed.

    # set a specific password
    python reset_password.py --email you@example.com --password 'NewPass123'

    # or let it generate a strong one and print it once
    python reset_password.py --email you@example.com

    # point at a non-default users file
    python reset_password.py --email you@example.com --file /path/NBA_Users.csv

It updates PasswordHash and clears any pending reset token. It never prints
existing hashes or other users' details.
"""
from __future__ import annotations

import argparse
import csv
import secrets
import string
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_USERS_PATH = BASE_DIR / "data" / "tracking" / "NBA_Users.csv"

# Columns the app expects (mirrors load_users() in app.py). Any missing ones are
# added so the row round-trips cleanly.
REQUIRED_COLUMNS = ["Email", "PasswordHash", "ResetTokenHash", "ResetTokenExpiry"]


def generate_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def update_password_hash(rows: list[dict], fieldnames: list[str], email: str, new_hash: str) -> tuple[list[dict], list[str], int]:
    """Return (rows, fieldnames, matched_count) with PasswordHash set for email.

    Pure CSV transform (no werkzeug) so it is easy to unit-test.
    """
    fields = list(fieldnames)
    for col in REQUIRED_COLUMNS:
        if col not in fields:
            fields.append(col)

    target = email.strip().lower()
    matched = 0
    for row in rows:
        for col in fields:
            row.setdefault(col, "")
        if str(row.get("Email", "")).strip().lower() == target:
            row["PasswordHash"] = new_hash
            row["ResetTokenHash"] = ""
            row["ResetTokenExpiry"] = ""
            matched += 1
    return rows, fields, matched


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reset a Bankroll Kings user's password.")
    parser.add_argument("--email", required=True, help="Account email to reset.")
    parser.add_argument("--password", help="New password. Omit to auto-generate one.")
    parser.add_argument("--file", default=str(DEFAULT_USERS_PATH), help="Path to NBA_Users.csv.")
    args = parser.parse_args(argv)

    try:
        from werkzeug.security import generate_password_hash
    except Exception:
        print("ERROR: werkzeug is not installed here. Run this on the server (or in the app's venv).", file=sys.stderr)
        return 2

    users_path = Path(args.file)
    if not users_path.exists():
        print(f"ERROR: users file not found: {users_path}", file=sys.stderr)
        return 2

    with users_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    if not fieldnames:
        print(f"ERROR: {users_path} has no header row.", file=sys.stderr)
        return 2

    new_password = args.password or generate_password()
    new_hash = generate_password_hash(new_password)
    rows, fieldnames, matched = update_password_hash(rows, fieldnames, args.email, new_hash)

    if matched == 0:
        print(f"No account found for {args.email!r}. (File has {len(rows)} users.)", file=sys.stderr)
        return 1
    if matched > 1:
        print(f"WARNING: {matched} rows matched {args.email!r}; all were updated.", file=sys.stderr)

    # Write to a temp file then replace, so a crash can't corrupt the user store.
    tmp_path = users_path.with_suffix(users_path.suffix + ".tmp")
    with tmp_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    tmp_path.replace(users_path)

    print(f"Password updated for {args.email}.")
    if not args.password:
        print(f"New password: {new_password}")
        print("Log in with it now, then change it from /account.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
