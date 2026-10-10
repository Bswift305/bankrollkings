# Trial-Code Security Containment — 2026-10-10

**Why:** invite codes were committed to this **public** repo (`KINGS14` unlimited, the `KB-*`
batch, and `CASINO01`/`BARBER01` added in `6b27b05`). Git history is permanent, so every code
that ever appeared in the repo must be treated as **exposed**. Deleting rows does not un-expose
history — the codes must be **deactivated** and the live store moved **off** the repo.

## Done (code side, committed `c64bb62`, deployed + verified)
- Live invite store now read/written via **`INVITE_CODES_PATH`** env var (a private, untracked
  production file). `load_invite_codes` + `consume_invite_code` use it. Falls back to the
  tracked path only if the env var is unset.
- Tracked `data/tracking/Invite_Codes.csv` replaced with a **header + one INACTIVE example row**
  (`Active=0`) — no live codes.
- **Deactivation verified on prod:** `/trial/CASINO01`, `/trial/BARBER01`, and `/trial/KINGS14`
  all now redirect to `/signup?trial=expired` (no code redeemable). Already-redeemed trials are
  **preserved** — they live on user records (`TrialExpiresAt`), not on the code rows.

## Operator steps (prod, via AWS SSM) — completes the containment
> New tokens are generated **on prod** and must never be pasted into the repo, chat, logs, or
> reports. The URLs print only on your SSM screen.

### 1 — Create the private store with two fresh random codes
```bash
sudo mkdir -p /opt/bankrollkings-private
sudo python3 - <<'PY'
import csv, secrets, os
p='/opt/bankrollkings-private/Invite_Codes.csv'
ALPH='ABCDEFGHJKLMNPQRSTUVWXYZ23456789'  # no ambiguous 0/O/1/I
tok=lambda: ''.join(secrets.choice(ALPH) for _ in range(10))
casino, barber = tok(), tok()
with open(p,'w',newline='') as f:
    w=csv.writer(f)
    w.writerow(['Code','Label','TrialDays','MaxRedemptions','TimesRedeemed','Active'])
    w.writerow([casino,'Casino','7','25','0','1'])
    w.writerow([barber,'Barbershop','7','25','0','1'])
print('WROTE', p)
print('CASINO  QR URL : https://bankrollkings.com/trial/'+casino)
print('BARBER  QR URL : https://bankrollkings.com/trial/'+barber)
PY
# give the app (owner of /opt/bankrollkings) read+write on the private store
APP=$(stat -c '%U:%G' /opt/bankrollkings)
sudo chown "$APP" /opt/bankrollkings-private /opt/bankrollkings-private/Invite_Codes.csv
sudo chmod 750 /opt/bankrollkings-private && sudo chmod 640 /opt/bankrollkings-private/Invite_Codes.csv
```
**Copy the two QR URLs** from the output (keep them private — they are the redemption secrets).

### 2 — Point the app at the private store and restart
```bash
grep -q '^INVITE_CODES_PATH=' /opt/bankrollkings/.env \
  || echo 'INVITE_CODES_PATH=/opt/bankrollkings-private/Invite_Codes.csv' | sudo tee -a /opt/bankrollkings/.env
sudo systemctl restart bankrollkings
```

### 3 — Verify URLs + redemption counters (prints PASS/FAIL, not the tokens)
```bash
sudo python3 - <<'PY'
import csv, urllib.request
rows=[r for r in csv.reader(open('/opt/bankrollkings-private/Invite_Codes.csv')) if r][1:]
for code,label,days,maxr,used,active in rows:
    try:
        final=urllib.request.urlopen('https://bankrollkings.com/trial/'+code, timeout=10).geturl()
    except Exception as e:
        final='ERR '+str(e)
    print(label, 'PASS' if ('invite='+code) in final else 'FAIL', f'(redeemed {used}/{maxr}, active={active})')
PY
```
Expect `Casino PASS` and `Barbershop PASS`, each `redeemed 0/25`.

### 4 — Remove the synthetic feedback (backup + content check)
Both test notes contain the literal `P0-4`; real tester notes will not.
```bash
F=/opt/bankrollkings/data/tracking/NBA_Feedback_Log.csv
sudo cp -p "$F" "$F.bak.$(date +%Y%m%d%H%M%S)"
sudo python3 - <<'PY'
import csv
F='/opt/bankrollkings/data/tracking/NBA_Feedback_Log.csv'
rows=list(csv.reader(open(F)))
head,data=rows[0],rows[1:]
fb=head.index('Feedback')
keep=[r for r in data if 'P0-4' not in (r[fb] if len(r)>fb else '')]
removed=len(data)-len(keep)
import os,stat; st=os.stat(F)
with open(F,'w',newline='') as f:
    w=csv.writer(f); w.writerow(head); w.writerows(keep)
os.chown(F, st.st_uid, st.st_gid)
print(f'removed {removed} synthetic row(s); {len(keep)} real row(s) remain')
PY
```
Confirm `removed 2` (the free + trial test notes) and the remaining count matches the real
feedback you expect. Backup is kept alongside as `*.bak.*`.

## After this passes
- The only live codes are the two private random ones (7-day, 25-use, active).
- QR/handout materials use those private URLs (internal labels: Casino, Barbershop).
- The tracked template stays header/example only; never add live codes to the repo again.

## Residual / notes
- Git history still contains the old exposed codes — they are now inert (deactivated). No
  rewrite of history is attempted here.
- `consume_invite_code` rewrites the private store on each redemption; because it is **outside**
  the repo, deploys no longer reset its counters (this also fixes the earlier tracked-file reset).
