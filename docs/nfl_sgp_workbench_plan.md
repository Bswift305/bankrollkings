# NFL SGP Workbench — V1 implementation plan + conflicts (step 2 deliverable)

Matchup-first construction/research tool at `/tools/sgp-workbench` (NFL-only). NOT an automatic "best SGP"
generator. This is the plan returned before implementation per the directive's delivery sequence.

## 1. Read-only characterization (what exists, what it provides, the gaps)

| Reuse path | Location | Provides | Gap for the Workbench |
|---|---|---|---|
| `_SGP_CATEGORY` / `_sgp_category(stat)` | app.py:45477 | QB / Rushing / Receiving / Touchdowns / Defense grouping | No Game/Period lines or Team Totals categories |
| `_nfl_game_prop_menu(away, home, props_df)` | app.py:45529 | per-game player-prop legs grouped by category; tackle-volume lean; QB-out injury flag. Leg = `{player, stat, line, lean, inj}` | **consensus median line only** — drops direction, price, book, timestamp, lineage, freshness |
| `NFL_Props.csv` | data/props | `Player, Team, Stat, MarketKey, Line, Game, Book, LastUpdated, OverOdds, UnderOdds, …` | individual O/U prices + book + timestamp ARE present (straight-prop quotes, not combined-SGP) |
| `_nfl_line_move(away, home)` | app.py:45583 | open→current spread/total movement | feeds "What's Changed?" |
| `build_nfl_matchup_context()` | app.py:45622 | matchup dossier, game story, injury/QB-out, current-form, line movement | the game-context + "Game Story" source |
| `calculate_correlation_iq(legs)` | app.py:14529 | same-player / same-game / same-team pair flags | not the directive's specific deterministic rules; no Supports/Conflicts/Concentration split |
| Decision Journal | services/decision_journal.py:29 | `ticket_type='same-game-parlay'` already a TICKET_TYPE | handoff must target THIS record; stays disabled while `DECISION_JOURNAL_ENABLED=0` |
| Parlay Builder | `/parlay` (app.py:40792) renders `parlay_formula.html` | existing slip + CorrelationIQ + ticket drawer | handoff target ("copy/transfer to Parlay Builder") — must not change its behavior |
| NFL matchup page | `/sports/nfl/matchup/<sheet>` (app.py:33453) | matchup render; entry point | add an SGP Workbench entry point |

## 2. V1 implementation (one reversible commit)

**Route:** `@app.route('/tools/sgp-workbench')` (authenticated, like other `/tools/*`), GET only;
`?game=<away@home>` (or matchup slug) selects the game. No game selected → matchup selector only.

**Context builder** `build_sgp_workbench_context(game=None)` in app.py:
- Matchup selector: this week's NFL games (reuse `build_nfl_matchup_context()` week list).
- "What's Changed?": reuse `_nfl_line_move()` + injury/QB-out deltas from the matchup context.
- Game Story: a fixed thesis list (Home controls / Away trails+passes / Low-scoring defensive / Shootout /
  Run-heavy / Pass-heavy / Custom) — presentation only; never marks legs profitable.
- **Available Legs** via a NEW richer menu `_nfl_sgp_leg_menu(away, home)` that preserves per leg:
  `player|team, stat, category, direction (OVER & UNDER as separate selectable legs), exact line,
  individual price (OverOdds/UnderOdds when present else null→"price unavailable"), book, last_updated
  (timestamp), lineage (NFL_Props + odds provider), availability/freshness, factual context (tackle lean,
  current-form note), injury/role warning (QB-out)`. Reuses `_sgp_category`, the tackle lean, and the
  QB-out flag from `_nfl_game_prop_menu`; ADDS Game/Period lines + Team Totals groups from the odds feed.
  Never synthesizes a per-leg price from a combined-SGP quote (the straight-prop feed has genuine
  individual prices; game/total lines carry their own two-sided prices or "price unavailable").
- Selected SGP: client-side slip (one game only); server validates single-game on any POST-free action
  via query encoding — V1 keeps selection client-side (no new writer), with a "copy ticket" to Parlay
  Builder (encodes legs into the existing `/parlay` handoff) and a disabled Decision Journal button.

**Contradiction engine** `sgp_contradictions(legs, thesis)` — pure, deterministic, no hidden score.
Returns four buckets, each finding = `{rule_id, rule_text, legs:[...], bucket}`:
- Conflicts: same player/stat OVER+UNDER; opposing game-total directions; team-total OVER + game UNDER
  (tight numbers); QB pass OVER + ≥2 primary-receiver UNDERs; QB pass UNDER + ≥2 receiving OVERs;
  RB rush OVER vs trailing/pass-heavy thesis; multiple TD legs vs limited scoring; defense/tackle legs vs
  the game story.
- Concentration: too many legs on one player; too many on one team's exact script.
- Supports: legs consistent with the chosen thesis (deterministic, descriptive).
- Unknown/insufficient evidence: legs lacking inputs to judge.
Every finding names the exact rule + the affected legs. Removing a leg removes its findings (pure fn of
current legs). Reuses `calculate_correlation_iq` only for the same-player/team concentration primitives.

**Correlation language (verbatim disclosure):** "These legs may move together, but the sportsbook prices
same-game correlation. Alignment can make the ticket coherent; it does not prove the combined price is
favorable." Any naive probability product is labeled "Assumes independence; not the sportsbook's
correlation-adjusted probability." Never present a product as the true SGP probability.

**Template** `templates/sgp_workbench.html` (extends `bk_base.html`, authed shell), sections in the
required order: 1 Matchup selector · 2 What's Changed? · 3 Game Story · 4 Available Legs · 5 Selected SGP
· 6 Alignment & Contradictions · 7 Market/price disclosure · 8 Decision Journal handoff (disabled while
dark). Mobile (375px): leg rows become tappable cards, the slip is a sticky/collapsible panel that never
blocks the menu, tables scroll internally, no horizontal overflow.

**Nav entry points:** NFL Hub (`nfl_hub.html`), NFL Matchup page (`nfl_matchup.html`), Parlay Builder
(`parlay_formula.html`), and relevant matchup/game cards → a labelled link to `/tools/sgp-workbench?game=…`.

**Governance (enforced):** facts create visibility; Discovery/Under-Review research may explain context but
never orders/selects/scores; only a Qualified registry entry (`has_authority`) could affect ordering —
none here. No PropScore revival; no contained-calibration ranking; no "best SGP/lock/highest confidence";
market prices stay market facts; missing/stale inputs abstain visibly.

**Legal/data:** cleared datasets only (`docs/legal_register_v2.md` — Odds API props/lines, nflverse);
`BK_NBA_STATS_ENABLED=0` untouched (NFL-only); no logos/player imagery; preserve provider attribution +
source timestamps; no new provider/paid dependency.

**QC** `qc_sgp_workbench.py` (registered in `run_all_scorecards.py`) — the 16 acceptance tests:
single-game-only, explicit clear/switch, same player/stat O/U contradiction, remove-leg-removes-warnings,
idempotent duplicate, missing-price stays "price unavailable", combined price never on a leg, each
finding links legs+rule, alignment never a recommendation/score, Discovery can't reorder, PropScore/
calibration containment intact, NFL matchup membership+ordering unchanged, Parlay Builder unchanged
outside the handoff, Journal dark, (desktop+375px verified in prod), cross-sport regression clean.

## 3. Conflicts / decisions discovered (need a nod before I build)

1. **Menu scope gap (expected):** the existing `_nfl_game_prop_menu` is player-props-only and consensus-
   line-only. V1 adds a parallel richer builder that also emits Game/Period lines + Team Totals and
   preserves direction/price/book/timestamp/lineage. I will NOT change `_nfl_game_prop_menu` (the NFL
   matchup page depends on it — acceptance test #12); the Workbench gets its own builder. OK?
2. **Selection persistence:** V1 keeps the slip client-side (no new server writer/store), with a "copy to
   Parlay Builder" handoff and a disabled Journal button — consistent with "no production writer" and the
   dark Journal. If you want server-side saved SGP drafts, that's a separate store (not in V1). OK to keep
   V1 client-side?
3. **Game/total leg prices:** game spreads/totals/team-totals come from the odds feed with two-sided
   prices; where a specific side's price is absent it shows "price unavailable" (never synthesized). Team-
   total availability varies by book — legs with no cleared line simply don't appear. OK?
4. **Contradiction thresholds** (e.g., "tight numbers" for team-total-Over + game-Under; "multiple primary
   receivers"; "too many legs on one player") will be explicit constants documented in-code. I'll pick
   defensible defaults (e.g., primary receivers = top-N by prop line; "too many on one player" = ≥3) and
   list them in the QC. Flag if you want specific thresholds.

No blockers. Awaiting a nod on the four decisions (or "proceed"), then I implement as one reversible
commit, run focused + cross-sport regression, push on green, deploy, and verify desktop + 375px.
