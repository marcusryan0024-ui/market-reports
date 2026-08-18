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

    grid = ('<div style="overflow-x:auto;"><div style="display:grid;'
            'grid-template-columns:repeat(5, minmax(240px, 1fr));gap:1px;background:#21262d;'
            f'min-width:1200px;">{cols}</div></div>')
    return (CARD + HDR.format(LABELS['thisweek'], '') + grid + '</div>')


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
    """cards: [(ticker, setup_name, name_colour, tier, read, plan, bull, bear, note), ...]"""
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
            s.append(f'<div class="sec">{label}</div>')
            rows = d.get(key) or []
            if not rows:
                s.append('<div class="ev"><div class="evd" style="color:var(--tx3);'
                         'font-style:italic;">None on file</div></div>')
            elif key == 'earnings':
                for sym, when, hot in rows:
                    k = 'sym hot' if hot else 'sym'
                    s.append(f'<div class="row"><span class="{k}">{sym}</span>'
                             f'<span class="when">{when}</span></div>')
            else:
                for t, desc in rows:
                    s.append(f'<div class="ev"><span class="evt">{t}</span>'
                             f'<div class="evd">{desc}</div></div>')
        s.append('</div>')
        out.append('\n'.join(s))
    return '\n\n'.join(out)


def build_weekahead(data, base):
    """Assemble the Sunday week-ahead page from a data dict."""
    head = weekahead_shell(base)
    head = re.sub(r'<title>[^<]*</title>',
                  f'<title>Week Ahead &mdash; {data["title"]}</title>', head)

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
