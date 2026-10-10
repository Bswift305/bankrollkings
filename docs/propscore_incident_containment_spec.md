# PropScore Incident Containment Specification (Final Freeze Candidate v2)

**Read-only specification. No implementation, no code.** Governing decisions (**final**):
**PropScore v1 → research status `Failed`; operational condition `Quarantined`.** Scope: PropScore v1
only. One explicit, neutral, executable behavior per surface — no options, no implementation-time
choices. Dated 2026-10-09.

Governing principle: *a failed mechanism may remain visible as part of the historical record; it may
not continue exercising authority over live customer decisions.* A replacement that swaps one
ungoverned authority ordering for another is not containment — replacement behavior is **neutral and
observable.**

---

## 1. PropScore removed from ALL live decision surfaces (FROZEN)

**No PropScore column, badge, score, caveat, tier, or row-level guidance appears on any live
decision surface.**

- **NFL props screener (`props.html`):** remove the PropScore display column/value. Default sort →
  **`player` (A→Z)**; remove the `prop_score` sort option (`props.html:423`); `app.py:32194` default
  `'prop_score'` → `'player'`; delete the "-EV" comment at `32192-93`. Membership unchanged.
- **Football method board (`football_method_board.html:544-546, 937-939`):** remove the
  `Prop {{ row.nfl_prop_score }}` cell and `prop_score_detail`.
- **NFL Spots, NFL Totals Context, matchup, any live board/card:** no PropScore value, tier, or
  inline guidance.

**PropScore survives ONLY in:** Formula Lab (relabeled research artifact), research archives
(`research/nfl_edge/`), audit records, preserved scored CSVs, future Research Ledger entry.

## 2. NFL Spots — membership & behavior (FROZEN)

- The `sp_top` PropScore section (`app.py:45486-45516`) is **removed** with its `≥10` floor, `≥20`
  premium tier, and `sp_premium_count`. Nothing re-populates it.
- **Remaining:** wind-under (§5) + injury-change-timing. Subtitle (`nfl_spots.html:47`) → *"Two
  situational signals this week — wind-driven passing unders and injury-change timing."*

## 3. NFL Totals Context (FROZEN — renamed, neutral)

Replaces the former "NFL Top-20 Board" after the PropScore candidate block (`app.py:44086-44104`) is
removed.

- **Name:** **"NFL Totals Context."** No "Board/Top/20," no ranked-edge framing.
- **Membership:** all eligible game totals for the week (every scheduled game with a posted total).
  No props.
- **Ordering (FROZEN, neutral):** **kickoff time (ascending), then matchup name (ascending).** The
  model `base`/edge is **removed** as the ordering authority — **no edge hierarchy.**
- **Model read is labeled context, not rank** (e.g. "model 44.1 vs posted 47") and does not reorder.
- **No cap, no padding, no "Top" framing.** Wind rows labeled per §5.

## 4. Marketing quarantine (FROZEN — executable)

Scoped **only** to the PropScore-selected cards. **Unrelated marketing assets are untouched** —
`proof_*.png`, `difference_*.png`, `feature_*.png`, `myth_*.png`, `howto_*.png`, `bk_openers.png`,
and every other `marketing/` asset (including the already-modified ones in the working tree) are
**out of scope.**

1. **Exact content manifest (the only files moved):** under `marketing/weekly_cards/` —
   `bk_top_props.png`, `bk_premium_board.png`, `bk_floor_board.png`, `bk_hitlist.png`,
   `bk_sunday_best.png`. (Move those that exist; absence of a file is a no-op, not an error.)
2. **Exact archive path:** `marketing/_archive/propscore_quarantine_2026-10-09/` — the five files
   above are moved here verbatim (filenames preserved).
3. **Dispatch removal:** in `marketing/generators/weekly_cards.py` `main()`, remove the dispatch
   lines for these modes — `top` (`:1616`), `premium` (`:1618`), `floor` (`:1620`), `hitlist`
   (`:1626`), `sunday_best` (`:1640`) — and remove `top,premium,floor` (and `hitlist`, `sunday_best`)
   from the `--only` help/allowed set (`:1598`).
4. **Publishing exclusion:** these modes produce no output on any path; any routine (run_daily /
   scheduled task) that invokes `weekly_cards.py` must not request them. No published card selects,
   ranks by, or labels PropScore "validated/proven edge."
5. **Rollback procedure:** `git revert` the containment commit restores the dispatch entries;
   restoring the five images is `git mv` back from `marketing/_archive/propscore_quarantine_2026-10-09/`
   to `marketing/weekly_cards/`. **Verification after the move:** `git status --porcelain` shows
   **only** those five path moves under `marketing/weekly_cards/` + `marketing/_archive/…` and the
   `weekly_cards.py` dispatch edit — nothing else; the pre-existing unrelated marketing modifications
   remain exactly as they were.
6. **Historical preservation:** the generator source and the archived images are **kept** (archived,
   not deleted).

## 5. Wind-under — interim language (FROZEN)

| Surface | Frozen wording |
|---|---|
| `football_method_board.html:331` | **"Wind-under historical backtest: approximately 55% in the documented sample. Governance status not yet assigned."** |
| `football_method_board.html:357` | "Wind-under rows are highlighted — **historical backtest approximately 55% in the documented sample; governance status not yet assigned.**" |
| NFL Totals Context wind tier (`app.py:44139`) | tier label **"Backtest ~55% (not yet governed)"**. |

## 6. Green Light — ordering + labels (FROZEN)

- **Ordering (`app.py:30957-30958`), frozen to:** **configured-lens count (descending), game
  identifier (ascending), player (ascending), stat (ascending)** — and nothing else. `eligible` and
  `opp_score` are **removed** from the sort key.
- **Labels (observed state, not interpretation).** `green_light.html:83` badge + gate notes
  (`app.py:30837-30843`) show exactly one of:
  - **"Line +X since open"**
  - **"Line −X since open"**
  - **"Over price shortened by X"**
  - **"No material line or Over-price shortening detected"**
- **Removed entirely:** the words **"eligible," "priced in," "unpriced," "caught up."**
- **Copy:** `:48` → **"the line is unchanged or softer since it opened"**; `:56` → **"the line
  hasn't moved since open"**; `:92` → **"a flat or softer line since open is an observation, not a
  prediction that the play will hit."**

## 7. Customer-facing claims (FROZEN)

| Surface | Current | Frozen action |
|---|---|---|
| `nfl_board.html:44,48,64` | "VALID" badge / "Validated plays… backtested ROI" / "validated PropScore… proven" | Remove all PropScore validated/proven language (board is totals-only, §3). |
| `nfl_spots.html:47,77,78,128` | "validated PropScore / held out of sample / out-of-sample-confirmed… monotonic" | Removed with `sp_top` (§2). |
| `cfb_board.html:33,45` | "best spread & total plays… model lean… NFL PropScore… do" | Replace **exactly** with: **"CFB markets are ordered by displayed model–market difference. No validated betting edge is claimed."** No "play / plays / lean / edge" language. |
| `nfl_formula_lab.html:15,31,61` | "PropScore Backtest" | Relabel: **"PropScore v1 — research artifact; shipped validation was leakage-contaminated and did not survive a clean holdout; not used for live selection."** |
| `how_we_analyze.html:127,133` | "a **validated edge**, a model lean, or a situational spot…" | The "validated edge" category **cannot remain live**. Replace with: **"We tier each play by how much evidence backs it — a documented backtest result, a model estimate, or a situational note — and show that status openly. No play is labeled a validated edge unless a governance record supports that claim."** |
| `weekly_cards.py` captions | "the validated edge / Our proven edge" | Removed with the cards (§4). |

## 8. Treatment of Failed mechanisms on live pages (FROZEN policy)

Status `Failed` + condition `Quarantined` (PropScore v1 and any future one): **may** appear **only**
in research/history surfaces as a labeled research artifact linking to its lineage; **may not**
appear on any live decision surface in any form, nor be a sort key / default sort / filter /
threshold / tier / selection input / board-or-card candidate, nor carry "validated / proven / edge /
premium / trusted / top signal" language, nor gate a premium surface. **Computation + artifacts
preserved** (`calculate_nfl_prop_score.py`, scored CSVs, `validate_nfl_prop_score_oos.py`,
`research/nfl_edge/FINDINGS.md` / `PRODUCT_SPEC.md` — each gains a one-line pointer to the validator).

## 9. Visual lock cues (FROZEN — one rule)

**Remove the customer-facing lock treatment entirely; preserve the underlying `is_lock` field only.**
A lock renders **identically to a non-lock row** — no special word, color, gradient, icon, or glow.

| Surface | Current cue | Frozen result |
|---|---|---|
| `matchup.html:330` | gold gradient badge | plain `grade-badge` |
| `smart_picks_v2.html:885-886` | gold gradient + literal "Lock" | gradient and "Lock" removed; neutral value |
| `smart_picks_v2.html:928` | `lock_reason` note | removed |
| `parlay.html:160-161` | 🔒 + accent fill | 🔒 and fill removed; neutral |
| `parlay_formula.html:579` | lock glow | glow removed; neutral |

(`is_lock` = `confidence ≥ 80`, `app.py:26249`; the field is preserved, only the customer-facing
treatment is removed.)

---

## Methodological boundary
PropScore v1 only. A corrected **v2** is a separate trail (mechanism statement → preregistration →
review → authorization → validation).

## Status
Nine sections, one explicit neutral behavior each; §4 is executable (manifest, path, dispatch lines,
rollback, non-touch scope). **No fixes, no code, no implementation.** Implementing this spec is a
separate authorized gate.
