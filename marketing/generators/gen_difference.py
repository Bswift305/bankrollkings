# -*- coding: utf-8 -*-
import pathlib, html, subprocess, os
SRC = pathlib.Path(__file__).parent
CHROME = r"C:/Program Files/Google/Chrome/Application/chrome.exe"

def render(stem):
    hp = (SRC/f"{stem}.html").resolve()
    pp = (SRC/f"{stem}.png").resolve()
    subprocess.run([CHROME,"--headless=new","--disable-gpu","--hide-scrollbars",
        "--force-device-scale-factor=2","--window-size=1080,1350",
        f"--screenshot={pp}", hp.as_uri()],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return pp, (pp.stat().st_size if pp.exists() else 0)

def esc(s): return html.escape(s)

# ---------- VERSUS cards ----------
VS_TPL = '''<!doctype html><html><head><meta charset="utf-8"><style>
  *{{margin:0;padding:0;box-sizing:border-box;}}
  html,body{{width:1080px;height:1350px;overflow:hidden;}}
  body{{background:#070e14;font-family:"Helvetica Neue",Arial,sans-serif;color:#eef5f7;position:relative;
    background-image:radial-gradient(110% 55% at 82% 6%,rgba(45,212,191,0.12),transparent 55%),radial-gradient(90% 45% at 10% 96%,rgba(255,111,126,0.08),transparent 55%);}}
  .frame{{position:absolute;inset:34px;border:1px solid rgba(132,215,210,0.20);border-radius:26px;}}
  .pad{{position:absolute;inset:92px 84px;}}
  .eyebrow{{font-family:ui-monospace,Consolas,monospace;font-size:25px;letter-spacing:8px;text-transform:uppercase;color:#2dd4bf;font-weight:600;}}
  h1{{font-weight:800;font-style:italic;text-transform:uppercase;font-size:86px;line-height:.92;letter-spacing:.5px;margin-top:18px;color:#fff;}}
  h1 .vs{{color:#637984;font-size:52px;font-style:italic;}}
  .cards{{margin-top:52px;display:flex;flex-direction:column;gap:26px;}}
  .box{{border-radius:18px;padding:34px 34px;border:1px solid var(--bc);background:linear-gradient(160deg,var(--bg),rgba(10,20,27,.55));position:relative;}}
  .box .lab{{font-family:ui-monospace,Consolas,monospace;font-size:22px;letter-spacing:3px;text-transform:uppercase;color:var(--fg);display:flex;align-items:center;gap:14px;}}
  .box .mk{{width:44px;height:44px;border-radius:11px;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:28px;background:var(--mkbg);color:var(--fg);border:1px solid var(--bc);}}
  .box .txt{{margin-top:18px;font-size:39px;line-height:1.32;color:#eef5f7;}}
  .them{{--bc:rgba(255,111,126,0.4);--bg:rgba(255,111,126,0.07);--fg:#ff6f7e;--mkbg:rgba(255,111,126,0.14);}}
  .them .txt{{color:#c9b7ba;}}
  .us{{--bc:rgba(45,212,191,0.45);--bg:rgba(45,212,191,0.10);--fg:#2dd4bf;--mkbg:rgba(45,212,191,0.16);}}
  .rail{{position:absolute;left:84px;bottom:150px;width:78px;height:5px;border-radius:3px;background:linear-gradient(90deg,#2dd4bf,#ffce6a);}}
  .footer{{position:absolute;left:84px;bottom:92px;display:flex;align-items:center;gap:20px;}}
  .wordmark{{font-weight:800;font-style:italic;text-transform:uppercase;letter-spacing:1px;font-size:34px;color:#fff;}}
  .wordmark b{{color:#2dd4bf;}}
  .handle{{font-family:ui-monospace,Consolas,monospace;font-size:24px;color:#637984;letter-spacing:1.5px;}}
</style></head><body>
  <div class="pad">
    <div class="eyebrow">The Difference</div>
    <h1>{ta}<br><span class="vs">vs.</span> {tb}</h1>
    <div class="cards">
      <div class="box them"><div class="lab"><span class="mk">&#10005;</span>Typical tout</div><div class="txt">{them}</div></div>
      <div class="box us"><div class="lab"><span class="mk">&#10003;</span>Bankroll Kings</div><div class="txt">{us}</div></div>
    </div>
  </div>
  <div class="rail"></div>
  <div class="footer"><span class="wordmark">Bankroll <b>Kings</b></span><span class="handle">bankrollkings.com</span></div>
  <div class="frame"></div>
</body></html>'''

VS = [
 ("diff_01","Locks","Math","Sells you \u201clocks\u201d and \u201cguaranteed\u201d winners.","Shows the model\u2019s number and the calibration that proves it."),
 ("diff_02","Hit rate","ROI","Brags about hit rate. Hides what it actually returned.","Shows ROI at the real price \u2014 even when it stings."),
 ("diff_03","Hype","Timing","Chases the streak everyone is already betting.","Hunts the number the market hasn\u2019t caught up to yet."),
 ("diff_04","Screenshots","Receipts","Posts the wins, quietly deletes the losses.","239,378 graded props on the record \u2014 good and bad."),
]

# ---------- VALUE / CTA card ----------
VAL_TPL = '''<!doctype html><html><head><meta charset="utf-8"><style>
  *{{margin:0;padding:0;box-sizing:border-box;}}
  html,body{{width:1080px;height:1350px;overflow:hidden;}}
  body{{background:#070e14;font-family:"Helvetica Neue",Arial,sans-serif;color:#eef5f7;position:relative;
    background-image:radial-gradient(120% 60% at 80% 8%,rgba(45,212,191,0.16),transparent 55%),radial-gradient(80% 50% at 8% 100%,rgba(255,206,106,0.08),transparent 55%);}}
  .frame{{position:absolute;inset:34px;border:1px solid rgba(132,215,210,0.20);border-radius:26px;}}
  .pad{{position:absolute;inset:96px 84px;}}
  .eyebrow{{font-family:ui-monospace,Consolas,monospace;font-size:26px;letter-spacing:8px;text-transform:uppercase;color:#2dd4bf;font-weight:600;}}
  .price{{margin-top:24px;display:flex;align-items:baseline;gap:14px;}}
  .price .d{{font-weight:800;font-style:italic;font-size:150px;line-height:.85;color:#fff;text-shadow:0 0 50px rgba(45,212,191,.35);}}
  .price .m{{font-family:ui-monospace,Consolas,monospace;font-size:34px;color:#9db0bb;letter-spacing:1px;}}
  .sub{{margin-top:22px;font-size:44px;font-weight:800;font-style:italic;text-transform:uppercase;color:#2dd4bf;letter-spacing:.5px;}}
  .panel{{margin-top:40px;border:1px solid rgba(45,212,191,0.30);border-radius:18px;padding:12px 30px;background:linear-gradient(160deg,rgba(45,212,191,0.08),rgba(10,20,27,.45));}}
  .li{{display:flex;gap:18px;align-items:center;padding:20px 0;border-bottom:1px solid rgba(255,255,255,.06);font-size:32px;color:#e7f0f3;}}
  .li:last-child{{border-bottom:none;}}
  .li .ck{{flex:none;width:36px;height:36px;border-radius:9px;background:rgba(45,212,191,.14);border:1px solid rgba(45,212,191,.5);display:flex;align-items:center;justify-content:center;color:#2dd4bf;font-weight:800;font-size:22px;}}
  .kick{{position:absolute;left:84px;right:84px;bottom:198px;font-size:34px;font-weight:700;font-style:italic;color:#ffce6a;}}
  .rail{{position:absolute;left:84px;bottom:150px;width:78px;height:5px;border-radius:3px;background:linear-gradient(90deg,#2dd4bf,#ffce6a);}}
  .footer{{position:absolute;left:84px;bottom:92px;display:flex;align-items:center;gap:20px;}}
  .wordmark{{font-weight:800;font-style:italic;text-transform:uppercase;letter-spacing:1px;font-size:34px;color:#fff;}}
  .wordmark b{{color:#2dd4bf;}}
  .handle{{font-family:ui-monospace,Consolas,monospace;font-size:24px;color:#637984;letter-spacing:1.5px;}}
</style></head><body>
  <div class="pad">
    <div class="eyebrow">One plan. Everything.</div>
    <div class="price"><span class="d">$19.99</span><span class="m">/ month</span></div>
    <div class="sub">No tiers. No upsells.</div>
    <div class="panel">
      <div class="li"><span class="ck">&#10003;</span>Every sport\u2019s board, model number, and confidence</div>
      <div class="li"><span class="ck">&#10003;</span>Best Lines, Market Movers, Risk Radar, Ticket Check</div>
      <div class="li"><span class="ck">&#10003;</span>Injury impact, Game Context, and the full Track Record</div>
      <div class="li"><span class="ck">&#10003;</span>Franchise Kings + Fantasy, included</div>
    </div>
  </div>
  <div class="kick">No \u201cVIP\u201d pick. No pay-per-play. One price, all of it.</div>
  <div class="rail"></div>
  <div class="footer"><span class="wordmark">Bankroll <b>Kings</b></span><span class="handle">bankrollkings.com</span></div>
  <div class="frame"></div>
</body></html>'''

out=[]
for stem,ta,tb,them,us in VS:
    doc=VS_TPL.format(ta=esc(ta),tb=esc(tb),them=esc(them),us=esc(us))
    (SRC/f"{stem}.html").write_text(doc,encoding="utf-8")
    p,sz=render(stem); out.append((stem,sz))
(SRC/"diff_05_value.html").write_text(VAL_TPL.format(),encoding="utf-8")
p,sz=render("diff_05_value"); out.append(("diff_05_value",sz))

for stem,sz in out:
    print(f"{stem}.png -> {sz} bytes")
