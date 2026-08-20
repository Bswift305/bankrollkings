# -*- coding: utf-8 -*-
import pathlib, subprocess
SRC = pathlib.Path(__file__).parent
CHROME = r"C:/Program Files/Google/Chrome/Application/chrome.exe"
CY="#2dd4bf"; GREEN="#4ed48a"; GOLD="#ffce6a"

def render(stem):
    hp=(SRC/f"{stem}.html").resolve(); pp=(SRC/f"{stem}.png").resolve()
    subprocess.run([CHROME,"--headless=new","--disable-gpu","--hide-scrollbars",
        "--force-device-scale-factor=2","--window-size=1080,1350",
        f"--screenshot={pp}",hp.as_uri()],
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
    return pp.stat().st_size if pp.exists() else 0

TPL='''<!doctype html><html><head><meta charset="utf-8"><style>
  *{{margin:0;padding:0;box-sizing:border-box;}}
  html,body{{width:1080px;height:1350px;overflow:hidden;}}
  body{{background:#070e14;font-family:"Helvetica Neue",Arial,sans-serif;color:#eef5f7;position:relative;
    background-image:radial-gradient(115% 78% at 78% 20%,{ac}26,transparent 55%),radial-gradient(80% 55% at 8% 100%,rgba(214,154,60,0.08),transparent 55%);}}
  .frame{{position:absolute;inset:34px;border:1px solid rgba(132,215,210,0.20);border-radius:26px;}}
  .pad{{position:absolute;inset:96px 84px;}}
  .eyebrow{{font-family:ui-monospace,Consolas,monospace;font-size:26px;letter-spacing:6px;text-transform:uppercase;color:{ac};font-weight:600;}}
  h1{{font-weight:800;font-style:italic;text-transform:uppercase;font-size:104px;line-height:.9;letter-spacing:.5px;margin-top:24px;color:#fff;text-shadow:0 8px 44px rgba(0,0,0,.5);}}
  h1 .cy{{color:{ac};text-shadow:0 0 44px {ac}80;}}
  .reveal{{margin-top:38px;display:flex;align-items:center;gap:16px;}}
  .reveal .arw{{color:#ffce6a;font-weight:800;font-style:italic;font-size:44px;}}
  .reveal .txt{{font-weight:800;font-style:italic;text-transform:uppercase;font-size:44px;color:#ffce6a;line-height:1;}}
  .body{{margin-top:42px;font-size:41px;line-height:1.4;color:#c7d7de;max-width:24ch;}}
  .body b{{color:#fff;}}
  .kick{{margin-top:36px;font-size:34px;line-height:1.35;color:#eef5f7;font-weight:700;max-width:25ch;}}
  .kick .cy{{color:{ac};}}
  .rail{{position:absolute;left:84px;bottom:150px;width:78px;height:5px;border-radius:3px;background:linear-gradient(90deg,{ac},#ffce6a);}}
  .footer{{position:absolute;left:84px;bottom:92px;display:flex;align-items:center;gap:20px;}}
  .wordmark{{font-weight:800;font-style:italic;text-transform:uppercase;letter-spacing:1px;font-size:34px;color:#fff;}}
  .wordmark b{{color:{ac};}}
  .handle{{font-family:ui-monospace,Consolas,monospace;font-size:24px;color:#637984;letter-spacing:1.5px;}}
</style></head><body>
  <div class="pad">
    <div class="eyebrow">{eyebrow}</div>
    <h1>{h1}</h1>
    <div class="reveal"><span class="arw">&#8594;</span><span class="txt">{reveal}</span></div>
    <div class="body">{body}</div>
    <div class="kick">{kick}</div>
  </div>
  <div class="rail"></div>
  <div class="footer"><span class="wordmark">Bankroll <b>Kings</b></span><span class="handle">bankrollkings.com</span></div>
  <div class="frame"></div>
</body></html>'''

CARDS=[
 ("myth_01_overs",CY,"Myth or Money","Stack<br>the <span class='cy'>overs.</span>","The fastest way to lose.",
  "Overs are correlated \u2014 a fast pace, a shootout, a blowout lifts them together. So they also <b>miss together.</b> One bad game sinks the whole slip.",
  "Mix your sides. Better yet \u2014 <span class='cy'>don't chain longshots at all.</span>"),
 ("myth_02_chase",CY,"Myth or Money","Win it back<br><span class='cy'>tonight.</span>","That's the tilt talking.",
  "Chasing a loss doesn't shrink the variance \u2014 it <b>doubles your exposure</b> to it. The board is there tomorrow. Your bankroll won't be if you force it now.",
  "Bet units, not feelings. <span class='cy'>Every night is a fresh slate.</span>"),
 ("myth_03_hot",CY,"Myth or Money","He's<br><span class='cy'>heating up.</span>","So is the price.",
  "A hot streak pulls the line \u2014 and pulls your eye to last night's box score. But one big game <b>regresses hard,</b> and the number already moved to match.",
  "Weigh the full sample, <span class='cy'>not the last highlight.</span>"),
 ("myth_04_fantasy_name",GOLD,"Fantasy \u00b7 Myth or Money","Start the<br><span class='cy'>big name.</span>","Not into that defense.",
  "A star in a brutal matchup can score less than a role player in a soft one. <b>Name value isn't a projection</b> \u2014 the opponent matters as much as the player.",
  "Our rankings bake the matchup in \u2014 <span class='cy'>Opp Soft / Neutral / Tough, live.</span>"),
 ("myth_05_fantasy_sim",GOLD,"Fantasy","2,000 seasons,<br><span class='cy'>every player.</span>","Before you set the lineup.",
  "We don't rank on last week's points. We <b>simulate 2,000 games</b> per player \u2014 projection, ceiling, floor, boom/bust \u2014 then shift for injuries and the matchup.",
  "Set your lineup on the <span class='cy'>distribution, not the hype.</span>"),
 ("myth_06_franchise",GREEN,"Free to play","Run the whole<br><span class='cy'>franchise.</span>","Draft. Trade. Dynasty.",
  "Take a team from the ground up \u2014 draft the class, work the trade market, develop your guys, chase a title. <b>A full GM career,</b> free, no card.",
  "The free way in. <span class='cy'>Come for the game, stay for the edge.</span>"),
]

out=[]
for stem,ac,eyebrow,h1,reveal,body,kick in CARDS:
    doc=TPL.format(ac=ac,eyebrow=eyebrow,h1=h1,reveal=reveal,body=body,kick=kick)
    (SRC/f"{stem}.html").write_text(doc,encoding="utf-8")
    out.append((stem,render(stem)))
for stem,sz in out:
    print(f"{stem}.png -> {sz} bytes")
