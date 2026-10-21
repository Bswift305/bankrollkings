# Green Light preference workspace — contract (v1)

Controlling spec for the Green Light preference workspace. **Contract only — no implementation in this
commit.** Implementation ships separately and reversibly against these rules. It does **not** require, and
must not touch, King's Tickets draft-store persistence (`KINGS_TICKETS_DRAFTS_ENABLED` stays `0`).

## 0. Purpose (and what it is not)
Green Light organizes **factual research** according to how each user prefers to make decisions. It is **not**
a picks model, not a ranking engine, and not a hidden confidence system. The preference layer changes how the
existing factual material is **presented and user-filtered** — it never changes what is true, never invents a
score, and never grants authority.

Anchor: the existing surface is `build_green_light` (`app.py:31923`), route `green_light_tool`
(`app.py:44469`, PRO-gated via `PRO_ENDPOINTS` at `app.py:813`), template `templates/green_light.html`. The
workspace is an **additive** layer on that surface; with no saved preferences a user sees today's default
board unchanged (full reversibility).

## 1. The lens registry (single source of truth)
Implementation adds a data-only lens registry (shape below) — the one place that declares which lenses exist,
their display name, source builder, scope, classification, and default order. No lens is re-derived by the
preference layer; each is an independent builder already in the codebase.

```
LENS = {
  key:            '<stable_snake_key>',       # stored in prefs; never a display string
  label:          '<human name>',
  builder:        '<function>',               # the existing factual builder (app.py / services)
  classification: 'fact' | 'governed-model',  # governed-model = RESEARCH_ONLY, never authority
  scope:          ['nfl', ...],               # sports it can serve; abstains where data is absent
  default_order:  <int>,
}
```

v1 lens set (keys the user named → existing builders, from the internals map):

| key | label | builder | class | scope |
|---|---|---|---|---|
| `whats_changed` | What's Changed | `build_nfl_matchup_center_context` (What's-Changed block, `app.py:48902`) / `_lookup_change_context` (`app.py:33065`) | fact | nfl |
| `heat_map` | Heat Map | `build_nfl_hot_hand` (`app.py:31140`) | fact | nfl |
| `riding_the_wave` | Riding the Wave | `build_nfl_prop_streaks` (`app.py:47155`) / `build_nfl_wave_context` (`app.py:47823`) | fact | nfl |
| `milestone_streaks` | Milestone Streaks | `build_nfl_milestone_streaks` (`app.py:47457`) | fact | nfl |
| `market_line_streaks` | Market-Line Streaks | `build_nfl_prop_streaks` graded over/under | fact | nfl |
| `ats_waves` | ATS Waves | `build_nfl_ats_wave` (`app.py:47778`) / `build_cfb_wave_context` (`app.py:45804`) | fact | nfl, cfb |
| `matchup_context` | Matchup Context | `build_nfl_matchup_center_context` (`app.py:48769`) | fact | nfl |
| `injuries_return` | Injuries / Return Status | `build_nfl_injury_changes` (`app.py:6956`) + `_nfl_player_return_status` (`app.py:31068`) | fact | nfl |
| `weather` | Weather | `_nfl_game_wind_map` (`app.py:6932`) | fact | nfl |
| `line_movement` | Line Movement | `_load_line_movement_current` (`app.py:38236`) / `_nfl_line_move` (`app.py:46592`) | fact | nfl |
| `contradictions` | Contradictions | `apply_nfl_contradiction_guardrails` (`app.py:8207`) / per-sport `services/*_contradiction_qc.py` | fact | nfl, cfb, mlb, nba, wnba |
| `governed_models` | Governed Research Models | `research_for_market` (`services/model_registry.py:65`) | governed-model | cross-sport |

`governed_models` is the only non-fact class: `model_registry.has_authority` (`services/model_registry.py:49`)
gates authority to `status=='Qualified'` + all validation `passed`; today the single entry is Discovery with
no authority. The preference layer may show/hide/order it but it **never** gains sort or membership authority
and is always visually tagged as a governed-model read, distinct from facts.

## 2. Preference capabilities
A user may:
- **select** which lenses are visible and **order** them;
- set **preferred sport(s)** and **markets** (a user-requested filter);
- set **display settings** (e.g. density, whether "why" is expanded by default);
- (the proposed-ticket default size/shape comes from the **existing shared card prefs** — see §3).

Preferences control presentation and user-requested filtering only. They are bound by these **rails**:
1. **No silent suppression of factual qualifiers.** A filter may hide a whole lens, or narrow by a sport/market
   the user chose, but within any shown item every factual qualifier stays — availability state
   (Verified/Partial/Pending/Stale/Unavailable), "data through week X", abstention, contradictions, the line's
   "captured not open/close" note, illustrative-price labels. The preference layer may not drop a qualifier to
   make a result look cleaner or stronger.
2. **Show how many items are hidden by the user's filters.** Every lens and the workspace as a whole display a
   visible hidden-count ("N hidden by your filters" / "Lens hidden by you"), so a filter never reads as "there
   is nothing here."
3. **Reset to Default** restores the owner/house default lens set, order and visibility (clears the user's
   `greenlight` prefs).
4. **Every result answers "Why is this showing up?"** Each shown item carries its factual `why` (Green Light
   lenses already emit `{'lens','why'}`; Matchup Center emits `why_interesting`/`whats_changed`). The workspace
   additionally states why a lens/item is visible or hidden using the shared reason-code pattern.
5. **Facts, user preferences and governed-model reads remain visibly distinct.** Three visual registers that are
   never blended: factual lens output; the user's own preference/filter state; governed-model reads (tagged,
   authority-free).

"Why is this showing / hidden" reuses `services/nfl_inclusion.py`: `Reason` codes (`:30`) and `reason_class`
(`:68`) split VIEW (user filtered it) from ELIGIBILITY (a factual gate). **Preference-driven hides are always
VIEW-class** — a user filter is never dressed up as a factual exclusion, and a factual exclusion is never
hidden behind a preference.

## 3. Storage boundary (reuse, do not fork)
Reuse the existing account-bound UI-preference store — one JSON per user at `data/user_prefs/{uid}.json`
(`_CARD_PREFS_DIR`, `app.py:32838`), uid via `_card_prefs_uid` (`app.py:32841`), anon → house default with a
**no-op write** (mirror `save_card_prefs`). Add one new top-level key, `greenlight`, via
`load_greenlight_prefs(uid)` / `save_greenlight_prefs(uid, prefs)` modeled verbatim on `load_home_view` /
`save_home_view` (`app.py:32895`–`32919`): read-merge-write, validate against controlled vocab, unknown values
dropped to default (never stored raw).

```
greenlight = {
  "lens_order":  ["<lens_key>", ...],      # subset/permutation of registry keys; unknown keys dropped
  "lens_hidden": ["<lens_key>", ...],      # lenses the user hid
  "sports":      ["nfl", ...],             # preferred sports (validated against lens scopes; v1 nfl[, cfb])
  "markets":     ["<market_key>", ...],    # user-requested market filter; validated vocab
  "display":     {"density": "...", "why_expanded": true|false}   # display settings only
}
```

**Store ONLY** UI configuration: lens visibility, lens order, preferred sport/markets, default ticket size,
display settings. The **default ticket size/shape** is read from the existing shared card prefs
(`load_card_prefs`, `DEFAULT_CARD_PREFS` `sizes/risk/legs/timeframe`, `app.py:32519`) so there is one ticket
default across Daily Cards, King's Tickets and this workspace — it is **not** duplicated into `greenlight`.

**Never store** (these are not UI configuration): ticket legs; prices; betting outcomes; journal reasoning;
sportsbook activity. Preferences are UI configuration, not ticket history. The workspace performs **no**
Decision Journal writes and **no** King's Tickets draft-store writes.

## 4. Green Light output (the proposed ticket)
The workspace may assemble an in-page proposed 2–5-leg ticket using the **existing shared editor**
(`templates/_ticket_editor.html`, the one component Daily Cards and King's Tickets both include; builder
`build_daily_cards`, `app.py:32760`). Until the draft feature is enabled:
- edits are **browser-page-only**; state does **not** persist across navigation;
- **no hidden handoff** and **no private data in URLs** (no legs/prices/provenance in query strings or logs);
- where a value can't be carried, use the **full-fidelity copyable fallback** (the current Green Light→King's
  Tickets pattern, `green_light.html:58`), never a silent transfer;
- the temporary limitation is **clearly disclosed** in-page ("not saved yet — edits stay on this page");
- the combined price stays **illustrative/calculated** (the editor's existing labeling and `—` abstention),
  never presented as a sportsbook quote.

## 5. Verification (acceptance criteria — the implementation must prove each)
1. **Same factual source universe before/after preferences** — the set of candidate items each lens builder
   produces is identical with and without prefs; preferences only hide/reorder for display. A regression test
   diffs the builder's full candidate set against the preference-applied set and asserts the hidden set = exactly
   what the user's filters removed (no extra drops, no silent additions).
2. **Deterministic lens ordering** — given the same prefs, order is stable and reproducible (explicit order list
   + stable tie-breaks; no randomness).
3. **Hidden-by-user count** — the count shown equals the number removed by the user's filters, per lens and
   overall.
4. **Reset restores owner default** — clearing prefs returns the exact house default order/visibility.
5. **No model-based membership suppression** — no lens or governed model removes a factually-eligible item from
   membership; only user filters (VIEW-class) and existing factual gates (ELIGIBILITY-class, unchanged) affect
   visibility, and each is labeled as such.
6. **No Decision Journal or draft-store writes** — asserted by inspection + a guard that the workspace path
   imports neither the journal nor `KingsTicketDraftStore`/`DraftService`.
7. **Cross-account isolation** — one account's prefs never affect another's; anon gets the house default and
   writes nothing.
8. **Authenticated desktop and 375px** — verified in the browser at both widths (no horizontal scroll, controls
   reachable), per the mobile-shell conventions.
9. **Performance within the recently closed budgets** — the workspace stays within the Site Performance P0
   budgets (warm well under the dashboard's ≤800ms; no new uncached per-request rebuild); lens outputs reuse
   their existing disk/TTL caches rather than recomputing.

## 6. Ship plan (reversible)
1. **This contract** (doc only) — commit 1.
2. **Preference store + lens registry** — `load_greenlight_prefs`/`save_greenlight_prefs` + `GREENLIGHT_LENSES`,
   with `qc_green_light_preferences.py` covering §5.1–§5.7. No UI yet. Commit 2.
3. **Workspace UI** — preference panel (select/order/hide, sport/market filter, display, Reset), the
   preference-applied composed view with hidden-counts and per-item "why", and the browser-only proposed ticket
   via the shared editor. Commit 3. Verify desktop + 375px + perf (§5.8–§5.9).

Each commit is independently revertible; with the `greenlight` key absent, the Green Light surface behaves
exactly as it does today.

**Stop point for this commit:** contract returned. No code, no route, no prefs key, no UI until the contract is
accepted.
