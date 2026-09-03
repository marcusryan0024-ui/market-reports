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
import json, re, os, glob, html as _html, datetime as _dt

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
# Columns default to an even split, but a row is free to weight one side. The
# prep panel carries six detailed cards against a short overview, so it takes
# ~2/3 and the overview column shrinks to fit its own content instead of
# padding out half the page with empty space.
def col_l(pct=50):
    return (f'<div style="flex:0 0 {pct}%;min-width:0;overflow:hidden;'
            'display:flex;flex-direction:column;">')


def col_r(pct=50):
    return (f'<div style="flex:0 0 {pct}%;background:var(--bg-card);padding:14px;'
            'overflow-y:auto;display:flex;flex-direction:column;">')


COL_L = col_l()
COL_R = col_r()
# left column has appeared with and without overflow:hidden - match either.
# The width is a capture-anything because rows are no longer always 50/50;
# validate() cares that the two columns are SIBLINGS, not how wide they are.
COL_L_RE = re.compile(r'<div style="flex:0 0 \d+%;min-width:0;[^"]*flex-direction:column;">')
COL_R_RE = re.compile(r'<div style="flex:0 0 \d+%;background:var\(--bg-card\);padding:14px;')


def card(label, body, right_note=''):
    note = (f'<span style="font-size:9px;font-weight:700;color:#f0883e;">{right_note}</span>' if right_note else '')
    return CARD + HDR.format(label, note) + body + '</div>'


def top_setups(rows, label='Top Setups'):
    """The left column of the prep row: three ranked names against six prep cards.

    The left column is always the shorter of the two, and the leftover used to
    pile up as one dead block under the last setup. Each entry now takes an
    EQUAL share of whatever height the row ends up being (flex:1) with its text
    centred in that share, so the surplus is spread between the three names
    instead of collecting at the bottom. If the column happens to be tall enough
    already, flex:1 costs nothing - the entries just sit at their natural size.

    rows: [(tier, tier_colour, ticker, change, name, why), ...]
    """
    out = ('<div style="background:var(--bg-card);border:1px solid var(--border);border-radius:6px;'
           'overflow:hidden;flex:1;display:flex;flex-direction:column;margin-top:6px;">'
           + HDR.format(label, '')
           + '<div style="padding:4px 14px 8px;flex:1;display:flex;flex-direction:column;">')
    for i, (tier, tc, sym, chg, name, why) in enumerate(rows):
        tc = _c(tc)
        border = '' if i == len(rows) - 1 else 'border-bottom:1px solid var(--border-s);'
        cc = '#3fb950' if chg.startswith('+') else '#f85149'
        out += (f'<div style="padding:9px 0;{border}flex:1;display:flex;flex-direction:column;'
                'justify-content:center;">'
                '<div style="display:flex;align-items:center;gap:5px;margin-bottom:4px;flex-wrap:wrap;">'
                f'<span style="font-size:9px;font-weight:700;color:{tc};">{tier}</span>'
                f'<span style="font-size:15px;font-weight:800;color:var(--tx1);">{sym}</span>'
                f'<span style="font-size:12px;font-weight:800;color:{cc};margin-left:auto;">{chg}</span></div>'
                f'<div style="font-size:10px;font-weight:700;color:#58a6ff;margin-bottom:3px;">{name}</div>'
                f'<div style="font-size:10px;color:var(--tx4);line-height:1.5;">{why}</div></div>')
    return out + '</div></div>'


def overview(text, label='Morning Overview'):
    """Top-left summary card. Content-height - it never absorbs surplus, so the
    prose stays a tight block and top_setups() below it takes the slack."""
    return (CARD.replace('margin-bottom:6px;', 'margin-bottom:6px;flex:0 0 auto;')
            + HDR.format(label, '')
            + f'<div style="padding:10px 14px;"><p style="margin:0;color:var(--tx4);font-size:11px;'
              f'line-height:1.65;">{text}</p></div></div>')


# ---------------------------------------------------------------- this week
# The five-day grid. The previous markup had two problems the user called out:
# every column carried border-left:3px solid #21262d - the same colour as the
# grid gutter, so the days visually merged into one block - and the category
# labels were #3d444d at 7px, effectively invisible. Event copy was also full
# prose truncated with an ellipsis, which reads as filler.
#
# So: the accent bar is the only thing that separates days, and it must CARRY
# INFORMATION - amber = the next session, blue = a day with a major macro print,
# grey = done. And event lines are hard-capped. If a line needs an ellipsis it
# was too long to belong here; shorten the text instead of truncating it.
TW_ACCENT = {'next': '#ffd54f', 'macro': '#58a6ff', 'done': '#30363d', '': '#484f58'}
TW_MAX_EVENTS = 3
TW_MAX_EARNINGS = 5
TW_MAX_CHARS = 92    # an event line longer than this is prose, not a calendar entry

# Text colours here are deliberate, not inherited. The palette is NOT ordered by
# brightness - tx4 (#94b4cc) is far lighter than tx3 (#334d6a) despite the name.
# Against --bg-card #091220 the contrast ratios are:
#     tx3 #334d6a  2.15:1   unreadable at 9px - this is what "blends in"
#     tx2 #5c80a8  4.57:1   fine for a small label
#     tx4 #94b4cc  8.56:1   the body-copy colour
#     tx1 #e0eafa  ~15:1    headers and tickers
# Body copy uses tx4, quiet labels use tx2, and tx3 is not used in this section
# at all. Hierarchy comes from weight and size, never from fading text into the
# background.
TW_BODY = 'var(--tx4)'
TW_LABEL = 'var(--tx2)'


def _tw_label(text):
    return (f'<div style="font-size:8px;font-weight:700;color:{TW_LABEL};letter-spacing:.1em;'
            'padding-bottom:3px;margin:9px 0 5px;border-bottom:1px solid var(--border-s);">'
            f'{text}</div>')


RAIL = 50    # px. The shared left rail every row hangs off of.


def _tw_row(anchor, text, accent, is_ticker):
    """One calendar line: anchor in the left rail, detail to the right.

    The anchor is what the eye lands on, so it is the TICKER wherever a ticker
    exists - monospace, brightest text on the card. Times were previously in
    this position, which made every event read as "All day" before it read as
    the company it was about. A time only takes the rail when the line has no
    ticker (an econ print, a futures expiry, a multi-day conference).
    """
    style = ('font-family:monospace;font-weight:700;color:var(--tx1);font-size:10px;'
             if is_ticker else
             f'font-weight:700;color:{accent};font-size:9px;')
    return ('<div style="display:flex;align-items:baseline;padding:3px 0;font-size:10px;">'
            f'<span style="{style}flex:0 0 {RAIL}px;">{anchor}</span>'
            f'<span style="color:{TW_BODY};line-height:1.45;min-width:0;">{text}</span></div>')


def thisweek(days):
    """The 5-day On Deck grid.

    days: list of dicts - {day, tag, accent, econ, earnings, events} where
      day      'TUE 8/18'
      tag      optional short right-aligned note on the day header
      accent   key into TW_ACCENT
      econ     [(time, text), ...]
      earnings [(ticker, when), ...]           when: 'AM &middot; est $4.73'
      events   [(ticker, when, text), ...]     ticker '' -> `when` takes the rail

    All three blocks share one left rail, so tickers line up down the whole
    column and a day can be scanned by symbol without reading a word.
    """
    cols = ''
    for d in days:
        accent = TW_ACCENT.get(d.get('accent', ''), TW_ACCENT[''])
        muted = d.get('accent') == 'done'
        daycol = TW_LABEL if muted else 'var(--tx1)'
        tag = d.get('tag', '')
        tag_html = (f'<span style="font-size:8px;font-weight:700;color:{accent};'
                    f'letter-spacing:.08em;margin-left:auto;">{tag}</span>') if tag else ''

        body = ''
        if d.get('econ'):
            body += _tw_label('ECONOMIC')
            for when, text in d['econ']:
                body += _tw_row(when, text, accent, is_ticker=False)
        if d.get('earnings'):
            body += _tw_label('EARNINGS')
            for tk, when in d['earnings'][:TW_MAX_EARNINGS]:
                body += _tw_row(tk, when, accent, is_ticker=True)
        if d.get('events'):
            body += _tw_label('EVENTS')
            for tk, when, text in d['events'][:TW_MAX_EVENTS]:
                if len(re.sub(r'<[^>]+>|&[a-z]+;', '', text)) > TW_MAX_CHARS:
                    raise ValueError(f'{d["day"]}: event line is {len(text)} chars - '
                                     f'shorten it, do not truncate: {text[:70]}...')
                if tk:
                    detail = f'{text} <span style="color:{accent};font-weight:700;">{when}</span>'
                    body += _tw_row(tk, detail, accent, is_ticker=True)
                else:
                    body += _tw_row(when, text, accent, is_ticker=False)

        cols += (f'<div style="background:var(--bg-card);border-left:3px solid {accent};padding:0 0 10px;">'
                 '<div style="background:var(--bg-page);padding:6px 10px;display:flex;align-items:center;'
                 'border-bottom:1px solid var(--border-s);">'
                 f'<span style="font-size:10px;font-weight:800;color:{daycol};letter-spacing:.06em;">{d["day"]}</span>'
                 f'{tag_html}</div>'
                 f'<div style="padding:0 10px;">{body}</div></div>')

    # The column count follows the data. It was hardcoded to 5, which silently
    # broke the layout the moment a week carried past days plus future ones -
    # 2026-09-02 wanted Mon and Tue behind today as well as the days ahead.
    # 240px per column is the floor that keeps a ticker rail plus its text on
    # one line; below that the rows wrap and the column stops being scannable.
    n = max(len(days), 1)
    hint = 'SWIPE &#8596;' if n > 5 else ''
    grid = ('<div style="overflow-x:auto;-webkit-overflow-scrolling:touch;">'
            '<div style="display:grid;'
            f'grid-template-columns:repeat({n}, minmax(240px, 1fr));gap:1px;background:#21262d;'
            f'min-width:{n * 240}px;">{cols}</div></div>')
    return (CARD + HDR.format(LABELS['thisweek'], hint) + grid + '</div>')


# ---------------------------------------------------------------- morning prep
# The prep panel is a LEAD PARAGRAPH plus a grid of per-name cards, two to a
# row. It is not a list of ticker rows - that was built wrong on 2026-08-18 and
# called out. Each card carries, in this order:
#     ticker | setup-name tag | tier tag
#     the read, in prose
#     the plan line - monospace blue, the price or the actual instruction
#     the bull case, the bear case
#     an italic closing note - why it is ranked where it is
# Read off 2026-08-14-premarket.html, which is the reference rendering.
def prep(date_pill, lead, cards, width=73):
    """cards: [(ticker, setup_name, name_colour, tier, read, plan, bull, bear, note), ...]

    name_colour accepts a PALETTE key or a literal colour.
    """
    cards = [(c[0], c[1], _c(c[2])) + tuple(c[3:]) for c in cards]
    out = ''
    for i in range(0, len(cards), 2):
        out += '<div style="display:flex;flex-wrap:wrap;gap:8px;flex:1;">'
        for tk, name, ncol, tier, read, plan, bull, bear, note in cards[i:i + 2]:
            out += ('<div style="background:var(--bg-hover);border-radius:6px;border:1px solid var(--border);'
                    'padding:14px 16px;min-width:180px;flex:1;">'
                    '<div style="display:flex;align-items:center;gap:6px;margin-bottom:6px;flex-wrap:wrap;">'
                    f'<span style="font-weight:700;font-size:16px;color:var(--tx1);">{tk}</span>'
                    f'<span style="font-size:9px;font-weight:800;color:{ncol};">{name}</span>'
                    f'<span style="font-size:9px;font-weight:800;color:var(--tx2);">{tier}</span></div>'
                    f'<div style="font-size:12px;color:var(--tx2);margin-bottom:5px;line-height:1.4;">{read}</div>'
                    f'<div style="font-size:12px;color:#388bfd;font-weight:600;margin-bottom:5px;'
                    f'font-family:monospace;">{plan}</div>'
                    f'<div style="font-size:12px;color:#3fb950;margin-bottom:4px;line-height:1.4;">&#9650; {bull}</div>'
                    f'<div style="font-size:12px;color:#f85149;margin-bottom:5px;line-height:1.4;">&#9660; {bear}</div>'
                    f'<div style="font-size:11px;color:var(--tx2);font-style:italic;line-height:1.5;">{note}</div>'
                    '</div>')
        out += '</div>'

    return (col_r(width)
            + '<div style="background:var(--bg-page);padding:8px 14px;border-bottom:1px solid var(--border-s);'
              'font-size:9px;font-weight:700;letter-spacing:.12em;color:var(--tx2);text-transform:uppercase;'
              'margin:-14px -14px 0;display:flex;align-items:center;justify-content:space-between;">'
              f'<span>{LABELS["prep"]}</span>'
              '<span style="font-size:9px;font-weight:700;color:#58a6ff;background:#0d2137;'
              'border:1px solid #1f6feb;padding:2px 7px;border-radius:10px;letter-spacing:.08em;">'
              f'{date_pill}</span></div>'
            + '<div style="padding:14px 2px 0;flex:1;display:flex;flex-direction:column;gap:14px;">'
            + f'<p style="margin:0;color:var(--tx1);font-size:13px;line-height:1.6;font-weight:500;">{lead}</p>'
            + out + '</div></div>')


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


# The masthead mode badge. Close reports are built from the PREVIOUS close
# report's shell, so once one drifted to PRE-MARKET every later one inherited it
# - 2026-08-24 through 2026-08-31 all shipped an After Close report labelled
# PRE-MARKET. build() now sets it from `kind` and validate() refuses the wrong one.
MODE = {'premarket': ('rpt-nav-mode-pre', 'PRE-MARKET'),
        'close':     ('rpt-nav-mode-cls', 'AFTER CLOSE')}
MODE_RE = re.compile(r'class="rpt-nav-mode-(?:pre|cls)">(?:PRE-MARKET|AFTER CLOSE)</span>')


def build(base, kind, title, tts, body):
    """Assemble a full report. `body` is the already-built section HTML."""
    if kind not in SPEC:
        raise ValueError(f'unknown kind {kind}')
    s = shell(base)
    head = re.sub(r'<title>[^<]*</title>',
                  f'<title>Catalyst Report &mdash; {title}</title>', s['head'])
    # The dateline is in BOTH head (<title>, meta) and mid (the on-page report
    # header bar). Substituting head alone shipped 2026-08-17 close with
    # "Thursday, August 13, 2026" printed across the top of the page.
    dateline = re.compile(r'(?:Monday|Tuesday|Wednesday|Thursday|Friday), \w+ \d+, \d{4}')
    head = dateline.sub(title, head)
    mid = dateline.sub(title, s['mid'])

    # the masthead mode badge must match `kind`, not whatever the base shell had
    cls, lbl = MODE[kind]
    mid, n = MODE_RE.subn(f'class="{cls}">{lbl}</span>', mid)
    if n != 1:
        raise AssertionError(f'masthead mode badge: expected 1 match, found {n}')

    return head + 'window._ttsScript=' + json.dumps(tts, ensure_ascii=False) + mid + body + s['tail']


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

    want_cls, want_lbl = MODE[kind]
    bad_lbl = MODE['close' if kind == 'premarket' else 'premarket'][1]
    if f'class="{want_cls}">{want_lbl}</span>' not in html:
        errs.append(f'masthead mode badge is not "{want_lbl}" for kind={kind}')
    if f'>{bad_lbl}</span>' in html:
        errs.append(f'masthead still shows "{bad_lbl}" on a {kind} report')

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


def write(path, html, kind, index=True):
    validate(html, kind)
    open(path, 'w', encoding='utf-8').write(html)
    if index:
        d = os.path.dirname(os.path.abspath(path))
        # A new date has no row on the landing page until something creates one,
        # and the only thing that ever did was catalyst_scan's rebuild - the same
        # pass that overwrites finished reports. So 8/18 had a report and no way
        # to reach it. Writing through the generator now guarantees the row, and
        # refresh_index fills its headline from the file we just wrote.
        m = re.search(r'(2026-\d\d-\d\d)', os.path.basename(path))
        if m:
            ensure_row(m.group(1), d)
            # Move the featured card to the newest date BEFORE refreshing, so
            # refresh_index fills it from the report it now points at.
            promote_featured(m.group(1), d)
        refresh_index(d)
    return path


# ---------------------------------------------------------------- landing page
# Every dated row on index.html carries the report's own TOP HEADLINE. These
# were previously filled in by hand, so 13 rows and the featured card sat blank
# with "No headline available for this date." while the headline was sitting in
# the report file the row already linked to. Nothing is authored here - the text
# is lifted from the report, so a row can only go blank if the report itself has
# no headline.
SNIP_LEN = 90    # row snippet, matches the existing rows
FEAT_LEN = 240   # featured card body

ROW_RE  = re.compile(r'(<div class="rleft">)(.*?)(</div>\s*<div class="rlinks">)(.*?)(</div>)', re.S)
SNIP_RE = re.compile(r'\s*<span class="rsnip">.*?</span>', re.S)
DATE_RE = re.compile(r'href="(2026-\d\d-\d\d)(?:-premarket)?\.html"')
# starts at the whole featured block, not feat-right - the date lives in
# feat-left's links, which sit before the fb body we are filling
FEAT_RE = re.compile(r'(<div class="feat">.*?<div class="fb")([^>]*)(>)(.*?)(</div>)', re.S)


def _plain(fragment):
    """Report markup -> plain text: drop tags, resolve entities, collapse space."""
    t = re.sub(r'<[^>]+>', ' ', fragment)
    t = _html.unescape(t)
    return re.sub(r'\s+', ' ', t).strip()


def _clip(text, n):
    text = text.strip()
    out = text if len(text) <= n else text[:n].rstrip() + '…'
    return _html.escape(out, quote=False)


def _legacy_headline(s):
    """The earliest reports (mid-May) predate the headline bar and lead with a
    TOP CATALYST spotlight instead. Read that rather than leave the row blank."""
    m = re.search(r'<div class="sp-rank">TOP CATALYST</div>\s*'
                  r'<div class="sp-label">([^<]+)</div>.*?'
                  r'<div class="sp-news">(.*?)</div>', s, re.S)
    if not m:
        return None
    return f'Top catalyst: {_plain(m.group(1))} — {_plain(m.group(2))}'


def report_headline(date, dirpath='.'):
    """The TOP HEADLINE of a date's report. Premarket first, close as fallback."""
    for suffix in ('-premarket.html', '.html'):
        p = os.path.join(dirpath, date + suffix)
        if not os.path.exists(p):
            continue
        s = open(p, encoding='utf-8').read()
        m = re.search(r'<div class="headline-title">(.*?)</div>', s, re.S)
        t = _plain(m.group(1)) if m else _legacy_headline(s)
        if t:
            return t
    return None


def refresh_index(dirpath='.'):
    """Refill every headline on the landing page from the reports themselves."""
    path = os.path.join(dirpath, 'index.html')
    if not os.path.exists(path):
        return None
    idx = open(path, encoding='utf-8').read()
    filled, blank = 0, []

    def do_row(m):
        nonlocal filled
        left, links = m.group(2), m.group(4)
        d = DATE_RE.search(links)
        if not d:
            return m.group(0)
        h = report_headline(d.group(1), dirpath)
        if not h:
            blank.append(d.group(1))
            return m.group(0)
        body = SNIP_RE.sub('', left).rstrip()
        body += f'\n    <span class="rsnip">{_clip(h, SNIP_LEN)}</span>\n  '
        filled += 1
        return m.group(1) + body + m.group(3) + links + m.group(5)

    idx = ROW_RE.sub(do_row, idx)

    def do_feat(m):
        nonlocal filled
        d = DATE_RE.search(m.group(0))
        h = report_headline(d.group(1), dirpath) if d else None
        if not h:
            return m.group(0)
        filled += 1
        # drop the placeholder grey so a real headline reads as body text
        attrs = re.sub(r'\s*style="color:#3d444d"', '', m.group(2))
        return m.group(1) + attrs + m.group(3) + _clip(h, FEAT_LEN) + m.group(5)

    idx = FEAT_RE.sub(do_feat, idx, count=1)
    open(path, 'w', encoding='utf-8').write(idx)
    if blank:
        print(f'refresh_index: no headline found for {", ".join(blank)}')
    return filled


MONTH_RE = re.compile(r'(<div class="mhdr"><span class="mlabel">([A-Z]+ \d{4})</span>'
                      r'<span class="mcnt">)(\d+)(</span></div>\s*)')


def ensure_row(date, dirpath='.'):
    """Add `date`'s row to index.html if it is not already there.

    Rows are newest-first inside a month block. This inserts directly after that
    month's header, which is correct for the normal case - a report being written
    for the newest date in its month. Returns True if a row was added.
    """
    path = os.path.join(dirpath, 'index.html')
    if not os.path.exists(path):
        return False
    idx = open(path, encoding='utf-8').read()
    # Key on the ROW link style, not on the bare href - the featured card at the
    # top of the page links to the newest date too (with its own larger padding),
    # and matching that made this think a row already existed when it did not.
    if re.search(rf'padding:5px 13px;font-size:11px" href="{date}(?:-premarket)?\.html"', idx):
        return False

    d = _dt.date(*(int(x) for x in date.split('-')))
    label = d.strftime('%B %Y').upper()
    row = (f'<div class="row">\n  <div class="rleft">\n'
           f'    <div class="rdate"><span class="rdow">{d.strftime("%a").upper()}</span>'
           f'<span class="rmd">{d.strftime("%b")} {d.day}</span></div>\n  </div>\n'
           f'  <div class="rlinks">'
           f'<a class="rl pre" style="padding:5px 13px;font-size:11px" '
           f'href="{date}-premarket.html">&#9651;&thinsp;Pre-Market</a>'
           f'<a class="rl close" style="padding:5px 13px;font-size:11px" '
           f'href="{date}.html">&#9660;&thinsp;After Close</a></div>\n</div>\n')

    hit = [False]

    def bump(m):
        if hit[0] or m.group(2) != label:
            return m.group(0)
        hit[0] = True
        return m.group(1) + str(int(m.group(3)) + 1) + m.group(4) + row

    idx = MONTH_RE.sub(bump, idx)
    if not hit[0]:
        return False
    open(path, 'w', encoding='utf-8').write(idx)
    return True


# ------------------------------------------------- week band on the landing page
# A slim divider that sits above the newest day row of its week and links that
# week's catalyst map. Deliberately NOT a .row - ROW_RE keys on rleft/rlinks and
# mcnt counts daily reports, so a band built from those classes would be picked
# up as a report that has no headline and fail validate_index.
WK_CSS_MARK = '/* weekahead-band */'
WK_CSS = '''<style>
''' + WK_CSS_MARK + '''
.wkband{display:flex;align-items:center;gap:10px;padding:6px 16px;margin:12px 0 6px}
.wkl{font-size:8px;font-weight:800;letter-spacing:.15em;color:#39404d;
  text-transform:uppercase;white-space:nowrap}
.wkr{flex:1;height:1px;background:#0e1420}
.wka{font-size:9px;font-weight:700;letter-spacing:.06em;color:#484f58;text-decoration:none;
  border:1px solid #141a24;border-radius:11px;padding:3px 11px;white-space:nowrap;
  transition:all .14s}
.wka:hover{color:#58a6ff;border-color:#1f6feb;background:#0d1421}
</style>'''


def ensure_weekahead_row(monday, dirpath='.', href=None):
    """Attach the week band for the week beginning `monday` (YYYY-MM-DD).

    Sits directly above that week's newest day row, or under the month header if
    the week has no rows yet. Idempotent - keyed on data-week. Refuses to link a
    page that is not on disk, so the landing page never gets a dead link.
    """
    path = os.path.join(dirpath, 'index.html')
    if not os.path.exists(path):
        return False
    mon = _dt.date(*(int(x) for x in monday.split('-')))
    if href is None:
        href = (mon - _dt.timedelta(days=1)).isoformat() + '-weekahead.html'
    if not os.path.exists(os.path.join(dirpath, href)):
        return False

    idx = open(path, encoding='utf-8').read()
    if f'data-week="{monday}"' in idx:
        return False

    sun = mon + _dt.timedelta(days=6)
    band = (f'<div class="wkband" data-week="{monday}">'
            f'<span class="wkl">Week of {mon.strftime("%b")} {mon.day}</span>'
            f'<span class="wkr"></span>'
            f'<a class="wka" href="{href}">Catalyst Map &#8594;</a></div>\n')

    if WK_CSS_MARK not in idx:
        idx = idx.replace('</head>', WK_CSS + '\n</head>', 1)

    pos = None
    for m in re.finditer(r'<div class="row">', idx):
        d = DATE_RE.search(idx, m.end(), m.end() + 1200)
        if not d:
            continue
        rd = _dt.date(*(int(x) for x in d.group(1).split('-')))
        if mon <= rd <= sun:
            pos = m.start()
            break

    if pos is None:
        label = mon.strftime('%B %Y').upper()
        mh = re.search(MONTH_RE.pattern.replace(r'([A-Z]+ \d{4})', re.escape(label)), idx)
        if not mh:
            return False
        pos = mh.end()

    idx = idx[:pos] + band + idx[pos:]
    open(path, 'w', encoding='utf-8').write(idx)
    return True


# ------------------------------------------------------- featured card promotion
# refresh_index only refills the featured card's BODY, and it reads the date out
# of that card's own links - so the card re-filled 2026-08-18's headline every
# single run and never advanced. The date and both hrefs were only ever set by
# hand. This moves the card forward; refresh_index then fills the text.
FEAT_DATE_RE = re.compile(r'(<div class="feat-dow">)([A-Z]+)(</div>\s*'
                          r'<div class="feat-date">)([^<]+)(</div>)', re.S)
FEAT_LINK_RE = re.compile(r'(padding:7px 18px;font-size:12px" href=")'
                          r'(2026-\d\d-\d\d)((?:-premarket)?\.html")')


def promote_featured(date, dirpath='.'):
    """Point the landing page's featured card at `date`.

    Only moves forward, and only to a date whose report files are on disk, so a
    rebuild of an older report can never drag the card backwards or leave it
    pointing at a file that does not exist.
    """
    path = os.path.join(dirpath, 'index.html')
    if not os.path.exists(path):
        return False
    if not os.path.exists(os.path.join(dirpath, f'{date}-premarket.html')):
        return False
    idx = open(path, encoding='utf-8').read()
    cur = FEAT_LINK_RE.search(idx)
    if cur and cur.group(2) >= date:
        return False
    d = _dt.date(*(int(x) for x in date.split('-')))
    idx = FEAT_DATE_RE.sub(
        lambda m: (m.group(1) + d.strftime('%a').upper() + m.group(3)
                   + f'{d.strftime("%b")} {d.day}, {d.year}' + m.group(5)), idx, count=1)
    idx = FEAT_LINK_RE.sub(lambda m: m.group(1) + date + m.group(3), idx, count=2)
    open(path, 'w', encoding='utf-8').write(idx)
    return True


def validate_index(dirpath='.'):
    """Fail if any dated row on the landing page is missing its headline."""
    idx = open(os.path.join(dirpath, 'index.html'), encoding='utf-8').read()
    missing = [DATE_RE.search(m.group(4)).group(1)
               for m in ROW_RE.finditer(idx)
               if 'rsnip' not in m.group(2) and DATE_RE.search(m.group(4))]
    if 'No headline available' in idx:
        missing.append('featured card')
    if missing:
        raise AssertionError('index.html missing headlines: ' + ', '.join(missing))
    return True


# ---------------------------------------------------------------- week ahead
# The Sunday catalyst map. Same principle as the daily reports: the shell (meta,
# title, CSS) is lifted verbatim from a known-good page and the body is generated
# from data, so a week's content can never drift the layout.
WEEKAHEAD_SECTIONS = ['lede', 'heroes', 'days', 'watch', 'howto']


def weekahead_shell(base_path):
    """Everything above the first content div - meta, title, style."""
    h = open(base_path, encoding='utf-8').read()
    i = h.find('<div class="hdr">')
    if i < 0:
        raise ValueError(f'{base_path}: no .hdr block - not a week-ahead base')
    return h[:i]


# A heavy earnings day carries 20 names. One row per ticker made Wednesday and
# Thursday tower over Monday and pushed the company events below the fold, so
# earnings render as wrapped AM/PM chips instead - same information, roughly a
# quarter of the height, and the columns stay comparable.
WA_EARN_CAP = 8


def _wa_earnings(rows, cap=WA_EARN_CAP):
    """Render the names that matter and count the tail.

    A heavy day carries 20 reports, most of which nobody trades. Listing all of
    them buries the four that move the tape. Every name flagged hot is always
    shown; the rest fill up to `cap` and whatever is left becomes a single
    "+N more" chip. The count is still visible on the section header, so nothing
    is hidden - it just stops competing for attention.
    """
    keep, tail = [], []
    for r in rows:
        (keep if r[2] else tail).append(r)
    room = max(0, cap - len(keep))
    keep, dropped = keep + tail[:room], tail[room:]
    keep = [r for r in rows if r in keep]          # restore the authored order

    def bucket(w):
        u = str(w).upper()
        return 'AM' if u.startswith('AM') else ('PM' if u.startswith('PM') else '')

    def detail(w):
        """Keep any time detail after the AM/PM marker - e.g. 'PM &middot; 3:20pm'."""
        w = str(w)
        if '&middot;' in w:
            return w.split('&middot;', 1)[1].strip()
        return '' if bucket(w) or w in ('&mdash;', '-', '') else w

    out = []
    for label in ('AM', 'PM', ''):
        grp = [r for r in keep if bucket(r[1]) == label]
        if not grp:
            continue
        chips = []
        for sym, when, hot in grp:
            d = detail(when)
            ex = f' <span class="tkt">{d}</span>' if d else ''
            # hot is a bool for "matters", or the string 'lead' for the one name
            # that defines the day. Both are truthy, so the keep/cap logic above
            # is unaffected.
            tier = ' lead' if hot == 'lead' else (' hot' if hot else '')
            chips.append(f'<span class="tick{tier}">{sym}{ex}</span>')
        lbl = f'<span class="tgrp">{label}</span>' if label else ''
        out.append(f'<div class="eern">{lbl}{"".join(chips)}</div>')
    if dropped:
        out.append(f'<div class="eern"><span class="tick more">+{len(dropped)} more</span></div>')
    return ''.join(out)


def _wa_days(days):
    out = []
    for d in days:
        cls = 'day big' if d.get('big') else 'day'
        pill = (f' &nbsp;<span class="pill {d.get("pill_cls","b")}">{d["pill"]}</span>'
                if d.get('pill') else '')
        s = [f'<div class="{cls}">', f'<div class="dname">{d["name"]}{pill}</div>',
             f'<div class="dnote">{d["note"]}</div>']
        for label, key in (('Economic', 'econ'), ('Earnings', 'earnings'),
                           ('Company Events', 'events')):
            rows = d.get(key) or []
            # An empty section used to print "None on file", which cost a line in
            # every column and read like a data failure. A day with no economic
            # release simply has no economic block now.
            if not rows:
                continue
            # No count badge here - the "+N more" chip already carries the tail,
            # and showing both said the same thing twice.
            s.append(f'<div class="sec">{label}</div>')
            if key == 'earnings':
                s.append(_wa_earnings(rows))
            else:
                for ev in rows:
                    t, desc = ev[0], ev[1]
                    key = len(ev) > 2 and ev[2]
                    cls = 'ev key' if key else 'ev'
                    s.append(f'<div class="{cls}"><span class="evt">{t}</span>'
                             f'<div class="evd">{desc}</div></div>')
        s.append('</div>')
        out.append('\n'.join(s))
    return '\n\n'.join(out)


# Layered onto the shell at build time so the base page stays untouched and
# already-written week-ahead files keep rendering exactly as they were.
WA_CSS = '''<style>
.day{display:flex;flex-direction:column}
.sec{display:flex;align-items:center;gap:5px}
.sec .cnt{font-size:7px;font-weight:800;color:var(--tx3);background:var(--bg-page);
  border:1px solid var(--border-s);border-radius:7px;padding:1px 5px;letter-spacing:0}
.eern{display:flex;flex-wrap:wrap;gap:3px;align-items:center;margin-bottom:3px}
.tgrp{font-size:7px;font-weight:800;letter-spacing:.1em;color:#3d444d;margin-right:2px}
.tick{font-size:9px;font-weight:700;color:var(--tx2);background:var(--bg-page);
  border:1px solid var(--border-s);border-radius:3px;padding:1px 4px;line-height:1.6;
  white-space:nowrap}
.tick.hot{color:var(--gold);border-color:#9e6a03;background:#2b1d0e}
/* the one name that defines the day - filled, not just outlined, so it reads
   before anything else in the column */
.tick.lead{color:#0b0e15;background:var(--gold);border-color:var(--gold);
  font-size:10px;font-weight:800;letter-spacing:.03em;padding:2px 6px}
.tick.lead .tkt{opacity:.75;font-weight:700}
.tick.more{color:#3d444d;border-style:dashed;background:none}
/* three weights inside a day column: key row > <strong> name > body */
.ev.key{border-left:2px solid var(--gold);padding-left:7px;margin-left:-9px;
  background:linear-gradient(90deg,rgba(227,179,65,.07),transparent 60%)}
.ev.key .evt{color:var(--gold)}
.ev.key .evd{color:var(--tx2)}
.evd b{color:var(--gold);font-weight:700}
/* the release name was competing with its own description - lift it out */
.evd strong{color:var(--tx1);font-weight:700}
.day.big .dnote{color:var(--tx4);font-style:normal}
.tick .tkt{font-size:8px;font-weight:600;opacity:.8;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.day.big .tick.hot{border-color:var(--gold)}
</style>'''


def build_weekahead(data, base):
    """Assemble the Sunday week-ahead page from a data dict."""
    head = weekahead_shell(base)
    head = re.sub(r'<title>[^<]*</title>',
                  f'<title>Week Ahead &mdash; {data["title"]}</title>', head)
    if '</head>' in head:
        head = head.replace('</head>', WA_CSS + '\n</head>', 1)
    else:
        head += WA_CSS

    heroes = '\n'.join(
        f'<div class="hcard {h.get("cls","")}">'
        f'<div class="hrank">{h["rank"]}</div>'
        f'<div class="htitle">{h["title"]}</div>'
        f'<div class="hwhen">{h["when"]}</div>'
        f'<div class="hwhy">{h["why"]}</div></div>' for h in data['heroes'])

    watch = '\n'.join(
        f'<div class="cl"><div class="cld">{w["date"]}</div>'
        f'<div class="clt" style="color:{w.get("color","var(--tx3)")}">{w["ticker"]}</div>'
        f'<div class="clb">{w["body"]}</div></div>' for w in data['watch'])

    howto = '\n'.join(
        f'<p style="margin-bottom:8px;"><strong style="color:var(--tx1)">{t}</strong> {b}</p>'
        for t, b in data['howto'])

    body = f'''<div class="hdr">
  <div>
    <h1>Week Ahead &mdash; Catalyst Map</h1>
    <div class="sub">{data["range"]} &middot; {data["published"]}</div>
  </div>
</div>

<div class="warn">{data["lede"]}</div>

<div class="hero">
{heroes}
</div>

<div class="card">
  <div class="ch"><span>The Week, Day by Day</span><span style="color:var(--tx3);font-weight:600;letter-spacing:0;text-transform:none;">All times Central</span></div>
  <div class="scroll"><div class="grid">
{_wa_days(data["days"])}
  </div></div>
</div>

<div class="card">
  <div class="ch"><span>Catalyst Watch &mdash; from the standing calendar</span><span style="color:var(--tx3);font-weight:600;letter-spacing:0;text-transform:none;">catalysts.json</span></div>
  <div class="pad">
{watch}
  </div>
</div>

<div class="card">
  <div class="ch">How to Trade the Shape of This Week</div>
  <div class="pad" style="font-size:11px;color:var(--tx4);line-height:1.7">
{howto}
  </div>
</div>

<div class="foot">{data["foot"]}</div>
'''
    return head + body


def validate_weekahead(html, n_days=5):
    errs = []
    if _depth(html) != 0:
        errs.append(f'whole-file div depth {_depth(html):+d}')
    if html.count('class="day') != n_days:
        errs.append(f'{html.count(chr(34)+"day")} day columns, expected {n_days}')
    if 'SAMPLE' in html:
        errs.append('SAMPLE badge still present')
    for lbl in ('The Week, Day by Day', 'Catalyst Watch', 'How to Trade'):
        if lbl not in html:
            errs.append(f'missing section: {lbl}')
    if errs:
        raise AssertionError('WEEK-AHEAD INVALID:\n  - ' + '\n  - '.join(errs))
    return True


def write_weekahead(path, data, base):
    html = build_weekahead(data, base)
    validate_weekahead(html, n_days=len(data['days']))
    open(path, 'w', encoding='utf-8').write(html)
    return path


# ================================================================= daily report
# WHY THIS EXISTS
# ---------------
# The week-ahead was already data-driven: weekahead/DATE.json holds facts,
# write_weekahead() renders them. The DAILY report was not - every morning meant
# a fresh ~490-line Python file, ~39% of which was identical renderer code, with
# all the prose living inside Python string literals.
#
# That cost real money in reliability. Patching those files with str.replace()
# fails SILENTLY when a string does not match, and it did: a stale headline
# shipped on 8/25 and was only caught because a verification count looked odd.
# Two other builds died on syntax errors from string surgery (an eaten "]" on
# 8/27, a quote mismatch on 8/28) minutes before the open.
#
# Now the daily follows the week-ahead's pattern: one dict of facts in, rendered
# HTML out. Prose is data, not code. Edits are dict operations that raise on a
# missing key instead of quietly doing nothing.

# Data files name colours, not hex - keeps palette drift out of the content.
PALETTE = {'g': '#3fb950', 'r': '#f85149', 'y': '#ffd54f', 'o': '#f0883e',
           'b': '#58a6ff', 'p': '#a78bfa', 'gold': '#e3b341', 'mute': 'var(--tx2)'}


def _c(key):
    """Resolve a palette key, or pass a literal colour straight through."""
    return PALETTE.get(key, key)


def _pct(now, prev):
    return (now - prev) / prev * 100.0


def _sg(p, d=1):
    return ('+' if p >= 0 else '&minus;') + f'{abs(p):.{d}f}%'


def _chg(p):
    return (f'<span class="chg {"up" if p >= 0 else "down"}">'
            f'{"+" if p >= 0 else "-"}{abs(p):.1f}%</span>')


# ---------------------------------------------------------------- watchlist
EM_GOLD_AT = 5.0     # implied move at or above this prints gold, not purple


def watchlist(groups, focus=(), em=None, stamp='', em_label=''):
    """Watchlist pills. groups/focus rows are [symbol, now, prior_close].

    `em` maps symbol -> implied move %, rendered as the expected-move badge that
    the report_lib migration originally dropped. Gold at/above EM_GOLD_AT.
    """
    em = em or {}

    def badge(sym):
        if sym not in em:
            return ''
        v = float(em[sym])
        col = PALETTE['gold'] if v >= EM_GOLD_AT else PALETTE['p']
        return (f'<span style="font-size:9px;font-weight:700;color:{col};margin-top:2px;'
                f'white-space:nowrap;">&plusmn;{v:.1f}%</span>')

    right = stamp
    if em_label:
        right += f' &middot; <span style="color:{PALETTE["p"]};">{em_label}</span>'
    h = (CARD + '<div style="background:var(--bg-page);padding:8px 14px;border-bottom:1px solid var(--border-s);'
         'font-size:9px;font-weight:700;letter-spacing:.12em;color:var(--tx2);text-transform:uppercase;">'
         f'{LABELS["watchlist"]} &mdash; ETFs &amp; Mag 11'
         f'<span style="float:right;color:#f0883e;">{right}</span></div>'
         '<div style="overflow-x:auto;"><div class="watchlist-grid">')
    for label, rows in groups:
        h += f'<span class="wl-group-label">{label}</span>'
        for sym, now, prev in rows:
            h += (f'<div class="wl-pill"><span class="sym">{sym}</span>'
                  f'{_chg(_pct(now, prev))}{badge(sym)}</div>')
    if focus:
        h += '<span class="wl-group-label">Focus</span>'
        for sym, now, prev in focus:
            p = _pct(now, prev)
            bc, bg = (PALETTE['g'], '#0f2a17') if p >= 0 else (PALETTE['r'], '#2d0f0f')
            h += (f'<div class="wl-pill" style="border-color:{bc};background:{bg};">'
                  '<div style="display:flex;align-items:center;gap:3px;white-space:nowrap;">'
                  f'<span class="sym" style="color:{bc};">&#9733; {sym}</span></div>'
                  f'{_chg(p)}</div>')
    return h + '</div></div></div>'


# ---------------------------------------------------------------- headline
def headline(title, summary):
    return (CARD + f'<div style="padding:14px 16px;"><div class="headline-title">{title}</div>'
            f'<div class="headline-summary">{summary}</div></div></div>')


# ---------------------------------------------------------------- charts
# Restored 2026-08-24. catalyst_scan.generate_chart() had been writing PNGs to
# reports/charts/ daily for months; nothing embedded one after the report_lib
# migration because SPEC named the row 'chart_trumpwatch' but LABELS had no
# 'chart' key and no builder existed - so validate() could not see the absence.
def charts(items, note='SWIPE &#8594;', label='Charts'):
    if not items:
        return ''
    blocks = ''
    for sym, src, meta in items:
        blocks += ('<div class="chart-block" style="width:auto;flex:0 0 94%;">'
                   '<div class="chart-label">'
                   f'<span class="ticker" style="font-weight:800;color:var(--tx1);">{sym}</span>'
                   f'<span class="meta">{meta}</span></div>'
                   f'<img src="{src}" alt="{sym} daily chart"></div>')
    return ('<div style="background:var(--bg-card);border-bottom:1px solid var(--border-s);">'
            '<div style="background:var(--bg-page);padding:8px 14px;border-bottom:1px solid var(--border-s);'
            'font-size:9px;font-weight:700;letter-spacing:.12em;color:var(--tx2);text-transform:uppercase;">'
            f'{label}<span style="float:right;color:var(--tx2);font-weight:600;">{note}</span></div>'
            f'<div class="charts-grid" style="overflow-x:auto;">{blocks}</div></div>')


# ---------------------------------------------------------------- trump watch
def trumpwatch(groups, stamp=''):
    body = ''
    for name, syms in groups:
        body += ('<div style="display:flex;flex-direction:column;padding-right:14px;">'
                 '<span style="font-size:8px;font-weight:700;letter-spacing:.12em;color:#3d444d;'
                 f'text-transform:uppercase;margin-bottom:4px;">{name}</span>')
        for sym, p in syms:
            body += ('<div style="display:flex;align-items:center;gap:6px;padding:2px 0;">'
                     '<span style="font-family:monospace;font-weight:700;font-size:11px;'
                     f'color:var(--tx1);min-width:40px;">{sym}</span>'
                     f'<span style="font-size:10px;font-weight:600;" class="chg '
                     f'{"up" if p >= 0 else "down"}">{"+" if p >= 0 else "-"}{abs(p):.1f}%</span></div>')
        body += '</div>'
    return ('<div style="border-top:1px solid #21262d;flex:1;min-width:0;display:flex;'
            'flex-direction:column;overflow-y:auto;">'
            '<div style="background:var(--bg-page);padding:8px 14px;border-bottom:1px solid var(--border-s);'
            'font-size:9px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#ffd54f;">'
            f'{LABELS["trumpwatch"]}'
            f'<span style="float:right;color:var(--tx2);font-weight:600;">{stamp}</span></div>'
            '<div style="display:flex;flex-wrap:nowrap;overflow-x:auto;gap:6px 0;padding:10px 14px;'
            f'align-items:flex-start;">{body}</div></div>')


# ---------------------------------------------------------------- strat setups
def strat_setups(rows, stamp=''):
    """rows: [sym, tier, tier_colour_key, name, name_colour_key, why, levels, bull, bear]"""
    out = ''
    for sym, tier, tc, name, nc, why, lvl, bull, bear in rows:
        out += ('<div class="setup-row"><div style="flex:0 0 58px;">'
                f'<div class="setup-ticker">{sym}</div>'
                f'<div style="font-size:9px;font-weight:800;color:{_c(tc)};">{tier}</div>'
                f'<div style="font-size:9px;font-weight:700;color:{_c(nc)};margin-top:1px;">{name}</div></div>'
                '<div style="flex:1;min-width:0;">'
                f'<div class="setup-why">{why}</div>'
                '<div style="font-size:10px;color:#58a6ff;font-family:monospace;font-weight:600;'
                f'margin-top:3px;">{lvl}</div>'
                f'<div style="font-size:10px;color:{PALETTE["g"]};margin-top:2px;line-height:1.4;">'
                f'&#9650; {bull}</div>'
                f'<div style="font-size:10px;color:{PALETTE["r"]};margin-top:2px;line-height:1.4;">'
                f'&#9660; {bear}</div></div></div>')
    return (COL_R + '<div style="background:var(--bg-page);padding:8px 14px;'
            'border-bottom:1px solid var(--border-s);font-size:9px;font-weight:700;letter-spacing:.12em;'
            'color:var(--tx2);text-transform:uppercase;margin:-14px -14px 10px;">'
            f'{LABELS["strat_setups"]}'
            f'<span style="float:right;color:var(--tx2);font-weight:600;">{stamp}</span></div>'
            + out + '</div>')


# ---------------------------------------------------------------- gappers
def _gapcard(label, rows, colour):
    body = ''
    for sym, p, why in rows:
        body += ('<div style="display:flex;align-items:center;gap:6px;padding:5px 0;'
                 'border-bottom:1px solid var(--border-s);font-size:12px;">'
                 f'<span style="font-weight:700;font-size:13px;color:var(--tx1);min-width:52px;">{sym}</span>'
                 f'<span style="font-weight:700;color:{colour};min-width:56px;">{_sg(p, 2)}</span>'
                 f'<span style="color:var(--tx4);font-size:11px;flex:1;">{why}</span></div>')
    return card(label, f'<div style="padding:8px 14px 10px;">{body}</div>')


def gappers(bull, bear):
    return row('<div style="flex:0 0 50%;min-width:0;overflow:hidden;display:flex;flex-direction:column;">'
               + _gapcard(LABELS['bullish_gappers'], bull, PALETTE['g']) + '</div>',
               '<div style="flex:0 0 50%;background:var(--bg-card);padding:14px;overflow-y:auto;'
               'display:flex;flex-direction:column;">'
               + _gapcard(LABELS['bearish_gappers'], bear, PALETTE['r']) + '</div>')


# ---------------------------------------------------------------- dark pool
def darkpool(note, chips, right_note='', dim=False):
    """chips: [symbol, amount, side_label, colour_key]. `dim` for carried-forward
    boards that are context only, never today's positioning."""
    op = 'opacity:.72;' if dim else ''
    body = f'<div style="font-size:10px;color:var(--tx4);width:100%;margin-bottom:6px;">{note}</div>'
    for sym, amt, side, ckey in chips:
        body += ('<div style="display:flex;flex-direction:column;align-items:center;'
                 f'background:var(--bg-hover);border-radius:4px;padding:8px 12px;min-width:88px;{op}">'
                 f'<span style="font-weight:700;font-size:13px;color:var(--tx1);">{sym}</span>'
                 f'<span style="font-size:12px;color:#ffd54f;font-weight:600;">{amt}</span>'
                 f'<span style="font-size:10px;font-weight:700;color:{_c(ckey)};">{side}</span></div>')
    return card(LABELS['darkpool'],
                f'<div style="display:flex;flex-wrap:wrap;gap:6px;padding:12px 14px;">{body}</div>',
                right_note=right_note)


# ---------------------------------------------------------------- assembly
DAILY_REQUIRED = ('title', 'kind', 'watchlist', 'headline', 'tts')


def build_daily(data, base):
    """Assemble a premarket report body from a data dict, then wrap it.

    Missing keys raise rather than rendering an empty section - the whole point
    of the port is that a mistake stops the build instead of shipping quietly.
    """
    for k in DAILY_REQUIRED:
        if k not in data:
            raise KeyError(f'daily data missing required key: {k}')
    kind = data['kind']
    if kind != 'premarket':
        raise ValueError('build_daily currently renders premarket only')

    w = data['watchlist']
    body = watchlist(w['groups'], w.get('focus', ()), w.get('em'),
                     w.get('stamp', ''), w.get('em_label', ''))
    body += headline(data['headline']['title'], data['headline']['summary'])

    p = data['prep']
    body += row(col_l(27) + overview(data['overview']) + top_setups(data['setups']) + '</div>',
                prep(p['pill'], p['lead'], p['cards']))
    body += thisweek(data['thisweek'])

    left = charts(data.get('charts', []), data.get('charts_note', 'SWIPE &#8594;'))
    t = data['trump']
    body += row(COL_L + left + trumpwatch(t['groups'], t.get('stamp', '')) + '</div>',
                strat_setups(data['strat']['rows'], data['strat'].get('stamp', '')))

    g = data['gappers']
    body += gappers(g['bull'], g['bear'])

    d = data['darkpool']
    body += darkpool(d['note'], d['chips'], d.get('right_note', ''), d.get('dim', False))

    return build(base, kind, data['title'], data['tts'], body)


def write_daily(path, data, base, index=True):
    html = build_daily(data, base)
    return write(path, html, data['kind'], index=index)


# ---------------------------------------------------------------- close report
# The close sections. Same contract as the premarket renderers: data in, HTML
# out, no per-day scripts. Shapes match the shipped template exactly - these
# were read off a real close report rather than invented.

def _stack(items, pad='6px 14px 10px', lead_size=12, body_size=11, lh=1.55):
    """Repeated 'bold coloured lead + body' block. what_happened and lessons
    are the same widget with different padding."""
    out = f'<div style="padding:{pad};">'
    for title, col, body in items:
        out += ('<div style="padding:9px 0;border-bottom:1px solid var(--border-s);">'
                f'<div style="font-size:{lead_size}px;font-weight:700;color:{_c(col)};'
                f'margin-bottom:3px;">{title}</div>'
                f'<div style="font-size:{body_size}px;color:var(--tx4);line-height:{lh};">'
                f'{body}</div></div>')
    return out + '</div>'


def what_happened(items, label='What Happened Today'):
    """items: [(title, colour, body), ...] - left column of the results row."""
    return card(label, _stack(items))


def lessons(items, label='Lessons of the Day'):
    """items: [(title, colour, body), ...]"""
    return card(label, _stack(items, pad='6px 16px 10px', lh=1.6))


def picks_results(rows, right_note='', label='Top-3 Picks &mdash; Results'):
    """rows: [(sym, chg, chg_colour, tag, tag_colour, called, body), ...]

    `called` is what the morning report actually said - quoted back verbatim so
    the grade is against the real call, not a remembered one.
    """
    out = col_r(58) + HDR.format(
        label, (f'<span style="font-size:9px;font-weight:700;color:#f0883e;">'
                f'{right_note}</span>') if right_note else '')
    out += '<div style="padding:6px 14px 10px;">'
    for sym, chg, cc, tag, tc, called, body in rows:
        out += ('<div style="padding:9px 0;border-bottom:1px solid var(--border-s);">'
                '<div style="display:flex;align-items:baseline;gap:8px;margin-bottom:3px;'
                'flex-wrap:wrap;">'
                f'<span style="font-size:14px;font-weight:800;color:var(--tx1);">{sym}</span>'
                f'<span style="font-size:13px;font-weight:700;color:{_c(cc)};">{chg}</span>'
                f'<span style="font-size:8px;font-weight:800;letter-spacing:.08em;'
                f'color:{_c(tc)};">{tag}</span></div>'
                f'<div style="font-size:10px;color:var(--tx3);font-style:italic;'
                f'margin-bottom:3px;">Called: {called}</div>'
                f'<div style="font-size:11px;color:var(--tx4);line-height:1.55;">{body}</div>'
                '</div>')
    return out + '</div></div>'


def how_played_out(paras, label='How Setups Played Out'):
    """paras: [(lead, body), ...] - rendered as one prose block, blank line between."""
    inner = '<br>\n<br>\n'.join(
        f'<b style="color:var(--tx1);">{lead}</b> {body}' for lead, body in paras)
    return card(label, '<div style="padding:12px 16px;font-size:11px;color:var(--tx4);'
                       f'line-height:1.7;">{inner}</div>')


def sector_perf(rows, right_note='', label='Sector Performance'):
    """rows: [(sym, name, pct), ...] - bar width is relative to the biggest |move|."""
    peak = max((abs(p) for _, _, p in rows), default=0) or 1
    out = '<div style="padding:10px 16px 12px;">'
    for sym, name, pct in rows:
        col = '#3fb950' if pct >= 0 else '#f85149'
        w = round(abs(pct) / peak * 100)
        out += ('<div style="display:flex;align-items:center;gap:8px;padding:4px 0;">'
                f'<span style="font-weight:700;font-size:11px;color:var(--tx1);'
                f'min-width:46px;">{sym}</span>'
                f'<span style="font-size:10px;color:var(--tx3);min-width:92px;">{name}</span>'
                f'<span style="font-weight:700;font-size:11px;color:{col};'
                f'min-width:56px;">{_sg(pct, 2)}%</span>'
                '<span style="flex:1;height:5px;background:var(--bg-hover);border-radius:3px;'
                'overflow:hidden;">'
                f'<span style="display:block;height:100%;width:{w}%;background:{col};'
                'border-radius:3px;"></span></span></div>')
    return card(label, out + '</div>',
                right_note) if right_note else card(label, out + '</div>')


def watch_tomorrow(items, label='Watch Tomorrow'):
    """items: [(ticker_or_empty, colour, text), ...] - blank ticker = prose row."""
    out = '<div style="padding:6px 16px 10px;">'
    for tk, col, text in items:
        chip = (f'<span style="font-weight:800;font-size:12px;color:{_c(col)};'
                f'min-width:52px;display:inline-block;">{tk}</span>') if tk else ''
        out += ('<div style="padding:7px 0;border-bottom:1px solid var(--border-s);'
                f'font-size:11px;color:var(--tx4);line-height:1.6;">{chip}{text}</div>')
    return card(label, out + '</div>')


CLOSE_REQUIRED = ('title', 'kind', 'watchlist', 'headline', 'what_happened',
                  'picks', 'how_played_out', 'sectors', 'lessons', 'tomorrow', 'tts')


def build_close(data, base):
    """Assemble an after-close report body from a data dict, then wrap it.

    Mirrors build_daily: every section comes from the dict, a missing key raises,
    and SPEC['close'] is the only source of section order.
    """
    for k in CLOSE_REQUIRED:
        if k not in data:
            raise KeyError(f'close data missing required key: {k}')
    if data['kind'] != 'close':
        raise ValueError(f"build_close renders kind 'close', got {data['kind']!r}")

    w = data['watchlist']
    body = watchlist(w['groups'], w.get('focus', ()), w.get('em'),
                     w.get('stamp', ''), w.get('em_label', ''))
    body += headline(data['headline']['title'], data['headline']['summary'])

    p = data['picks']
    body += row(col_l(42) + what_happened(data['what_happened']) + '</div>',
                picks_results(p['rows'], p.get('right_note', '')))
    body += thisweek(data['thisweek'])

    left = charts(data.get('charts', []), data.get('charts_note', 'SWIPE &#8594;'))
    t = data['trump']
    body += row(COL_L + left + trumpwatch(t['groups'], t.get('stamp', '')) + '</div>',
                strat_setups(data['strat']['rows'], data['strat'].get('stamp', '')))

    body += how_played_out(data['how_played_out'])
    d = data['darkpool']
    body += darkpool(d['note'], d['chips'], d.get('right_note', ''), d.get('dim', False))
    s = data['sectors']
    body += sector_perf(s['rows'], s.get('right_note', ''))
    body += lessons(data['lessons'])
    body += watch_tomorrow(data['tomorrow'])

    return build(base, data['kind'], data['title'], data['tts'], body)
