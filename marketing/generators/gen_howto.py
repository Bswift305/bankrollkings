# -*- coding: utf-8 -*-
import pathlib, html, subprocess
SRC = pathlib.Path(__file__).parent
CHROME = r"C:/Program Files/Google/Chrome/Application/chrome.exe"
CY="#2dd4bf"; GOLD="#ffce6a"

def render(stem):
    hp=(SRC/f"{stem}.html").resolve(); pp=(SRC/f"{stem}.png").resolve()
    subprocess.run([CHROME,"--headless=new","--disable-gpu","--hide-scrollbars",
        "--force-device-scale-factor=2","--window-size=1080,1350",
        f"--screenshot={pp}",hp.as_uri()],
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
    return pp.stat().st_size if pp.exists() else 0
def esc(s): return html.escape(s)

HEAD='''<!doctype html><html><head><meta charset="utf-8"><style>
  *{margin:0;padding:0;box-sizing:border-box;}
  html,body{width:1080px;height:1350px;overflow:hidden;}
  body{background:#070e14;font-family:"Helvetica Neue",Arial,sans-serif;color:#eef5f7;position:relative;
    background-image:radial-gradient(120% 72% at 82% 8%,rgba(45,212,191,0.15),transparent 55%),radial-gradient(80% 55% at 6% 100%,rgba(255,206,106,0.07),transparent 55%);}
  .frame{position:absolute;inset:34px;border:1px solid rgba(132,215,210,0.20);border-radius:26px;}
  .pad{position:absolute;inset:96px 84px;}
  .eyebrow{font-family:ui-monospace,Consolas,monospace;font-size:26px;letter-spacing:8px;text-transform:uppercase;color:#2dd4bf;font-weight:600;}
  .rail{position:absolute;left:84px;bottom:150px;width:78px;height:5px;border-radius:3px;background:linear-gradient(90deg,#2dd4bf,#ffce6a);}
  .footer{position:absolute;left:84px;bottom:92px;display:flex;align-items:center;gap:20px;}
  .wordmark{font-weight:800;font-style:italic;text-transform:uppercase;letter-spacing:1px;font-size:34px;color:#fff;}
  .wordmark b{color:#2dd4bf;}
  .handle{font-family:ui-monospace,Consolas,monospace;font-size:24px;color:#637984;letter-spacing:1.5px;}
</style></head><body>'''
FOOT='''<div class="rail"></div>
  <div class="footer"><span class="wordmark">Bankroll <b>Kings</b></span><span class="handle">bankrollkings.com</span></div>
  <div class="frame"></div></body></html>'''

# ---- Cover ----
cover=HEAD+'''<style>
  h1{font-weight:800;font-style:italic;text-transform:uppercase;font-size:120px;line-height:.9;letter-spacing:.5px;margin-top:24px;color:#fff;text-shadow:0 8px 44px rgba(0,0,0,.5);}
  h1 .cy{color:#2dd4bf;text-shadow:0 0 44px rgba(45,212,191,.5);}
  .sub{margin-top:34px;font-size:42px;line-height:1.3;color:#c7d7de;max-width:22ch;}
  .steps{position:absolute;left:84px;bottom:250px;display:flex;flex-direction:column;gap:18px;}
  .st{display:flex;align-items:center;gap:20px;font-size:34px;color:#e7f0f3;}
  .st b{width:52px;height:52px;border-radius:13px;background:rgba(45,212,191,.15);border:1px solid rgba(45,212,191,.5);color:#2dd4bf;display:flex;align-items:center;justify-content:center;font-weight:800;font-style:italic;font-size:30px;flex:none;}
</style>
  <div class="pad">
    <div class="eyebrow">Start here</div>
    <h1>New here?<br>Start in<br><span class="cy">3 steps.</span></h1>
    <div class="sub">From a blank slate to a smarter bet in five minutes.</div>
  </div>
  <div class="steps">
    <div class="st"><b>1</b> Pick your sport</div>
    <div class="st"><b>2</b> Read the number</div>
    <div class="st"><b>3</b> Shop the best line</div>
  </div>'''+FOOT
(SRC/"howto_00_cover.html").write_text(cover,encoding="utf-8")

# ---- Step template ----
STEP='''<style>
  .num{{font-weight:800;font-style:italic;font-size:210px;line-height:.8;color:{ac};text-shadow:0 0 60px {ac}66;margin-top:8px;}}
  h1{{font-weight:800;font-style:italic;text-transform:uppercase;font-size:82px;line-height:.94;letter-spacing:.5px;margin-top:6px;color:#fff;}}
  .desc{{margin-top:30px;font-size:40px;line-height:1.34;color:#c7d7de;max-width:24ch;}}
  .desc b{{color:#fff;}}
  .where{{position:absolute;left:84px;bottom:210px;font-family:ui-monospace,Consolas,monospace;font-size:26px;letter-spacing:1px;color:{ac};text-transform:uppercase;}}
  .where span{{color:#637984;}}
</style>
  <div class="pad">
    <div class="eyebrow">Start here · Step {n} of 3</div>
    <div class="num">{n}</div>
    <h1>{title}</h1>
    <div class="desc">{desc}</div>
  </div>
  <div class="where"><span>where:</span> {where}</div>'''
STEPS=[
 ("howto_01_step1",CY,"1","Pick your sport",
  "The board loads <b>every game and every prop</b> for the day — NFL, NBA, MLB, WNBA, CFB. No digging, no ten tabs.","The Command Center"),
 ("howto_02_step2",CY,"2","Read the number",
  "Our model's number sits <b>right next to the market's</b>, with a confidence that's calibrated. The gap between them is the edge.","Props Board + Command Center"),
 ("howto_03_step3",CY,"3","Shop the best line",
  "Before you bet, <b>Best Lines finds the sharpest number and price</b> across every book. Same pick, better payout.","Best Lines"),
]
for stem,ac,n,title,desc,where in STEPS:
    doc=HEAD+STEP.format(ac=ac,n=n,title=esc(title),desc=desc,where=esc(where))+FOOT
    (SRC/f"{stem}.html").write_text(doc,encoding="utf-8")

out=[("howto_00_cover",render("howto_00_cover"))]
for stem,*_ in STEPS:
    out.append((stem,render(stem)))
for stem,sz in out:
    print(f"{stem}.png -> {sz} bytes")
