"""Static scan for a price field assigned the literal -110 (the conventional default that was
being shown as a real book price). A real line without a real price is incomplete information,
not a -110 bet -- so production code must never default a price.

Flags, in any tracked .py file, a literal -110 that is:
  * the value of a dict entry whose key names a price/odds field;
  * assigned to a price/odds name, attribute or subscript;
  * passed as a price/odds keyword argument;
  * the default of `.get('<price/odds key>', -110)`;
  * the fallback operand of `or` / a conditional expression on a line naming price/odds.

A test fixture may use -110 only when that exact line carries the marker `# synthetic-fixture`
(an explicit statement that the value is synthetic test data, not production fallback logic).
"""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

FIXTURE_MARKER = '# synthetic-fixture'
PRICE_NAME = re.compile(r'(price|odds)', re.IGNORECASE)


def _is_neg110(node) -> bool:
    if isinstance(node, ast.Constant) and node.value == -110 and not isinstance(node.value, bool):
        return True
    return (isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub)
            and isinstance(node.operand, ast.Constant) and node.operand.value == 110
            and not isinstance(node.operand.value, bool))


def _target_name(t) -> str:
    if isinstance(t, ast.Name):
        return t.id
    if isinstance(t, ast.Attribute):
        return t.attr
    if isinstance(t, ast.Subscript):
        s = t.slice
        if isinstance(s, ast.Constant) and isinstance(s.value, str):
            return s.value
    return ''


def scan_source(src: str, filename: str = '<src>') -> list[tuple[int, str]]:
    """Return [(lineno, kind)] for every fabricated -110 price in `src` (fixture-marked lines excluded)."""
    try:
        tree = ast.parse(src, filename=filename)
    except SyntaxError:
        return []
    lines = src.splitlines()
    hits: list[tuple[int, str]] = []

    def add(node, kind):
        ln = getattr(node, 'lineno', 0)
        text = lines[ln - 1] if 0 < ln <= len(lines) else ''
        if FIXTURE_MARKER not in text:
            hits.append((ln, kind))

    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if (isinstance(k, ast.Constant) and isinstance(k.value, str)
                        and PRICE_NAME.search(k.value) and _is_neg110(v)):
                    add(v, f'dict[{k.value!r}] = -110')
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if node.value is not None and _is_neg110(node.value):
                for t in targets:
                    nm = _target_name(t)
                    if nm and PRICE_NAME.search(nm):
                        add(node.value, f'{nm} = -110')
        elif isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg and PRICE_NAME.search(kw.arg) and _is_neg110(kw.value):
                    add(kw.value, f'{kw.arg}=-110')
            f = node.func
            if (isinstance(f, ast.Attribute) and f.attr in ('get', 'setdefault', 'pop') and len(node.args) >= 2
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
                    and PRICE_NAME.search(node.args[0].value) and _is_neg110(node.args[1])):
                add(node.args[1], f".{f.attr}({node.args[0].value!r}, -110)")
        elif isinstance(node, (ast.BoolOp, ast.IfExp)):
            operands = node.values if isinstance(node, ast.BoolOp) else [node.body, node.orelse]
            if isinstance(node, ast.BoolOp) and not isinstance(node.op, ast.Or):
                continue
            for v in operands:
                if _is_neg110(v):
                    ln = v.lineno
                    text = lines[ln - 1] if 0 < ln <= len(lines) else ''
                    if PRICE_NAME.search(text):
                        add(v, 'fallback -110 on a price/odds line')
    return hits


def scan_repo(root: Path) -> dict[str, list[tuple[int, str]]]:
    """Scan every git-tracked .py file under `root`. Returns {relpath: hits} for files with hits."""
    out = subprocess.run(['git', 'ls-files', '*.py'], cwd=root, capture_output=True, text=True, check=True)
    result = {}
    for rel in out.stdout.split():
        p = root / rel
        try:
            src = p.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            continue
        hits = scan_source(src, rel)
        if hits:
            result[rel.replace('\\', '/')] = hits
    return result
