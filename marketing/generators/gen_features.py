# -*- coding: utf-8 -*-
import pathlib, html
SRC = pathlib.Path(__file__).parent

# (id, eyebrow, name, accent, tagline, [bullets], kicker)
CY="#2dd4bf"; GREEN="#4ed48a"; GOLD="#ffce6a"
FEATURES = [
 ("01","Inside the app","The Command Center",CY,
  "Every game, every line — with our model’s number sitting right next to the market’s.",
  ["An Elo-based power rating we build independent of the book",
   "See exactly where our number disagrees with the line — the gap is the edge",
   "Full slate, every sport: NFL · NBA · MLB · WNBA · CFB"],
  "We don’t chase the market. We measure it."),
 ("02","Inside the app","Best Lines",CY,
  "The same prop is priced differently at every book. We show you the best one.",
  ["Best number and best price across every book, per player prop",
   "Filter by league, stat, over/under, or player — instantly",
   "No ‘best bet’ hype — just the sharpest number available right now"],
  "A great read at a bad number is still a bad bet."),
 ("03","Inside the app","Parlay Builder",CY,
  "Build smarter slips — and see how often each leg actually clears its floor.",
  ["Floor-reliability history on every leg: how often it beats the number",
   "Sport-aware — each league’s own board feeds the build",
   "Structural warnings flag the traps before you lock it in"],
  "Know your legs before you stack them."),
 ("04","Inside the app","Injury Report",CY,
  "Not just who’s out — who cashes when they sit.",
  ["Every league’s injuries in one filterable table",
   "With / without impact: when X sits, teammate Y produces Z (NBA + NFL)",
   "Status normalized — Out / Doubtful / Questionable, no guessing"],
  "The line moves late on news. Be there first."),
 ("05","Inside the app","Market Movers",CY,
  "Watch the line travel from open to now — and see where the market is leaning.",
  ["Open → current movement, consensus across the books",
   "Tiered Major / Moderate / Stable — no fake ‘steam’ labels",
   "Near-term slate, re-captured every four hours"],
  "Timing is the edge. Movement is the clock."),
 ("06","Free to play","Franchise Kings",GREEN,
  "Take over a franchise. Draft, trade, and build a dynasty — full GM career mode.",
  ["A complete GM career: draft, trades, development, seasons",
   "Your save, your calls — progress carries game to game",
   "Free to play. No card, no catch — just the game"],
  "The free way in. Come for the game, stay for the edge."),
 ("07","Inside the app","The Props Board",CY,
  "Every player prop — with our confidence, and the proof it’s calibrated.",
  ["A model confidence on each prop — and 80% really means 80%",
   "Sport-aware board: NBA · WNBA · MLB · NFL · CFB",
   "Sort, filter, search — find the number that fits your read"],
  "Confidence you can trust, because we show the math behind it."),
 ("08","Inside the app","Risk Radar",CY,
  "Every prop on the board, scanned for the traps you can’t always see.",
  ["Injury flags — Out / Doubtful / Questionable, with the reason",
   "Longshot-over and single-book warnings, called out by type",
   "Observable warnings only — never a made-up ‘risk score’"],
  "Know the trap before it springs."),
 ("09","Inside the app","Ticket Check",CY,
  "Paste your parlay. We flag the structural traps before you ever submit.",
  ["Injury exposure, all-overs, same-player and concentration flags",
   "Combined implied probability — honestly labeled",
   "Works across every sport on a single slip"],
  "A second set of eyes on every slip."),
 ("10","Inside the app","Game Context",CY,
  "Lineups, weather, park, officials — the stuff that quietly moves totals.",
  ["Per-matchup context with a freshness state on every field",
   "Missing data reads as ‘unavailable’, never as neutral",
   "Cross-sport coverage so you know exactly what’s verified"],
  "Context the box score won’t give you."),
 ("11","Inside the app","Slate Pulse",CY,
  "The whole day at a glance — which slates are live, which have gone stale.",
  ["One row per league: live markets, props, books, injuries",
   "Feed freshness, so you always know the data is current",
   "Pure observation — no ranking, no ‘best bets’"],
  "Start here. See the whole board breathe."),
 ("12","The honest part","Track Record",GOLD,
  "Our real record — hit rate, break-even, and the ROI most sites bury.",
  ["Every method’s record against the break-even it actually needs",
   "ROI at the true price — shown even when it stings",
   "Ranked by sample size, never by a cherry-picked hit rate"],
  "The receipts, good and bad. That’s the whole point."),
 ("13","Inside the app","Fantasy",GOLD,
  "Simulation-driven rankings for your NFL and NBA lineups.",
  ["2,000-game Monte Carlo per player — projection, ceiling, floor",
   "Live injury and matchup shifts baked into every ranking",
   "DraftKings, FanDuel and Yahoo scoring, your pick"],
  "Set your lineup on the math, not the hype."),
]

TPL = '''<!doctype html><html><head><meta charset="utf-8"><style>
  *{{margin:0;padding:0;box-sizing:border-box;}}
  html,body{{width:1080px;height:1350px;overflow:hidden;}}
  body{{background:#070e14;font-family:"Helvetica Neue",Arial,sans-serif;color:#eef5f7;position:relative;
    background-image:radial-gradient(120% 72% at 82% 10%,{ac}22,transparent 55%),radial-gradient(80% 55% at 6% 100%,rgba(255,206,106,0.06),transparent 55%);}}
  .frame{{position:absolute;inset:34px;border:1px solid rgba(132,215,210,0.20);border-radius:26px;}}
  .pad{{position:absolute;inset:96px 84px;}}
  .eyebrow{{font-family:ui-monospace,Consolas,monospace;font-size:25px;letter-spacing:7px;text-transform:uppercase;color:{ac};font-weight:600;}}
  .num{{position:absolute;right:84px;top:96px;font-family:ui-monospace,Consolas,monospace;font-size:22px;letter-spacing:2px;color:#4a5b64;}}
  h1{{font-weight:800;font-style:italic;text-transform:uppercase;font-size:92px;line-height:.92;letter-spacing:.5px;margin-top:20px;color:#fff;text-shadow:0 8px 44px rgba(0,0,0,.5);}}
  .tag{{margin-top:30px;font-size:40px;line-height:1.3;color:#c7d7de;max-width:24ch;}}
  .panel{{margin-top:44px;border:1px solid {ac}44;border-radius:18px;padding:14px 30px;background:linear-gradient(160deg,{ac}12,rgba(10,20,27,.45));}}
  .li{{display:flex;gap:20px;align-items:flex-start;padding:22px 0;border-bottom:1px solid rgba(255,255,255,.06);}}
  .li:last-child{{border-bottom:none;}}
  .ck{{flex:none;width:40px;height:40px;border-radius:10px;background:{ac}1f;border:1px solid {ac}66;display:flex;align-items:center;justify-content:center;color:{ac};font-weight:800;font-size:24px;margin-top:2px;}}
  .li span{{font-size:32px;line-height:1.32;color:#e7f0f3;}}
  .li b{{color:#fff;}}
  .kick{{position:absolute;left:84px;right:84px;bottom:200px;font-size:33px;font-weight:700;font-style:italic;color:{ac};line-height:1.25;}}
  .rail{{position:absolute;left:84px;bottom:150px;width:78px;height:5px;border-radius:3px;background:linear-gradient(90deg,{ac},#ffce6a);}}
  .footer{{position:absolute;left:84px;bottom:92px;display:flex;align-items:center;gap:20px;}}
  .wordmark{{font-weight:800;font-style:italic;text-transform:uppercase;letter-spacing:1px;font-size:34px;color:#fff;}}
  .wordmark b{{color:{ac};}}
  .handle{{font-family:ui-monospace,Consolas,monospace;font-size:24px;color:#637984;letter-spacing:1.5px;}}
</style></head><body>
  <div class="num">{num} / INSIDE</div>
  <div class="pad">
    <div class="eyebrow">{eyebrow}</div>
    <h1>{name}</h1>
    <div class="tag">{tag}</div>
    <div class="panel">{lis}</div>
  </div>
  <div class="kick">{kick}</div>
  <div class="rail"></div>
  <div class="footer"><span class="wordmark">Bankroll <b>Kings</b></span><span class="handle">bankrollkings.com</span></div>
  <div class="frame"></div>
</body></html>'''

def esc(s): return html.escape(s)
for fid,eyebrow,name,ac,tag,bullets,kick in FEATURES:
    lis=""
    for b in bullets:
        lis+=f'<div class="li"><div class="ck">&#10003;</div><span>{esc(b)}</span></div>'
    doc=TPL.format(ac=ac,num=fid,eyebrow=esc(eyebrow),name=esc(name),tag=esc(tag),lis=lis,kick=esc(kick))
    (SRC/f"feature_{fid}.html").write_text(doc,encoding="utf-8")
    print("wrote feature_"+fid+".html")
