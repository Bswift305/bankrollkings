# -*- coding: utf-8 -*-
import pathlib, subprocess, shutil, sys
SRC = pathlib.Path(__file__).parent
CHROME = r"C:/Program Files/Google/Chrome/Application/chrome.exe"
FPS = 24
BUILD_SEC = 2.6      # animation builds in over this long
HOLD_SEC = 5.0       # then the finished card FREEZES still (readable) before the loop
N = int(FPS*BUILD_SEC)
W, H = 1080, 1920

import base64
MASCOT = "data:image/webp;base64,"+base64.b64encode(pathlib.Path(r"C:/Users/Decatur/OneDrive/Documents/Kings of Bankrolls/static/king-bankroll.webp").read_bytes()).decode()

STYLE = r'''
*{margin:0;padding:0;box-sizing:border-box;}
html,body{width:1080px;height:1920px;overflow:hidden;}
body{background:#070e14;font-family:"Helvetica Neue",Arial,sans-serif;color:#eef5f7;position:relative;--ac:#2dd4bf;}
#glow{position:absolute;inset:0;}
.frame{position:absolute;inset:40px;border:1px solid rgba(132,215,210,0.18);border-radius:30px;}
.pad{position:absolute;left:100px;right:100px;top:160px;}
.eyebrow{font-family:ui-monospace,Consolas,monospace;font-size:30px;letter-spacing:9px;text-transform:uppercase;color:var(--ac);font-weight:600;}
.num{position:absolute;right:100px;top:160px;font-family:ui-monospace,Consolas,monospace;font-size:26px;letter-spacing:2px;color:#4a5b64;}
.tag{margin-top:26px;font-family:ui-monospace,Consolas,monospace;font-size:26px;color:#ffce6a;letter-spacing:2px;text-transform:uppercase;}
h1.tt{font-weight:800;font-style:italic;text-transform:uppercase;font-size:116px;line-height:.9;letter-spacing:.5px;margin-top:28px;color:#fff;text-shadow:0 8px 44px rgba(0,0,0,.5);}
h1.tt .cy{color:var(--ac);text-shadow:0 0 44px var(--ac);}
.ln{display:block;}
.pnum{font-weight:800;font-style:italic;font-size:58px;color:var(--ac);margin-top:22px;text-shadow:0 0 40px var(--ac);}
.mascot{width:400px;height:400px;object-fit:cover;border-radius:26px;display:block;margin:0 0 10px;box-shadow:0 24px 70px rgba(0,0,0,.55);}
.ctaline{font-size:52px;font-weight:800;font-style:italic;color:var(--ac);text-shadow:0 0 40px var(--ac);}
.bignum{font-weight:800;font-style:italic;font-size:200px;line-height:.78;color:var(--ac);text-shadow:0 0 70px var(--ac);margin-top:8px;}
.wheretag{font-family:ui-monospace,Consolas,monospace;font-size:28px;letter-spacing:1px;color:var(--ac);text-transform:uppercase;}
.chips{margin-top:56px;display:flex;flex-direction:column;gap:24px;}
.chip{display:flex;align-items:center;gap:22px;font-size:42px;color:#e7f0f3;}
.chip b{width:66px;height:66px;border-radius:16px;background:color-mix(in srgb,var(--ac) 15%,transparent);border:1px solid color-mix(in srgb,var(--ac) 55%,transparent);color:var(--ac);display:flex;align-items:center;justify-content:center;font-weight:800;font-style:italic;font-size:36px;flex:none;}
.reveal{margin-top:44px;display:inline-flex;align-items:center;gap:18px;transform-origin:left center;}
.reveal .arw{color:#ffce6a;font-weight:800;font-style:italic;font-size:52px;}
.reveal .txt{font-weight:800;font-style:italic;text-transform:uppercase;font-size:52px;color:#ffce6a;line-height:1;}
.body{margin-top:52px;font-size:46px;line-height:1.4;color:#c7d7de;max-width:22ch;}
.body b{color:#fff;}
.kick{margin-top:44px;font-size:40px;line-height:1.35;color:#eef5f7;font-weight:700;max-width:22ch;}
.kick .cy{color:var(--ac);}
/* bars */
.rows{margin-top:66px;display:flex;flex-direction:column;gap:36px;}
.row{display:grid;grid-template-columns:250px 1fr 210px;align-items:center;gap:26px;}
.tier{font-weight:800;font-style:italic;font-size:46px;color:#eef5f7;}
.track{height:42px;border-radius:10px;background:rgba(255,255,255,0.06);overflow:hidden;}
.fill{height:100%;width:0%;border-radius:10px;background:linear-gradient(90deg,rgba(45,212,191,.55),#4fe9d4);box-shadow:0 0 24px rgba(45,212,191,.35);}
.fill.g{background:linear-gradient(90deg,rgba(78,212,138,.55),#4ed48a);box-shadow:0 0 24px rgba(78,212,138,.35);}
.fill.gy{background:linear-gradient(90deg,rgba(120,140,150,.35),#7d95a0);box-shadow:none;}
.pct{font-family:ui-monospace,Consolas,monospace;font-size:48px;color:var(--ac);text-align:right;font-variant-numeric:tabular-nums;}
.pct.g{color:#4ed48a;} .pct.gy{color:#8ea3b0;}
/* duo */
.duo{margin-top:90px;display:grid;grid-template-columns:1fr 1fr;gap:26px;}
.stat{border-radius:20px;padding:40px 32px;border:1px solid var(--bc);background:linear-gradient(160deg,var(--bg),rgba(10,20,27,.6));overflow:hidden;}
.stat .k{font-family:ui-monospace,Consolas,monospace;font-size:23px;letter-spacing:1.2px;text-transform:uppercase;color:#9db0bb;}
.stat .big{font-weight:800;font-style:italic;font-size:104px;line-height:.9;margin-top:18px;color:var(--fg);font-variant-numeric:tabular-nums;text-shadow:0 0 40px var(--gl);white-space:nowrap;}
.stat .cap{font-size:32px;color:#c7d7de;margin-top:8px;font-weight:600;}
.win{--bc:rgba(78,212,138,0.4);--bg:rgba(78,212,138,0.08);--fg:#4ed48a;--gl:rgba(78,212,138,.35);}
.lose{--bc:rgba(255,111,126,0.4);--bg:rgba(255,111,126,0.08);--fg:#ff6f7e;--gl:rgba(255,111,126,.35);}
/* versus */
h1.vt{font-weight:800;font-style:italic;text-transform:uppercase;font-size:104px;line-height:.92;margin-top:22px;color:#fff;}
h1.vt .vs{color:#637984;font-size:64px;}
.vbox{margin-top:44px;border-radius:22px;padding:40px 40px;border:1px solid var(--bc);background:linear-gradient(160deg,var(--bg),rgba(10,20,27,.55));}
.vbox .vlab{font-family:ui-monospace,Consolas,monospace;font-size:26px;letter-spacing:3px;text-transform:uppercase;color:var(--fg);display:flex;align-items:center;gap:18px;}
.vbox .mk{width:56px;height:56px;border-radius:14px;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:34px;background:var(--mkbg);color:var(--fg);border:1px solid var(--bc);}
.vbox .vtxt{margin-top:22px;font-size:46px;line-height:1.3;color:#eef5f7;}
.them{--bc:rgba(255,111,126,0.4);--bg:rgba(255,111,126,0.07);--fg:#ff6f7e;--mkbg:rgba(255,111,126,0.14);}
.them .vtxt{color:#c9b7ba;}
.us{--bc:rgba(45,212,191,0.45);--bg:rgba(45,212,191,0.10);--fg:#2dd4bf;--mkbg:rgba(45,212,191,0.16);}
/* value */
.price{margin-top:30px;display:flex;align-items:baseline;gap:16px;}
.price .d{font-weight:800;font-style:italic;font-size:190px;line-height:.85;color:#fff;text-shadow:0 0 50px rgba(45,212,191,.35);font-variant-numeric:tabular-nums;}
.price .m{font-family:ui-monospace,Consolas,monospace;font-size:38px;color:#9db0bb;letter-spacing:1px;}
.subv{margin-top:26px;font-size:52px;font-weight:800;font-style:italic;text-transform:uppercase;color:var(--ac);}
.vp{margin-top:56px;display:flex;flex-direction:column;gap:30px;}
.vli{display:flex;gap:22px;align-items:center;font-size:40px;color:#e7f0f3;}
.vli .ck{flex:none;width:52px;height:52px;border-radius:13px;background:rgba(45,212,191,.14);border:1px solid rgba(45,212,191,.5);display:flex;align-items:center;justify-content:center;color:var(--ac);font-weight:800;font-size:30px;}
/* feature */
h1.fn{font-weight:800;font-style:italic;text-transform:uppercase;font-size:108px;line-height:.92;margin-top:22px;color:#fff;}
.ftag{margin-top:32px;font-size:46px;line-height:1.28;color:#c7d7de;max-width:22ch;}
.fp{margin-top:50px;border:1px solid color-mix(in srgb,var(--ac) 40%,transparent);border-radius:20px;padding:16px 36px;background:linear-gradient(160deg,color-mix(in srgb,var(--ac) 10%,transparent),rgba(10,20,27,.45));}
.fli{display:flex;gap:24px;align-items:flex-start;padding:28px 0;border-bottom:1px solid rgba(255,255,255,.06);}
.fli:last-child{border-bottom:none;}
.fli .ck{flex:none;width:48px;height:48px;border-radius:12px;background:color-mix(in srgb,var(--ac) 18%,transparent);border:1px solid color-mix(in srgb,var(--ac) 60%,transparent);display:flex;align-items:center;justify-content:center;color:var(--ac);font-weight:800;font-size:28px;margin-top:2px;}
.fli span{font-size:38px;line-height:1.3;color:#e7f0f3;}
.fli b{color:#fff;}
.fkick{margin-top:44px;font-size:40px;font-weight:700;font-style:italic;color:var(--ac);}
/* shared bottom */
.callout{position:absolute;left:100px;right:120px;bottom:340px;font-size:42px;line-height:1.4;color:#c7d7de;}
.callout b{color:#fff;}
.rail{position:absolute;left:100px;bottom:220px;width:86px;height:6px;border-radius:3px;background:linear-gradient(90deg,var(--ac),#ffce6a);}
.footer{position:absolute;left:100px;bottom:140px;display:flex;align-items:center;gap:22px;}
.wordmark{font-weight:800;font-style:italic;text-transform:uppercase;letter-spacing:1px;font-size:40px;color:#fff;}
.wordmark b{color:var(--ac);}
.handle{font-family:ui-monospace,Consolas,monospace;font-size:28px;color:#637984;letter-spacing:1.5px;}
'''

SCRIPT = r'''
function clamp(x,a,b){return Math.max(a,Math.min(b,x));}
function ease(t){t=clamp(t,0,1);return t*t*(3-2*t);}
function seg(p,s,d){return ease((p-s)/(d||0.16));}
function apply(p){
  var gl=document.getElementById('glow'); if(gl) gl.style.opacity=0.55+0.45*Math.sin(p*Math.PI*2);
  document.querySelectorAll('[data-s]').forEach(function(el){
    var s=parseFloat(el.dataset.s), d=parseFloat(el.dataset.d||'0.16'), k=el.dataset.k||'fade';
    var g=seg(p,s,d);
    if(k=='fade'){el.style.opacity=g; el.style.transform='translateY('+((1-g)*26)+'px)';}
    else if(k=='pop'){el.style.opacity=g; el.style.transform='scale('+(0.84+0.16*g)+')';}
    else if(k=='slideL'){el.style.opacity=g; el.style.transform='translateX('+((1-g)*-48)+'px)';}
    else if(k=='bar'){el.style.width=(parseFloat(el.dataset.t)*g)+'%';}
    else if(k=='count'){var t=parseFloat(el.dataset.t),dc=parseInt(el.dataset.dec||'0');el.textContent=(el.dataset.pre||'')+(t*g).toFixed(dc)+(el.dataset.suf||'');}
  });
}
var p=parseFloat(new URLSearchParams(location.search).get('p')||'1'); apply(p);
'''

def wrap(inner, ac="#2dd4bf", glow="rgba(45,212,191,0.20)"):
    return ('<!doctype html><html><head><meta charset="utf-8"><style>'+STYLE+'</style></head>'
            f'<body style="--ac:{ac}">'
            f'<div id="glow" style="background:radial-gradient(120% 42% at 80% 12%,{glow},transparent 55%)"></div>'
            + inner +
            '<div class="rail"></div>'
            '<div class="footer"><span class="wordmark">Bankroll <b>Kings</b></span><span class="handle">bankrollkings.com</span></div>'
            '<div class="frame"></div>'
            '<script>'+SCRIPT+'</script></body></html>')

def footer_slots():  # standard fade timings for rail/footer not animated (kept static-visible)
    return ""

# ---------- builders ----------
def teach(eyebrow,h1_lines,reveal,body,kick,ac,glow):
    lns="".join(f'<span class="ln" data-s="{0.05+i*0.07}" data-d="0.16" data-k="fade">{t}</span>' for i,t in enumerate(h1_lines))
    inner=f'''<div class="pad">
      <div class="eyebrow" data-s="0" data-d="0.10">{eyebrow}</div>
      <h1 class="tt">{lns}</h1>
      <div class="reveal" data-s="0.34" data-d="0.14" data-k="pop"><span class="arw">&#8594;</span><span class="txt">{reveal}</span></div>
      <div class="body" data-s="0.52" data-d="0.16">{body}</div>
      <div class="kick" data-s="0.70" data-d="0.16">{kick}</div>
    </div>'''
    return wrap(inner,ac,glow)

def bars(eyebrow,h1_lines,tag,bars_list,callout,ac,glow):
    lns="".join(f'<span class="ln" data-s="{0.05+i*0.07}" data-d="0.16">{t}</span>' for i,t in enumerate(h1_lines))
    rows=""
    for i,(tier,target,cls) in enumerate(bars_list):
        s=0.30+i*0.09
        rows+=f'''<div class="row" data-s="{s-0.03}" data-d="0.10">
          <span class="tier">{tier}</span>
          <div class="track"><div class="fill {cls}" data-s="{s}" data-d="0.24" data-k="bar" data-t="{target}"></div></div>
          <span class="pct {cls}" data-s="{s}" data-d="0.24" data-k="count" data-t="{target}" data-dec="1" data-suf="%">0.0%</span>
        </div>'''
    inner=f'''<div class="pad">
      <div class="eyebrow" data-s="0" data-d="0.10">{eyebrow}</div>
      <h1 class="tt" style="font-size:96px">{lns}</h1>
      <div class="tag" data-s="0.16" data-d="0.10">{tag}</div>
      <div class="rows">{rows}</div>
    </div>
    <div class="callout" data-s="0.82" data-d="0.14">{callout}</div>'''
    return wrap(inner,ac,glow)

def duo(eyebrow,h1_lines,win,lose,callout,ac,glow):
    lns="".join(f'<span class="ln" data-s="{0.05+i*0.07}" data-d="0.16">{t}</span>' for i,t in enumerate(h1_lines))
    inner=f'''<div class="pad">
      <div class="eyebrow" data-s="0" data-d="0.10">{eyebrow}</div>
      <h1 class="tt" style="font-size:104px">{lns}</h1>
      <div class="duo">
        <div class="stat win" data-s="0.34" data-d="0.16" data-k="pop"><div class="k">{win[0]}</div>
          <div class="big"><span data-s="0.40" data-d="0.34" data-k="count" data-t="{win[1]}" data-dec="1" data-suf="%">0.0%</span></div>
          <div class="cap">{win[2]}</div></div>
        <div class="stat lose" data-s="0.44" data-d="0.16" data-k="pop"><div class="k">{lose[0]}</div>
          <div class="big"><span data-s="0.50" data-d="0.34" data-k="count" data-t="{lose[1]}" data-dec="1" data-pre="&#8722;" data-suf="%">0.0%</span></div>
          <div class="cap">{lose[2]}</div></div>
      </div>
    </div>
    <div class="callout" data-s="0.82" data-d="0.14">{callout}</div>'''
    return wrap(inner,ac,glow)

def versus(eyebrow,ta,tb,them,us,ac,glow):
    inner=f'''<div class="pad">
      <div class="eyebrow" data-s="0" data-d="0.10">{eyebrow}</div>
      <h1 class="vt"><span class="ln" data-s="0.06" data-d="0.16">{ta}</span><span class="ln" data-s="0.14" data-d="0.16"><span class="vs">vs.</span> {tb}</span></h1>
      <div class="vbox them" data-s="0.34" data-d="0.16" data-k="slideL"><div class="vlab"><span class="mk">&#10005;</span>Typical tout</div><div class="vtxt">{them}</div></div>
      <div class="vbox us" data-s="0.52" data-d="0.16" data-k="slideL"><div class="vlab"><span class="mk">&#10003;</span>Bankroll Kings</div><div class="vtxt">{us}</div></div>
    </div>'''
    return wrap(inner,ac,glow)

def value(items,ac,glow):
    lis=""
    for i,it in enumerate(items):
        lis+=f'<div class="vli" data-s="{0.52+i*0.09}" data-d="0.14" data-k="slideL"><span class="ck">&#10003;</span>{it}</div>'
    inner=f'''<div class="pad">
      <div class="eyebrow" data-s="0" data-d="0.10">One plan. Everything.</div>
      <div class="price"><span class="d"><span data-s="0.10" data-d="0.34" data-k="count" data-t="19.99" data-dec="2" data-pre="$">$0.00</span></span><span class="m" data-s="0.30" data-d="0.12">/ month</span></div>
      <div class="subv" data-s="0.34" data-d="0.14">No tiers. No upsells.</div>
      <div class="vp">{lis}</div>
    </div>
    <div class="callout" data-s="0.86" data-d="0.12" style="bottom:300px;color:#ffce6a;font-weight:700;font-style:italic">No &#8220;VIP&#8221; pick. No pay-per-play. One price, all of it.</div>'''
    return wrap(inner,ac,glow)

def feature(num,eyebrow,name,tagline,bullets,kick,ac,glow):
    lis=""
    for i,b in enumerate(bullets):
        lis+=f'<div class="fli" data-s="{0.44+i*0.11}" data-d="0.14" data-k="slideL"><div class="ck">&#10003;</div><span>{b}</span></div>'
    inner=f'''<div class="num" data-s="0" data-d="0.10">{num} / INSIDE</div>
    <div class="pad">
      <div class="eyebrow" data-s="0" data-d="0.10">{eyebrow}</div>
      <h1 class="fn"><span class="ln" data-s="0.08" data-d="0.16">{name}</span></h1>
      <div class="ftag" data-s="0.22" data-d="0.14">{tagline}</div>
      <div class="fp">{lis}</div>
      <div class="fkick" data-s="0.84" data-d="0.12">{kick}</div>
    </div>'''
    return wrap(inner,ac,glow)

def proverb(n, headline, sub, ac="#2dd4bf", glow="rgba(45,212,191,0.20)"):
    hl = headline.replace("[[","<span class='cy'>").replace("]]","</span>")
    parts = hl.split("<br>")
    lns = "".join(f'<span class="ln" data-s="{0.16+i*0.07}" data-d="0.16">{t}</span>' for i,t in enumerate(parts))
    inner = f'''<div class="pad">
      <div class="eyebrow" data-s="0" data-d="0.10">The King&#39;s Proverbs</div>
      <div class="pnum" data-s="0.10" data-d="0.14" data-k="pop">No. {n}</div>
      <h1 class="tt" style="font-size:90px;margin-top:12px">{lns}</h1>
      <div class="body" data-s="0.56" data-d="0.16" style="margin-top:48px;max-width:24ch">{sub}</div>
    </div>'''
    return wrap(inner, ac, glow)

CY="#2dd4bf"; GREEN="#4ed48a"; GOLD="#ffce6a"
GCY="rgba(45,212,191,0.20)"; GGN="rgba(78,212,138,0.16)"; GGD="rgba(255,206,106,0.14)"

def intro1():
    inner=f'''<div class="pad" style="top:140px">
      <img class="mascot" data-s="0.05" data-d="0.24" data-k="pop" src="{MASCOT}">
      <div class="eyebrow" data-s="0.30" data-d="0.10" style="margin-top:24px">Meet</div>
      <h1 class="tt" style="font-size:120px;margin-top:14px"><span class="ln" data-s="0.36" data-d="0.16">Bankroll</span><span class="ln" data-s="0.44" data-d="0.16"><span class="cy">Kings.</span></span></h1>
      <div class="body" data-s="0.62" data-d="0.18" style="margin-top:32px;max-width:23ch">Sports betting, run on <b>math — not locks.</b> We show the model's number, the proof it's calibrated, and the ROI most sites hide.</div>
    </div>'''
    return wrap(inner, CY, GCY)

def intro2():
    items=["Our model's number vs. the market — every sport","Best Lines across every book, every prop",
           "Injury impact, Game Context & Market Movers","A smarter Parlay Builder + Risk Radar",
           "The honest Track Record — real ROI","Franchise Kings + Fantasy, included"]
    lis="".join(f'<div class="fli" data-s="{0.34+i*0.08}" data-d="0.12" data-k="slideL"><div class="ck">&#10003;</div><span>{t}</span></div>' for i,t in enumerate(items))
    inner=f'''<div class="pad">
      <div class="eyebrow" data-s="0" data-d="0.10">What you get</div>
      <h1 class="tt" style="font-size:98px"><span class="ln" data-s="0.08" data-d="0.16">Everything,</span><span class="ln" data-s="0.16" data-d="0.16">one <span class="cy">place.</span></span></h1>
      <div class="fp" style="margin-top:44px;padding:8px 34px">{lis}</div>
    </div>'''
    return wrap(inner, CY, GCY)

def intro3():
    items=["Every board, model number & confidence","Best Lines, Movers, Risk Radar, Ticket Check",
           "Injury impact, Track Record, Game Context","Franchise Kings + Fantasy"]
    lis="".join(f'<div class="vli" data-s="{0.50+i*0.08}" data-d="0.12" data-k="slideL"><span class="ck">&#10003;</span>{t}</div>' for i,t in enumerate(items))
    inner=f'''<div class="pad">
      <div class="eyebrow" data-s="0" data-d="0.10">One price. Everything.</div>
      <div class="price"><span class="d"><span data-s="0.10" data-d="0.32" data-k="count" data-t="19.99" data-dec="2" data-pre="$">$0.00</span></span><span class="m" data-s="0.28" data-d="0.12">/ month</span></div>
      <div class="subv" data-s="0.32" data-d="0.14">No tiers. No upsells.</div>
      <div class="vp" style="margin-top:42px">{lis}</div>
    </div>
    <div class="ctaline" data-s="0.84" data-d="0.12" style="position:absolute;left:100px;bottom:320px">&#8594; bankrollkings.com</div>'''
    return wrap(inner, CY, GCY)

def howto_cover():
    inner=f'''<div class="pad">
      <div class="eyebrow" data-s="0" data-d="0.10">Start here</div>
      <h1 class="tt" style="font-size:104px"><span class="ln" data-s="0.08" data-d="0.16">New here?</span><span class="ln" data-s="0.16" data-d="0.16">Start in <span class="cy">3 steps.</span></span></h1>
      <div class="body" data-s="0.30" data-d="0.16" style="margin-top:34px;max-width:20ch">From a blank slate to a smarter bet in five minutes.</div>
      <div class="chips">
        <div class="chip" data-s="0.46" data-d="0.12" data-k="slideL"><b>1</b> Pick your sport</div>
        <div class="chip" data-s="0.54" data-d="0.12" data-k="slideL"><b>2</b> Read the number</div>
        <div class="chip" data-s="0.62" data-d="0.12" data-k="slideL"><b>3</b> Shop the best line</div>
      </div>
    </div>'''
    return wrap(inner, CY, GCY)

def howto_step(n,title,desc,where):
    inner=f'''<div class="pad">
      <div class="eyebrow" data-s="0" data-d="0.10">Start here · Step {n} of 3</div>
      <div class="bignum" data-s="0.10" data-d="0.16" data-k="pop">{n}</div>
      <h1 class="tt" style="font-size:92px;margin-top:4px"><span class="ln" data-s="0.24" data-d="0.16">{title}</span></h1>
      <div class="body" data-s="0.42" data-d="0.16" style="margin-top:34px;max-width:22ch">{desc}</div>
    </div>
    <div class="wheretag" data-s="0.72" data-d="0.14" style="position:absolute;left:100px;bottom:320px">where: {where}</div>'''
    return wrap(inner, CY, GCY)

JOBS = {
 # ---- brand intro (first post) ----
 "vid_intro_01": intro1(),
 "vid_intro_02": intro2(),
 "vid_intro_03": intro3(),
 # ---- teach / myth ----
 "vid_myth_overs": teach("Myth or Money",["Stack","the <span class='cy'>overs.</span>"],"The fastest way to lose.",
   "Overs are correlated \u2014 a shootout lifts them together, so they also <b>miss together.</b>","Mix your sides. <span class='cy'>Don't chain longshots.</span>",CY,GCY),
 "vid_myth_chase": teach("Myth or Money",["Win it back","<span class='cy'>tonight.</span>"],"That's the tilt talking.",
   "Chasing a loss doesn't shrink the variance \u2014 it <b>doubles your exposure</b> to it.","Bet units, not feelings. <span class='cy'>Every night is a fresh slate.</span>",CY,GCY),
 "vid_myth_hot": teach("Myth or Money",["He's","<span class='cy'>heating up.</span>"],"So is the price.",
   "One hot game <b>regresses hard,</b> and the line already moved to match the streak.","Weigh the full sample, <span class='cy'>not the last highlight.</span>",CY,GCY),
 "vid_myth_fantasy_name": teach("Fantasy \u00b7 Myth or Money",["Start the","<span class='cy'>big name.</span>"],"Not into that defense.",
   "A star in a brutal matchup can score less than a role player in a soft one. <b>Name value isn't a projection.</b>","We bake the matchup in \u2014 <span class='cy'>Soft / Neutral / Tough, live.</span>",GOLD,GGD),
 "vid_myth_fantasy_sim": teach("Fantasy",["2,000 seasons,","<span class='cy'>every player.</span>"],"Before you set the lineup.",
   "We don't rank on last week's points. We <b>simulate 2,000 games</b> per player \u2014 then adjust for injuries and matchup.","Set your lineup on the <span class='cy'>distribution, not the hype.</span>",GOLD,GGD),
 "vid_myth_franchise": teach("Free to play",["Run the whole","<span class='cy'>franchise.</span>"],"Draft. Trade. Dynasty.",
   "Draft the class, work the trade market, develop your guys, chase a title. <b>A full GM career,</b> free.","The free way in. <span class='cy'>Come for the game, stay for the edge.</span>",GREEN,GGN),
 # ---- bars ----
 "vid_calibration": bars("The Proof",["We say 80%.","It hits <span class='cy'>80%.</span>"],"239,378 graded",
   [("90+",89.9,""),("80-89",83.2,""),("70-79",72.5,""),("60-69",61.7,""),("under 60",36.7,"")],
   "Our confidence predicts the real hit rate. <b>That's math, not marketing.</b>",CY,GCY),
 "vid_wind": bars("The one edge",["Wind kills","<span class='cy'>totals.</span>"],"5,205 outdoor games",
   [("0\u20135",50.0,"gy"),("5\u201310",48.2,"gy"),("10\u201315",53.8,"g"),("15\u201320",57.3,"g"),("20+",56.0,"g")],
   "15+ mph \u2192 <b>55.5% unders, +5.9% ROI</b> out of sample.",GREEN,GGN),
 # ---- duo ----
 "vid_roi": duo("Receipts \u00b7 The Honest Part",["58% Hit.","Still <span class='cy'>Lost.</span>"],
   ("Our WNBA featured picks",58.6,"hit rate"),("At the closing price",7.9,"ROI"),
   "A winning record can still <b>bleed money.</b> So we show the ROI.",CY,GCY),
 # ---- versus ----
 "vid_diff_locks": versus("The Difference","Locks","Math","Sells you &#8220;locks&#8221; and &#8220;guaranteed&#8221; winners.","Shows the model's number and the calibration that proves it.",CY,GCY),
 "vid_diff_roi": versus("The Difference","Hit rate","ROI","Brags about hit rate. Hides what it returned.","Shows ROI at the real price \u2014 even when it stings.",CY,GCY),
 "vid_diff_hype": versus("The Difference","Hype","Timing","Chases the streak everyone is already betting.","Hunts the number the market hasn't caught up to.",CY,GCY),
 "vid_diff_receipts": versus("The Difference","Screenshots","Receipts","Posts the wins, quietly deletes the losses.","239,378 graded props on the record \u2014 good and bad.",CY,GCY),
 # ---- value ----
 "vid_value": value(["Every sport's board, model number & confidence","Best Lines, Market Movers, Risk Radar, Ticket Check","Injury impact, Game Context, full Track Record","Franchise Kings + Fantasy, included"],CY,GCY),
 # ---- feature ----
 "vid_feat_command": feature("01","Inside the app","The Command Center","Every game, every line \u2014 with our model's number next to the market's.",
   ["An Elo power rating we build <b>independent of the book</b>","See where our number <b>disagrees with the line</b>","Full slate: NFL \u00b7 NBA \u00b7 MLB \u00b7 WNBA \u00b7 CFB"],"We don't chase the market. We measure it.",CY,GCY),
 "vid_feat_bestlines": feature("02","Inside the app","Best Lines","The same prop is priced differently at every book. We show the best one.",
   ["<b>Best number and best price</b> across every book","Filter by league, stat, over/under, player","No hype \u2014 just the sharpest number available"],"A great read at a bad number is still a bad bet.",CY,GCY),
}

PROVERBS_RAW = [
 (1,"IT'S IN<br>THE [[PRICE.]]","If your reason is on the broadcast, <b>the market already knows.</b>"),
 (2,"THE STREAK<br>IS [[PRICED.]]","It's real — but the line <b>already moved.</b> You're paying retail."),
 (3,"BE [[FIRST,]]<br>NOT SMART.","You don't out-analyze the book. <b>Edge is a timing advantage.</b>"),
 (4,"THE NUMBER<br>IS THE [[BET.]]","A great read at a bad price is <b>still a bad bet.</b> Shop every line."),
 (5,"ONE BOOK<br>IS A [[QUOTE.]]","Three books is a market. <b>Never trust a single price.</b>"),
 (6,"THE SWEET<br>[[SPOT.]]","Live in the <b>−200 to −400</b> band — high enough to hit, priced enough to matter."),
 (7,"+900 IS A<br>LOTTERY<br>[[TICKET.]]","With your rent money. <b>10% break-even — and it hits far less.</b>"),
 (8,"CHASE THE<br>[[NUMBER.]]","Not the result. <b>Closing-line value</b> is the only scoreboard that predicts tomorrow."),
 (9,"NEVER<br>PARLAY<br>[[OVERS.]]","The fastest way to donate a bankroll. <b>Overs love to miss together.</b>"),
 (10,"WHEN TORN,<br>GO [[UNDER.]]","Variance is cheaper on the low side. <b>Unders bleed less.</b>"),
 (11,"OVERS DIE<br>ON A [[WALL.]]","Never take an over into a top defense — <b>a ceiling that isn't there.</b>"),
 (12,"ZERO ISN'T<br>[[SAFE.]]","A prop that needs a literal 0 to cash is <b>a trap in a suit.</b>"),
 (13,"BET<br>[[UNITS.]]","Not feelings. <b>The size never depends</b> on how sure you feel."),
 (14,"NEVER<br>[[CHASE.]]","The board is there tomorrow. <b>Your bankroll won't be</b> if you force it tonight."),
 (15,"RIGHT-SIZE<br>[[EVERYTHING.]]","If one bet can change your week, <b>it can change it the wrong way too.</b>"),
 (16,"CAP IT<br>[[FIRST.]]","Down days are the tax. <b>Blow-up days are the funeral.</b> Set the ceiling early."),
 (17,"THE EDGE<br>IS [[LATE.]]","The last 90 minutes — lineups, scratches, wind. <b>Late info is un-priced.</b>"),
 (18,"WIND KILLS<br>[[TOTALS.]]","Over 15 mph, quietly. <b>The market's slow on weather</b> — you don't have to be."),
 (19,"ROI TELLS<br>THE [[TRUTH.]]","Hit rate flatters. A 70% record can <b>still bleed money.</b>"),
 (20,"GRADE THE<br>[[DECISION.]]","Not the outcome. Losing bets aren't mistakes — <b>bad process is.</b>"),
 (21,"FADE YOUR<br>[[HYPE.]]","The play you love most is the one to <b>shrink.</b> Excitement is expensive."),
 (22,"DISCIPLINE<br>[[EATS.]]","Boring — and it's why the <b>King wins.</b> Excitement is a cost."),
]
for _n,_h,_s in PROVERBS_RAW:
    JOBS[f"vid_prov_{_n:02d}"] = proverb(_n,_h,_s)

JOBS.update({
 "vid_feat_parlay": feature("03","Inside the app","Parlay Builder","Build smarter slips — and see how often each leg clears its floor.",
   ["<b>Floor-reliability</b> on every leg — how often it beats the number","Sport-aware: each league's own board feeds the build","Structural warnings flag the traps first"],"Know your legs before you stack them.",CY,GCY),
 "vid_feat_injury": feature("04","Inside the app","Injury Report","Not just who's out — who cashes when they sit.",
   ["Every league's injuries in one filterable table","<b>With / without impact</b>: when X sits, Y produces Z","Status normalized — Out / Doubtful / Questionable"],"The line moves late on news. Be there first.",CY,GCY),
 "vid_feat_movers": feature("05","Inside the app","Market Movers","Watch the line travel from open to now.",
   ["Open → current movement, <b>consensus across books</b>","Tiered Major / Moderate / Stable — no fake 'steam'","Near-term slate, re-captured every 4 hours"],"Timing is the edge. Movement is the clock.",CY,GCY),
 "vid_feat_franchise": feature("06","Free to play","Franchise Kings","Take over a franchise. Draft, trade, build a dynasty — GM career mode.",
   ["A complete GM career: draft, trades, development","Your save, your calls — progress carries over","<b>Free to play.</b> No card, just the game"],"Come for the game, stay for the edge.",GREEN,GGN),
 "vid_feat_props": feature("07","Inside the app","The Props Board","Every player prop — with our confidence, and proof it's calibrated.",
   ["A confidence on each prop — and <b>80% means 80%</b>","Sport-aware: NBA · WNBA · MLB · NFL · CFB","Sort, filter, search to your read"],"Confidence you can trust — we show the math.",CY,GCY),
 "vid_feat_risk": feature("08","Inside the app","Risk Radar","Every prop, scanned for the traps you can't always see.",
   ["Injury flags — with the reason","Longshot-over & single-book warnings","Observable only — never a fake 'risk score'"],"Know the trap before it springs.",CY,GCY),
 "vid_feat_ticket": feature("09","Inside the app","Ticket Check","Paste your parlay. We flag the traps before you submit.",
   ["Injury exposure, all-overs, concentration flags","Combined implied probability — honestly labeled","Works across every sport on one slip"],"A second set of eyes on every slip.",CY,GCY),
 "vid_feat_context": feature("10","Inside the app","Game Context","Lineups, weather, park, officials — what quietly moves totals.",
   ["Per-matchup context, <b>freshness on every field</b>","Missing data reads 'unavailable', never neutral","Cross-sport coverage of what's verified"],"Context the box score won't give you.",CY,GCY),
 "vid_feat_slate": feature("11","Inside the app","Slate Pulse","The whole day at a glance — live slates vs. stale.",
   ["One row per league: markets, props, books, injuries","Feed freshness so you know it's current","Pure observation — no ranking, no 'best bets'"],"See the whole board breathe.",CY,GCY),
 "vid_feat_track": feature("12","The honest part","Track Record","Our real record — hit rate, break-even, and the ROI most sites bury.",
   ["Every method vs. the <b>break-even it needs</b>","ROI at the true price — even when it stings","Ranked by sample size, not a cherry-picked hit rate"],"The receipts, good and bad.",GOLD,GGD),
 "vid_feat_fantasy": feature("13","Inside the app","Fantasy","Simulation-driven rankings for your NFL & NBA lineups.",
   ["<b>2,000-game Monte Carlo</b> — projection, ceiling, floor","Live injury + matchup shifts in every ranking","DraftKings, FanDuel & Yahoo scoring"],"Set your lineup on the math, not the hype.",GOLD,GGD),
 "vid_streak": teach("Myth or Money",["Hot hands","are <span class='cy'>real.</span>"],"And the book knows it.",
   "A streaking player really does keep producing. So the line <b>already moved to match</b> — before you clicked.","The streak is real. The edge is gone. <span class='cy'>Hunt what the market missed.</span>",CY,GCY),
 "vid_howto_00": howto_cover(),
 "vid_howto_01": howto_step(1,"Pick your <span class='cy'>sport.</span>","The board loads every game and prop for the day — NFL, NBA, MLB, WNBA, CFB.","The Command Center"),
 "vid_howto_02": howto_step(2,"Read the <span class='cy'>number.</span>","Our model's number sits next to the market's, with a calibrated confidence. The gap is the edge.","Props Board + Command Center"),
 "vid_howto_03": howto_step(3,"Shop the best <span class='cy'>line.</span>","Best Lines finds the sharpest number and price across every book before you bet.","Best Lines"),
})

def render_full(stem, html):
    (SRC/f"{stem}.html").write_text(html, encoding="utf-8")
    fdir = SRC/("vf_"+stem)
    if fdir.exists(): shutil.rmtree(fdir)
    fdir.mkdir()
    base=(SRC/f"{stem}.html").resolve().as_uri()
    for i in range(N):
        p=i/(N-1)
        out=(fdir/f"f_{i:04d}.png").resolve()
        subprocess.run([CHROME,"--headless=new","--disable-gpu","--hide-scrollbars",
            "--force-device-scale-factor=1",f"--window-size={W},{H}",
            f"--screenshot={out}",f"{base}?p={p:.5f}"],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
    mp4=(SRC/f"{stem}.mp4").resolve()
    # after the build frames, freeze (clone) the last, fully-composed frame for HOLD_SEC so it's readable
    subprocess.run(["ffmpeg","-y","-framerate",str(FPS),"-i",str(fdir/"f_%04d.png"),
        "-c:v","libx264","-pix_fmt","yuv420p","-movflags","+faststart",
        "-vf",f"tpad=stop_mode=clone:stop_duration={HOLD_SEC},scale={W}:{H}",str(mp4)],
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
    shutil.rmtree(fdir, ignore_errors=True)
    return mp4.stat().st_size if mp4.exists() else 0

def render_still(stem, html, p):
    (SRC/f"{stem}.html").write_text(html, encoding="utf-8")
    base=(SRC/f"{stem}.html").resolve().as_uri()
    out=(SRC/f"{stem}_v{int(p*100):03d}.png").resolve()
    subprocess.run([CHROME,"--headless=new","--disable-gpu","--hide-scrollbars",
        "--force-device-scale-factor=1",f"--window-size={W},{H}",
        f"--screenshot={out}",f"{base}?p={p:.5f}"],
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)

def main():
    mode = sys.argv[1] if len(sys.argv)>1 else "all"
    only = sys.argv[2:] if len(sys.argv)>2 else list(JOBS.keys())
    if mode=="validate":
        for stem in only:
            render_still(stem, JOBS[stem], 1.0)
            render_still(stem, JOBS[stem], 0.60)
            print("validated", stem, flush=True)
    else:
        for stem in only:
            sz=render_full(stem, JOBS[stem])
            print(f"{stem}.mp4 -> {sz} bytes", flush=True)

main()
