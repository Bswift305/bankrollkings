# Resize prod to t3.large — runbook

**Why:** prod's prelaunch scorecard is **NO-GO** for exactly one reason — the 4 GB
box's `earlyoom` reaper SIGTERM-kills the `platform_routes` section of the scorecard
during the daily run (documented in PROJECT_MAP §1). It is not a product defect; the
box is too small to run its own verification suite alongside the worker + archiver.
Resizing to **t3.large** (2 vCPU → **8 GB RAM**) clears that, lets us drop the
temporary one-worker stopgap, and buys launch-traffic headroom.

**Pre-flight (verified 2026-07-26):**
- Instance: `i-08d2fd818875381dd`, currently **t3.medium**, us-east-1.
- **Elastic IP is attached**, so the public IP (`32.195.123.245`) is unchanged by a
  stop/start — no DNS change, `bankrollkings.com` keeps resolving.
- **Pre-launch traffic is ~zero**, so the ~2–5 min of downtime during the stop/start
  has effectively no user impact. Now is a safe time.
- App data lives on a separate 50 GB EBS volume — untouched by the resize.

## Step 1 — Resize (you, in the AWS Console — ~3 clicks, ~3 min)

1. EC2 → **Instances** → select `i-08d2fd818875381dd`.
2. **Instance state → Stop instance.** Wait until state = **Stopped** (~30–60 s).
3. **Actions → Instance settings → Change instance type** → choose **t3.large** → **Apply**.
4. **Instance state → Start instance.** Wait until **Running** + status checks pass (~1–2 min).

(CLI equivalent, if you have `aws` configured locally — same three actions:)
```bash
aws ec2 stop-instances --instance-ids i-08d2fd818875381dd
aws ec2 wait instance-stopped --instance-ids i-08d2fd818875381dd
aws ec2 modify-instance-attribute --instance-id i-08d2fd818875381dd --instance-type t3.large
aws ec2 start-instances --instance-ids i-08d2fd818875381dd
```

## Step 2 — Post-resize (I do this over SSH once it's Running)

1. Confirm the box is back and the app is serving.
2. Remove the temporary one-worker stopgap so workers return to cpu_count:
   ```bash
   sudo rm /etc/systemd/system/bankrollkings.service.d/override.conf
   sudo systemctl daemon-reload
   sudo systemctl restart bankrollkings
   ```
3. Verify: instance type is `t3.large`, `WEB_CONCURRENCY` no longer pinned to 1,
   `free -m` shows ~8 GB, app probes HTTP 200.
4. Re-run `run_prelaunch_scorecard.py` — the `platform_routes` section should now
   complete instead of being OOM-killed, flipping **Scorecard Completeness → PASS**
   and the decision to **GO** (0 FAIL, 2 WATCH — the two structural WATCH items,
   Visual Trust + offseason integrity, remain and are expected).

## Rollback (if anything looks wrong)

Resize is reversible: Stop → Change instance type back to **t3.medium** → Start, then
recreate the one-worker drop-in:
```bash
sudo mkdir -p /etc/systemd/system/bankrollkings.service.d
sudo tee /etc/systemd/system/bankrollkings.service.d/override.conf >/dev/null <<'CONF'
[Service]
Environment=WEB_CONCURRENCY=1
CONF
sudo systemctl daemon-reload && sudo systemctl restart bankrollkings
```

## After GO

Update PROJECT_MAP §1 (box is now t3.large; the WEB_CONCURRENCY stopgap is removed)
and the memory note about the one-worker override.
