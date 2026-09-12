"""Test the CSV transform in reset_password.py (no werkzeug needed).

Run:  python3 tests/test_reset_password.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reset_password import update_password_hash  # noqa: E402

_fails = 0


def check(cond: bool, msg: str) -> None:
    global _fails
    if not cond:
        _fails += 1
    print(f"[{'  ok  ' if cond else ' FAIL '}] {msg}")


fieldnames = ["UserId", "Email", "PasswordHash", "Plan", "ResetTokenHash", "ResetTokenExpiry"]
rows = [
    {"UserId": "1", "Email": "Decaturjones019@gmail.com", "PasswordHash": "old-hash-1",
     "Plan": "all_access", "ResetTokenHash": "pending", "ResetTokenExpiry": "123"},
    {"UserId": "2", "Email": "someone@else.com", "PasswordHash": "old-hash-2",
     "Plan": "free", "ResetTokenHash": "", "ResetTokenExpiry": ""},
]

# Case-insensitive email match, only the target row changes.
rows, fields, matched = update_password_hash(rows, fieldnames, "decaturjones019@GMAIL.com", "NEW-HASH")
check(matched == 1, f"exactly one row matched (got {matched})")
check(rows[0]["PasswordHash"] == "NEW-HASH", "target PasswordHash updated")
check(rows[0]["ResetTokenHash"] == "" and rows[0]["ResetTokenExpiry"] == "", "pending reset token cleared")
check(rows[1]["PasswordHash"] == "old-hash-2", "other users untouched")
check(rows[0]["Plan"] == "all_access", "other columns preserved")

# Missing required columns get added.
rows2, fields2, matched2 = update_password_hash(
    [{"Email": "x@y.com", "PasswordHash": "h"}], ["Email", "PasswordHash"], "x@y.com", "H2")
check("ResetTokenHash" in fields2 and "ResetTokenExpiry" in fields2, "missing token columns added")
check(matched2 == 1 and rows2[0]["PasswordHash"] == "H2", "update works when token cols absent")

# No match -> zero.
_, _, matched3 = update_password_hash(
    [{"Email": "a@b.com", "PasswordHash": "h", "ResetTokenHash": "", "ResetTokenExpiry": ""}],
    fieldnames, "nobody@nowhere.com", "H3")
check(matched3 == 0, "no match returns 0")

print(f"\n{'ALL CHECKS PASSED' if _fails == 0 else str(_fails) + ' CHECK(S) FAILED'}")
sys.exit(1 if _fails else 0)
