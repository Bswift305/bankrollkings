# -*- coding: utf-8 -*-
import base64, io, shutil, os, pathlib, html
from PIL import Image

SRC = pathlib.Path(r"C:/Users/Decatur/AppData/Local/Temp/claude/C--Users-Decatur-OneDrive-Documents-Kings-of-Bankrolls/62db271a-c1b0-431e-8d01-603bfcf4fcc4/scratchpad")
REPO = pathlib.Path(r"C:/Users/Decatur/OneDrive/Documents/Kings of Bankrolls/marketing/content_pack")
OUT_HTML = SRC / "content_pack.html"
REPO.mkdir(parents=True, exist_ok=True)

def thumb_b64(fn, w=380):
    im = Image.open(SRC / fn).convert("RGB")
    h = int(im.height * (w / im.width))
    im = im.resize((w, h), Image.LANCZOS)
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()

def copy_full(fn, newname):
    shutil.copy2(SRC / fn, REPO / newname)
    return newname

HASHTAGS = "#SportsBetting #PlayerProps #BettingTwitter #SportsBettingTips #GamblingTwitter #BankrollManagement #SportsBettingModel"

PROOF = [
 ("proof_cover.png","cover_the-proof.png","COVER","We don't sell locks. We show math.",
  "Most touts sell you locks. We'll show you the math instead. \U0001F9F5\n\n4 receipts from 239,378 graded props \u2014 including the one edge that actually held up out of sample. Swipe. \u2192 bankrollkings.com"),
 ("proof_calibration.png","proof_01_calibration.png","SLIDE 2","We say 80%. It hits 80%.",
  "When we say a pick is 80% to hit, does it actually hit 80%?\n\nWe graded 239,378 props to find out. It does \u2014 top to bottom. That's calibration: the difference between a real model and a marketing line. \u2192 bankrollkings.com"),
 ("proof_roi.png","proof_02_roi.png","SLIDE 3","58% hit. Still lost.",
  "A 58% win rate sounds like a winner. It lost money.\n\nHere's the lesson most cappers won't teach you: hit rate flatters, ROI tells the truth. We show both \u2014 because we'd rather you learn the read than buy the lock. \u2192 bankrollkings.com"),
 ("proof_wind.png","proof_03_wind.png","SLIDE 4","Wind kills totals.",
  "We tested every 'edge' against 5,205 outdoor games. Almost all of them were already priced in.\n\nOne survived: wind on totals. 15+ mph \u2192 55.5% unders, +5.9% ROI on games the model never saw. The market's slow on weather. We're not. \u2192 bankrollkings.com"),
 ("teach_streak.png","proof_04_streak.png","SLIDE 5","Hot hands are real.",
  "Everyone chases the hot hand. Here's why the smart money doesn't.\n\nA streaking player really is producing more \u2014 that part's true. But the line already moved to match, before you ever clicked. The streak is real. The edge is gone. \u2192 bankrollkings.com"),
]

FEAT = [
 ("01","command_center","The Command Center","#2dd4bf",
  "Stop guessing where the value is. Our Command Center puts our model's number right next to the book's — the gap between them is the edge. Every game, every sport. → bankrollkings.com"),
 ("02","best_lines","Best Lines","#2dd4bf",
  "Same prop, different price at every book. We show you the best number available right now — no hype, just the sharpest line. → bankrollkings.com"),
 ("03","parlay_builder","Parlay Builder","#2dd4bf",
  "Before you stack a parlay, know your legs. We show how often each one actually clears its floor — plus warnings on the traps. → bankrollkings.com"),
 ("04","injury_report","Injury Report","#2dd4bf",
  "Injuries aren't just who's out — they're who cashes when a starter sits. Our report shows the with/without impact (NBA + NFL). → bankrollkings.com"),
 ("05","market_movers","Market Movers","#2dd4bf",
  "Watch the line travel from open to now. Major, Moderate, or Stable — no fake 'steam' labels, just where the market's actually leaning. → bankrollkings.com"),
 ("06","franchise_kings","Franchise Kings","#4ed48a",
  "Take over a franchise and build a dynasty — full GM career mode, free to play. Come for the game, stay for the edge. → bankrollkings.com"),
 ("07","props_board","The Props Board","#2dd4bf",
  "Every prop with a confidence rating you can actually trust — when we say 80%, it hits 80%. Calibrated across 239,378 graded props. → bankrollkings.com"),
 ("08","risk_radar","Risk Radar","#2dd4bf",
  "Every prop, scanned for traps: injuries, longshots, single-book markets — flagged by type, never a fake 'risk score'. → bankrollkings.com"),
 ("09","ticket_check","Ticket Check","#2dd4bf",
  "Paste your parlay, get a second set of eyes: injury exposure, all-overs, concentration traps — before you submit. → bankrollkings.com"),
 ("10","game_context","Game Context","#2dd4bf",
  "Lineups, weather, park, officials — the stuff that quietly moves totals, with a freshness state on every field. → bankrollkings.com"),
 ("11","slate_pulse","Slate Pulse","#2dd4bf",
  "The whole day at a glance — which slates are live, which are stale, which books are in. Start here every day. → bankrollkings.com"),
 ("12","track_record","Track Record","#ffce6a",
  "Most sites hide the ROI. We don't. Real record, real break-even, real ROI — even when it stings. The receipts are the point. → bankrollkings.com"),
 ("13","fantasy","Fantasy","#ffce6a",
  "Sim-driven fantasy rankings: 2,000-game Monte Carlo per player, live injury + matchup shifts, DK/FD/Yahoo scoring. → bankrollkings.com"),
]
FEATURES_PACK = [(f"feature_{fid}.png", f"feature_{fid}_{slug}.png", name, ac, cap) for fid,slug,name,ac,cap in FEAT]

DIFF = [
 ("diff_01.png","difference_01_locks_vs_math.png","Locks vs. Math","#2dd4bf",
  "Everyone else sells you 'locks.' We show you the math. Our model posts its own number and the calibration that proves it's honest. That's the whole difference. → bankrollkings.com"),
 ("diff_02.png","difference_02_hitrate_vs_roi.png","Hit rate vs. ROI","#2dd4bf",
  "A tout brags about hit rate and hides the losses. We show ROI at the real price — even when it stings. A winning record can still lose money. → bankrollkings.com"),
 ("diff_03.png","difference_03_hype_vs_timing.png","Hype vs. Timing","#2dd4bf",
  "By the time a streak is trending, the line already moved. We don't chase hype — we hunt the number the market hasn't caught up to yet. → bankrollkings.com"),
 ("diff_04.png","difference_04_screenshots_vs_receipts.png","Screenshots vs. Receipts","#2dd4bf",
  "Anyone can screenshot their wins. We put 239,378 graded props on the record — good and bad. Receipts, not highlights. → bankrollkings.com"),
 ("diff_05_value.png","difference_05_value_1999.png","$19.99 — Everything","#ffce6a",
  "One plan. $19.99/month. Every board, every tool, Franchise Kings and Fantasy included. No tiers, no 'VIP' pick, no pay-per-play. → bankrollkings.com"),
]
DIFF_PACK = [(src,new,name,ac,cap) for src,new,name,ac,cap in DIFF]

HOWTO = [
 ("howto_00_cover.png","howto_00_cover.png","Start Here — Cover","#2dd4bf",
  "New here? Here's how Bankroll Kings works in 3 steps. From a blank slate to a smarter bet in five minutes. Swipe → bankrollkings.com"),
 ("howto_01_step1.png","howto_01_pick_sport.png","Step 1 — Pick your sport","#2dd4bf",
  "Step 1 — Pick your sport. The board loads every game and prop for the day: NFL, NBA, MLB, WNBA, CFB. No digging, no ten tabs. → bankrollkings.com"),
 ("howto_02_step2.png","howto_02_read_number.png","Step 2 — Read the number","#2dd4bf",
  "Step 2 — Read the number. Our model's number sits next to the market's, with a calibrated confidence. The gap between them is the edge. → bankrollkings.com"),
 ("howto_03_step3.png","howto_03_shop_line.png","Step 3 — Shop the best line","#2dd4bf",
  "Step 3 — Shop the best line. Best Lines finds the sharpest number and price across every book before you bet. Same pick, better payout. → bankrollkings.com"),
]
HOWTO_PACK = [(src,new,name,ac,cap) for src,new,name,ac,cap in HOWTO]

MYTH = [
 ("myth_01_overs.png","myth_01_parlay_overs.png","Stack the overs","#2dd4bf",
  "Why do parlayed overs feel cursed? They're correlated — a shootout lifts them together, so they miss together. One bad game sinks the slip. Mix your sides. → bankrollkings.com"),
 ("myth_02_chase.png","myth_02_chasing.png","Win it back tonight","#2dd4bf",
  "Chasing a loss doesn't shrink the variance — it doubles your exposure to it. The board is there tomorrow; your bankroll won't be if you force it. Bet units, not feelings. → bankrollkings.com"),
 ("myth_03_hot.png","myth_03_recency.png","He's heating up","#2dd4bf",
  "'He's heating up' — so is the price. One hot game regresses hard, and the line already moved to match. Weigh the full sample, not the last highlight. → bankrollkings.com"),
 ("myth_04_fantasy_name.png","myth_04_fantasy_name_value.png","Fantasy: name value","#ffce6a",
  "Fantasy myth: just start the big name. But a star in a brutal matchup can score less than a role player in a soft one. Name value isn't a projection — the opponent matters. → bankrollkings.com"),
 ("myth_05_fantasy_sim.png","myth_05_fantasy_sim.png","Fantasy: the sim engine","#ffce6a",
  "Our fantasy rankings don't run on last week's points. We simulate 2,000 games per player — projection, ceiling, floor, boom/bust — then shift for injuries and matchup. → bankrollkings.com"),
 ("myth_06_franchise.png","myth_06_franchise.png","Franchise Kings hook","#4ed48a",
  "Run the whole franchise: draft the class, work the trades, develop your guys, chase a title. A full GM career — free, no card. Come for the game, stay for the edge. → bankrollkings.com"),
]
MYTH_PACK = [(src,new,name,ac,cap) for src,new,name,ac,cap in MYTH]

PROV = [
 (1,"It's in the price."),(2,"The streak is priced."),(3,"Be first, not smart."),(4,"The number is the bet."),
 (5,"One book is a quote."),(6,"The sweet spot."),(7,"+900 is a lottery ticket."),(8,"Chase the number."),
 (9,"Never parlay overs."),(10,"When torn, go under."),(11,"Overs die on a wall."),(12,"Zero isn't safe."),
 (13,"Bet units."),(14,"Never chase."),(15,"Right-size everything."),(16,"Cap it first."),
 (17,"The edge is late."),(18,"Wind kills totals."),(19,"ROI tells the truth."),(20,"Grade the decision."),
 (21,"Fade your hype."),(22,"Discipline eats."),
]
PROVERBS = [(f"proverb_{n:02d}.png", f"proverb_{n:02d}.png", f"No. {n}", t) for n,t in PROV]

WEEK1 = [
 ("day2_s1.png","week1_day2_s1.png","Day 2 \u00b7 Slide 1"),
 ("day2_s2.png","week1_day2_s2.png","Day 2 \u00b7 Slide 2"),
 ("day2_s3.png","week1_day2_s3.png","Day 2 \u00b7 Slide 3"),
 ("day4_card.png","week1_day4_card.png","Day 4 \u00b7 Card"),
 ("king_rule_1.png","week1_king_rule_1.png","King Rule #1"),
]

# ---- copy full-res ----
for fn,new,*_ in PROOF: copy_full(fn,new)
for fn,new,*_ in FEATURES_PACK: copy_full(fn,new)
for fn,new,*_ in DIFF_PACK: copy_full(fn,new)
for fn,new,*_ in HOWTO_PACK: copy_full(fn,new)
for fn,new,*_ in MYTH_PACK: copy_full(fn,new)
for fn,new,*_ in PROVERBS: copy_full(fn,new)
for fn,new,*_ in WEEK1: copy_full(fn,new)

def esc(s): return html.escape(s)
def cap_attr(s): return html.escape(s).replace("\n","&#10;")

# ---- build HTML ----
proof_cards = ""
for i,(fn,new,tag,title,cap) in enumerate(PROOF, start=1):
    proof_cards += f'''
      <div class="card">
        <div class="thumb"><img src="{thumb_b64(fn)}" alt=""><span class="ord">{i}</span></div>
        <div class="meta">
          <div class="tag">{esc(tag)}</div>
          <div class="ttl">{esc(title)}</div>
          <div class="file">{esc(new)}</div>
          <div class="cap" data-cap="{cap_attr(cap)}">{esc(cap)}</div>
          <button class="copy" onclick="cp(this)">Copy caption</button>
        </div>
      </div>'''

feat_cards = ""
for fn,new,name,ac,cap in FEATURES_PACK:
    feat_cards += f'''
      <figure class="fcard">
        <img src="{thumb_b64(fn, 320)}" alt="">
        <figcaption>
          <div class="fname" style="color:{ac}">{esc(name)}</div>
          <div class="fcap" data-cap="{cap_attr(cap)}">{esc(cap)}</div>
          <button class="copy sm" onclick="cp(this)">Copy caption</button>
        </figcaption>
      </figure>'''

howto_cards = ""
for fn,new,name,ac,cap in HOWTO_PACK:
    howto_cards += f'''
      <figure class="fcard">
        <img src="{thumb_b64(fn, 320)}" alt="">
        <figcaption>
          <div class="fname" style="color:{ac}">{esc(name)}</div>
          <div class="fcap" data-cap="{cap_attr(cap)}">{esc(cap)}</div>
          <button class="copy sm" onclick="cp(this)">Copy caption</button>
        </figcaption>
      </figure>'''

myth_cards = ""
for fn,new,name,ac,cap in MYTH_PACK:
    myth_cards += f'''
      <figure class="fcard">
        <img src="{thumb_b64(fn, 320)}" alt="">
        <figcaption>
          <div class="fname" style="color:{ac}">{esc(name)}</div>
          <div class="fcap" data-cap="{cap_attr(cap)}">{esc(cap)}</div>
          <button class="copy sm" onclick="cp(this)">Copy caption</button>
        </figcaption>
      </figure>'''

diff_cards = ""
for fn,new,name,ac,cap in DIFF_PACK:
    diff_cards += f'''
      <figure class="fcard">
        <img src="{thumb_b64(fn, 320)}" alt="">
        <figcaption>
          <div class="fname" style="color:{ac}">{esc(name)}</div>
          <div class="fcap" data-cap="{cap_attr(cap)}">{esc(cap)}</div>
          <button class="copy sm" onclick="cp(this)">Copy caption</button>
        </figcaption>
      </figure>'''

prov_cards = ""
for fn,new,tag,title in PROVERBS:
    prov_cards += f'''
      <figure class="pcard">
        <img src="{thumb_b64(fn, 300)}" alt="">
        <figcaption><b>{esc(tag)}</b> {esc(title)}</figcaption>
      </figure>'''

week_cards = ""
for fn,new,title in WEEK1:
    week_cards += f'''
      <figure class="pcard">
        <img src="{thumb_b64(fn, 300)}" alt="">
        <figcaption>{esc(title)}<span class="fn">{esc(new)}</span></figcaption>
      </figure>'''

HTML = f'''<title>Bankroll Kings \u2014 Content Pack</title>
<style>
  :root{{--bg:#070e14;--panel:#0d1922;--line:rgba(132,215,210,.16);--ink:#eef5f7;--dim:#9db0bb;--faint:#637984;--cy:#2dd4bf;--gold:#ffce6a;--green:#4ed48a;--red:#ff6f7e;}}
  *{{box-sizing:border-box;}}
  body{{margin:0;background:var(--bg);color:var(--ink);font-family:"Helvetica Neue",Arial,sans-serif;
    background-image:radial-gradient(120% 40% at 85% 0%,rgba(45,212,191,.10),transparent 60%);line-height:1.5;}}
  .wrap{{max-width:1080px;margin:0 auto;padding:56px 32px 96px;}}
  .kicker{{font-family:ui-monospace,Consolas,monospace;font-size:13px;letter-spacing:5px;text-transform:uppercase;color:var(--cy);font-weight:600;}}
  h1{{font-size:clamp(40px,7vw,72px);font-style:italic;font-weight:800;text-transform:uppercase;letter-spacing:.5px;line-height:.92;margin:14px 0 0;}}
  h1 b{{color:var(--cy);}}
  .lede{{color:var(--dim);font-size:19px;max-width:56ch;margin-top:18px;}}
  .stripe{{height:5px;width:88px;border-radius:3px;background:linear-gradient(90deg,var(--cy),var(--gold));margin:26px 0 8px;}}
  h2{{font-size:15px;font-family:ui-monospace,Consolas,monospace;letter-spacing:3px;text-transform:uppercase;color:var(--gold);margin:64px 0 6px;}}
  .sec-sub{{color:var(--faint);font-size:15px;margin:0 0 26px;max-width:60ch;}}
  /* calendar */
  .cal{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-top:8px;}}
  .day{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px;}}
  .day .d{{font-family:ui-monospace,Consolas,monospace;font-size:12px;letter-spacing:2px;color:var(--cy);text-transform:uppercase;}}
  .day .w{{font-weight:700;margin-top:6px;font-size:15px;}}
  .day .n{{color:var(--dim);font-size:13px;margin-top:3px;}}
  /* proof cards */
  .card{{display:grid;grid-template-columns:300px 1fr;gap:24px;background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:20px;margin-bottom:18px;}}
  .thumb{{position:relative;}}
  .thumb img{{width:100%;border-radius:10px;display:block;border:1px solid rgba(255,255,255,.05);}}
  .ord{{position:absolute;top:-10px;left:-10px;width:38px;height:38px;border-radius:50%;background:var(--cy);color:#04222; color:#031014;font-weight:800;font-style:italic;display:flex;align-items:center;justify-content:center;font-size:20px;box-shadow:0 6px 18px rgba(45,212,191,.4);}}
  .meta .tag{{font-family:ui-monospace,Consolas,monospace;font-size:12px;letter-spacing:2px;color:var(--faint);text-transform:uppercase;}}
  .meta .ttl{{font-size:26px;font-weight:800;font-style:italic;margin:4px 0 2px;}}
  .meta .file{{font-family:ui-monospace,Consolas,monospace;font-size:12px;color:var(--cy);margin-bottom:12px;}}
  .cap{{color:var(--dim);font-size:15px;white-space:pre-line;background:rgba(255,255,255,.03);border-left:2px solid var(--line);padding:12px 14px;border-radius:0 8px 8px 0;}}
  .copy{{margin-top:12px;background:transparent;border:1px solid var(--cy);color:var(--cy);font-family:ui-monospace,Consolas,monospace;font-size:12px;letter-spacing:1px;text-transform:uppercase;padding:8px 14px;border-radius:8px;cursor:pointer;transition:.15s;}}
  .copy:hover{{background:var(--cy);color:#031014;}}
  /* grids */
  .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:16px;margin-top:8px;}}
  .pcard{{margin:0;background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden;}}
  .pcard img{{width:100%;display:block;}}
  .pcard figcaption{{padding:10px 12px;font-size:13px;color:var(--dim);}}
  .pcard figcaption b{{color:var(--gold);font-family:ui-monospace,Consolas,monospace;margin-right:4px;}}
  .pcard .fn{{display:block;font-family:ui-monospace,Consolas,monospace;font-size:11px;color:var(--faint);margin-top:3px;}}
  /* feature cards */
  .fgrid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:18px;margin-top:8px;}}
  .fcard{{margin:0;background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden;display:flex;flex-direction:column;}}
  .fcard img{{width:100%;display:block;border-bottom:1px solid var(--line);}}
  .fcard figcaption{{padding:14px 16px 16px;display:flex;flex-direction:column;gap:8px;}}
  .fname{{font-weight:800;font-style:italic;font-size:19px;letter-spacing:.3px;}}
  .fcap{{color:var(--dim);font-size:13px;line-height:1.5;}}
  .copy.sm{{margin-top:2px;padding:6px 12px;font-size:11px;align-self:flex-start;}}
  /* hashtags + tools */
  .box{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:20px 22px;margin-top:14px;}}
  .box code{{font-family:ui-monospace,Consolas,monospace;color:var(--cy);font-size:14px;word-break:break-word;}}
  .tool{{display:flex;gap:14px;align-items:baseline;padding:10px 0;border-bottom:1px solid var(--line);}}
  .tool:last-child{{border-bottom:none;}}
  .tool b{{color:var(--ink);}} .tool span{{color:var(--dim);font-size:14px;}}
  .tool .tl{{color:var(--cy);font-weight:700;text-decoration:none;white-space:nowrap;flex:none;}}
  .tool .tl:hover{{text-decoration:underline;}}
  .note{{color:var(--faint);font-size:13px;margin-top:10px;}}
  footer{{margin-top:72px;border-top:1px solid var(--line);padding-top:24px;color:var(--faint);font-size:13px;}}
  footer b{{color:var(--ink);font-style:italic;}}
</style>

<div class="wrap">
  <div class="kicker">Bankroll Kings \u00b7 Social Content Pack</div>
  <h1>Everything, <b>in one place.</b></h1>
  <p class="lede">60 finished graphics + 3 self-serve tools \u2014 built to run a month-plus without repeating yourself. Full-resolution files (1080\u00d71350) are saved in <code style="font-family:ui-monospace,Consolas,monospace;color:var(--cy)">marketing/content_pack/</code>. Thumbnails below are previews; upload the named file for each.</p>
  <div class="stripe"></div>

  <h2>\u25B8 Suggested first two weeks</h2>
  <p class="sec-sub">Posting 4\u20135\u00d7/day? Rotate the three pillars so the feed never feels repetitive: <b style="color:var(--cy)">Proof</b> (why trust us) \u2192 <b style="color:var(--cy)">Feature</b> (what you get) \u2192 <b style="color:var(--cy)">Proverb</b> (free value) \u2192 repeat, with a Sunday Card as the weekly ritual. A sample day: morning Proof card, midday Feature spotlight, afternoon Proverb, evening Proverb or Franchise Kings.</p>
  <div class="cal">
    <div class="day"><div class="d">Wk1 \u00b7 Mon</div><div class="w">The Proof cover</div><div class="n">carousel, all 5 slides</div></div>
    <div class="day"><div class="d">Wk1 \u00b7 Wed</div><div class="w">Proverb: The number is the bet</div><div class="n">No. 4</div></div>
    <div class="day"><div class="d">Wk1 \u00b7 Fri</div><div class="w">Proverb: One book is a quote</div><div class="n">No. 5</div></div>
    <div class="day"><div class="d">Wk1 \u00b7 Sun</div><div class="w">Sunday Card</div><div class="n">your real W/L, made in the tool</div></div>
    <div class="day"><div class="d">Wk2 \u00b7 Mon</div><div class="w">Proof: Hit rate vs ROI</div><div class="n">re-share slide 3 solo</div></div>
    <div class="day"><div class="d">Wk2 \u00b7 Wed</div><div class="w">Proverb: Never chase</div><div class="n">No. 14</div></div>
    <div class="day"><div class="d">Wk2 \u00b7 Fri</div><div class="w">Proof: Wind kills totals</div><div class="n">re-share slide 4 solo</div></div>
    <div class="day"><div class="d">Wk2 \u00b7 Sun</div><div class="w">Sunday Card</div><div class="n">weekly ritual</div></div>
  </div>

  <h2>\u25B8 The Proof \u2014 carousel (real graded data)</h2>
  <p class="sec-sub">Post as one 5-slide carousel in this order, or re-share any single slide standalone during the week. Every number traces to 239,378 graded props. Tap "Copy caption" to grab the text.</p>
  {proof_cards}

  <h2>\u25B8 Start Here \u2014 onboarding carousel (4 cards)</h2>
  <p class="sec-sub">The "what even is this?" fix \u2014 a cover + 3 steps that walk a first-timer from blank slate to a smarter bet. Post as one carousel, pin it, or use as a link-in-bio explainer.</p>
  <div class="fgrid">{howto_cards}</div>

  <h2>\u25B8 Inside the App \u2014 feature series (13 cards)</h2>
  <p class="sec-sub">The "what you actually get" pillar \u2014 every card promotes a real, live feature. These convert followers into subscribers, so end each with the CTA. Post one every day or two, mixed between proof cards and proverbs. Tap "Copy caption" for ready text.</p>
  <div class="fgrid">{feat_cards}</div>

  <h2>\u25B8 The Difference \u2014 positioning & value (5 cards)</h2>
  <p class="sec-sub">The trust pillar \u2014 contrasts the honest approach against typical tout tactics, plus the $19.99 value card. Post the versus cards standalone or as a carousel; pin the value card. High-conversion; use sparingly so it doesn't read as constant selling.</p>
  <div class="fgrid">{diff_cards}</div>

  <h2>\u25B8 Myth or Money \u2014 myth-busting (6 cards)</h2>
  <p class="sec-sub">Your reach plays \u2014 teach something true, no pick required. Includes dedicated <b style="color:var(--gold)">Fantasy</b> (name value + the sim engine) and <b style="color:var(--green)">Franchise Kings</b> cards. Great as standalone posts; the format screenshots and shares well.</p>
  <div class="fgrid">{myth_cards}</div>

  <h2>\u25B8 King's Proverbs \u2014 22 cards</h2>
  <p class="sec-sub">The always-on drip. One per post, no caption needed beyond the line itself + a soft CTA. Caption template: "Proverb No. X \u2014 [the line]. More at bankrollkings.com". Rotate 2\u20133 a week; they never expire.</p>
  <div class="grid">{prov_cards}</div>

  <h2>\u25B8 Week-1 launch graphics</h2>
  <p class="sec-sub">The original launch set \u2014 use as intro/announcement posts or filler between proof drops.</p>
  <div class="grid">{week_cards}</div>

  <h2>\u25B8 Self-serve tools</h2>
  <div class="box">
    <div class="tool"><a class="tl" href="https://claude.ai/code/artifact/cbe1b716-1e5f-43bc-bf9e-26690a635b76" target="_blank" rel="noopener">Sunday Card Maker \u2197</a><span>Paste your week's plays (Player | Prop | W/L) \u2192 auto-computes record + hit rate \u2192 downloads a branded results PNG. Your weekly proof ritual.</span></div>
    <div class="tool"><a class="tl" href="https://claude.ai/code/artifact/48c95ede-45db-4616-af50-97b0a4902ce0" target="_blank" rel="noopener">King's Proverbs page \u2197</a><span>Browsable reference of all 22 proverbs grouped by theme (Market / Number / Avoidance / Bankroll / Timing / Mind).</span></div>
    <div class="tool"><a class="tl" href="https://claude.ai/code/artifact/02c03a88-5175-4e7e-ba58-67bc62c372ba" target="_blank" rel="noopener">Social Playbook \u2197</a><span>The strategy doc: 4 content pillars, format rules, series ideas, and compliance guardrails.</span></div>
    <p class="note">Each opens its own private artifact page on claude.ai.</p>
  </div>

  <h2>\u25B8 Hashtag block</h2>
  <div class="box"><code id="tags">{HASHTAGS}</code><br><button class="copy" style="margin-top:14px" onclick="cpt()">Copy hashtags</button></div>
  <p class="note">Use 3\u20135 per post, not all seven \u2014 mix in the sport/league of the day (#NFL, #WNBA, etc.).</p>

  <h2>\u25B8 One rule for every post</h2>
  <div class="box">
    <p style="margin:0;color:var(--dim)">Never post a number you can't trace to the graded data. Where we don't have the receipt, we teach the concept \u2014 we don't invent the stat. <b style="color:var(--ink)">That honesty is the product.</b> No "guaranteed", no "lock", no fabricated records.</p>
  </div>

  <footer><b>Bankroll Kings</b> \u2014 content pack generated from live graded results. Files in <code style="font-family:ui-monospace,Consolas,monospace;color:var(--cy)">marketing/content_pack/</code>.</footer>
</div>

<script>
  function cp(btn){{
    const t = btn.parentElement.querySelector('.cap, .fcap').getAttribute('data-cap');
    navigator.clipboard.writeText(t).then(()=>{{const o=btn.textContent;btn.textContent='Copied \u2713';setTimeout(()=>btn.textContent=o,1400);}});
  }}
  function cpt(){{
    navigator.clipboard.writeText(document.getElementById('tags').textContent);
    event.target.textContent='Copied \u2713';setTimeout(()=>event.target.textContent='Copy hashtags',1400);
  }}
</script>'''

OUT_HTML.write_text(HTML, encoding="utf-8")
print("wrote", OUT_HTML, len(HTML), "chars")
print("copied full-res to", REPO)
print("files in repo:", len(list(REPO.glob('*.png'))))
