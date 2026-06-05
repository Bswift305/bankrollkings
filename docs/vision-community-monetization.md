# Vision: Community Layer + Dual-Revenue Monetization

Status: **Future / post-launch.** Captured so the idea is preserved, not built yet.
Owner: Decatur (founder). Drafted during the June 2026 launch.

---

## The idea, in one line

Turn Bankroll Kings from a subscription analytics tool into **a social network for
gamblers** — "a gambler's version of X" — and monetize the resulting traffic
twice: subscriptions *and* sportsbook affiliate / advertising revenue.

---

## Why it's strong

Gamblers are inherently social. They want to talk trash during games, share
picks, brag about hits, and follow sharp users. A community layer is one of the
highest-leverage retention, engagement, and virality engines the product could
add. It also unlocks a second, potentially larger revenue stream (below).

---

## The features (the "X for gamblers" surface)

| Feature | What it is | Build weight |
| --- | --- | --- |
| **Member profiles** | Public profile with tracked record, saved picks, badges | Moderate (accounts already exist) |
| **Shared picks feed** | Make a parlay/ticket public; others see a feed | Low–moderate (rides on existing parlay/bet-review data) |
| **Live game chats** | Real-time room per game during the action | High (needs WebSockets) |
| **Direct messaging** | User-to-user DMs | High (real-time + abuse handling) |
| **Member post page** | X-style posting + feed | Highest (UGC at scale) |

---

## The monetization — two engines

**Engine 1 — Subscriptions (already live):** Free / Pro $29 / Sharp $79 / Elite $149.

**Engine 2 — Community traffic → advertising + affiliate:**
- **Sportsbook affiliate is the prize.** DraftKings, FanDuel, BetMGM, Caesars pay
  ~$100–$500+ per new depositing customer (CPA), plus revenue share. Gamblers are
  the single most valuable affiliate audience that exists.
- Community surfaces (game chats, feeds, profiles) become **ad + affiliate
  inventory**: referral links, "bet $5 get $200" promos, sponsored content, display.
- **The free tier becomes the top of the ad funnel.** Free users who never pay a
  subscription are still monetized through sportsbook affiliate links. "Free tier
  is still traffic advertisers want" — the community is what scales that traffic.

---

## Why NOT now (sequencing)

1. **A social network with no users is a ghost town.** The product launched with
   zero subscribers; community features shown to an empty room make the product
   feel dead. Build the audience on the analytics tool first.
2. **It forces the Postgres + Redis migration.** Posts, messages, and chat cannot
   live in CSVs. Real-time (chat/DMs) needs WebSockets (Flask-SocketIO + Redis).
   This feature is the trigger for the next infrastructure tier.
3. **UGC brings a moderation + legal burden.** Spam, tout scams ("pay me for
   locks"), harassment, content liability. Requires community guidelines,
   reporting, banning, active monitoring. Gambling advertising is also regulated
   and varies by jurisdiction (affiliate licensing, responsible-gambling
   disclosures, age-gating).

---

## Recommended phasing

| Phase | Feature | Prerequisite |
| --- | --- | --- |
| 0 (now) | Validate the analytics product; get paying subscribers | — |
| 1 | Public **profiles** + **shared picks feed** (no real-time) | Postgres migration |
| 2 | **Live game chat** | WebSockets + Redis |
| 3 | **DMs + full posting feed** | Moderation tooling |
| Cross-cutting | Sportsbook **affiliate program** signup + ad inventory | Legal/compliance review |

**First step after user validation:** the shared picks feed. It turns existing
ticket data into social content, drives sign-ups ("come see my card"), and needs
no real-time stack — the cheapest, highest-value entry into the community vision.

---

## The trigger condition

Build Phase 1 when the analytics product has enough active users that they are
*already trying* to share picks and talk to each other (e.g., asking for it, or
posting screenshots elsewhere). Let real demand pick which social feature is first.
