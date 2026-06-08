# Transactional Email Deliverability Setup

Goal: send account email (password resets, etc.) from **no-reply@bankrollkings.com**
so messages land in the inbox, not spam — and not from a personal Gmail.

The app code is already provider-agnostic: `send_account_email()` (and the ops
alerter) just read SMTP settings from `.env`. So switching providers is a
**`.env` + DNS** change, **no code change**. Below is the recommended path.

---

## Recommended provider: Amazon SES (you're already on AWS, cheapest, reliable)

SES is ~$0.10 per 1,000 emails and integrates cleanly with your AWS account.
(Quick alternative: **SendGrid** free tier = 100 emails/day, fastest signup —
same `.env` shape, just different host/creds and DKIM CNAMEs from their console.)

### 1. Verify the domain in SES
1. AWS Console → **Amazon SES** (same region as the app, **us-east-1**) → **Identities → Create identity**
2. Choose **Domain**, enter `bankrollkings.com`, enable **Easy DKIM** (RSA 2048)
3. SES shows **3 CNAME records** for DKIM — you'll add these at Namecheap (step 3)

### 2. Leave the SES sandbox (required to email real users)
- New SES accounts are in **sandbox** (can only send to verified addresses).
- SES → **Account dashboard → Request production access**. Approval is usually
  quick (hours–1 day). Do this early.

### 3. Add DNS records at Namecheap (Domain List → Manage → Advanced DNS)

| Type | Host | Value | Purpose |
|------|------|-------|---------|
| CNAME | `<from SES>._domainkey` ×3 | `<from SES>.dkim.amazonses.com` | DKIM (SES gives exact names/values) |
| TXT | `@` | `v=spf1 include:amazonses.com ~all` | SPF (authorizes SES to send) |
| TXT | `_dmarc` | `v=DMARC1; p=none; rua=mailto:postmaster@bankrollkings.com` | DMARC (start in monitor mode) |

Notes:
- **SPF:** if you ever add another sender, combine includes in ONE TXT record
  (only one `v=spf1` record is allowed per domain).
- **DMARC:** start with `p=none` (monitor). After a week of clean reports,
  tighten to `p=quarantine`, then `p=reject`.
- DKIM CNAME exact values come from the SES console — copy them verbatim.

### 4. Create SES SMTP credentials
- SES → **SMTP settings → Create SMTP credentials** (this makes an IAM user with
  SMTP user/password — **save the password, it's shown once**).
- SMTP endpoint for us-east-1: `email-smtp.us-east-1.amazonaws.com` (port 587, STARTTLS).

### 5. Update `/opt/bankrollkings/.env` (then restart the app)
```
SMTP_HOST=email-smtp.us-east-1.amazonaws.com
SMTP_PORT=587
SMTP_USER=<SES SMTP username>
SMTP_PASSWORD=<SES SMTP password>
SMTP_FROM=no-reply@bankrollkings.com
SMTP_FROM_NAME=Bankroll Kings
SMTP_REPLY_TO=support@bankrollkings.com   # optional; where replies go
SMTP_USE_TLS=1
```
Restart: `sudo systemctl restart bankrollkings`

### 6. Verify
- App: trigger a password reset to a real inbox; confirm it arrives **not in spam**,
  shows **From: Bankroll Kings <no-reply@bankrollkings.com>**, and passes SPF+DKIM
  (Gmail → "Show original" → SPF: PASS, DKIM: PASS, DMARC: PASS).
- Ops alerts (notify_failure.py / monitor_health.py) automatically use the same
  SMTP settings, so they'll also send from the new sender.

---

## Keep in mind
- The ops alert recipient (`ALERT_EMAIL_TO`) and the transactional sender are
  independent — alerts can still go to your personal inbox.
- Don't commit `.env` (secrets). Edit it directly on the server.
- Monitor SES **bounce/complaint** rates in the SES console; high rates can get
  sending paused.
