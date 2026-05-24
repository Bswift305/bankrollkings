# Bankroll Kings Methods-First Redesign Translation Plan

## Source References
- `C:\Users\Decatur\Downloads\props_redesign.html`
- `C:\Users\Decatur\Downloads\heatmap_redesign.html`

## Decision
Bankroll Kings should move forward as a `methods-first` betting product.

That means the core product lanes are:
- `Floor Plays`
- `Trends`
- `Market Edge`
- `Matchup Lens`
- `Parlay Builder`

The redesign work should support that structure directly instead of treating every page like a generic prop table.

## Big Picture Read
### `props_redesign.html`
This is the stronger design system.

Why it works:
- The typography stack feels premium and intentional.
- The stat-strip is cleaner than the current live page.
- The spacing is tighter without feeling cramped.
- The page has a better editorial feel, which fits a methods-based product.
- The floor-play explainer block is strong and beginner-friendly.

Risk:
- It is still labeled like a generic props board.
- It needs to absorb live app features that were added after the mockup:
  - multi-book comparison
  - injury context notes
  - methods-first naming
  - rank-driver chips
  - beginner-language notes

### `heatmap_redesign.html`
This is a good base for `Trends`.

Why it works:
- The recent-games cells read much better than the current table.
- The playoff palette idea is smart.
- The page hierarchy is stronger than the live heat-map page.
- The stat strip and control rows already feel like a coherent product surface.

Risk:
- It still thinks of itself as a `Heat Map`.
- It needs clearer betting-language framing:
  - streaks
  - recent form
  - hot hand
  - cooling off
- It should teach a trend method, not just display colored cells.

## Keep / Merge / Cut
## 1. Market Edge Board
Current live destination:
- `templates/smart_picks_v2.html`

Visual base:
- `props_redesign.html`

Keep from redesign:
- top bar layout
- typography stack
- stat-strip tiles
- tighter filter bar
- cleaner table shell
- floor panel visual treatment
- confidence / tier chip styling
- model-read disclosure pattern

Merge from live app:
- `DK / Vegas` comparison
- book count
- line range
- best-book note
- injury context note
- public trend note
- game environment note
- rank-driver chips
- current-team sample toggle
- multi-book refresh metadata

Cut or avoid:
- generic `Props Screener` framing
- overly plain column labels with no methods context
- anything that hides price context to chase a cleaner look

Rename / reframe:
- `Smart Picks` -> `Market Edge`
- hero language should explain:
  - this board finds soft numbers
  - this board compares books
  - this board is for value, not just raw hit rate

Implementation note:
- This should be the first page implemented because it becomes the clearest proof of the methods-first direction.

## 2. Trends Board
Current live destination:
- `templates/heatmap.html`
- route alias already live at `/trends/<stat>`

Visual base:
- `heatmap_redesign.html`

Keep from redesign:
- top bar
- stat strip
- playoff palette banner
- compact controls
- recent-game cell styling
- opponent badge
- legend treatment

Merge from live app:
- postseason and overall scope toggle
- team/opponent filters
- current schedule context
- live refresh metadata
- route alias support:
  - `/trends/<stat>`
  - legacy `/heatmap/<stat>`

Cut or avoid:
- the phrase `Heat Map` as the primary identity
- purely visual framing with no betting explanation

Rename / reframe:
- `Heat Map` -> `Trends`
- page copy should explain:
  - ride the hot hand
  - spot streaks of 3+
  - watch for trend breaks
  - use opponent-specific reads in postseason mode

Implementation note:
- This should be the second page implemented.
- It will feel much better once the methods-first nav is already live.

## 3. Floor Plays Board
Current live destination:
- `templates/props.html`
- especially `/props/floor`

Visual base:
- `props_redesign.html`

Keep from redesign:
- the `How to Use Floor Plays` panel almost as-is
- the table shell
- tier styling
- clean chip hierarchy

Merge from live app:
- baseline reasons
- model read details
- public trend note
- injury context note
- multi-book market context
- matchup filters and playoff sample handling

Cut or avoid:
- overloading the row with too many equally loud colors
- making Floor Plays look identical to Market Edge

Rename / reframe:
- keep `Floor Plays`
- make it clearly your flagship proprietary method
- this page should feel more stable and disciplined than Market Edge

Implementation note:
- This is the third page to translate.
- It should share components with Market Edge, but not feel identical.

## 4. Dashboard
Current live destination:
- `templates/dashboard.html`

Keep:
- current playoff matchup cards
- workflow positioning

Change:
- make the dashboard a launcher for methods, not just features

Primary cards should become:
- `Floor Plays`
- `Trends`
- `Market Edge`
- `Parlay Builder`

Secondary cards:
- `Matchup Lens`
- `Injuries`
- `Trend Board`
- `Bet Review`

Implementation note:
- Update after Market Edge and Trends are visually translated.

## 5. Front Page / Info
Current live destinations:
- `templates/frontpage.html`
- `templates/info.html`

Goal:
- teach bettors how to think, not just where to click

Core framing:
- `Floor Plays` = your safer anchor method
- `Trends` = riding repeatable recent form
- `Market Edge` = finding soft lines and book splits
- `Matchup Lens` = context that explains whether a trend should continue
- `Parlay Builder` = structured ticket building, not chaos

Implementation note:
- polish after the first two method pages are live

## Recommended Rollout Order
1. `Market Edge`
   - biggest payoff
   - already has the most differentiated live data
   - best place to showcase multi-book comparison

2. `Trends`
   - strongest visual redesign candidate
   - easiest method for novices to understand immediately

3. `Floor Plays`
   - flagship proprietary method
   - should inherit proven components from the first two builds

4. `Dashboard`
   - reposition as methods launcher

5. `Front Page / Info`
   - align the teaching story with the finished product

## Product Principle
Every method page should answer these questions fast:
- `What is this method?`
- `When should I use it?`
- `When should I avoid it?`
- `What signals make it strong?`
- `What signals make it dangerous?`

That is how Bankroll Kings becomes useful for novices without losing sharper users.

## Stopping Point Definition
The next real stopping point after implementation work begins is:
- `Market Edge` is visually translated
- `Trends` is visually translated
- both pages still preserve live model features
- the dashboard clearly presents the methods-first system

At that point, the product identity will be strong enough to judge the full design direction with confidence.
