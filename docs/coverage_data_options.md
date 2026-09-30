# Coverage / Man-Zone Data — Options to Get the "Real" Version

**Context:** Darrel wants ESPN-style notes like *"Diggs has a 30% target share vs man
coverage, which the Colts play at the 3rd-highest rate."* We shipped the honest **free
proxy** (Matchup Edge: usage + NGS separation + opponent pass-D rank — `/tools/nfl-matchup-edge`).
This doc is the decision brief for the **exact** man/zone version, which needs a paid feed.

---

## Why we can't build the exact version for free

The two ingredients — **a receiver's split vs man vs zone** and **a team's man/zone rate** —
are **play-by-play charting**: someone (or a proprietary model) tags the coverage on every
snap. That tag is **not** in any free source we run on:

| Source | Have it? | What it gives |
|---|---|---|
| nflverse play-by-play | ❌ | no coverage type |
| nflverse **FTN charting** (free) | ❌ | motion, play-action, screen, RPO, box count — **no man/zone** |
| **NFL Next Gen Stats** (what we pull) | ❌ (adjacent) | separation, cushion, air yards — coverage-*flavored*, no man/zone label |
| ESPN / NFL Pro app | ✅ (to view) | licensed from a charting partner; **not** redistributable |

So the label itself is a **licensed product**. This is a spend + contract decision, the same
bucket as the DFS/fantasy-salary call.

---

## The providers (who actually charts man/zone)

### 1. PFF — Pro Football Focus  ⭐ the standard
- **Has:** WR & CB man/zone stats and grades, **team coverage scheme rates** (man/zone %),
  target share vs man/zone — exactly the ESPN-note inputs.
- **Access:** a consumer **PFF+** subscription (~$40–200/yr) lets you *read* it, but **does
  not license republishing** it on a commercial site. To put it in our product we need
  **PFF Data & Tech / API** — an **enterprise data license** (annual contract, negotiated,
  typically low-to-mid **four figures and up**, scales with usage/redistribution rights).
- **Integration effort:** low once licensed — clean API/CSV, maps straight into Matchup Edge.
- **Watch-outs:** redistribution terms are the real gate (what we can show, attribution,
  caching). Pricing is a sales conversation, not a public number.

### 2. Sports Info Solutions (SIS) — DataHub
- **Has:** comparable coverage charting (man/zone), defensive scheme data, plus deep
  situational data. Strong alternative to PFF; some sharps prefer SIS charting.
- **Access:** enterprise **DataHub** license, negotiated. Similar cost posture to PFF.
- **Integration effort:** low–medium (API/flat files).

### 3. FTN Data (now home of DVOA / Football Outsiders)
- **Has:** their free charting (via nflverse) is the one WITHOUT man/zone; their **premium**
  products lean fantasy/DVOA and matchup, **less** standardized man/zone than PFF/SIS.
- **Access:** subscription + some data deals. A weaker fit for *this specific* stat.

### 4. TruMedia / other aggregators
- Resell PFF/SIS-style data through an enterprise platform. Same enterprise-contract posture;
  usually pricier because it's a full analytics platform, not just a feed.

---

## Recommendation

1. **Ship the free proxy** (done). It covers ~80% of the intent honestly and legally, and it
   already reads great: *"40% target share, 52% of the air yards, 2.6 yd sep → into WAS's pass
   D ranked 30th."*
2. **When revenue supports a data line-item, license PFF** (first call) or **SIS** (second).
   PFF is the closest one-to-one with the ESPN-note format and the cleanest API. Ask
   specifically for: **team coverage rates (man/zone %)**, **WR receiving vs man/zone**, and
   **CB coverage splits** — and get **redistribution rights for a paid consumer product** in
   writing.
3. **Do NOT** scrape PFF+/NFL Pro and republish. It violates their terms and undercuts the
   honesty brand — a compliance and reputational risk, not a shortcut.

## How it plugs in when we have it

`build_nfl_matchup_edge()` is already the right shape. Swap/augment the NGS-separation term
with the licensed man/zone split, and add the opponent's man-coverage rate as a second
matchup factor. The board's sentence becomes the exact ESPN format:
*"Diggs — 30% target share vs man, into a Colts D that plays man at the 3rd-highest rate."*
No re-architecture — just a richer input behind the same UI.

---
*Status 2026-09-30: free proxy LIVE (`/tools/nfl-matchup-edge`, commit 8c57743). Paid feed =
open decision, pending a spend/licensing call.*
