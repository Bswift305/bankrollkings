# User preference store — operations (retention, deletion, backup, DR)

Covers the account-bound UI-preference store shared by Daily Cards, King's Tickets, the home-view, the
onboarding flag, and the Green Light workspace. Implementation: `services/user_prefs_store.py` (atomic +
multi-worker-safe) + the app helpers (`load/save_card_prefs`, `load/save_home_view`, `load/save_greenlight_prefs`,
`reset_greenlight_prefs`, `delete_user_prefs`). It stores **UI configuration only** — lens order/visibility,
preferred sport/markets, card sizes/risk/legs/timeframe, landing surface, display settings — and **never**
ticket legs, prices, betting outcomes, journal reasoning or sportsbook activity.

## Location
- **Default:** `<checkout>/data/user_prefs/{uid}.json` (i.e. `/opt/bankrollkings/data/user_prefs` on prod),
  one JSON file per account, with independent top-level keys (`card`, `home`, `seen_start`, `greenlight`).
- **Relocatable:** set `BK_USER_PREFS_DIR` (e.g. to `${BK_RUNTIME_DIR}/user_prefs`) to move the store with
  no code change. See **Disaster recovery** for when to do this.

## Durability (atomic + multi-worker)
Every write is a **locked, atomic read-merge-write**: an exclusive cross-process lock on a sidecar `.lock`
(`fcntl` on prod Linux — auto-released on worker death; `msvcrt` on Windows), an in-process thread lock, then
a temp file + `fsync` + `os.replace`. Consequences, proven by `verify_user_prefs_store.py`:
- a reader only ever sees the complete old or complete new file (no torn/truncated JSON);
- two gunicorn workers writing different keys never lose an update (16-process no-lost-update proof);
- a crash mid-write cannot leave a partial file at the real path;
- a corrupt/garbage file degrades to `{}` and is replaced with valid JSON on the next write, preserving the
  new key.

## Retention
Preferences persist **indefinitely** until the user changes them or the account is deleted — there is **no
TTL** (unlike the ephemeral King's Tickets draft store, which self-expires in 24h). They are configuration,
not activity, so they carry no freshness/staleness semantics.

## Account deletion
`delete_user_prefs(uid)` removes the user's entire prefs file (`{uid}.json`) and any stray `.lock`. It is
idempotent and anon-safe. **Wire it into the account-deletion flow** so a deleted account leaves no residual
preference data. `reset_greenlight_prefs(uid)` is the narrower control that removes only the `greenlight`
key (used by the workspace "Reset to default"), leaving the other settings intact.

## Backup
Preferences are low-value, user-regenerable UI configuration and are **not part of the critical backup set**
(unlike the Decision Journal, which is a durable record and is backed up). If an operator wants them on the
persistent, backed-up volume, relocate the store with `BK_USER_PREFS_DIR=${BK_RUNTIME_DIR}/user_prefs`.

## Deploy / restart survival
- **Deploy** (`bk-deploy`: `git pull --ff-only` + `systemctl restart`): the default location is **gitignored**
  (`.gitignore` `data/user_prefs/`), so a pull never touches, deletes, or conflicts with it, and a dirty-tree
  HOLD never triggers on it. The restart does not delete disk files.
- **Restart:** files on disk survive a `systemctl restart`.
- **Proof:** `verify_user_prefs_store.py` writes a `deploy_sentinel`; run it, deploy, run it again, and the
  sentinel still reads back. "Gitignored in the checkout" is *not* claimed as sufficient on its own — the
  receipt demonstrates survival empirically, and the relocation knob below covers the gap it cannot.

## Disaster recovery (the honest caveat)
A **full checkout rebuild / re-clone** at the default location would lose the files (they are gitignored, so
not in git). This is acceptable for UI configuration (the user re-picks their preferences), but operators who
want prefs to survive a rebuild should set `BK_USER_PREFS_DIR=${BK_RUNTIME_DIR}/user_prefs` so the store lives
on the persistent volume (`/var/lib/bankrollkings`) alongside the other durable stores — exactly as the
Decision Journal and King's Tickets draft store do. The code already honors the env var; no migration is
forced (existing default-location files can be moved once with `install -d` + `mv` during a maintenance
window if relocation is chosen).

## Production receipt
```bash
sudo -u ubuntu bash -lc 'cd /opt/bankrollkings && python3 verify_user_prefs_store.py'
```
Expect all `[OK]` incl. the 16-process no-lost-update line and (POSIX) the `0600` file-permission line.
