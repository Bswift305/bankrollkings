# Bankroll Kings — pre-launch checklist

Prod passes the launch gate (prelaunch scorecard = **GO**, 0 FAIL). This is the final
human gate before flipping it on for real users. Items marked **(you)** need your
judgment/credentials; **(Claude)** I can run/verify on request.

---

## A. Final gate — do these before announcing

- [ ] **Visual-trust pass (you, ~10 min).** The scorecard confirms pages return 200; it
      can't judge whether they *look* right. Log in and click through:
      Home → a sport command center (MLB or WNBA — they're in season) → NFL/CFB command
      center (preseason O/U card) → Pricing → Checkout → one Quick Tool. Look for broken
      layout, wrong numbers, stale dates, anything that erodes trust.
- [ ] **Real end-to-end payment test (you).** Stripe is in **live** mode. Do ONE genuine
      run: create a fresh account → `/checkout/start` → pay $19.99 → confirm the account
      flips to `all_access` and paid surfaces unlock → then cancel + refund yourself in
      Stripe. The scorecard verifies config, not that a real dollar flows and unlocks
      access. (I can't do this — it involves payment details.)
- [ ] **Confirm the webhook fired (Claude).** After your test payment, I can check the
      user row flipped to `all_access` / `IsFounder` handling and that the Stripe webhook
      activated it (not just the success-redirect).
- [ ] **Founders promo decision (you).** It's currently **DISABLED** (selling flat
      $19.99). If you want the "first 100 subscribers → $10/mo ×12" live at launch, that's
      a deliberate flip (set `STRIPE_ALL_ACCESS_FOUNDER_MONTHLY_URL` + enable
      `FOUNDER_PROMO`). Decide before launch, not after.
- [ ] **Responsible-gaming + legal surfaces present (you).** Confirm the age gate,
      responsible-gambling disclaimer, "not financial/betting advice," Terms, and Privacy
      are visible and current. (This is a legal call — confirm they exist; I'm not the
      authority on their adequacy.)
- [ ] **Re-run the launch gate right before flipping (Claude).** `run_prelaunch_scorecard.py`
      should still say **GO** the morning of.

## B. Flip-on

- [ ] Pick the timing (you). It's **offseason for NFL/NBA/CFB**; **MLB + WNBA are live**.
      Launching now is valid; timing to football season (~6 weeks) is when the product is
      strongest. Either is technically fine.
- [ ] Announce / open signups.

## C. Day-one → first-week watch list

- [ ] **App health (Claude).** `bk-health.timer` runs every few min; watch
      `journalctl -u bk-health.service`. App should stay `active`, probes HTTP 200.
- [ ] **First real signups activate correctly (Claude).** Spot-check the users CSV: new
      paid accounts get `all_access`, founder flags correct, no one stuck on `free` after
      paying.
- [ ] **Memory / earlyoom (Claude).** On t3.large there's ~6 GB free with 2 workers — the
      old OOM risk is gone, but confirm earlyoom isn't firing under real traffic:
      `journalctl -k | grep -i earlyoom`. Watch RSS as concurrent users climb.
- [ ] **First-request latency.** Cold cache after idle can be ~8 s on the first hit
      (prewarm concern, not CPU). If users report a slow first load, that's the cause;
      `BK_PREWARM_ON_BOOT=1` already mitigates on restart.
- [ ] **Auto-deploy still healthy (Claude).** `journalctl -u bk-deploy.service` — pushes
      land within ~2 min. Don't push risky changes during peak launch hours.
- [ ] **Data feeds fresh (Claude).** `bk-daily`, `bk-injuries`, `bk-linemove`,
      `bk-nfl-gameday`, `bk-backup` timers all firing; boards/injuries not stale.
- [ ] **Stripe dashboard (you).** Watch for failed payments, disputes, or webhook errors.

## D. If something breaks

- **App down / bad deploy:** `sudo systemctl restart bankrollkings`; to revert code,
  `git revert` + push (auto-deploy picks it up), or roll back on the box.
- **Instance trouble:** rollback steps in `docs/resize_to_t3large_runbook.md`.
- **Incident procedure:** `docs/platform_prelaunch_checklist.md` → "Rollback And Incident
  Response".
- **Kill payments fast if needed:** unset the Stripe URL env → falls back to demo mode
  (no real charges) → restart.

---

*Standing WATCH items (expected, not blockers): Suggestion Integrity is "unverified"
only because NBA/NFL are offseason (self-clears at kickoff); Visual Trust is the manual
pass in section A.*
