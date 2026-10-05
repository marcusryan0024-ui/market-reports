#!/usr/bin/env python3
"""Behavioural test for the collapsible report sections.

The collapse feature is pure client-side JS injected by report_lib._COLLAPSE,
so nothing in the build can tell you whether it WORKS - a build that passes
validate() ships a page whose sections may or may not actually toggle. That is
the shape of failure this project keeps paying for: a green build standing in
for a verified behaviour.

So the script is pulled out of the real built page (not out of report_lib, so a
build-time escaping mistake is caught too) and run against a DOM shim in
JavaScriptCore, which ships with macOS as `osascript -l JavaScript`.

What it cannot see: real layout. Whether a collapsed panel LOOKS right is a
browser question. What it does prove is that the right elements hide, the
storage key is stable across days, and the three shapes that must be left alone
are left alone.

    python3 test_collapse.py [built-report.html]
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

ASSERTS = r'''
var out=[], fails=0;
function t(name,cond,extra){
  if(!cond)fails++;
  out.push((cond?'PASS  ':'FAIL  ')+name+(extra?'   ['+extra+']':''));
}

// --- the chevron goes in a different place depending on the header's display.
// A space-between flex header with a third flex item shoves its label to the
// centre, so on those the chevron has to go INSIDE the label span.
t('flex header: chevron inside the label span, flex item count unchanged',
  h1.children.length===2 && h1.children[0].children[0] &&
  h1.children[0].children[0].className==='rpt-sec-c', 'flex items='+h1.children.length);
t('float header: chevron prepended to the header itself',
  h2.children[0] && h2.children[0].className==='rpt-sec-c');

// --- things that must be left alone
t('header with no body is not wired', h4.getAttribute('role')===null);
t('matching div that is NOT a first child is not wired', h5.getAttribute('role')===null);

// --- at rest
t('wired as buttons', h1.getAttribute('role')==='button' && h2.getAttribute('role')==='button');
t('every section starts EXPANDED',
  h1.getAttribute('aria-expanded')==='true' && b1.hidden===false &&
  h2.getAttribute('aria-expanded')==='true' && b2a.hidden===false);

// --- toggling
h1.fire('click');
t('click hides the body', b1.hidden===true);
t('aria-expanded flips to false', h1.getAttribute('aria-expanded')==='false');
t('storage key excludes the daily-changing note',
  ('rptsec:Morning Overview' in LS), JSON.stringify(Object.keys(LS)));
h1.fire('click');
t('clicking again re-shows it and clears the key',
  b1.hidden===false && !('rptsec:Morning Overview' in LS));

h2.fire('click');
t('ALL following siblings hide, not just the first', b2a.hidden===true && b2b.hidden===true);
t('a collapsed column of a flex ROW gets align-self:flex-start',
  colR.style.alignSelf==='flex-start');
t('header bottom margin zeroed', h2.style.marginBottom==='0px');
t('panel bottom padding zeroed', colR.style.paddingBottom==='0px');
t('float-header key is the section name only',
  ('rptsec:Strat Setups' in LS), JSON.stringify(Object.keys(LS)));
h2.fire('click');
t('expanding restores align-self', colR.style.alignSelf==='');

// align-self on a child of a COLUMN flex shrinks it SIDEWAYS - must not happen
h3.fire('click');
t('a card in a COLUMN parent gets no align-self',
  card2.style.alignSelf===undefined||card2.style.alignSelf==='', 'got='+card2.style.alignSelf);

t('Enter toggles from the keyboard', (function(){
   var before=b1.hidden;
   (h1._listeners['keydown']||[]).forEach(function(f){f({key:'Enter',preventDefault:function(){}});});
   return b1.hidden!==before;})());

JSON.stringify({fails:fails, lines:out});
'''

# A seeded key must come back collapsed on the next page load - that is the
# whole point of persisting it, and it is the half a toggle test never reaches.
PERSIST = r'''
var out=[], fails=0;
function t(name,cond,extra){if(!cond)fails++;out.push((cond?'PASS  ':'FAIL  ')+name+(extra?'   ['+extra+']':''));}
t('a seeded key makes the section load COLLAPSED',
  b1.hidden===true && h1.getAttribute('aria-expanded')==='false');
t('an unseeded section still loads expanded', b2a.hidden===false);
JSON.stringify({fails:fails, lines:out});
'''


def extract_script(html_path):
    """Pull the collapse IIFE out of a BUILT page, not out of report_lib.

    Reading report_lib would test the source; reading the page tests what
    actually shipped, which is the only thing a reader ever runs.
    """
    h = open(html_path, encoding='utf-8').read()
    i = h.find('.rpt-sec-h{')
    if i < 0:
        raise SystemExit(f'{html_path}: no collapse block - was it built with the current report_lib?')
    j = h.find('<script>', i)
    k = h.find('</script>', j)
    if j < 0 or k < 0:
        raise SystemExit(f'{html_path}: collapse style present but its script is missing')
    return h[j + len('<script>'):k]


def run(src, asserts, seed=None):
    shim = open(os.path.join(HERE, 'tests', 'collapse_shim.js'), encoding='utf-8').read()
    scene = open(os.path.join(HERE, 'tests', 'collapse_scene.js'), encoding='utf-8').read()
    pre = ''
    if seed:
        pre = ''.join(f'LS[{json.dumps(k)}]="1";' for k in seed) + '\n'
    prog = shim + '\n' + pre + scene + '\n' + src + '\n' + asserts
    path = os.path.join(HERE, '.collapse_run.jxa')
    open(path, 'w', encoding='utf-8').write(prog)
    try:
        r = subprocess.run(['osascript', '-l', 'JavaScript', path],
                           capture_output=True, text=True, timeout=60)
    finally:
        os.unlink(path)
    if r.returncode != 0:
        raise SystemExit('JS failed to run:\n' + (r.stderr or r.stdout))
    return json.loads(r.stdout.strip())


def main():
    page = sys.argv[1] if len(sys.argv) > 1 else None
    if not page:
        pages = sorted(f for f in os.listdir(HERE) if re.match(r'\d{4}-\d\d-\d\d-premarket\.html$', f))
        if not pages:
            raise SystemExit('no built premarket report found - pass one as an argument')
        page = os.path.join(HERE, pages[-1])
    print(f'page: {os.path.basename(page)}\n')

    src = extract_script(page)
    fails = 0
    for title, asserts, seed in (('toggle + scope', ASSERTS, None),
                                 ('persistence', PERSIST, ['rptsec:Morning Overview'])):
        res = run(src, asserts, seed)
        print(f'-- {title}')
        for line in res['lines']:
            print('  ' + line)
        fails += res['fails']
        print()

    total = sum(len(run(src, a, s)['lines'])
                for a, s in ((ASSERTS, None), (PERSIST, ['rptsec:Morning Overview'])))
    print(f'{total - fails} passed, {fails} failed')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
