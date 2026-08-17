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
import json, re, os, glob, html as _html

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


def write(path, html, kind, index=True):
    validate(html, kind)
    open(path, 'w', encoding='utf-8').write(html)
    if index:
        refresh_index(os.path.dirname(os.path.abspath(path)))
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
