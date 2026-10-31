# Research Candidate 2D1 — NFL Identity/Event Feasibility Audit (READ-ONLY)

**Status: READ-ONLY feasibility audit. No paid fetches, no code, no flag/route/schema edit.** Date
2026-10-31. Determines whether a **governed NFL identity+event adapter** (the first 2D1 prerequisite)
can be built from existing artifacts. **Verdict up front: EVENT binding is feasible now; PLAYER identity
is BLOCKED** on an immutable-id source contract — so 2D1 stays blocked.

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

## 4. Owner `UserId` integrity (prod, read-only)

The observer is the account `UserId` (§Rev-3). Prove production owner records have a **unique, nonblank**
`UserId` before relying on it; **reject** missing/duplicate legacy identities rather than synthesizing one:

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

- **Event binding: FEASIBLE now** — `EventId` + `CommenceTime` are present and authoritative on every
  props row (100% locally). The adapter's event id + kickoff come from the **persisted Odds event**, not
  user input.
- **Player identity: BLOCKED.** The props feed has **no immutable player id**; a name→roster join is the
  only path and is authoritative **only if** the prod measurement (§3) shows **every** props name resolves
  to exactly one roster `player_id` with **zero** roster name-collisions affecting those names. Until that
  is demonstrated AND a governed **abstain** path for any non-unique/unresolved name is designed, 2D1
  stays blocked.
- **Missing source contract (if the join is not clean):** 2D1 requires **either** an immutable player id
  delivered *on the props/event feed itself* (an Odds-API participant/player id, if available), **or** a
  separately governed roster-join adapter that (a) uses an EXACT normalized match only, (b) binds to the
  roster `player_id`, (c) **abstains** (no record) on any unresolved or >1-id name, and (d) is
  collision-audited on every refresh. **Name-only authoritative identity, fuzzy matching, short-form
  inference, and user-supplied kickoff remain prohibited.**

**STOP — 2D1 remains blocked** pending the §3 prod measurement (clean exact join) + a governed
abstain-capable identity/event adapter, and the §4 owner `UserId` integrity confirmation. Return those
results before the adapter is designed for build.
