# -*- coding: utf-8 -*-
import pathlib, subprocess, shutil, sys
SRC = pathlib.Path(__file__).parent
CHROME = r"C:/Program Files/Google/Chrome/Application/chrome.exe"
FPS = 24
DUR = 5.0
N = int(FPS*DUR)
W,H = 1080,1920

HTML = r'''<!doctype html><html><head><meta charset="utf-8"><style>
  *{margin:0;padding:0;box-sizing:border-box;}
  html,body{width:1080px;height:1920px;overflow:hidden;}
  body{background:#070e14;font-family:"Helvetica Neue",Arial,sans-serif;color:#eef5f7;position:relative;}
  #glow{position:absolute;inset:0;background:radial-gradient(120% 45% at 80% 12%,rgba(45,212,191,0.20),transparent 55%);}
  .frame{position:absolute;inset:40px;border:1px solid rgba(132,215,210,0.18);border-radius:30px;}
  .pad{position:absolute;left:96px;right:96px;top:150px;}
  .eyebrow{font-family:ui-monospace,Consolas,monospace;font-size:30px;letter-spacing:9px;text-transform:uppercase;color:#2dd4bf;font-weight:600;}
  h1{font-weight:800;font-style:italic;text-transform:uppercase;font-size:98px;line-height:.95;letter-spacing:.5px;margin-top:30px;color:#fff;text-shadow:0 8px 44px rgba(0,0,0,.5);}
  h1 .cy{color:#2dd4bf;text-shadow:0 0 44px rgba(45,212,191,.6);}
  .ln{display:block;}
  .tag{margin-top:26px;font-family:ui-monospace,Consolas,monospace;font-size:26px;color:#ffce6a;letter-spacing:2px;text-transform:uppercase;}
  .rows{margin-top:70px;display:flex;flex-direction:column;gap:38px;}
  .row{display:grid;grid-template-columns:230px 1fr 200px;align-items:center;gap:26px;}
  .tier{font-weight:800;font-style:italic;font-size:46px;color:#eef5f7;}
  .track{height:42px;border-radius:10px;background:rgba(255,255,255,0.06);overflow:hidden;}
  .fill{height:100%;width:0%;border-radius:10px;background:linear-gradient(90deg,rgba(45,212,191,.55),#4fe9d4);box-shadow:0 0 24px rgba(45,212,191,.35);}
  .pct{font-family:ui-monospace,Consolas,monospace;font-size:48px;color:#2dd4bf;text-align:right;font-variant-numeric:tabular-nums;}
  .callout{position:absolute;left:96px;right:110px;top:1420px;font-size:40px;line-height:1.4;color:#c7d7de;}
  .callout b{color:#fff;}
  .rail{position:absolute;left:96px;bottom:210px;width:86px;height:6px;border-radius:3px;background:linear-gradient(90deg,#2dd4bf,#ffce6a);}
  .footer{position:absolute;left:96px;bottom:130px;display:flex;align-items:center;gap:22px;}
  .wordmark{font-weight:800;font-style:italic;text-transform:uppercase;letter-spacing:1px;font-size:40px;color:#fff;}
  .wordmark b{color:#2dd4bf;}
  .handle{font-family:ui-monospace,Consolas,monospace;font-size:28px;color:#637984;letter-spacing:1.5px;}
</style></head><body>
  <div id="glow"></div>
  <div class="pad">
    <div class="eyebrow" data-a>The Proof</div>
    <h1><span class="ln" data-l>We say 80%.</span><span class="ln" data-l>It hits <span class="cy">80%.</span></span></h1>
    <div class="tag" data-a>239,378 graded</div>
    <div class="rows" id="rows"></div>
  </div>
  <div class="callout" data-a>Our confidence predicts the real hit rate. <b>That's math, not marketing.</b></div>
  <div class="rail"></div>
  <div class="footer" data-a><span class="wordmark">Bankroll <b>Kings</b></span><span class="handle">bankrollkings.com</span></div>
  <div class="frame"></div>
<script>
  var BARS=[["90+",89.9],["80-89",83.2],["70-79",72.5],["60-69",61.7],["under 60",36.7]];
  var rows=document.getElementById('rows');
  BARS.forEach(function(b){
    var r=document.createElement('div'); r.className='row';
    r.innerHTML='<span class="tier">'+b[0]+'</span><div class="track"><div class="fill"></div></div><span class="pct">0.0%</span>';
    rows.appendChild(r);
  });
  function clamp(x,a,b){return Math.max(a,Math.min(b,x));}
  function ease(t){t=clamp(t,0,1);return t*t*(3-2*t);}
  function seg(p,s,d){return ease((p-s)/d);}
  function apply(p){
    // ambient glow pulse
    document.getElementById('glow').style.opacity = 0.65+0.35*Math.sin(p*Math.PI*2);
    // eyebrow / tag / callout / footer generic fades
    var eb=document.querySelector('.eyebrow'); var a=seg(p,0.0,0.10);
    eb.style.opacity=a; eb.style.transform='translateY('+((1-a)*24)+'px)';
    var tag=document.querySelector('.tag'); var t2=seg(p,0.16,0.10);
    tag.style.opacity=t2; tag.style.transform='translateY('+((1-t2)*20)+'px)';
    var lines=document.querySelectorAll('[data-l]');
    lines.forEach(function(ln,i){var g=seg(p,0.05+i*0.07,0.16);ln.style.opacity=g;ln.style.transform='translateY('+((1-g)*30)+'px)';});
    var rowsEl=document.querySelectorAll('.row');
    rowsEl.forEach(function(row,i){
      var s=0.26+i*0.10, d=0.26;
      var g=seg(p,s,d);
      var target=BARS[i][1];
      row.style.opacity=seg(p,s-0.03,0.10);
      row.querySelector('.fill').style.width=(target*g)+'%';
      row.querySelector('.pct').textContent=(target*g).toFixed(1)+'%';
    });
    var co=document.querySelector('.callout'); var c=seg(p,0.80,0.14);
    co.style.opacity=c; co.style.transform='translateY('+((1-c)*20)+'px)';
    var ft=document.querySelector('.footer'); var f=seg(p,0.86,0.12);
    ft.style.opacity=f;
  }
  var p=parseFloat(new URLSearchParams(location.search).get('p')||'1');
  apply(p);
</script>
</body></html>'''

def main():
    stem = "vid_calibration"
    (SRC/f"{stem}.html").write_text(HTML, encoding="utf-8")
    fdir = SRC/"vframes";
    if fdir.exists(): shutil.rmtree(fdir)
    fdir.mkdir()
    base = (SRC/f"{stem}.html").resolve().as_uri()
    for i in range(N):
        p = i/(N-1)
        out = (fdir/f"f_{i:04d}.png").resolve()
        subprocess.run([CHROME,"--headless=new","--disable-gpu","--hide-scrollbars",
            "--force-device-scale-factor=1",f"--window-size={W},{H}",
            f"--screenshot={out}", f"{base}?p={p:.5f}"],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
        if i % 24 == 0: print(f"  frame {i}/{N}", flush=True)
    mp4 = (SRC/f"{stem}.mp4").resolve()
    subprocess.run(["ffmpeg","-y","-framerate",str(FPS),"-i",str(fdir/"f_%04d.png"),
        "-c:v","libx264","-pix_fmt","yuv420p","-movflags","+faststart",
        "-vf",f"scale={W}:{H}", str(mp4)],
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
    print("MP4:", mp4, mp4.stat().st_size if mp4.exists() else "FAILED")

main()
