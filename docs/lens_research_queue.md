# Lens Research Queue — the roster

Bankroll Kings now has something most betting products never build: a mechanism for
**killing its own ideas**. Lens Attribution (`capture_green_light.py` → `grade_lenses.py`
→ `data/tracking/Lens_Grades_Summary.json`) grades the *evidence*, not the bet, and the
doctrine's 4th question is law — **a lens that fails Q4 loses its seat, no matter how
good its story was** (`BANKROLL_KINGS_DOCTRINE.md` §10).

So this file is a roster, not a wishlist. A lens is in one of **four** states —
**Production, Under Review (probation), Research Queue (applicant), Retired** — and it
moves between them only on evidence from the attribution archive, never on how smart it
sounds. What we've accidentally built is not a feature workflow (Research → Board) but a
research-organization one:

```
Research → Lens → Capture → Grade → Attribution → Promotion / Termination
```

Most betting products stop at "Board." The states below are the back half of that chain.

---

## Production — proven, in the board

These vote in Green Light today and have cleared discovery (Q1), independence (Q2) and
market (Q3). They keep their seat only as long as Q4 keeps agreeing.

| Lens | Mechanism (why it's independent) |
|---|---|
| **Opportunity** | Volume/role creates the chance — usage, routes, carries |
| **Matchup** | Defense-vs-channel surrenders the specific production |
| **Game Identity** | Game script dictates whether the plan even gets run |
| **Role Stability** | A locked share is a floor; a volatile one isn't — validated, partial r +0.69 |
| **Channel Dependency** | One channel vs many changes how a defense can take it away |
| **Concentration (TD)** | Red-zone/goal-line share concentrates scoring in one back |

## Under Review — earning their keep right now

Built and capturing, **not yet proven**. These are the rows to watch as the archive
fills. The whole point of the next few weeks is to resolve these:

- **Script Confidence** (high / medium split) — does conditioning on win-prob certainty
  actually separate the hit rate, or is it noise dressed as humility?
- **Fragile warning** (single-channel × shaky script) — **this one has to underperform or
  it loses its seat.** A warning that doesn't predict misses is just anxiety.
- **Lens interactions** — the killer table. The headline row to watch:
  **Opportunity ALONE vs Opportunity + Role Stability (Locked).** If Role Stability is
  a genuinely independent lens, that pair should separate from Opportunity alone fairly
  quickly. Then: Opportunity + Stability + Matchup (does stacking independent lenses
  compound?).

## Research Queue — not built, not promoted, just waiting

Ordered by mechanistic promise. **None of these gets built until the Under-Review rows
resolve** — and when one is built, Attribution judges it on day one.

1. **Coach Identity** — the special one. Unlike Let-Down Factor (killed as folklore,
   persistence +0.04), this keeps passing every test, and the reason is *mechanistic*:
   the coordinator literally controls PROE, pace, personnel grouping, red-zone play
   selection and 4th-down aggression — and those decisions **create opportunity**. That's
   a real causal layer, not a narrative. The discipline: when it's built, we don't argue
   about whether it's real — Attribution tells us "did it help?" or "did it sound smart?"
2. **Red-Zone Concentration expansion** — widen Concentration beyond anytime-TD share.
3. **Deep passing channels** — split WR receiving into deep vs underneath channels.
4. **TE middle-field channels** — seam/middle usage as its own channel.
5. **Market Overreaction research** — does a line move *past* the news create a fade edge,
   or is it already priced (the null our whole record keeps confirming)?
6. **Travel / Rest dynamics** — short week, cross-country, Thursday games.

## Retired — had a seat, lost it

Empty, and that's the point: nothing has failed Q4 yet because nothing has *resolved*
yet. When a lens degrades past its mechanism's promise, it lands here with the date and
the row that killed it — not deleted, *recorded*. A retired lens is evidence too: it tells
the next idea what "sounded smart but didn't survive" looks like. (Let-Down Factor would
live here if it had ever earned a seat; it was killed as an applicant instead —
`research_expectation_sensitivity.py`, persistence +0.04.)

---

## The rule that governs this file

> Out-of-sample or it does not count. A lens is promoted from Under Review to Production
> only after it clears the sample floor (MIN_SAMPLE=25 resolved) **and** shows the
> separation its mechanism predicts. A lens is demoted — or a Research-Queue idea is never
> built — when Attribution says the story didn't survive contact with resolved games.

### Lens Longevity — the metric to add once plays resolve

Don't only track hit rate and ROI. Track **state over time**. A lens rarely dies in a
day; it degrades — or quietly strengthens — across weeks, and that trajectory is
information a single snapshot hides (the Averaging Audit discipline applied to our own
record). The intended shape, **activated when the archive has resolved plays, not built
ahead of the data**: stamp each lens in `Lens_Grades_Summary.json` with its current state
and the week it entered that state, so we can later read a lens's path
(`Research → Probation → Production`, or `Production → … → Retired`) rather than just its
latest cell. Degrading-but-not-dead and strengthening are both signals worth seeing early.

---

The highest-value thing on the platform for the next few weeks is not a new lens. It's
`GreenLight_Archive.csv` slowly filling with resolved plays. That CSV is where we learn
which of our ideas deserve to survive.

See also: [[project_green_light_lens_attribution]], `BANKROLL_KINGS_DOCTRINE.md` §10.
