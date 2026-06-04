# AWS Deployment Runbook — bankrollkings.com

End-to-end steps to take the app from local to live HTTPS on a single EC2 host.
Console steps are yours; server steps are copy-paste over SSH. Config artifacts
live in `deploy/`.

Target shape: one EC2 instance running gunicorn (systemd) behind Nginx (TLS),
data on a persistent EBS volume, scheduled refresh lanes via systemd timers.

---

## Phase 1 — EC2 (AWS console)

1. **Billing alarm first.** Billing → Budgets → create a $100/mo budget with email alert.
2. **Launch instance:**
   - AMI: Ubuntu Server 22.04 LTS (x86_64)
   - Type: `t3.medium` (2 vCPU / 4 GB)
   - Key pair: create/download one (you SSH with it)
   - Storage: keep the 8 GB root, then **add a second EBS volume, 50 GB gp3** (this holds `data/`)
3. **Security group** — inbound rules:
   - SSH (22) — source: *My IP* only
   - HTTP (80) — source: Anywhere
   - HTTPS (443) — source: Anywhere
4. **Elastic IP:** Network & Security → Elastic IPs → Allocate → Associate to the instance.
   Record this IP — it goes into Namecheap and never changes.

---

## Phase 2 — Base server setup (SSH)

```bash
ssh -i your-key.pem ubuntu@<ELASTIC_IP>

sudo apt update && sudo apt -y upgrade
sudo apt -y install python3-venv python3-pip nginx git certbot python3-certbot-nginx

# Mount the 50GB data volume at /opt/bankrollkings/data (first time only).
lsblk                                   # find the new disk, e.g. /dev/nvme1n1
sudo mkfs -t ext4 /dev/nvme1n1          # ONLY if brand new/empty — destroys data
sudo mkdir -p /opt/bankrollkings
sudo mount /dev/nvme1n1 /opt/bankrollkings   # temporary; persist below
# Persist the mount across reboots:
echo "/dev/nvme1n1 /opt/bankrollkings ext4 defaults,nofail 0 2" | sudo tee -a /etc/fstab
sudo chown -R ubuntu:ubuntu /opt/bankrollkings
```

---

## Phase 3 — App deploy (SSH)

```bash
cd /opt/bankrollkings
git clone <YOUR_REPO_URL> .            # or rsync the project up
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt        # installs gunicorn on Linux
```

Create the production env file (NOT committed):

```bash
nano /opt/bankrollkings/.env
```

```
SECRET_KEY=<long-random-string>
ENABLE_HSTS=true
ODDS_API_KEY=<key>
CFBD_API_KEY=<key>

# LIVE Stripe URLs (all 18 + portal) — copy from the working .env.local
STRIPE_PRO_MONTHLY_URL=...
STRIPE_PRO_ANNUAL_URL=...
STRIPE_SHARP_MONTHLY_URL=...
STRIPE_SHARP_ANNUAL_URL=...
STRIPE_ELITE_MONTHLY_URL=...
STRIPE_ELITE_ANNUAL_URL=...
STRIPE_NBA_PASS_MONTHLY_URL=...
# ... (all sport passes) ...
STRIPE_BILLING_PORTAL_URL=...
STRIPE_BILLING_PORTAL_CONFIG_ID=...
```

> `ENABLE_HSTS=true` is required: behind Nginx the app may not see the request as
> secure on its own, and this flag forces the HSTS header on regardless.

Verify config before serving:

```bash
python -c "import app; print('import OK')"
python qc_checkout_readiness.py        # must report Mode: live, 0 test-mode
```

---

## Phase 4 — gunicorn service + Nginx (SSH)

```bash
# Web service
sudo cp deploy/bankrollkings.service /etc/systemd/system/bankrollkings.service
sudo systemctl daemon-reload
sudo systemctl enable --now bankrollkings
systemctl status bankrollkings          # should be active (running)

# Nginx (HTTP first; certbot adds HTTPS next)
sudo cp deploy/nginx-bankrollkings.conf /etc/nginx/sites-available/bankrollkings
sudo ln -s /etc/nginx/sites-available/bankrollkings /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

At this point `http://<ELASTIC_IP>` should serve the site.

---

## Phase 5 — DNS + SSL

1. **Namecheap → Domain List → Manage → Advanced DNS.** Delete default parking
   records, then add:
   ```
   A   @     <ELASTIC_IP>   Automatic
   A   www   <ELASTIC_IP>   Automatic
   ```
   Confirm WhoisGuard/privacy is ON.
2. Wait for propagation (usually <1 hr): `dig +short bankrollkings.com` returns the IP.
3. **Issue the certificate** (DNS must resolve first):
   ```bash
   sudo certbot --nginx -d bankrollkings.com -d www.bankrollkings.com
   ```
   certbot rewrites the Nginx config to add the 443 server block and the
   HTTP→HTTPS redirect, and installs an auto-renew timer.
4. Verify: `https://bankrollkings.com` loads with a valid lock, `www` redirects to apex.

---

## Phase 6 — Scheduled refresh lanes (systemd timers)

All live-refresh scripts are hang-safe (per-step timeouts, non-blocking
snapshots). The heavy archive grading runs in its OWN lane so it can never block
live boards.

Create a oneshot service + timer per lane. Example for the daily live refresh:

```ini
# /etc/systemd/system/bk-daily.service
[Service]
Type=oneshot
User=ubuntu
WorkingDirectory=/opt/bankrollkings
EnvironmentFile=/opt/bankrollkings/.env
ExecStart=/opt/bankrollkings/venv/bin/python run_daily.py --sports nba,wnba,mlb
# Warm the running web tier after data changes (zero-downtime):
ExecStartPost=/bin/systemctl reload bankrollkings
```

```ini
# /etc/systemd/system/bk-daily.timer
[Timer]
OnCalendar=*-*-* 10:00:00 UTC
Persistent=true
[Install]
WantedBy=timers.target
```

Separate lane for archive grading (never inline with live):

```ini
# /etc/systemd/system/bk-results.service  → ExecStart=... python refresh_all_prop_results.py
# /etc/systemd/system/bk-results.timer    → OnCalendar later than bk-daily
```

Enable:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now bk-daily.timer bk-results.timer
systemctl list-timers | grep bk-
```

---

## Post-launch verification

- [ ] `https://bankrollkings.com` loads, valid TLS, www redirects to apex
- [ ] `qc_checkout_readiness.py` on the server reports Mode: live, 0 test-mode
- [ ] Real signup → upgrade to Pro on a live card → plan updates → billing portal opens
- [ ] `systemctl status bankrollkings` active; survives `sudo reboot`
- [ ] Day-after check: timers fired, boards show fresh data, no cold-load stall
- [ ] Legal pages reachable: /terms /privacy /refund-policy /responsible-gambling
- [ ] UptimeRobot (or similar) monitor on the apex URL

---

## Operations cheatsheet

| Task | Command |
|---|---|
| Web logs | `journalctl -u bankrollkings -f` |
| Restart web | `sudo systemctl restart bankrollkings` |
| Warm reload after refresh | `sudo systemctl reload bankrollkings` |
| Deploy new code | `git pull && sudo systemctl restart bankrollkings` |
| Nginx logs | `sudo tail -f /var/log/nginx/{access,error}.log` |
| Cert renewal dry-run | `sudo certbot renew --dry-run` |
