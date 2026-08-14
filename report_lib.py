"""
Report generator for the daily premarket / close reports.

WHY THIS EXISTS
---------------
Reports were previously built by writing a one-off script each day and then
patching its HTML output. That drifted: sections got renamed, the chart was
dropped, panels ended up nested in the wrong column, and a whole-file
"div count balances" check passed while the page rendered wrong.

This module fixes the root cause:
  * The page SHELL (head, CSS, TTS player, trader reference) is lifted verbatim
    from a known-good prior report. It is never hand-edited.
  * The BODY is generated from data through section builders whose names and
    order come from SPEC below - the single source of truth.
  * validate() checks nesting DEPTH AT COLUMN BOUNDARIES, not the file total.
    A missing </div> inside a flex column is exactly what broke 2026-08-14 and
    a whole-file count cannot catch it.

USAGE
    import report_lib as R
    html = R.build(base='2026-08-14-premarket.html', kind='premarket',
                   title='Friday, August 14, 2026', tts=[...], sections={...})
    R.write('2026-08-17-premarket.html', html)
"""
import json, re

# ---------------------------------------------------------------- spec
# Canonical section names and order. Read off the known-good templates:
#   premarket -> 2026-08-12-premarket.html
#   close     -> 2026-08-11.html
SPEC = {
    'premarket': [
        'watchlist', 'headline',
        ('row', ['overview_setups', 'prep']),
        'thisweek',
        ('row', ['chart_trumpwatch', 'strat_setups']),
        ('row', ['bullish_gappers', 'bearish_gappers']),
        'darkpool',
    ],
    'close': [
        'watchlist', 'headline',
        ('row', ['what_happened_top3', 'picks_results']),
        'thisweek',
        ('row', ['chart_trumpwatch', 'strat_setups']),
        'how_setups_played_out',
        'darkpool',
        'sector_performance', 'lessons', 'watch_tomorrow',
    ],
}

# Exact header labels. These are the template's words, not paraphrases.
LABELS = {
    'watchlist':        'Watchlist',
    'overview':         'Morning Overview',
    'top_setups':       'Top Setups',
    'prep':             'JR Morning Prep: Market Recap &amp; Trade Plan',
    'thisweek':         'This Week &mdash; On Deck',
    'trumpwatch':       'Trump Watch',
    'strat_setups':     'Strat Setups',
    'bullish_gappers':  '&#9650; Bullish Gappers',
    'bearish_gappers':  '&#9660; Bearish Gappers',
    'darkpool':         'Dark Pool Blocks',
    'what_happened':    'What Happened Today',
    'top3_plays':       'Top 3 Plays',
    'picks_results':    'Top-3 Picks &mdash; Results',
    'how_played_out':   'How Setups Played Out',
    'sector_perf':      'Sector Performance',
    'lessons':          'Lessons of the Day',
    'watch_tomorrow':   'Watch Tomorrow',
}

CARD = '<div style="background:var(--bg-card);border:1px solid var(--border);border-radius:6px;overflow:hidden;margin-bottom:6px;">'
HDR  = ('<div style="background:var(--bg-page);padding:8px 14px;border-bottom:1px solid var(--border-s);'
        'font-size:9px;font-weight:700;letter-spacing:.12em;color:var(--tx2);text-transform:uppercase;'
        'display:flex;align-items:center;justify-content:space-between;"><span>{}</span>{}</div>')
ROW  = ('<div style="display:flex;gap:1px;background:#21262d;background:var(--bg-card);border:1px solid var(--border);'
        'border-radius:6px;overflow:hidden;margin-bottom:6px;">')
ROW6 = '<div style="display:flex;gap:6px;margin-bottom:6px;align-items:stretch;">'
COL_L = '<div style="flex:0 0 50%;min-width:0;overflow:hidden;display:flex;flex-direction:column;">'
COL_R = '<div style="flex:0 0 50%;background:var(--bg-card);padding:14px;overflow-y:auto;display:flex;flex-direction:column;">'
# left column has appeared with and without overflow:hidden - match either
COL_L_RE = re.compile(r'<div style="flex:0 0 50%;min-width:0;[^"]*flex-direction:column;">')
COL_R_RE = re.compile(r'<div style="flex:0 0 50%;background:var\(--bg-card\);padding:14px;')


def card(label, body, right_note=''):
    note = (f'<span style="font-size:9px;font-weight:700;color:#f0883e;">{right_note}</span>' if right_note else '')
    return CARD + HDR.format(label, note) + body + '</div>'


def row(*children, gap6=False):
    """A flex row. Children must be complete, self-closed blocks."""
    for i, c in enumerate(children):
        d = _depth(c)
        if d != 0:
            raise ValueError(f'row child {i} is not self-closed (depth {d:+d}) - '
                             f'this is what pushes a panel into the wrong column')
    return (ROW6 if gap6 else ROW) + ''.join(children) + '</div>'


# ---------------------------------------------------------------- shell
def shell(base_path):
    """Split a known-good report into the parts that never change."""
    h = open(base_path, encoding='utf-8').read()
    i = h.find('window._ttsScript=')
    j = h.find(';</script>', i)
    if i < 0 or j < 0:
        raise ValueError(f'{base_path}: no _ttsScript - not a valid base')
    n_placeholder = h.count('card-header">')
    if n_placeholder > 0:
        raise ValueError(f'{base_path}: {n_placeholder} placeholder cards - '
                         'this is the broken template, pick another base')
    body_start = h.find(CARD[:80])
    if body_start < 0:
        body_start = h.find('<div style="background:var(--bg-card);border:1px solid var(--border);border-radius:6px;margin-bottom:6px;">', j)
    tail = h.find('</body>')
    return {'head': h[:i], 'mid': h[j:body_start], 'tail': h[tail:]}


def build(base, kind, title, tts, body):
    """Assemble a full report. `body` is the already-built section HTML."""
    if kind not in SPEC:
        raise ValueError(f'unknown kind {kind}')
    s = shell(base)
    head = re.sub(r'<title>[^<]*</title>',
                  f'<title>Catalyst Report &mdash; {title}</title>', s['head'])
    head = re.sub(r'(?:Monday|Tuesday|Wednesday|Thursday|Friday), \w+ \d+, \d{4}', title, head)
    return head + 'window._ttsScript=' + json.dumps(tts, ensure_ascii=False) + s['mid'] + body + s['tail']


# ---------------------------------------------------------------- validation
def _matching_close(html, start):
    """Index just past the </div> that closes the div opening at `start`."""
    d, i = 0, start
    while i < len(html):
        o = html.find('<div', i)
        c = html.find('</div>', i)
        if c == -1:
            return len(html)
        if o != -1 and o < c:
            d += 1; i = o + 4
        else:
            d -= 1; i = c + 6
            if d == 0:
                return i
    return len(html)


def _depth(fragment):
    """Div depth of a fragment, ignoring <script> bodies."""
    f = re.sub(r'<script.*?</script>', '', fragment, flags=re.S)
    return f.count('<div') - f.count('</div>')


def validate(html, kind):
    """Fail loudly on the things that actually broke reports."""
    errs = []

    if html.count('card-header">'):
        errs.append('broken template: placeholder cards present')

    if _depth(html) != 0:
        errs.append(f'whole-file div depth {_depth(html):+d}')

    # THE important check: every flex row's children must be SIBLINGS.
    # Walk to the row's real closing tag, then measure depth between the left
    # column's start and the right column's start. Non-zero means the right
    # panel is nested inside the left one and renders below it, not beside it.
    for m in re.finditer(re.escape(ROW), html):
        seg = html[m.start(): _matching_close(html, m.start())]
        ml = COL_L_RE.search(seg)
        mr = COL_R_RE.search(seg)
        if ml and mr and mr.start() > ml.start():
            d = _depth(seg[ml.start():mr.start()])
            if d != 0:
                errs.append(f'flex row at {m.start()}: left column depth {d:+d} - '
                            'right panel nests inside it and renders BELOW, not beside')
        elif ml and not mr:
            errs.append(f'flex row at {m.start()}: only one column found - '
                        'the right panel is missing or malformed')

    # section names must be the template's, in the template's order
    want = []
    for item in SPEC[kind]:
        want.extend(item[1] if isinstance(item, tuple) else [item])
    pos, order_ok = -1, True
    for key in ('watchlist', 'thisweek', 'strat_setups', 'darkpool'):
        lbl = LABELS.get(key)
        if not lbl:
            continue
        m2 = re.search('>' + re.escape(lbl) + '(?:<| )', html)
        p = m2.start() if m2 else -1
        if p < 0:
            errs.append(f'missing section: {lbl}')
        elif p < pos:
            order_ok = False
        else:
            pos = p
    if not order_ok:
        errs.append('sections out of template order')

    # nothing invented
    for banned in ('The Semi Split', 'Called vs Happened', 'Scorecard',
                   'Sector Movers', 'Premarket Gainers', 'Premarket Losers'):
        if banned in html:
            errs.append(f'non-template section present: "{banned}"')

    if errs:
        raise AssertionError('REPORT INVALID:\n  - ' + '\n  - '.join(errs))
    return True


def write(path, html, kind):
    validate(html, kind)
    open(path, 'w', encoding='utf-8').write(html)
    return path
