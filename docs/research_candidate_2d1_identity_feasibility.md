# Research Candidate 2D1 — NFL Identity/Event Feasibility Audit (READ-ONLY)

**Status: READ-ONLY feasibility audit — PROD RECEIPT RETURNED 2026-10-31 (§3a). No paid fetches, no code,
no flag/route/schema edit.** Determines whether a **governed NFL identity+event adapter** (the first 2D1
prerequisite) can be built from existing artifacts. **Verdict up front (confirmed on prod): EVENT binding
is feasible now AND authoritative (100% — 0 blank ids / 0 unparseable kickoffs / 0 conflicts over 2,158
rows); the observer `UserId` is unique + nonblank; PLAYER identity is FEASIBLE for the resolved majority
(80% of names, 92% of rows) via an EXACT name→player_id join, but ONLY with a governed ABSTAIN path for
the 85 non-authoritative names (171 rows) and the 3 roster collisions.** Per the reviewer's abstain-capable
contract, positive authoritative coverage with zero ambiguity among admitted rows SATISFIES feasibility —
100% resolution is NOT required. The adapter may now be DESIGNED; 2D1 routing stays blocked until the
adapter is designed+approved+built (the registry prerequisite is now BUILT, schema v3).

The adapter must supply, authoritatively, for an owner-entered NFL player observation: (1) an immutable
player id, (2) a canonical display identity, (3) an event id, (4) an authoritative kickoff, (5) explicit
unresolved/ambiguous/missing-event behavior. **No fuzzy matching, no short-form inference, no name-only
authoritative identity.**

---

## 1. Candidate sources (existing artifacts only)

- **Event side — persisted Odds event:** the props feed rows carry `EventId` (the Odds event id) and
  `CommenceTime` (the event commence, UTC). Confirmed on the committed historical artifact
  `data/historical/NFL_Props_History.csv` (schema: `…,CommenceTime,EventId,Player,Team,Opponent,Stat,…`)
  and produced the same way by the live props refresh (`fetch_game_lines.py` etc., `CommenceTime`).
- **Player side — props identity:** the props feed identifies a player by **`Player` (a name string) only**
  — there is **no `player_id` column** on the props/props-history rows.
- **Player side — roster identity:** nflverse carries `player_id` + `player_display_name` (seen build-time
  in `build_nfl_player_stats_from_pbp.py` / the weekly parquet `data/tracking/_nflverse_stats_<yr>.parquet`
  folded into `NFL_GameLogs.csv`). This roster artifact is **prod/runtime-refreshed and not present in the
  checkout**, so the props↔roster join cannot be measured locally.

## 2. Local findings (what the committed artifact proves)

Measured read-only on `NFL_Props_History.csv` (17,394 rows, 550 distinct `EventId`, 438 distinct `Player`):

| Check | Result |
|---|---|
| `EventId` blank | **0** (100% present) |
| `CommenceTime` unparseable / non-UTC | **0** — all 17,394 parse as tz-aware UTC |
| `Player` blank | **0** |
| Normalized names (casefold + whitespace-collapse, **no** fuzzy/short-form) with >1 raw spelling | **0** |
| `(Season, Week, name)` groups spanning >1 `Team` (within-slate ambiguity) | **0 / 6,430** |

So on real historical data the **event binding is complete and authoritative** (`EventId` +
`CommenceTime`), and the props player **names are internally clean** — no punctuation/case variants, no
within-slate same-name-two-teams ambiguity. This is necessary but **not sufficient**: the props side still
has no immutable id.

## 3. The gap and the decisive (prod) measurement

Authoritative player identity requires an **exact, collision-tested join** from the props `Player` name to
a roster `player_id`. Because the roster artifact is prod-only, the coverage/collision counts must be
measured there, **read-only, on persisted artifacts (no paid fetch)**. The owner runs (via SSM):

```bash
# Adjust the two paths to the live props board + the roster/gamelog carrying (player_id, display name).
PROPS=/opt/bankrollkings/data/props/NFL_Props.csv
ROSTER=/opt/bankrollkings/data/tracking/_nflverse_stats_2026.parquet
python3 - "$PROPS" "$ROSTER" <<'PY'
import sys, re, pandas as pd
props = pd.read_csv(sys.argv[1], dtype=str, keep_default_na=False)
ros = pd.read_parquet(sys.argv[2])
def norm(s): return re.sub(r"\s+"," ", str(s).strip()).casefold()
# roster: canonical (player_id, display) -> does ONE normalized name map to exactly ONE player_id?
ros = ros[["player_id","player_display_name"]].dropna().drop_duplicates()
ros["_nm"] = ros["player_display_name"].map(norm)
ids_per_name = ros.groupby("_nm")["player_id"].nunique()
collisions = ids_per_name[ids_per_name>1]                       # a name -> >1 id = NOT authoritative
dup_ids = ros.groupby("player_id")["_nm"].nunique()
props["_nm"] = props["Player"].map(norm)
pnames = set(props["_nm"].unique())
resolvable = {n for n in pnames if ids_per_name.get(n,0)==1}
unresolved = sorted(n for n in pnames if ids_per_name.get(n,0)==0)   # props name absent from roster
ambiguous  = sorted(n for n in pnames if ids_per_name.get(n,0)>1)    # props name -> multiple ids
print("props distinct names:", len(pnames))
print("resolvable to EXACTLY one roster player_id:", len(resolvable))
print("unresolved (absent from roster):", len(unresolved), unresolved[:20])
print("ambiguous (name -> >1 id):", len(ambiguous), ambiguous[:20])
print("roster name-collisions (name->>1 id):", int((ids_per_name>1).sum()))
print("roster duplicate ids (id-> >1 name):", int((dup_ids>1).sum()))
print("props EventId blank:", int((props['EventId'].str.strip()=='').sum()) if 'EventId' in props else 'NO EventId col')
ct = pd.to_datetime(props['CommenceTime'], errors='coerce', utc=True) if 'CommenceTime' in props else None
print("props CommenceTime unparseable:", int(ct.isna().sum()) if ct is not None else 'NO CommenceTime col')
PY
```

Report: resolvable count, **unresolved names**, **ambiguous names (name→>1 id)**, roster
**name-collisions** and **duplicate ids**, props **EventId blanks** (event-binding failures) and
**CommenceTime** completeness (temporal). **Authoritative binding is only possible if every props name
resolves to exactly one roster `player_id`**; any ambiguous/unresolved name must **abstain** (never
guess).

## 3a. Production receipt (redacted, count-only — 2026-10-31)

The owner ran the single corrected `sudo -u ubuntu bash -lc` command (`OWNER_EMAILS` parsed from `app.py`
via `ast`, no app import, unioned with `Role=="owner"`; users `data/tracking/NBA_Users.csv`; props
`data/props/NFL_Props.csv` keyed on `EventCommenceAtUTC`; roster auto-discovered). **Count-only output, no
names:**

| Dimension | Result |
|---|---|
| Observer `UserId` | 13 users, 1 owner; **global duplicate (nonblank) = 0**, **owner blank = 0** → unique + nonblank |
| Event id (`EventId`) | **0 blank** of **2,158** prop rows |
| Kickoff (`EventCommenceAtUTC`) | **0 missing/unparseable**; **0 EventIds with >1 distinct kickoff** |
| Roster artifact | `data/tracking/_nflverse_stats_2026.parquet` — `player_id` + display name present |
| Name resolution | 424 distinct props names → **339 resolved** (exactly one id), **84 unresolved**, **1 ambiguous**; **coverage 80.0%** |
| Roster collisions | **3** name→>1 id; **0** id→>1 name |
| Admitted rows | **1,987 / 2,158 (92.1%)** — resolved name + valid non-conflicting event + kickoff |
| `RECEIPT_COMPLETE` | **True** |

Reading: event binding and the observer id are clean and authoritative. Name identity is majority-clean
with a hard tail: **84 unresolved + 1 ambiguous = 85 names (≈171 rows, 7.9%)** have no authoritative id, and
**3 roster name-collisions** make those names non-authoritative even if they later appear on the board. The
**0 id→>1-name** result means a resolved name's `player_id` is a stable 1:1 — so a resolved match is safe.
These are exactly the rows the abstain path must refuse; feasibility does not require resolving them.

## 4. Owner `UserId` integrity (prod, read-only)

The observer is the account `UserId` (§Rev-3). **CONFIRMED (§3a): the owner row's `UserId` is unique
(0 global nonblank duplicates) and nonblank.** The probe below is retained as the standing check; the
adapter must still **reject** any missing/duplicate legacy identity rather than synthesizing one:

```bash
# owners = OWNER_EMAILS; the users store is prod-only. READ ONLY.
python3 - /opt/bankrollkings/data/users.csv <<'PY'
import sys, os, pandas as pd
owners = {e.strip().lower() for e in os.environ.get("OWNER_EMAILS","").split(",") if e.strip()}
df = pd.read_csv(sys.argv[1], dtype=str, keep_default_na=False)
o = df[df["Email"].str.strip().str.lower().isin(owners)] if owners else df[df["Role"].str.lower()=="owner"]
blank = (o["UserId"].str.strip()=="").sum()
dup = o["UserId"].str.strip()[o["UserId"].str.strip()!=""].duplicated().sum()
print("owner rows:", len(o), "| blank UserId:", int(blank), "| duplicate UserId:", int(dup))
print("OK" if blank==0 and dup==0 else "FAIL: missing/duplicate owner UserId -> 2D1 must reject, not synthesize")
PY
```

## 5. Verdict + missing source contract

- **Observer: RESOLVED (prod-confirmed).** 1 owner row, `UserId` unique (0 global nonblank duplicates)
  and nonblank. The observer is set server-side from this immutable account id, never from email/payload.
- **Event binding: FEASIBLE + AUTHORITATIVE (prod-confirmed, 100%).** Over 2,158 live prop rows: 0 blank
  `EventId`, 0 missing/unparseable `EventCommenceAtUTC`, 0 EventIds carrying >1 distinct kickoff. The
  adapter's event id + kickoff come from the **persisted Odds event**, not user input.
- **Player identity: FEASIBLE for the resolved majority, abstain-capable (prod-confirmed).** The props feed
  has **no immutable player id**; the EXACT normalized name→roster `player_id` join resolves **339/424
  names (80%)** to exactly one id with **0 id→>1-name duplicates** (a resolved match is a stable 1:1),
  covering **1,987/2,158 rows (92%)**. The residual **84 unresolved + 1 ambiguous names (171 rows)** and the
  **3 roster name-collisions** have no authoritative id. Per the reviewer's correction, feasibility requires
  **positive authoritative coverage + zero ambiguity among ADMITTED rows** (true by construction —
  resolved-only), **not** that every provider name resolves. **CONFIRMED feasible** on that basis.
- **Required adapter contract (the join is majority-clean, so build it abstain-first):** a separately
  governed roster-join adapter that (a) uses an EXACT normalized match only — no fuzzy/short-form — (b)
  binds to the roster `player_id`, (c) **abstains** (no record, surfaced as unresolved/ambiguous) on any
  unresolved, >1-id, or roster-collision name, (d) **abstains** on a blank/unparseable `EventId` or kickoff
  or a conflicting kickoff, and (e) is **collision-audited on every roster refresh** (the 3 collisions — and
  the unresolved set — can change week to week). **User-supplied kickoff and name-only authoritative
  identity remain prohibited.**

**STOP — returned for review.** The §3a prod receipt + §4 observer integrity confirm feasibility, so the
governed NFL identity+event adapter may now be **designed** (abstain-first, per the contract above). It has
**not** been designed or built here. 2D1 production routing stays blocked until that adapter is
designed → approved → built; the other prerequisite (the idempotency registry, schema v3) is now BUILT.
