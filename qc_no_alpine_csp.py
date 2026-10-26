"""QC: Alpine.js removed + CSP cleaned (Decision 1 — NBA P0 F13 fix).

The only Alpine component was the bet-slip's three visual tab buttons in bk_base.html; it is replaced by
a CSP-safe vanilla tablist. This QC proves: (1) no Alpine directives remain in any template; (2) no
unpkg.com reference remains (templates or CSP); (3) the CSP script-src contains neither unpkg nor
'unsafe-eval'; (4) the vanilla tablist markup + selector are present (initial active, aria-selected,
roving tabindex, click + keyboard). Actual tab-state behavior is verified in-browser.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TPL = os.path.join(HERE, 'templates')
fails = []


def check(cond, msg):
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        fails.append(msg)


# Alpine attribute tokens (as they appear in HTML): component root, directives, and the shorthand
# bindings (:x=) / event handlers (@x=). Matched as attributes to avoid CSS/URL false positives.
ALPINE_PATTERNS = [
    r'\bx-data\b', r'\bx-show\b', r'\bx-bind\b', r'\bx-init\b', r'\bx-text\b', r'\bx-html\b',
    r'\bx-for\b', r'\bx-if\b', r'\bx-model\b', r'\bx-on:', r'\bx-transition\b', r'\bx-ref\b',
    r'\s@[a-z]+(?:\.[a-z]+)*\s*=', r'\s:[a-z-]+\s*=',
]


def _html_files():
    for root, _dirs, files in os.walk(TPL):
        for f in files:
            if f.endswith('.html'):
                yield os.path.join(root, f)


def test_no_alpine_directives():
    print("\n[A] no Alpine directives remain in any template")
    hits = []
    for path in _html_files():
        src = open(path, encoding='utf-8').read()
        for pat in ALPINE_PATTERNS:
            for m in re.finditer(pat, src):
                hits.append((os.path.relpath(path, HERE), pat, src[max(0, m.start() - 20):m.start() + 20]))
    if hits:
        for h in hits[:20]:
            print("      hit:", h)
    check(not hits, "zero Alpine directives (x-*, @event=, :bind=) across all templates (%d found)" % len(hits))


def test_no_unpkg():
    print("\n[B] no unpkg.com reference remains")
    offenders = []
    for path in list(_html_files()) + [os.path.join(HERE, 'app.py')]:
        if 'unpkg' in open(path, encoding='utf-8').read():
            offenders.append(os.path.relpath(path, HERE))
    check(not offenders, "no 'unpkg' in templates or app.py (offenders: %r)" % offenders)


def test_csp_clean():
    print("\n[C] CSP script-src has neither unpkg nor 'unsafe-eval'")
    src = open(os.path.join(HERE, 'app.py'), encoding='utf-8').read()
    m = re.search(r'"script-src ([^"]*)"', src)
    check(m is not None, "found the script-src directive in the CSP")
    directive = m.group(1) if m else ''
    check("script-src 'self' 'unsafe-inline';" in src, "script-src is exactly 'self' 'unsafe-inline' (%r)" % directive)
    check('unpkg' not in directive, "script-src does not allow unpkg")
    check('unsafe-eval' not in src.split('apply_security_headers', 1)[-1][:1200],
          "CSP never adds 'unsafe-eval'")


def test_vanilla_tablist():
    print("\n[D] bet-slip vanilla tablist markup + selector present")
    src = open(os.path.join(TPL, 'bk_base.html'), encoding='utf-8').read()
    check('class="bk-slip-tabs" role="tablist"' in src, "tabs container is a role=tablist")
    for sliptab in ('parlay', 'roundrobin', 'singles'):
        check(('data-sliptab="%s"' % sliptab) in src, "tab present: %s" % sliptab)
    check(src.count('role="tab"') >= 3, "three role=tab buttons")
    check('aria-selected="true" tabindex="0" data-sliptab="parlay"' in src,
          "Parlay is the initial active tab (aria-selected=true, tabindex=0)")
    check(src.count('aria-selected="false" tabindex="-1"') >= 2, "other tabs start aria-selected=false, tabindex=-1")
    # selector logic (CSP-safe vanilla; no eval)
    for tok in ["document.querySelectorAll('.bk-slip-tabs [role=\"tab\"]')",
                "t.classList.toggle('active', on)", "setAttribute('aria-selected'",
                "t.tabIndex = on ? 0 : -1", "addEventListener('click'", "addEventListener('keydown'",
                "e.key === 'ArrowRight'", "e.key === 'ArrowLeft'", "e.key === 'Home'", "e.key === 'End'"]:
        check(tok in src, "selector has %r" % tok)
    check('eval(' not in src and 'new Function' not in src, "no eval / new Function in the selector (CSP-safe)")


if __name__ == '__main__':
    print("=" * 72)
    print("ALPINE REMOVED + CSP CLEANED QC (NBA P0 F13 fix — Decision 1)")
    print("=" * 72)
    test_no_alpine_directives()
    test_no_unpkg()
    test_csp_clean()
    test_vanilla_tablist()
    print("\nClean:", not fails)
    sys.exit(1 if fails else 0)
