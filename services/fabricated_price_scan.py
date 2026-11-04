"""Static scan for the conventional -110 price default in any form. A real line without a real
price is incomplete information, not a -110 bet -- so tracked code must never carry a -110 value
except as explicitly marked synthetic test data.

Flags, in any git-tracked .py file, every expression equivalent to -110:
  * numeric literals: -110, -110.0, (-110), -(110), - 110.0;
  * strings whose whole value is the number: "-110", "-110.0", "−110" (Unicode minus);
  * conversions of those: Decimal("-110"), float("-110"), int(-110), Fraction(-110), -Decimal(110),
    np.float64(-110), ...;
  * constants: a name bound (module/class/function level, incl. annotated and helper/function
    defaults) to a -110 equivalent, every later load of that name, and `-NAME` where NAME is bound
    to 110;
  * helper defaults: def f(price=-110), lambda price=-110: ..., .get('price', -110), x or -110.
Field names do not matter -- a -110 is flagged wherever it appears.

A test fixture may carry -110 only when that exact line ends with the marker `# synthetic-fixture`
(an explicit statement that the value is synthetic test data, not production fallback logic).
Not values, so not flagged: text that merely MENTIONS -110 inside a longer string/docstring/comment;
a -110 string that is the SEARCHED-FOR left operand of `in` / `not in` (e.g. `'-110' not in html`,
a check for its absence). This module is exempt from its own scan (SELF) -- its constants define
what to look for.
"""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

FIXTURE_MARKER = '# synthetic-fixture'
SELF = 'services/fabricated_price_scan.py'
_NUM_STRINGS = {'-110', '-110.0', '-110.00', '−110', '−110.0'}
_POS_STRINGS = {'110', '110.0', '+110'}
_CONVERTERS = {'Decimal', 'float', 'int', 'Fraction', 'float64', 'float32', 'int64', 'int32', 'str'}


def _call_name(node) -> str:
    f = node.func
    return f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else '')


def _is_pos110(node, pos_names) -> bool:
    if isinstance(node, ast.Constant) and not isinstance(node.value, bool):
        v = node.value
        if isinstance(v, (int, float)) and v == 110:
            return True
        if isinstance(v, str) and v.strip() in _POS_STRINGS:
            return True
    if isinstance(node, ast.Name) and node.id in pos_names:
        return True
    if isinstance(node, ast.Call) and _call_name(node) in _CONVERTERS and len(node.args) == 1:
        return _is_pos110(node.args[0], pos_names)
    return False


def _is_neg110(node, neg_names=frozenset(), pos_names=frozenset()) -> bool:
    if isinstance(node, ast.Constant) and not isinstance(node.value, bool):
        v = node.value
        if isinstance(v, (int, float)) and v == -110:
            return True
        if isinstance(v, str) and v.strip() in _NUM_STRINGS:
            return True
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return _is_pos110(node.operand, pos_names)
    if isinstance(node, ast.Call) and _call_name(node) in _CONVERTERS and len(node.args) == 1:
        return _is_neg110(node.args[0], neg_names, pos_names)
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in neg_names:
        return True
    return False


def _bound_names(tree):
    """Names assigned a +/-110 equivalent anywhere (constants and helper defaults)."""
    neg, pos = set(), set()
    for _ in range(3):  # tiny fixpoint: A = -110; B = A
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in targets:
                    if isinstance(t, ast.Name):
                        if _is_neg110(node.value, neg, pos):
                            neg.add(t.id)
                        elif _is_pos110(node.value, pos):
                            pos.add(t.id)
    return frozenset(neg), frozenset(pos)


def scan_source(src: str, filename: str = '<src>') -> list[tuple[int, str]]:
    """Return [(lineno, kind)] for every -110 equivalent in `src` (fixture-marked lines excluded)."""
    try:
        tree = ast.parse(src, filename=filename)
    except SyntaxError:
        return []
    lines = src.splitlines()
    neg, pos = _bound_names(tree)
    hits: list[tuple[int, str]] = []
    seen_lines: set[int] = set()

    def add(node, kind):
        ln = getattr(node, 'lineno', 0)
        text = lines[ln - 1] if 0 < ln <= len(lines) else ''
        if FIXTURE_MARKER in text or ln in seen_lines:
            return
        seen_lines.add(ln)
        hits.append((ln, kind))

    searched = {id(n.left) for n in ast.walk(tree)
                if isinstance(n, ast.Compare) and n.ops and isinstance(n.ops[0], (ast.In, ast.NotIn))
                and isinstance(n.left, ast.Constant) and isinstance(n.left.value, str)}
    for node in ast.walk(tree):
        if id(node) in searched:
            continue
        if _is_neg110(node, neg, pos):
            if isinstance(node, ast.Name):
                add(node, f'name {node.id} bound to -110')
            elif isinstance(node, ast.Call):
                add(node, f'{_call_name(node)}(...) == -110')
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                add(node, f'string {node.value!r}')
            else:
                add(node, 'literal -110')
    return sorted(hits)


# ---------------------------------------------------------------- invented bookmaker attribution
# A real number attributed to a bookmaker the feed never named is false market provenance. These
# shapes substitute a sportsbook name when the source is missing; the honest label is
# 'Unrecorded source'. Input placeholders and provider-request parameters (which books to FETCH)
# are not attributions and do not match.
_BOOKS = (r'DraftKings|FanDuel|BetMGM|Caesars|Bovada|ESPN ?BET|BetRivers|PointsBet|Pinnacle|BetOnline|'
          r'Fanatics|Hard ?Rock|bet365|MyBookie|LowVig|Unibet|WynnBET|Barstool|SuperBook|BetUS')
_BOOK_FALLBACK = re.compile(
    r"""(?ix)
    (?:\bor\s+|\|\|\s*|\?\?\s*|\|\s*default\(\s*|fillna\(\s*)['"](?:%(b)s)['"]      # x or 'Book' / x || 'Book' / |default('Book')
    | \.get\(\s*['"]book(?:maker)?['"]\s*,\s*['"](?:%(b)s)['"]                       # .get('Book', 'Book')
    | \[\s*['"]book(?:maker)?['"]\s*\]\s*=\s*['"](?:%(b)s)['"]                      # df['Book'] = 'Book'
    | \bbook(?:maker)?\s*=\s*['"](?:%(b)s)['"]                                       # book='Book' default
    """ % {'b': _BOOKS})
_BOOK_SCAN_EXCLUDE = ('qc_', 'research/', 'marketing/', '_attic/')


def scan_book_text(text: str) -> list[tuple[int, str]]:
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        if FIXTURE_MARKER in line or 'placeholder=' in line:
            continue
        m = _BOOK_FALLBACK.search(line)
        if m:
            hits.append((i, m.group(0).strip()))
    return hits


def scan_book_fallbacks(root: Path) -> dict[str, list[tuple[int, str]]]:
    """Invented-bookmaker fallbacks in tracked production code + templates + JS."""
    out = subprocess.run(['git', 'ls-files', '*.py', '*.html', '*.js'], cwd=root, capture_output=True,
                         text=True, check=True)
    result = {}
    for rel in out.stdout.split():
        r = rel.replace('\\', '/')
        if r == SELF or any(r.startswith(x) or ('/' + x) in r for x in _BOOK_SCAN_EXCLUDE):
            continue
        try:
            text = (root / rel).read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            continue
        hits = scan_book_text(text)
        if hits:
            result[r] = hits
    return result


def scan_repo(root: Path) -> dict[str, list[tuple[int, str]]]:
    """Scan every git-tracked .py file under `root`. Returns {relpath: hits} for files with hits."""
    out = subprocess.run(['git', 'ls-files', '*.py'], cwd=root, capture_output=True, text=True, check=True)
    result = {}
    for rel in out.stdout.split():
        if rel.replace('\\', '/') == SELF:
            continue
        p = root / rel
        try:
            src = p.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            continue
        hits = scan_source(src, rel)
        if hits:
            result[rel.replace('\\', '/')] = hits
    return result
