# Entity-link JS inventory — client-rendered player/team names

**Read-only audit. No conversions were made in this pass.** This inventories where
**JavaScript** builds a player/team name into the DOM (as opposed to Jinja rendering it
server-side), classifies each by whether the resolver has a destination, and records the
nested-anchor / event-handler risks. It closes the *inventory* half of remaining item (2)
of the universal entity-links work (`docs/entity_link_migration.md`,
[[project_entity_links]]): "one server resolver payload across JS surfaces." Conversions
are proposed as reversible batches at the end; none are applied here.

Scope note: the NFL ATS runtime pilot stays OFF; nothing here touches governed boards,
Green Light, rankings, tickets, or models.

---

## The resolver (what "resolvable" means here)

Server-side, gate-aware, sport-scoped (`services/entity_links.py` + `app.py`
`player_url` / `team_url` / `entity_anchor`, all exposed to templates via a context
processor). A name becomes a link **only** when it resolves to exactly one current
entity in that sport; unknown / ambiguous / gated / non-navigational → plain text. So
"gated" is a *per-row* outcome the resolver already handles safely — it is **not** a
reason to skip a surface. What actually disqualifies a surface is **no destination for
that kind** or **no clean entity field to resolve**.

Destinations that exist today:

| kind | nba | wnba | mlb | nfl | cfb |
|---|---|---|---|---|---|
| **player** | ✅ `/player?sport=nba` (or `/tools/nba-player` while stats gate off) | ✅ `/tools/wnba-player` | ✅ `/player?sport=mlb` | ✅ `/tools/player-check` | ❌ **none** |
| **team** | ✅ `/team` or `/tools/nba-team` | ✅ `/tools/wnba-team` | ✅ `/tools/mlb-team` | ✅ `/tools/nfl-team` | ✅ `/tools/cfb-team` |
| **coach** | ❌ no coach entity in any sport | | | | |

Correction to an earlier working note: **MLB / CFB / WNBA teams DO have destinations**
(`mlb-team` / `cfb-team` / `wnba-team` pages exist); they are *resolvable*, not
"no-destination." Only **CFB players** and **coaches** have no destination.

## The reference pattern (already shipped — replicate, don't reinvent)

`templates/green_light_workspace.html` (~L232): the server computes the resolver URL into
the `/tools/green-light/lens/<key>` JSON payload, and the JS renders

```js
var nm = it.url ? '<a class="bk-entity-link" href="'+it.url+'">'+(it.label||'')+'</a>'
                : '<span>'+(it.label||'')+'</span>';
```

So the name is a link **iff** the server emitted a `url`. **Reversible by construction:**
server stops emitting `url` → JS auto-falls back to plain text. Every batch below is
phrased in these terms: the server adds a resolver-backed `url` (or a pre-rendered
`anchor`) to each row of the existing payload; the JS wraps the name cell in `<a>` iff
`url` is present. No eligibility/ordering logic moves into JS.

## Architecture

There is **no `static/js/` directory** — all JS is inline in templates. The dominant
surface shape is:

```js
const DATA = JSON.parse(document.getElementById('X-data').textContent); // server-embedded JSON
// a generic renderTable maps columns -> <td>, injecting r.team / r.player / r[0] as PLAIN TEXT
```

Across **every** embedded-DATA table surface below, a scan for row/cell-level handlers
(`tr.onclick`, `td.onclick`, `.closest('tr')`, `data-player=`/`data-team=` used for a
click) returned **zero** — click handlers live only on `<th>` (sort) and chips/tabs. So
the name cell is a bare `<td>` with no competing handler: **nested-anchor risk LOW,
handler risk LOW** for that whole family.

---

## Matrix — genuinely JS-rendered entity names

| Surface | Route | Entity (field) | Source payload | Sport | Class | Nested-anchor | Handler | Notes |
|---|---|---|---|---|---|---|---|---|
| `bk_power.html` | `/tools/bk-power` | player, team *(td)*; coach *(td)* | embedded `#bp-data` | NFL + CFB | **resolvable** (player/team); coach = **no-destination** | low | low | Generic table. Link player+team; leave coach as text. |
| `cfb_power.html` | `/tools/cfb-power` | team *(td)* | embedded `#pw-data` | CFB | **resolvable** (`cfb-team`) | low | low | Generic table. |
| `cfb_regression.html` | `/tools/cfb-regression` | team *(td)* | embedded `#cr-data` | CFB | **resolvable** | low | low | Generic table. |
| `cfb_situational.html` | `/tools/cfb-situational` | team *(td)* | embedded `#si-data` | CFB | **resolvable** | low | low | Generic table. |
| `cfb_totals.html` | `/tools/cfb-totals` | team *(td)* | embedded `#to-data` | CFB | **resolvable** | low | low | Generic table. |
| `mlb_luck.html` | `/tools/real-vs-luck` | player *(row[0])* | embedded `#rl-data` (`board.rows`) | MLB | **resolvable** (`/player?sport=mlb`) | low | low | Positional-array cells. |
| `mlb_situational.html` | `/tools/mlb-situational` | player *(row[0])* | embedded `#ms-data` (`board.rows`) | MLB | **resolvable** | low | low | Positional-array cells. |
| `scenario_lab.html` | `/tools/scenario-lab` | player *(row[0])* | embedded `#sl-data` | NFL | **resolvable** (`player-check`) | low | low | Player table. Section **titles** (`#sl-scen-title`) are headings → plain text by contract. |
| `nfl_ats.html` | `/tools/nfl-ats` | team *(td)* + `<select>` | embedded `DATA` | NFL | resolvable **but self-referential** | low | low | The link target *is* the NFL-team dossier the page already is → **DEFER** (low value). |
| `cfb_ats.html` | `/tools/cfb-ats` | team *(`<span class="at-exp">`)* | embedded `DATA` + `fetch /tools/cfb-ats/games?team=` | CFB | resolvable **+ HANDLER COLLISION** | n/a | **HIGH** | The team span has `onclick=toggleLog` (expand game log). A nested `<a>` would fight the expand click. Needs a separate affordance; also `gameLogHTML` prints opponent names from the fetch. |
| `parlay.html` | `/parlay` *(slip)* | `${prop.player}` *(JS innerHTML)* | `selectedProps` built from `data-player` | NBA | resolvable **but transient** | low | med (leg has remove control) | Working slip, churns on every pick — **low value**. Board-row name is server-side (below). |
| `fantasy_league.html` | `/fantasy/<league>` *(builder)* | `p.player`, `p.team` *(JS innerHTML)* | lineup-builder state (`data-player`/`data-team`) | per-slate\*\* | resolvable **but transient** | low | med (draggable picks) | Working lineup, not a reference surface — **low value**. |
| `menu_board.html` | `/tools/menu` *(slip)* | `l.label` *(JS innerHTML)* | `#...` leg objects (`data-label`) | multi | **no clean entity field** | — | **HIGH** | Leg is a **composite label** ("Player O/U line") with no separate player field; the `.mb-leg` div is tap-to-add. Needs the server to emit a structured entity before any link — **DEFER**. |
| `_ticket_editor.html` | shared (Daily Card / King's Tickets) | `b.label` *(JS textContent)* | bench/leg objects (`data-label`) | multi | **no clean entity field** | — | **HIGH** | Same as menu_board: composite label; legs are swap/remove/reorder-interactive — **DEFER**. |
| `cfb_matchup.html` | `/tools/cfb-matchup` | team *(header innerHTML)*; coach *(prose)* | embedded `#mu-data` | CFB | **non-navigational** / no-destination | — | — | Team names are page **headings** (`#mu-away-name`), coaches are reasoning **prose** → plain text by the `entity_anchor` contract (context heading/prose). Coaches have no destination. **Exclude.** |

\*\* fantasy league sport depends on the active slate.

### Already done / excluded (not JS-conversion candidates)

| Surface | Why excluded |
|---|---|
| `green_light_workspace.html` | **Reference implementation** — server emits `it.url`, JS links iff present. |
| `_injury_rows.html` (fetched by `injury_report.html` via `/tools/injury-report/rows`) | The "load more" fetch returns **server-rendered** HTML that already uses `entity_anchor('team'/'player', r.league, …)`. Names are not JS-built. **Done.** |
| `football_method_board.html` | Server-side (Jinja). Player block at ~L518 already uses `entity_anchor('player', …)` + `team_mark`. (Some plain `{{ play.player }}` / `{{ row.players }}` remain — server-side gap, see Batch 2, **not JS**.) |

### Server-side names to reconcile (NOT JS — tracked here so the gap is one list)

These render names **server-side** but bypass the resolver (raw `/player/` link or plain
text). They belong to a *Jinja* batch, not this JS inventory, but are the same gate:

- `parlay.html` ~L113 — `<a href="/player/{{ prop.player|urlencode }}">` (raw, not gate-aware; NBA).
- `fantasy_league.html` ~L142 — `<a href="/player/{{ row.player|urlencode }}">` (raw, not gate-aware).
- `parlay_tickets.html` ~L181 — `<strong>{{ pick.player }}</strong>` (plain, saved-ticket picks).
- `parlay_formula.html` ~L389 — `{{ handoff_context.leg.player }}` (plain, SGP handoff leg).
- `football_method_board.html` ~L620 / ~L921 / ~L1033 — `{{ row.players }}` / `{{ play.player }}` (plain).

---

## Proposed reversible batches (for review — not started)

Each batch follows the Green Light contract: **server adds a resolver-backed `url` to the
existing payload row; JS renders `<a class="bk-entity-link">` iff `url` present, else the
current plain text.** Reversing = server stops emitting `url`. No logic moves into JS.

- **Batch 1 — generic embedded-DATA tables (lowest risk, highest value).**
  `bk_power`, `cfb_power`, `cfb_regression`, `cfb_situational`, `cfb_totals`,
  `mlb_luck`, `mlb_situational`, `scenario_lab`. All share the positional-array /
  column-def `renderTable` with a bare-`<td>` name cell and no row handler. For
  positional-array payloads (`board.rows` as arrays), the server emits a parallel
  per-row `url` (or a `{text,url}` cell object) for the name column only; JS wraps that
  one cell. Coaches in `bk_power` stay text (no destination). This is the cleanest
  mirror of Green Light and should be proven on **one** surface (suggest `bk_power` or
  `mlb_luck`) before the rest.

- **Batch 2 — server-side Jinja reconcile (parallel track, not JS).** Replace the raw
  `/player/` links and plain `{{ player }}` listed above with `entity_anchor(...)` so
  they become gate-aware. Closes the same gap without touching any JS.

- **Batch 3 — handler-aware (`cfb_ats`).** The team name lives in a span that already
  owns the expand-log `onclick`. Do **not** nest an `<a>` inside it; instead give the
  name its own small link affordance (icon or a separate linked span) that doesn't
  swallow the toggle, or move the toggle onto a dedicated caret. Needs a design call.

- **Batch 4 — transient builders (optional, low value).** `parlay.html` slip,
  `fantasy_league` lineup builder. These churn on every interaction and are working
  scratchpads, not reference surfaces. Link only if the owner wants it; the leg/pick
  controls mean handler care is required.

- **Deferred / never.** `menu_board` + `_ticket_editor` (composite `label` — the server
  must first emit a structured entity field; until then there is no clean name to
  resolve, and the leg elements are interactive). Coaches and CFB players (no
  destination). Headings/prose in `cfb_matchup`/`scenario_lab` titles (non-navigational
  by contract). `nfl_ats` team (self-referential link).

---

## Open decisions (recommended defaults)

1. **Positional-array payloads** (`mlb_luck`, `scenario_lab`): add a parallel per-row
   `url`, or switch the name column to a `{text,url}` cell object? **Default: parallel
   per-row `url` keyed to the known name-column index** — smaller change, and the JS
   already knows which column is the name.
2. **Prove-one-first:** wire **`bk_power`** as the single Batch-1 pilot (it exercises
   player *and* team *and* a no-destination coach in one surface), QC that displayed
   links equal resolver output, then fan out. **Default: yes.**
3. **nfl_ats self-link:** leave unlinked. **Default: defer** (the destination is the
   page itself).

**Stopping here for review per the directive — no conversions made.**
