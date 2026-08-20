# -*- coding: utf-8 -*-
import base64, pathlib

SCR = pathlib.Path(r"C:\Users\Decatur\AppData\Local\Temp\claude\C--Users-Decatur-OneDrive-Documents-Kings-of-Bankrolls\62db271a-c1b0-431e-8d01-603bfcf4fcc4\scratchpad")
MASCOT = "data:image/webp;base64," + base64.b64encode(
    pathlib.Path(r"C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls\static\king-bankroll.webp").read_bytes()
).decode()

TEMPLATE = '''<!doctype html><html><head><meta charset="utf-8"><style>
  *{margin:0;padding:0;box-sizing:border-box;}
  html,body{width:1080px;height:1350px;overflow:hidden;}
  body{background:#070e14;font-family:"Helvetica Neue",Arial,sans-serif;color:#eef5f7;position:relative;
    background-image:radial-gradient(115% 80% at 74% 28%,rgba(45,212,191,0.17),transparent 55%),radial-gradient(80% 55% at 8% 98%,rgba(214,154,60,0.10),transparent 55%);}
  .frame{position:absolute;inset:34px;border:1px solid rgba(132,215,210,0.20);border-radius:26px;}
  .mascot{position:absolute;right:-72px;bottom:-6px;height:1000px;width:auto;filter:drop-shadow(0 20px 60px rgba(45,212,191,0.30));}
  .copy{position:absolute;left:96px;top:116px;right:400px;}
  .eyebrow{font-family:ui-monospace,Consolas,monospace;font-size:27px;letter-spacing:8px;text-transform:uppercase;color:#2dd4bf;font-weight:600;}
  .eyebrow .num{color:#ffce6a;}
  h1{font-weight:800;font-style:italic;text-transform:uppercase;font-size:96px;line-height:.9;letter-spacing:.5px;margin-top:24px;color:#fff;text-shadow:0 8px 44px rgba(0,0,0,0.55);}
  h1 .cy{color:#2dd4bf;text-shadow:0 0 44px rgba(45,212,191,0.55);}
  .sub{margin-top:34px;font-size:39px;line-height:1.34;color:#c7d7de;max-width:13ch;font-weight:500;}
  .sub b{color:#fff;}
  .rail{position:absolute;left:96px;bottom:150px;width:78px;height:5px;border-radius:3px;background:linear-gradient(90deg,#2dd4bf,#ffce6a);}
  .footer{position:absolute;left:96px;bottom:92px;display:flex;align-items:center;gap:20px;}
  .wordmark{font-weight:800;font-style:italic;text-transform:uppercase;letter-spacing:1px;font-size:36px;color:#fff;}
  .wordmark b{color:#2dd4bf;}
  .handle{font-family:ui-monospace,Consolas,monospace;font-size:25px;color:#637984;letter-spacing:1.5px;}
</style></head><body>
  <img class="mascot" src="__MASCOT__" alt="">
  <div class="copy">
    <div class="eyebrow">King's Proverb <span class="num">No.__N__</span></div>
    <h1>__HEADLINE__</h1>
    <div class="sub">__SUB__</div>
  </div>
  <div class="rail"></div>
  <div class="footer"><span class="wordmark">Bankroll <b>Kings</b></span><span class="handle">@bankrollkings</span></div>
  <div class="frame"></div>
</body></html>'''

# headline uses [[word]] for the cyan highlight; numbered to match the reference page.
proverbs = [
  (1,  "IT'S IN<br>THE [[PRICE.]]", "If your reason is on the broadcast, <b>the market already knows.</b>"),
  (2,  "THE STREAK<br>IS [[PRICED.]]", "It's real — but the line <b>already moved.</b> You're paying retail."),
  (3,  "BE [[FIRST,]]<br>NOT SMART.", "You don't out-analyze the book. <b>Edge is a timing advantage.</b>"),
  (4,  "THE NUMBER<br>IS THE [[BET.]]", "A great read at a bad price is <b>still a bad bet.</b> Shop every line."),
  (5,  "ONE BOOK<br>IS A [[QUOTE.]]", "Three books is a market. <b>Never trust a single price.</b>"),
  (6,  "THE SWEET<br>[[SPOT.]]", "Live in the <b>−200 to −400</b> band — high enough to hit, priced enough to matter."),
  (7,  "+900 IS A<br>LOTTERY<br>[[TICKET.]]", "With your rent money. <b>10% break-even — and it hits far less.</b>"),
  (8,  "CHASE THE<br>[[NUMBER.]]", "Not the result. <b>Closing-line value</b> is the only scoreboard that predicts tomorrow."),
  (9,  "NEVER<br>PARLAY<br>[[OVERS.]]", "The fastest way to donate a bankroll. <b>Overs love to miss together.</b>"),
  (10, "WHEN TORN,<br>GO [[UNDER.]]", "Variance is cheaper on the low side. <b>Unders bleed less.</b>"),
  (11, "OVERS DIE<br>ON A [[WALL.]]", "Never take an over into a top defense — <b>a ceiling that isn't there.</b>"),
  (12, "ZERO ISN'T<br>[[SAFE.]]", "A prop that needs a literal 0 to cash is <b>a trap in a suit.</b>"),
  (13, "BET<br>[[UNITS.]]", "Not feelings. <b>The size never depends</b> on how sure you feel."),
  (14, "NEVER<br>[[CHASE.]]", "The board is there tomorrow. <b>Your bankroll won't be</b> if you force it tonight."),
  (15, "RIGHT-SIZE<br>[[EVERYTHING.]]", "If one bet can change your week, <b>it can change it the wrong way too.</b>"),
  (16, "CAP IT<br>[[FIRST.]]", "Down days are the tax. <b>Blow-up days are the funeral.</b> Set the ceiling early."),
  (17, "THE EDGE<br>IS [[LATE.]]", "The last 90 minutes — lineups, scratches, wind. <b>Late info is un-priced.</b>"),
  (18, "WIND KILLS<br>[[TOTALS.]]", "Over 15 mph, quietly. <b>The market's slow on weather</b> — you don't have to be."),
  (19, "ROI TELLS<br>THE [[TRUTH.]]", "Hit rate flatters. A 70% record can <b>still bleed money.</b>"),
  (20, "GRADE THE<br>[[DECISION.]]", "Not the outcome. Losing bets aren't mistakes — <b>bad process is.</b>"),
  (21, "FADE YOUR<br>[[HYPE.]]", "The play you love most is the one to <b>shrink.</b> Excitement is expensive."),
  (22, "DISCIPLINE<br>[[EATS.]]", "Boring — and it's why the <b>King wins.</b> Excitement is a cost."),
]

for n, head, sub in proverbs:
    head = head.replace("[[", '<span class="cy">').replace("]]", "</span>")
    html = (TEMPLATE.replace("__MASCOT__", MASCOT)
                    .replace("No.__N__", f"No.{n}")
                    .replace("__HEADLINE__", head)
                    .replace("__SUB__", sub))
    (SCR / f"proverb_{n:02d}.html").write_text(html, encoding="utf-8")
print("generated", len(proverbs), "proverb cards (proverb_01..proverb_22)")
