"""Franchise Kings multiplayer scheduler tick.

Advances any commissioner league whose game-day deadline has passed, even when
nobody is viewing it (the hub also lazily advances on view). Wire to a systemd
timer running every few minutes:

    [Service] ExecStart=/opt/bankrollkings/venv/bin/python franchise_tick.py
    [Timer]   OnCalendar=*:0/5   (every 5 minutes)
"""
import franchise_league as fl

if __name__ == "__main__":
    n = fl.run_due_leagues()
    print(f"franchise_tick: advanced {n} league(s) past deadline")
