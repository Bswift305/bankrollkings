# Bankroll Kings Platform Pre-Launch Checklist

Use this before handing the site to outside testers, collaborators, or paying users.

This is not the same as the day-to-day QA checklist.

- [platform_qa_checklist.md](C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls\docs\platform_qa_checklist.md) is the recurring closeout flow.
- This document is the higher bar for external eyes.

The standard is:

- `fresh`
- `factual`
- `gated correctly`
- `visually trustworthy`
- `calibration-ready`

If one of those is not true, the site is not pre-launch ready.

Use these status labels while running this checklist:

- `PASS` = section is clean and launch-safe
- `WATCH` = not ideal, but not a blocker if explicitly understood
- `FAIL` = external testing should not proceed until fixed

---

## 1. Platform Reliability

These are the things that should never quietly fail.

### Route health

Run both route tiers:

```powershell
cd "C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls"
py qc_platform_routes.py --tier fast
py qc_platform_routes.py --tier slow
```

Pass standard:

- fast tier returns `0 failures`
- slow tier returns `0 failures`
- slow tier completes all batches

### Access gate

Verify these states:

- anonymous user sees locked-page teaser on protected routes
- free user gets upgrade path on protected routes
- pro user can access pro routes
- sharp user can access sharp routes
- owner/admin user is never accidentally locked out

Required checks:

- `/props?postseason=1`
- `/sports/nfl`
- `/nba-calibration`
- `/bet-review`

### Owner/admin safety

Confirm the owner row in:

- [NBA_Users.csv](C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls\data\tracking\NBA_Users.csv)

has:

- `Plan = sharp`
- `PlanStatus = active`
- `Role = owner`
- `IsAdmin = 1`

No duplicate owner row should exist.

### Section status

- `PASS` if route smoke is clean, access tiers behave correctly, and owner/admin access is safe
- `WATCH` if there is only a known non-blocking slowness issue in smoke coverage
- `FAIL` if a protected route misgates, owner/admin access is broken, or smoke testing is incomplete

---

## 2. Data Freshness And Source Truth

This is the core trust layer.

### Refresh discipline

NBA daily run:

```powershell
cd "C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls"
py refresh_nba_daily.py
```

Or:

- [REFRESH_NBA_DAILY.bat](C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls\batch\REFRESH_NBA_DAILY.bat)

### Source audit

Run:

```powershell
py qc_nba_sources.py
py qc_nba_series_mappings.py
```

Pass standard:

- no stale live props
- no missing playoff mappings
- no regular-season fallback leaking into postseason series state

### Never allow these again

These are now checklist items because they already bit us once:

- stale schedule or props feed presented as live
- playoff page showing regular-season series record
- injury file staying stale without warning
- return-impact cases not reflected in support-role props

If any one of those appears, stop and fix before outside testing.

### Section status

- `PASS` if feeds are fresh, mappings are correct, and postseason/return-context source truth is intact
- `WATCH` if a source is temporarily thin but the site degrades honestly and clearly
- `FAIL` if stale or wrong data is being presented as current

---

## 3. Suggestion Integrity

This is where the model either feels sharp or fake.

### Contradiction gate

Run:

```powershell
py qc_nba_contradictions.py --report-only
py qc_nfl_contradictions.py
```

Pass standard:

- no failed featured contradictions
- warnings are reviewed, not ignored

### Promotion rules

Featured cards must not show:

- `PASS`
- `CONFLICTED`
- stale injury-state plays
- role-down promoted overs
- return-squeeze overs
- zero-required fragile unders presented like clean premium bets

### Special risk flags

These should be visible before the user gets to the book:

- `ZERO REQUIRED`
- `FRAGILE UNDER`
- `RUN CONFLICT`
- `RETURN SQUEEZE`
- `MARKET HOLD`
- `MARKET SPLIT`

If a play needs a literal zero to cash on:

- `AST UNDER 0.5`
- `STL UNDER 0.5`
- `BLK UNDER 0.5`

it should never look like a clean normal under.

### Section status

- `PASS` if featured suggestions are contradiction-clean and special-risk flags are visible where needed
- `WATCH` if only narrow, reviewed warnings remain
- `FAIL` if a public premium play violates contradiction rules or hides material fragility

---

## 4. Archive And Replay Readiness

If the site suggests a play, it should be recoverable later.

### Suggestion capture

Confirm these suggestion classes are archived:

- `Featured Top Play`
- `Market Edge`
- `Floor Play`
- `Matchup Top Props`
- WNBA featured/archive paths when live

If a suggestion surface is visible but not being saved, it is not finished.

### Result grading

Confirm the result loop works:

```powershell
py refresh_featured_results.py
py report_nba_featured_results.py
```

And for football:

```powershell
py refresh_nfl_featured_results.py
```

Expected:

- rows are written to the sport's `FeaturedResults` file
- outcomes become `Hit`, `Miss`, `Push`, or `Pending`

### Replay mindset

Before launch, ask:

- if a tester challenges a pick tomorrow, can we reconstruct what the model showed?

If the answer is no, archive coverage is still incomplete.

### Section status

- `PASS` if visible suggestion surfaces are archived and result grading runs
- `WATCH` if a low-priority surface is still being added but core promoted surfaces are captured
- `FAIL` if a visible suggestion surface cannot be reconstructed later

---

## 5. Calibration Readiness

The site should not just score and display. It should learn.

### Calibration scripts

Run:

```powershell
py calibrate_nba_model.py
py calibrate_nfl_model.py
py calibrate_wnba_model.py
py calibrate_cfb_model.py
```

Expected output files:

- [NBA_Calibration_Report.csv](C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls\data\tracking\NBA_Calibration_Report.csv)
- [NFL_Calibration_Report.csv](C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls\data\tracking\NFL_Calibration_Report.csv)
- [WNBA_Calibration_Report.csv](C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls\data\tracking\WNBA_Calibration_Report.csv)
- [NCAAF_Calibration_Report.csv](C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls\data\tracking\NCAAF_Calibration_Report.csv)

### Pass standard

Calibration is only considered meaningful when there is enough resolved volume.

Required rule:

- fewer than `50` resolved featured rows for a sport = `NOT YET MEANINGFUL`
- do not treat the calibration section as a launch pass just because the script ran
- do not harden formula changes off thin result sets

Use calibration status labels like:

- `NOT YET MEANINGFUL`
- `WATCH`
- `ACTIONABLE`

### Guardrails

The calibration engine should not recommend formula changes on tiny samples.

Required rule:

- fewer than `10` resolved rows = `WATCH`, not formula change

### Questions calibration should eventually answer

- are cleared props hitting better than board average?
- which weight profile is most honest?
- which player tiers are overpromoted?
- which stat/direction buckets are lying?
- which contradiction rules should harden?

If the site cannot answer those over time, the feedback loop is incomplete.

### Section status

- `PASS` if scripts run, reports write successfully, and resolved volume is either actionable or honestly labeled `NOT YET MEANINGFUL`
- `WATCH` if the loop is operational but sample size is still maturing
- `FAIL` if calibration scripts are broken, missing, or being treated as meaningful without enough resolved rows

---

## 6. Visual Trust

This is where users decide whether the site feels real.

### Dense board checks

- no overlap
- no bleeding text
- no clipped pills
- wide tables scroll horizontally
- top horizontal scroll bar exists on tall/wide tables
- sticky/frozen top behavior works where expected

### Empty-space discipline

Every large widget should either:

- explain more
- show more
- or shrink

Do not ship giant dead zones with one unexplained pick in them.

### Explanation standard

Featured plays should explain:

- why this side
- why now
- what could break it

If a section makes the user ask "what is this?", it is not done.

### Section status

- `PASS` if dense boards are readable, scroll behavior works, and featured explanations feel trustworthy
- `WATCH` if only minor cosmetic polish remains
- `FAIL` if overlap, clipping, dead space, or unclear explanation damages trust

---

## 7. Pricing And Membership Boundary

The product boundary should feel intentional.

### Pricing flow

Check:

- `/pricing`
- `/login`
- `/signup`
- `/checkout/start`
- `/checkout/success`

Required behavior:

- destination is preserved
- logged-in users see current plan status
- upgrade CTAs are plan-aware
- demo checkout works without live Stripe URLs
- real Stripe URLs can be dropped in later by env var

### Real-payment boundary

Do not present the site as truly subscribed/charged until Stripe is fully wired and tested end-to-end.

Required rule:

- no live external tester should be told they paid unless real Stripe checkout and success handling are active
- demo checkout is acceptable for internal flow testing only
- if Stripe is not live, the site must clearly remain in `demo membership flow` mode

### Premium UX

Locked pages should:

- explain why access is limited
- show the required tier
- preserve the return destination
- offer sign-in / signup / upgrade in one place

If the boundary feels broken instead of premium, conversion will suffer.

### Section status

- `PASS` if auth, pricing, upgrade, and locked-page flows behave intentionally
- `WATCH` if Stripe is still demo-only but clearly labeled as such for internal testing
- `FAIL` if users can be misled about payment state or cannot understand how access works

---

## 8. Sport-Specific Launch Questions

### NBA

- are playoff series states correct?
- are later rounds using playoff data first?
- are zero-required volatile unders flagged?
- are contradiction warnings narrow and meaningful?

### NFL

- are workbook top plays contradiction-clean?
- are weak governance buckets demoted?
- are receiver-yard tight-support warnings monitored?

### CFB

- is stale-feed protection active on live market surfaces?
- are suggestion/archive paths confirmed for any CFB surfaced plays?
- does contradiction QC exist or is there an explicit note that CFB is still lighter-governed than NBA/NFL?
- is the product still lines/totals/matchups first?
- are props still treated as optional support rather than the product core?

### WNBA

- is stale-feed protection active?
- is the board honest when live props are absent?
- are WNBA featured suggestions being archived if they are shown?
- does WNBA calibration remain labeled `NOT YET MEANINGFUL` until enough rows resolve?

### Section status

- `PASS` if each sport going out to testers has the right freshness, archive, and governance checks in place
- `WATCH` if a sport is intentionally limited in scope but honestly labeled as such
- `FAIL` if a tester-facing sport is live without the basic safeguards defined above

---

## 9. Rollback And Incident Response

If an outside tester finds a factual or integrity issue, the response should be immediate and boring, not improvised.

### Trigger conditions

Treat these as rollback-class issues:

- wrong series state
- stale props presented as live
- wrong injury/return context materially changing a recommendation
- contradiction-breaking featured play shown publicly
- archive/suggestion surface not saving what was displayed
- access/paywall error that blocks the owner or grants the wrong tier

### Immediate response

1. pull or gate the affected surface
2. fix the source or logic issue
3. rerun the relevant QC scripts
4. rerun route smoke for the affected area
5. confirm the archive/calibration path is still intact
6. only then reopen the surface to testers

### Rule

Do not leave a known bad surface publicly visible while "working on it."

### Section status

- `PASS` if the team knows exactly how to pull, fix, re-QC, and reopen a bad surface
- `WATCH` if the procedure is understood but not yet rehearsed
- `FAIL` if a tester-found issue would likely create confusion or delay because nobody owns the rollback steps

---

## 10. External Tester Readiness Decision

### Go / No-Go Scorecard

Before allowing external testing, assign each major section one status:

- `1. Platform Reliability` = `PASS / WATCH / FAIL`
- `2. Data Freshness And Source Truth` = `PASS / WATCH / FAIL`
- `3. Suggestion Integrity` = `PASS / WATCH / FAIL`
- `4. Archive And Replay Readiness` = `PASS / WATCH / FAIL`
- `5. Calibration Readiness` = `PASS / WATCH / FAIL`
- `6. Visual Trust` = `PASS / WATCH / FAIL`
- `7. Pricing And Membership Boundary` = `PASS / WATCH / FAIL`
- `8. Sport-Specific Launch Questions` = `PASS / WATCH / FAIL`
- `9. Rollback And Incident Response` = `PASS / WATCH / FAIL`

### Final decision rule

- `GO` only if there are no `FAIL` sections and any `WATCH` sections are explicitly understood and accepted
- `NO-GO` if any section is `FAIL`
- `NO-GO` if multiple `WATCH` sections combine into a trust risk, even without a formal `FAIL`

You can hand the site to other people only when:

- route smoke passes
- source audits pass
- contradiction QC passes
- stale feeds degrade honestly
- owner/admin access is safe
- suggestion surfaces are archived
- result grading runs
- calibration scripts run
- locked-page UX feels intentional
- the main boards explain themselves

If any one of those is weak, keep it internal.

---

## 11. Operating Principle

Bankroll Kings should not live in trial-and-error mode forever.

The goal is:

1. notice the issue
2. classify the issue
3. write the QC rule
4. write the archive/calibration hook
5. make the failure structurally harder next time

That is how the site stops being reactive and starts becoming durable.
