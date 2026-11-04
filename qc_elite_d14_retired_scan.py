"""Static scan (adversarial): retired D14 fields / phrases can never reappear on user-rendered surfaces.

Owner D14 final decision (2026-11-04). Scanned code: app.py, services/**/*.py (string constants only -- comments
and docstrings are developer prose, never rendered), templates/** (text with Jinja comments removed),
static/** (js/css/html/svg/json). No file under docs/ is rendered to users (no route serves docs/*.md), so docs
are developer records and out of scope.

  R1 everywhere scanned: no `WINDOW CLOSING`; no `sharp_side` / `SharpSide` except the ONE read-only legacy
     archive column name marked `# legacy-column-migration`; no `sharp money` / `sharp-money` / `sharp_money`
     except an explicit negation disclaimer ("never claim ..." / "do not label ...").
  R2 everywhere scanned: `ACT` never appears as a label value (a Python string constant exactly "ACT", or a
     template/static `>ACT<` / `'ACT'` / `"ACT"`).
  R3 D14 surfaces only (the live line-movement scanner card, the matchup-builder line-movement card, the alert
     history block, the alert export/migration/persist/history code, services/elite_live_labels.py, the
     Elite preview copy and the "Reading Line Movement" learning module): no `Start with` guidance, no
     ANCHOR / WATCH / AVOID badge words, no score/confidence surfaced.
  R4 no combined ordering: the scanner and the label module never sort by a composite score, and no single sort
     key mixes the line unit and the price unit (line and price are separate explicit sorts).
  R5 the alert archive schema carries none of the retired columns (Urgency, Score, Reliability, TrueProb,
     OverMove, UnderMove, the legacy side column) -- they are migration inputs only.
  M  mutation self-test: every rule FLAGS an injected violation (so a green scan is meaningful).
Exit 0 on pass, 1 otherwise.
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("SECRET_KEY", "qc-elite-d14-scan")

FAILS: list[str] = []
NOTES: list[str] = []
MARKER = "# legacy-column-migration"
WINDOW_RE = re.compile(r"window\s+closing", re.I)
SIDE_RE = re.compile(r"sharp_side|SharpSide", re.I)
MONEY_RE = re.compile(r"sharp[\s_\-]+money", re.I)
NEGATION_RE = re.compile(r"never claim|do not label|don&rsquo;t label|we never", re.I)
ACT_TPL_RE = re.compile(r">\s*ACT\s*<|['\"]ACT['\"]")
START_RE = re.compile(r"\bstart with\b", re.I)
TIER_RE = re.compile(r"\b(ANCHOR|WATCH|AVOID)\b")
SCORE_RE = re.compile(r"\b(score|confidence)\b", re.I)


def check(cond, msg):
    (NOTES if cond else FAILS).append(msg)


def tracked(*pats):
    out = subprocess.run(["git", "ls-files", *pats], cwd=HERE, capture_output=True, text=True, check=True).stdout
    return [p for p in out.split() if p]


def py_strings(src: str):
    """(lineno, text, line) for every string constant that is NOT a docstring."""
    tree = ast.parse(src)
    doc_ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant) \
                    and isinstance(first.value.value, str):
                doc_ids.add(id(first.value))
    lines = src.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in doc_ids:
            ln = getattr(node, "lineno", 0)
            yield ln, node.value, lines[ln - 1] if 0 < ln <= len(lines) else ""


def template_text(src: str) -> str:
    return re.sub(r"\{#.*?#\}", "", src, flags=re.S)


def scan_global(sources: dict) -> list[str]:
    """R1 + R2 over {relpath: source}."""
    hits = []
    for rel, src in sources.items():
        if rel.endswith(".py"):
            for ln, text, line in py_strings(src):
                if WINDOW_RE.search(text):
                    hits.append(f"R1 {rel}:{ln} WINDOW CLOSING")
                if SIDE_RE.search(text) and MARKER not in line:
                    hits.append(f"R1 {rel}:{ln} retired side field")
                if MONEY_RE.search(text) and not NEGATION_RE.search(text):
                    hits.append(f"R1 {rel}:{ln} sharp money")
                if text.strip() == "ACT":
                    hits.append(f"R2 {rel}:{ln} ACT label")
        else:
            text = template_text(src)
            for i, line in enumerate(text.splitlines(), 1):
                if WINDOW_RE.search(line):
                    hits.append(f"R1 {rel}:{i} WINDOW CLOSING")
                if SIDE_RE.search(line):
                    hits.append(f"R1 {rel}:{i} retired side field")
                if MONEY_RE.search(line) and not NEGATION_RE.search(line):
                    hits.append(f"R1 {rel}:{i} sharp money")
                if ACT_TPL_RE.search(line):
                    hits.append(f"R2 {rel}:{i} ACT label")
    return hits


D14_TEMPLATE_BLOCKS = (
    ("templates/elite_dashboard.html", "Line Movement Scanner", "clv-report-card"),
    ("templates/elite_dashboard.html", "Recent Alerts", "Best-Book Shopping Board"),
    ("templates/elite_matchup_builder.html", "Line Movement In This Game", "Best-Book Edges"),
)
D14_APP_FUNCS = ("build_elite_line_move_scanner", "annotate_elite_line_moves", "migrate_elite_alert_frame",
                 "elite_alert_export_frame", "elite_alert_history_row", "persist_elite_line_move_alerts",
                 "_elite_alert_id", "build_elite_alert_history_summary")


_FUNC_CACHE: dict = {}


def _func_srcs(app_src: str) -> dict:
    """{name: source} for the D14 app functions -- located by a cheap text scan of top-level `def` lines (app.py
    is ~50k lines; one full AST parse per mutation would take minutes)."""
    key = hash(app_src)
    if key in _FUNC_CACHE:
        return _FUNC_CACHE[key]
    lines = app_src.splitlines()
    starts = [i for i, l in enumerate(lines) if l.startswith(("def ", "class ", "@")) or
              (l and not l[0].isspace() and not l.startswith(("#", ")", "]", "}")))]
    out = {}
    for name in D14_APP_FUNCS:
        i = next((k for k, l in enumerate(lines) if l.startswith(f"def {name}(")), None)
        if i is None:
            out[name] = ""
            continue
        j = next((k for k in starts if k > i), len(lines))
        out[name] = "\n".join(lines[i:j])
    _FUNC_CACHE[key] = out
    return out


def _func_src(app_src: str, name: str) -> str:
    return _func_srcs(app_src).get(name, "")


def _code_strings(src: str) -> str:
    try:
        return "\n".join(t for _ln, t, _l in py_strings(src))
    except SyntaxError:
        return src


def scan_d14(app_src: str, tpl: dict, labels_src: str, preview_text: str, learn_text: str) -> list[str]:
    """R3 + R4 over the D14 surfaces."""
    hits = []
    for rel, start, end in D14_TEMPLATE_BLOCKS:
        full = template_text(tpl[rel])
        i = full.find(start)
        block = full[i:full.find(end, i)] if i >= 0 else ""
        if not block:
            hits.append(f"R3 {rel}: block {start!r} not found")
        for word, rx in (("Start with", START_RE), ("tier badge", TIER_RE), ("score/confidence", SCORE_RE)):
            if rx.search(block):
                hits.append(f"R3 {rel} [{start}] {word}")
    for fn in D14_APP_FUNCS:
        src = _func_src(app_src, fn)
        if not src:
            hits.append(f"R3 app.py:{fn} missing")
            continue
        strings = _code_strings(src)
        for word, rx in (("Start with", START_RE), ("tier badge", TIER_RE)):
            if rx.search(strings):
                hits.append(f"R3 app.py:{fn} {word}")
        if re.search(r"['\"]score['\"]|['\"]Score['\"]|\.score\b", src):
            hits.append(f"R4 app.py:{fn} composite score")
    lab = _code_strings(labels_src)
    for word, rx in (("Start with", START_RE), ("tier badge", TIER_RE)):
        if rx.search(lab):
            hits.append(f"R3 services/elite_live_labels.py {word}")
    if re.search(r"['\"]score['\"]", labels_src):
        hits.append("R4 services/elite_live_labels.py composite score")
    for name, text in (("Elite preview", preview_text), ("learning module", learn_text)):
        for word, rx in (("Start with", START_RE), ("tier badge", TIER_RE), ("sharp", re.compile("sharp", re.I)),
                         ("WINDOW CLOSING", WINDOW_RE)):
            if rx.search(text):
                hits.append(f"R3 {name} {word}")
    # R4: no single sort key mixes the two units
    tree = ast.parse(labels_src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in ("neutral_sort_key", "_size_key"):
            body = list(node.body)
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
                body = body[1:]   # the docstring is prose, not the key
            seg = chr(10).join(ast.unparse(b) for b in body)
            if ("line" in seg and "price" in seg) or "score" in seg:
                hits.append(f"R4 services/elite_live_labels.py:{node.name} mixes units / scores")
    return hits


def main() -> int:
    import app
    sources = {}
    for rel in ["app.py"] + tracked("services/*.py") + tracked("templates/*") + tracked("static/*"):
        rel = rel.replace("\\", "/")
        if not rel.endswith((".py", ".html", ".js", ".css", ".svg", ".json", ".txt")):
            continue
        try:
            sources[rel] = (HERE / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
    g = scan_global(sources)
    check(not g, f"R1/R2 no WINDOW CLOSING / retired side field / sharp money / ACT label on any rendered "
                 f"surface ({len(sources)} files scanned) {g[:6]}")
    side_marked = [l for l in sources["app.py"].splitlines() if SIDE_RE.search(l)]
    check(len(side_marked) == 1 and MARKER in side_marked[0],
          f"R1 exactly one marked legacy side-column literal remains (migration input) ({len(side_marked)})")
    tpl = {rel: sources[rel] for rel, _s, _e in D14_TEMPLATE_BLOCKS}
    prev = app.GLOBAL_FEATURE_PREVIEWS.get("elite", {})
    preview_text = " ".join([str(prev.get("preview_copy")), str(prev.get("subtitle"))] +
                            [" ".join(x) for x in prev.get("steps", [])])
    learn = next((m for m in app.build_elite_learning_modules() if m.get("slug") == "line-movement"), {})
    learn_text = " ".join(str(v) for v in learn.values())
    labels_src = sources["services/elite_live_labels.py"]
    d = scan_d14(sources["app.py"], tpl, labels_src, preview_text, learn_text)
    check(not d, f"R3/R4 D14 surfaces: no 'Start with', no ANCHOR/WATCH/AVOID badges, no score, no mixed-unit "
                 f"ordering {d[:6]}")
    retired = {"Urgency", "Score", "Reliability", "TrueProb", "OverMove", "UnderMove", "SharpSide"}
    check(not retired & set(app.ELITE_ALERT_COLUMNS) and set(app.ELITE_ALERT_RETIRED_COLUMNS) == retired,
          "R5 alert archive schema has none of the retired columns; they exist only as migration inputs")
    check(not hasattr(app, "build_elite_" + "sharp_money_scanner"), "R5 the retired scanner name is gone")

    # ---- M: mutation self-test -- every rule must FLAG an injected violation
    muts = [
        ("app.py", "\nX_LABEL = 'WINDOW CLOSING'\n", "R1 WINDOW CLOSING (py)"),
        ("app.py", "\nrow = {'sharp_side': 'OVER'}\n", "R1 sharp_side (py)"),
        ("services/elite_live_labels.py", "\nCOPY = 'Sharp money came in.'\n", "R1 sharp money (services)"),
        ("app.py", "\nurgency = 'ACT'\n", "R2 ACT label (py)"),
        ("templates/elite_dashboard.html", "\n<span class=\"badge\">ACT</span>\n", "R2 ACT badge (template)"),
        ("templates/info.html", "\n<div>Sharp Money moved this line.</div>\n", "R1 sharp money (template)"),
        ("templates/elite_matchup_builder.html", "\n<td>{{ row.SharpSide }}</td>\n", "R1 SharpSide (template)"),
    ]
    for rel, inj, label in muts:
        src = (sources[rel] if not rel.endswith(".py") else "") + inj   # a .py mutant is scanned as the injected
        check(scan_global({rel: src}), f"M mutant ({label}) is FLAGGED")  # module (same rules, no 50k-line re-parse)
    ok_disclaimer = {"templates/info.html": sources["templates/info.html"] +
                     "\n<p>We never claim to see &ldquo;sharp money&rdquo; we can&rsquo;t observe.</p>\n"}
    check(not scan_global(ok_disclaimer), "M an explicit negation disclaimer is not a violation")
    d14_muts = [
        ("templates/elite_dashboard.html", "Line Movement Scanner", "Line Movement Scanner<div>Start with the biggest move</div>",
         "R3 Start with (scanner card)"),
        ("templates/elite_dashboard.html", "Line Movement Scanner", "Line Movement Scanner<span class=\"badge\">ANCHOR</span>",
         "R3 ANCHOR badge (scanner card)"),
        ("templates/elite_matchup_builder.html", "Line Movement In This Game",
         "Line Movement In This Game<span>{{ row.score }} score</span>", "R3 score (matchup card)"),
        ("templates/elite_dashboard.html", "Recent Alerts", "Recent Alerts<span class=\"badge\">WATCH</span>",
         "R3 WATCH badge (history block)"),
    ]
    for rel, anchor, repl, label in d14_muts:
        t2 = dict(tpl)
        t2[rel] = tpl[rel].replace(anchor, repl, 1)
        check(scan_d14(sources["app.py"], t2, labels_src, preview_text, learn_text), f"M mutant ({label}) is FLAGGED")
    app_mut = sources["app.py"].replace("def build_elite_line_move_scanner(candidates):",
                                        "def build_elite_line_move_scanner(candidates):\n    _k = 'AVOID'", 1)
    check(scan_d14(app_mut, tpl, labels_src, preview_text, learn_text), "M mutant (AVOID inside the scanner) is FLAGGED")
    app_mut2 = sources["app.py"].replace("def build_elite_line_move_scanner(candidates):",
                                         "def build_elite_line_move_scanner(candidates):\n    _o = sorted([], key=lambda r: r['score'])", 1)
    check(scan_d14(app_mut2, tpl, labels_src, preview_text, learn_text), "M mutant (score ordering in the scanner) is FLAGGED")
    lab_mut = labels_src.replace("def neutral_sort_key(row, now=None):",
                                 "def neutral_sort_key(row, now=None):\n    _mix = (row.get('line_delta'), row.get('over_price_delta_cents'))", 1)
    check(scan_d14(sources["app.py"], tpl, lab_mut, preview_text, learn_text),
          "M mutant (one sort key mixing line + price units) is FLAGGED")
    check(scan_d14(sources["app.py"], tpl, labels_src, preview_text + " Start with the alerts", learn_text),
          "M mutant ('Start with' in the Elite preview) is FLAGGED")
    check(scan_d14(sources["app.py"], tpl, labels_src, preview_text, learn_text + " sharp side"),
          "M mutant ('sharp' in the learning module) is FLAGGED")

    print("=" * 64)
    print("QC: ELITE D14 RETIRED FIELDS / PHRASES (static, adversarial)")
    print("=" * 64)
    for n in NOTES:
        print(f"[OK]   {n}")
    for f in FAILS:
        print(f"[FAIL] {f}")
    print(f"\n{len(NOTES)} passed, {len(FAILS)} failed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
