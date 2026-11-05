"""QC: no rendered surface implies WHO bet (owner decision 2026-11-04: market-movement neutral language).

The product has no licensed bettor-classification, ticket, handle or bet-split data. A line or price move
is a fact about the posted market; it never identifies who placed wagers or why. So no user-rendered text
may say or imply "sharp money", "sharps", "sharp side/action", "steam", "smart money", "wiseguys",
"professional bettors", "pros bet ...", bet splits or "% of bets/handle".

  S  STATIC SCAN of every rendered source:
       templates/**            (Jinja {# comments #} removed -- never sent to the browser)
       static/** text files    (js/css/json/svg/txt/webmanifest/html)
       marketing/**.html       (generated content packs / flyers that are published as images/video)
       Python string constants in app.py, services/**/*.py, marketing/generators/*.py
         -- docstrings and # comments are developer prose, never rendered, so they are excluded
            structurally (AST), not by a per-line waiver.
     ALLOWLIST (below; currently empty) may name only NON-rendered, existing files, each with a written
     justification; the QC fails if an entry points at a rendered location (templates/, static/,
     marketing/**.html), lacks a justification, or does not exist.
  R  RENDER CHECK via the Flask test client, offline, with an isolated in-memory owner principal
     (services.qc_auth -- no user store read/write): /how-we-analyze (signed out AND signed in) and
     /tools/market-movers (movers-only and ?all=1, fed a synthetic in-memory snapshot so the table
     renders on a data-less box). Each page must carry the exact disclaimer sentence and no banned term.
  W  NO WRITES: data/ is fingerprinted (path, size, mtime) before app import and after every check; the
     activity heartbeat and user-store writer are stubbed for the run.
  M  MUTATION PROOFS (temp copies only -- real files are never modified):
       M1 every banned pattern flags a sample phrase;
       M2 a banned phrase injected into a temp copy of market_movers.html is caught by the static scan;
       M3 a banned string constant in a temp .py is caught, while the same words in a docstring/comment
          are not (proves the exclusion is structural);
       M4 a temp how_we_analyze.html with a banned phrase, served ahead of the real template, makes the
          RENDER check fail; a temp copy with the disclaimer removed makes it fail too.
  A  OLD-CAPTION MARKETING ASSETS (follow-up 2026-11-05). Three generated assets still print the retired
     "no fake 'steam'" caption (feature_05 Market Movers card + its two videos). They are archival files
     under marketing/ (not servable). DENYLIST_ASSETS names them (plus the generator intermediates that
     carried the same caption) and pins their SHA-256 so a renamed copy is still recognised.
       A1 REFERENCE CHECK: no template, static JS/CSS/JSON/webmanifest/SVG/HTML (incl. service-worker.js,
          manifest), app.py / services/**.py string constant (routes, url_for('static', ...), sitemap,
          meta/OG tags), or deploy/ nginx config names a denylisted asset;
       A2 LOCATION CHECK: no file under a servable root (static/ -- Flask static + nginx alias; assets/ --
          the /assets/<path> route) has a denylisted name or a denylisted content hash. Walks the disk,
          not just git, so an untracked copy dropped into static/ also fails.
       MA mutation proofs on temp trees: an injected <img src=url_for(static ...)> reference, an injected
          service-worker cache entry, a denylisted name under temp static/, a renamed copy (hash match)
          under temp assets/ -- each is flagged; a clean control tree passes.
     A regenerated asset with the NEW wording must use a new filename (e.g. *_v2.png); the old names stay
     denied so an old-caption file can never be wired in by name.
Exit 0 on pass, 1 otherwise.  Run: py -3 qc_offline.py qc_market_language_bettor_type.py
"""
from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("SECRET_KEY", "qc-market-language-bettor-type")

DISCLAIMER = ("Market movement shows changes in posted lines or prices. It does not identify who placed "
              "wagers or why, and it is not a recommendation.")

_SEP = r"(?:\s|&nbsp;|-)+"
_APOS = r"(?:'|&rsquo;|&#x27;|&#39;|’)"
BANNED = [
    ("sharp money", re.compile(rf"\bsharp{_SEP}money\b", re.I)),
    ("sharps", re.compile(r"\bsharps\b", re.I)),
    ("sharp's", re.compile(rf"\bsharp{_APOS}s\b", re.I)),
    ("sharp side/action/bettor/...", re.compile(
        rf"\bsharp{_SEP}(?:side|action|bettors?|play|plays|book|crowd|report|university|betting|lesson|factors)\b",
        re.I)),
    ("a/the/true sharp", re.compile(rf"\b(?:a|the|true|like{_SEP}a){_SEP}sharp\b(?![\w-])", re.I)),
    ("public vs sharp", re.compile(rf"\bpublic{_SEP}(?:vs\.?|versus|and|or){_SEP}sharp", re.I)),
    ("steam", re.compile(r"\bsteam(?:ed|ing)?\b", re.I)),
    ("smart money", re.compile(rf"\bsmart{_SEP}money\b", re.I)),
    ("wiseguy", re.compile(rf"\bwise(?:{_SEP})?guys?\b", re.I)),
    ("professional bettors", re.compile(rf"\bprofessional{_SEP}(?:bettors?|gamblers?|money|action)\b", re.I)),
    ("pros <verb>", re.compile(rf"\bpros{_SEP}(?:are|bet|bets|do|don{_APOS}?t|know|play|take|fade|hammer)\b", re.I)),
    ("bet split", re.compile(rf"\b(?:bet|betting|ticket|money){_SEP}splits?\b", re.I)),
    ("% of bets/handle", re.compile(r"%\s*of\s+(?:the\s+)?(?:bets|handle|tickets|wagers|money)\b", re.I)),
    ("handle moved", re.compile(rf"\bhandle{_SEP}(?:shifted|moved|split|percentage|share)\b", re.I)),
    ("public money/side", re.compile(rf"\bpublic{_SEP}(?:money|bettors?|side)\b", re.I)),
    ("square money/bettors", re.compile(rf"\bsquare{_SEP}(?:money|bettors?|side)\b", re.I)),
]

# Non-rendered files only. Each entry must be justified; the QC fails if an entry points at a rendered
# location. Python docstrings/comments need no entry (excluded structurally), and qc_*.py / docs/ are not
# in the scanned set at all (QC sources hold negating fixtures; docs/ has no serving route).
# Currently EMPTY: after the 2026-11-04 rewording no scanned non-docstring/non-comment text needs a waiver.
ALLOWLIST: dict[str, str] = {}

RENDERED_PREFIXES = ("templates/", "static/")

# ---- A: old-caption marketing assets (archival; must never be referenced or servable) --------------------
# name -> (sha256 or None, which retired phrase it carries). Hashes taken 2026-11-05 from the archival
# files in the dev checkout; the intermediates are generator scratch outputs (no archived copy -> name only).
DENYLIST_ASSETS = {
    "feature_05_market_movers.png": (
        "4f9e461f5adc46fccd2a2868c5828da7ddf2c17a43cd032e4ecb4e744d7beebe",
        "card text: \"no fake 'steam' labels\" + \"where the market is leaning\" (gen_features.py feature 05)"),
    "feature_05_market_movers.mp4": (
        "32b61637201325e78435f33d38524348ae7badfda91ffa267063b3c88698c2fa",
        "video of the same card: \"no fake 'steam' labels\" (render of gen_features feature 05)"),
    "video_feature_market_movers.mp4": (
        "1bb5bba5a77b6427736aecf48fa94f3859e22a2a9b7ff38d82a4743dca8a9951",
        "animated card: \"no fake 'steam'\" (video_engine.py vid_feat_movers)"),
    "feature_05.png": (None, "gen_features.py scratch render of feature 05 (old wording)"),
    "feature_05.html": (None, "gen_features.py scratch page for feature 05 (old wording)"),
    "vid_feat_movers.mp4": (None, "video_engine.py scratch output for Market Movers (old wording)"),
    "vid_feat_movers.html": (None, "video_engine.py scratch page for Market Movers (old wording)"),
}
# Stills from video_engine.render_still are named vid_feat_movers_vNNN.png.
DENYLIST_NAME_RE = re.compile(r"^vid_feat_movers_v\d{3}\.png$", re.I)
SERVABLE_ROOTS = ("static", "assets")
REF_TEXT_SUFFIXES = {".html", ".htm", ".js", ".css", ".json", ".webmanifest", ".svg", ".txt", ".xml", ".conf"}


def _denied_ref_rx():
    stems = sorted({Path(n).stem for n in DENYLIST_ASSETS} | {Path(n).name for n in DENYLIST_ASSETS}, key=len,
                   reverse=True)
    alts = "|".join(re.escape(s) for s in stems) + r"|vid_feat_movers_v\d{3}"
    # Bounded so 'feature_05' does not match 'feature_051' or 'my_feature_05x'.
    return re.compile(rf"(?<![\w-])(?:{alts})(?![\w-])", re.I)


DENIED_REF_RE = _denied_ref_rx()


def asset_reference_hits(root: Path, files: list[str]):
    """Every reference to a denylisted asset in the given repo-relative text/py files."""
    hits = []
    for rel in files:
        p = root / rel
        if not p.is_file():
            continue
        src = p.read_text(encoding="utf-8", errors="replace")
        if rel.endswith(".py"):
            # Only string constants can become a route/url_for/meta/sitemap value; prose is excluded.
            for ln, val in py_string_constants(src):
                for m in DENIED_REF_RE.finditer(val):
                    hits.append(f"{rel}:{ln} references {m.group(0)!r}")
        else:
            text = template_text(src) if rel.endswith((".html", ".htm")) else src
            for i, line in enumerate(text.splitlines(), 1):
                for m in DENIED_REF_RE.finditer(line):
                    hits.append(f"{rel}:{i} references {m.group(0)!r}")
    return hits


def reference_files(root: Path, use_git: bool = True):
    if use_git:
        allf = tracked("templates", "static", "services", "deploy", "ops", "app.py")
    else:
        allf = [str(p.relative_to(root)).replace(os.sep, "/") for p in root.rglob("*") if p.is_file()]
    out = []
    for rel in allf:
        if rel == "app.py" or (rel.startswith("services/") and rel.endswith(".py")):
            out.append(rel)
        elif rel.startswith(("templates/", "static/", "deploy/", "ops/")) and Path(rel).suffix.lower() in REF_TEXT_SUFFIXES:
            out.append(rel)
    return out


def _sha256(p: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def servable_location_hits(root: Path, denylist: dict):
    """Files on disk under a servable root that carry a denylisted name or content hash."""
    hashes = {v[0]: k for k, v in denylist.items() if v[0]}
    sizes_needed = bool(hashes)
    hits = []
    for top in SERVABLE_ROOTS:
        base = root / top
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            rel = str(p.relative_to(root)).replace(os.sep, "/")
            name = p.name
            if name.lower() in {k.lower() for k in denylist} or DENYLIST_NAME_RE.match(name):
                hits.append(f"{rel}: denylisted name")
                continue
            if sizes_needed:
                try:
                    digest = _sha256(p)
                except OSError:
                    continue
                if digest in hashes:
                    hits.append(f"{rel}: content matches denylisted {hashes[digest]}")
    return hits

TEXT_STATIC = {".js", ".css", ".json", ".svg", ".txt", ".webmanifest", ".html", ".htm"}

FAILS: list[str] = []
OKS: list[str] = []


def check(cond, msg):
    (OKS if cond else FAILS).append(msg)
    return bool(cond)


# ---------------------------------------------------------------- scanning primitives

def banned_hits(text: str):
    out = []
    for name, rx in BANNED:
        for m in rx.finditer(text):
            out.append((name, m.group(0)))
    return out


def template_text(src: str) -> str:
    return re.sub(r"\{#.*?#\}", "", src, flags=re.S)


def py_string_constants(src: str):
    """(lineno, value) for every str constant that is NOT a docstring. Comments are not in the AST."""
    tree = ast.parse(src)
    doc_ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant) \
                    and isinstance(first.value.value, str):
                doc_ids.add(id(first.value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in doc_ids:
            yield getattr(node, "lineno", 0), node.value


def scan_text_file(rel: str, src: str):
    text = template_text(src) if rel.endswith((".html", ".htm", ".jinja", ".j2")) else src
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        for name, frag in banned_hits(line):
            hits.append(f"{rel}:{i} [{name}] {frag!r}")
    return hits


def scan_py_file(rel: str, src: str):
    hits = []
    for ln, val in py_string_constants(src):
        for name, frag in banned_hits(val):
            hits.append(f"{rel}:{ln} [{name}] {frag!r}")
    return hits


def allowlist_violations(allow: dict) -> list[str]:
    bad = []
    for rel, why in allow.items():
        rendered = rel.startswith(RENDERED_PREFIXES) or (rel.startswith("marketing/") and rel.endswith((".html", ".htm")))
        if rendered or not str(why).strip() or not (HERE / rel).exists():
            bad.append(rel)
    return bad


def tracked(*pats):
    out = subprocess.run(["git", "ls-files", *pats], cwd=HERE, capture_output=True, text=True, check=True).stdout
    return [p for p in out.splitlines() if p]


def scan_repo():
    hits = []
    files = 0
    for rel in tracked("templates"):
        files += 1
        hits += scan_text_file(rel, (HERE / rel).read_text(encoding="utf-8", errors="replace"))
    for rel in tracked("static"):
        if Path(rel).suffix.lower() in TEXT_STATIC:
            files += 1
            hits += scan_text_file(rel, (HERE / rel).read_text(encoding="utf-8", errors="replace"))
    for rel in tracked("marketing"):
        if Path(rel).suffix.lower() in (".html", ".htm"):
            files += 1
            hits += scan_text_file(rel, (HERE / rel).read_text(encoding="utf-8", errors="replace"))
    py = ["app.py"] + [p for p in tracked("services") if p.endswith(".py")] \
        + [p for p in tracked("marketing/generators") if p.endswith(".py")]
    for rel in py:
        if rel in ALLOWLIST:
            continue
        files += 1
        hits += scan_py_file(rel, (HERE / rel).read_text(encoding="utf-8", errors="replace"))
    return files, hits


# ---------------------------------------------------------------- no-write fingerprint

def fingerprint(root: Path):
    fp = {}
    if root.exists():
        for p in root.rglob("*"):
            try:
                st = p.stat()
            except OSError:
                continue
            fp[str(p.relative_to(root))] = (p.is_dir(), 0 if p.is_dir() else st.st_size,
                                             0 if p.is_dir() else st.st_mtime_ns)
    return fp


def fp_diff(a, b):
    added = sorted(set(b) - set(a))
    removed = sorted(set(a) - set(b))
    changed = sorted(k for k in set(a) & set(b) if a[k] != b[k])
    return added, removed, changed


# ---------------------------------------------------------------- render check

def synthetic_movers():
    base = {"href": "/sports/mlb", "date": "2026-11-05", "books": 5, "snapshots": 6}
    return [
        dict(base, league="mlb", league_label="MLB", matchup="Away A @ Home A", spread_cur=-1.5,
             spread_move=-1.0, total_cur=8.5, total_move=0.5, ml_move=-12, tier="major", _mag=1.0),
        dict(base, league="mlb", league_label="MLB", matchup="Away B @ Home B", spread_cur=1.5,
             spread_move=0.5, total_cur=9.0, total_move=0.0, ml_move=6, tier="moderate", _mag=0.5),
        dict(base, league="mlb", league_label="MLB", matchup="Away C @ Home C", spread_cur=-1.5,
             spread_move=0.0, total_cur=7.5, total_move=0.0, ml_move=None, tier="stable", _mag=0.0),
    ]


def render_pages(app_mod, isolated_owner_client, unauth_client):
    """{label: (status, html)} for the two surfaces."""
    pages = {}
    app_mod.RUNTIME_TTL_CACHE.pop("market_movers", None)
    real_snapshot = app_mod._build_market_movers_snapshot
    app_mod._build_market_movers_snapshot = synthetic_movers
    try:
        anon = unauth_client()
        r = anon.get("/how-we-analyze")
        pages["/how-we-analyze (signed out)"] = (r.status_code, r.get_data(as_text=True))
        with isolated_owner_client() as c:
            for path in ("/how-we-analyze", "/tools/market-movers", "/tools/market-movers?all=1"):
                r = c.get(path)
                pages[f"{path} (signed in)"] = (r.status_code, r.get_data(as_text=True))
    finally:
        app_mod._build_market_movers_snapshot = real_snapshot
        app_mod.RUNTIME_TTL_CACHE.pop("market_movers", None)
    return pages


def render_failures(pages, require_rows=True):
    fails = []
    for label, (code, html) in pages.items():
        if code != 200:
            fails.append(f"{label}: HTTP {code}")
            continue
        if DISCLAIMER not in html:
            fails.append(f"{label}: disclaimer sentence missing")
        hits = banned_hits(html)
        if hits:
            fails.append(f"{label}: banned bettor-type language {hits[:4]}")
        if require_rows and "market-movers" in label and "Away A @ Home A" not in html:
            fails.append(f"{label}: synthetic mover rows did not render (table path not exercised)")
    return fails


# ---------------------------------------------------------------- main

def main() -> int:
    data_dir = HERE / "data"
    fp_before = fingerprint(data_dir)

    # S: allowlist hygiene + static scan
    bad_allow = allowlist_violations(ALLOWLIST)
    check(not bad_allow, f"S0 allowlist ({len(ALLOWLIST)} entries) names only non-rendered, existing, justified files"
          + ("" if not bad_allow else f" -> {bad_allow}"))
    probe = allowlist_violations({"templates/market_movers.html": "x", "app.py": "", "nope/missing.py": "y"})
    check(len(probe) == 3, f"S0b allowlist guard rejects a rendered path, an unjustified entry and a missing file ({len(probe)}/3)")
    files, hits = scan_repo()
    check(files > 100, f"S1 static scan covered {files} rendered source files")
    check(not hits, "S2 no bettor-type language in rendered sources"
          + ("" if not hits else ":\n      " + "\n      ".join(hits[:40])))
    for rel in ("templates/how_we_analyze.html", "templates/market_movers.html"):
        src = (HERE / rel).read_text(encoding="utf-8")
        check(DISCLAIMER in src, f"S3 {rel} carries the exact disclaimer sentence")

    # A: old-caption marketing assets -- references + servable location
    ref_files = reference_files(HERE)
    check(len(ref_files) > 100 and "static/service-worker.js" in ref_files and "app.py" in ref_files
          and any(f.startswith("deploy/") for f in ref_files),
          f"A0 reference scan covers {len(ref_files)} files (templates, static incl. service worker, app.py, services, deploy)")
    ref_hits = asset_reference_hits(HERE, ref_files)
    check(not ref_hits, "A1 no route/template/static/service-worker/sitemap/meta/nginx reference to an old-caption asset"
          + ("" if not ref_hits else ":\n      " + "\n      ".join(ref_hits[:20])))
    loc_hits = servable_location_hits(HERE, DENYLIST_ASSETS)
    check(not loc_hits, "A2 no old-caption asset (by name or SHA-256) under a servable root (static/, assets/)"
          + ("" if not loc_hits else ":\n      " + "\n      ".join(loc_hits[:20])))
    with tempfile.TemporaryDirectory(prefix="qc_mm_assets_") as tmp:
        t = Path(tmp)
        (t / "templates").mkdir()
        (t / "static" / "img").mkdir(parents=True)
        (t / "assets").mkdir()
        shutil.copy2(HERE / "templates/market_movers.html", t / "templates/market_movers.html")
        shutil.copy2(HERE / "static/service-worker.js", t / "static/service-worker.js")
        (t / "static/img/feature_05_v2.png").write_bytes(b"new-wording-card")
        control_ref = asset_reference_hits(t, reference_files(t, use_git=False))
        control_loc = servable_location_hits(t, DENYLIST_ASSETS)
        check(not control_ref and not control_loc,
              f"MA0 control temp tree (real template + service worker, a *_v2 asset) passes ({control_ref + control_loc})")
        tpl = (t / "templates/market_movers.html").read_text(encoding="utf-8")
        (t / "templates/market_movers.html").write_text(tpl.replace(
            "{% block content %}",
            "{% block content %}<img src=\"{{ url_for('static', filename='img/feature_05_market_movers.png') }}\">", 1),
            encoding="utf-8")
        got = asset_reference_hits(t, reference_files(t, use_git=False))
        check(any("market_movers.html" in h and "feature_05_market_movers" in h for h in got),
              f"MA1 injected url_for('static') <img> of the old card is flagged ({got[:2]})")
        (t / "templates/market_movers.html").write_text(tpl, encoding="utf-8")
        sw = (t / "static/service-worker.js").read_text(encoding="utf-8")
        (t / "static/service-worker.js").write_text(sw + "\nconst EXTRA = ['/static/video_feature_market_movers.mp4'];\n",
                                                   encoding="utf-8")
        got = asset_reference_hits(t, reference_files(t, use_git=False))
        check(any("service-worker.js" in h for h in got), f"MA2 injected service-worker cache entry is flagged ({got[:2]})")
        (t / "static/service-worker.js").write_text(sw, encoding="utf-8")
        (t / "static/img/feature_05_market_movers.png").write_bytes(b"old")
        (t / "static/img/vid_feat_movers_v050.png").write_bytes(b"old-still")
        got = servable_location_hits(t, DENYLIST_ASSETS)
        check(sum("denylisted name" in h for h in got) == 2,
              f"MA3 denylisted names dropped under temp static/ are flagged ({got})")
        (t / "static/img/feature_05_market_movers.png").unlink()
        (t / "static/img/vid_feat_movers_v050.png").unlink()
        (t / "assets/innocent_name.png").write_bytes(b"pretend-old-caption-bytes")
        fake = dict(DENYLIST_ASSETS)
        fake["feature_05_market_movers.png"] = (_sha256(t / "assets/innocent_name.png"), "mutation stand-in")
        got = servable_location_hits(t, fake)
        check(len(got) == 1 and "content matches" in got[0],
              f"MA4 a renamed copy under temp assets/ is caught by content hash ({got})")
        check(not servable_location_hits(t, DENYLIST_ASSETS),
              "MA5 the same renamed file is NOT flagged without a hash match (no false positive by location alone)")

    # R: render
    import app as app_mod  # noqa: E402
    from services.qc_auth import isolated_owner_client, unauth_client  # noqa: E402
    # app import itself does JINJA_CACHE_DIR.mkdir(data/cache/jinja) -- an app side effect, not this QC's.
    # Record which (empty) directories that created so they can be removed again, and turn the on-disk
    # Jinja bytecode cache off so rendering writes no .cache files into data/.
    import_created = [k for k in fingerprint(data_dir) if k not in fp_before]
    orig_bcc = app_mod.app.jinja_env.bytecode_cache
    app_mod.app.jinja_env.bytecode_cache = None
    orig_heartbeat, orig_save = app_mod.record_active_user, app_mod.save_user
    saves = []
    app_mod.record_active_user = lambda *a, **k: None
    app_mod.save_user = lambda *a, **k: saves.append(a)
    try:
        pages = render_pages(app_mod, isolated_owner_client, unauth_client)
        rf = render_failures(pages)
        for label in pages:
            mine = [f for f in rf if f.startswith(label + ":")]
            check(not mine, f"R1 {label}: 200, disclaimer present, no banned term"
                  + ("" if not mine else " -> " + "; ".join(mine)))
        check(len(pages) == 4, f"R2 rendered {len(pages)}/4 page variants")

        # M1: every pattern flags a sample
        samples = {
            "sharp money": "Sharp money hit the over", "sharps": "the sharps faded it",
            "sharp's": "The Sharp&rsquo;s checklist", "sharp side/action/bettor/...": "follow the Sharp Side",
            "a/the/true sharp": "bet like a sharp", "public vs sharp": "public vs sharp split",
            "steam": "late steam on the under", "smart money": "where the smart money went",
            "wiseguy": "wiseguys loved it", "professional bettors": "professional bettors took the dog",
            "pros <verb>": "pros bet the under", "bet split": "see the bet splits",
            "% of bets/handle": "72% of bets on the over", "handle moved": "handle shifted toward over",
            "public money/side": "public money on the favorite", "square money/bettors": "square bettors on the over",
        }
        missing = [n for n, _ in BANNED if not any(nm == n for nm, _ in banned_hits(samples.get(n, "")))]
        check(not missing and len(samples) == len(BANNED), f"M1 every banned pattern ({len(BANNED)}) flags its sample"
              + ("" if not missing else f" -> unflagged {missing}"))
        clean = ["sharpest number available", "reads sharpen over the day", "a sharp drop-off"]
        # 'a sharp drop-off' is deliberately flagged (conservative); the first two must stay clean.
        check(not banned_hits(clean[0]) and not banned_hits(clean[1]),
              "M1b price-accuracy wording ('sharpest number', 'sharpen') is not flagged")

        with tempfile.TemporaryDirectory(prefix="qc_mm_lang_") as tmp:
            tmpd = Path(tmp)
            # M2: static scan catches an injected phrase in a temp template copy
            src = (HERE / "templates/market_movers.html").read_text(encoding="utf-8")
            check(not scan_text_file("tmp/market_movers.html", src), "M2a unmodified temp copy scans clean")
            bad = src.replace("<strong>How to read this:</strong>",
                              "<strong>How to read this:</strong> Sharp money hit this side.", 1)
            (tmpd / "market_movers.html").write_text(bad, encoding="utf-8")
            got = scan_text_file("tmp/market_movers.html", (tmpd / "market_movers.html").read_text(encoding="utf-8"))
            check(any("sharp money" in h for h in got), f"M2b injected 'Sharp money' in a temp template is flagged ({len(got)} hit)")
            jinja_only = src + "\n{# sharp money: developer note #}\n"
            check(not scan_text_file("tmp/x.html", jinja_only), "M2c a Jinja comment (never rendered) is not flagged")

            # M3: python constants vs docstrings/comments
            py_bad = 'def f():\n    """Never say sharp money."""\n    # steam\n    return "follow the smart money"\n'
            got = scan_py_file("tmp/x.py", py_bad)
            check(len(got) == 1 and "smart money" in got[0],
                  f"M3 rendered string constant flagged; docstring + comment not ({got})")

            # M4: render check fails on a mutated how_we_analyze.html served ahead of the real one
            from jinja2 import ChoiceLoader, FileSystemLoader
            hwa = (HERE / "templates/how_we_analyze.html").read_text(encoding="utf-8")
            orig_loader = app_mod.app.jinja_env.loader

            def render_with(tpl_text):
                (tmpd / "how_we_analyze.html").write_text(tpl_text, encoding="utf-8")
                app_mod.app.jinja_env.loader = ChoiceLoader([FileSystemLoader(str(tmpd)), orig_loader])
                app_mod.app.jinja_env.cache.clear()
                try:
                    r = unauth_client().get("/how-we-analyze")
                    return render_failures({"/how-we-analyze (mutant)": (r.status_code, r.get_data(as_text=True))},
                                           require_rows=False)
                finally:
                    app_mod.app.jinja_env.loader = orig_loader
                    app_mod.app.jinja_env.cache.clear()

            injected = hwa.replace(DISCLAIMER, DISCLAIMER + " Follow the sharps and the steam.", 1)
            f1 = render_with(injected)
            check(any("banned" in f for f in f1), f"M4a render check FAILS on injected bettor-type text ({f1})")
            f2 = render_with(hwa.replace(DISCLAIMER, "Movement is just movement.", 1))
            check(any("disclaimer sentence missing" in f for f in f2), f"M4b render check FAILS when the disclaimer is removed ({f2})")
            f3 = render_with(hwa)
            check(not f3, f"M4c control: the real template text through the same override passes ({f3})")
        check(app_mod.app.jinja_env.loader is orig_loader, "M4d jinja loader restored")
    finally:
        app_mod.record_active_user, app_mod.save_user = orig_heartbeat, orig_save
        app_mod.app.jinja_env.bytecode_cache = orig_bcc
    check(not saves, "W1 nothing written to the user store")

    # W: no writes into data/. Directories the app import created are removed only if still empty
    # (deepest first); anything else new or changed is a failure.
    for rel in sorted(import_created, key=lambda s: -s.count(os.sep)):
        p = data_dir / rel
        if p.is_dir() and not any(p.iterdir()):
            p.rmdir()
    added, removed, changed = fp_diff(fp_before, fingerprint(data_dir))
    check(not (added or removed or changed),
          f"W2 data/ untouched (added={added[:5]} removed={removed[:5]} changed={changed[:5]})")

    print("=" * 64)
    print("BANKROLL KINGS MARKET LANGUAGE (BETTOR-TYPE) QC")
    print("=" * 64)
    for m in OKS:
        print(f"[OK] {m}")
    for m in FAILS:
        print(f"[FAIL] {m}")
    print(f"\n{len(OKS)}/{len(OKS) + len(FAILS)} checks passed")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    raise SystemExit(main())
