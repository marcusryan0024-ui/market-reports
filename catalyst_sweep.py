#!/usr/bin/env python3
"""Forward sweeps of the catalyst calendar, and the record that proves they happened.

WHY THIS EXISTS
---------------
On 2026-09-13 the week-ahead for 9/14-9/18 published "no verified slate for this
week sits in catalysts.json". OSCR's Investor Day and Salesforce's Dreamforce
investor session were both scheduled for 9/16 and had been public for weeks.

The git history explains it exactly. A sweep that looked more than 7 days ahead
happened ONCE, on 2026-08-13, the day catalysts.json was created. Every long-lead
entry the file ever held came from that one day - QCOM 40 days out, COST 42, NVDA
and AAPL 13, Jackson Hole 14. Then, for the thirty days from 8/14 to 9/12, not a
single event more than a week out was added. The horizon was set once and decayed
one day per day until it reached zero.

What fed the file instead was same-day transcription: the FlowMS morning
newsletter, prep sheets, a corporate-calendar screenshot. Median lead time across
all 37 dated events was ONE DAY, and 17 of them were entered on or after the day
the event happened. A morning newsletter describes today. It cannot see forward,
so neither could the calendar.

So the failure was never "the file went stale". There was no mechanism whose job
was to look ahead. This module is that mechanism, and - more importantly - it is
the RECORD of it, because the thing that actually went wrong is that nobody could
tell the difference between "swept, nothing there" and "nobody looked".

THE INTEGRITY RULE
------------------
coverage_through() is DERIVED from recorded sweeps. It is never asserted. An
earlier version of today's fix hand-set checked_through to a date, which is the
same unearned claim in miniature - a number saying "trust me" with nothing
behind it. Here, the only way the horizon moves is for a sweep to be recorded
with what was searched and what it found. A sweep you did not do is a sweep you
cannot write down.

Consequence: this deliberately BLOCKS builds when the horizon runs out. That is
the feature. The alternative is what already happened - pages that quietly
describe an empty week because nobody had looked at it.
"""
import sys, os, json, datetime as _dt
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
CAL = os.path.join(HERE, 'catalysts.json')

# How far ahead a sweep should reach. Five days - what the daily build needs -
# would have found OSCR on 9/11: five days late instead of never, which is not
# the point. Three weeks is roughly the horizon at which an investor day is
# still actionable rather than merely known.
HORIZON_DAYS = 30

# A universe sweep older than this is decaying toward the 8/13 failure. Warn
# before the horizon actually runs out, not after.
STALE_AFTER_DAYS = 7


def load(path=CAL):
    return json.load(open(path, encoding='utf-8'), object_pairs_hook=OrderedDict)


def save(cal, path=CAL):
    json.dump(cal, open(path, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    open(path, 'a', encoding='utf-8').write('\n')


def universe(cal=None):
    """Every name a sweep is responsible for: the user list plus Mag 11."""
    u = (cal or load())['universe']
    return sorted(set(u.get('user_list', [])) | set(u.get('mag11_baseline', [])))


def sweeps(cal=None):
    return ((cal or load()).get('coverage') or {}).get('sweeps', [])


def coverage_through(cal=None):
    """The furthest date the calendar has actually been swept to.

    Only scope='universe' sweeps move this. A single-ticker lookup tells you
    about that ticker, not about the week - counting it here would let one
    convenient check vouch for fifty names nobody opened.
    """
    ds = [s['through'] for s in sweeps(cal) if s.get('scope') == 'universe'
          and s.get('through')]
    return max(ds) if ds else None


def last_universe_sweep(cal=None):
    ds = [s['on'] for s in sweeps(cal) if s.get('scope') == 'universe' and s.get('on')]
    return max(ds) if ds else None


def record(through, method, found=(), scope='universe', on=None, path=CAL):
    """Write down a sweep that was actually performed.

    `method` is not decoration - it is the audit trail. It must say what was
    searched, because the whole point is that a future reader can tell whether
    the horizon was earned or asserted.
    """
    if not method or len(str(method).strip()) < 20:
        raise ValueError('record() needs a real `method`: what did you actually '
                         'search? This is the only evidence the sweep happened.')
    cal = load(path)
    cov = cal.setdefault('coverage', OrderedDict())
    cov.setdefault('sweeps', [])
    cov['sweeps'].append(OrderedDict([
        ('on', on or _dt.date.today().isoformat()),
        ('scope', scope),
        ('through', through),
        ('found', list(found)),
        ('method', method),
    ]))
    cov['sweeps'].sort(key=lambda s: (s.get('on', ''), s.get('through', '')))
    # Kept only so a human reading the raw file sees the derived answer; every
    # consumer must call coverage_through(), never trust this line.
    cov['checked_through'] = coverage_through(cal)
    cov['_derived'] = ('checked_through is DERIVED from coverage.sweeps by '
                       'catalyst_sweep.coverage_through(). Never hand-edit it - '
                       'record a sweep instead.')
    save(cal, path)
    return cov['checked_through']


def status(cal=None, today=None):
    """Three states again, because that is the lesson this file is named after."""
    cal = cal or load()
    today = today or _dt.date.today().isoformat()
    through = coverage_through(cal)
    last = last_universe_sweep(cal)
    age = ((_dt.date.fromisoformat(today) - _dt.date.fromisoformat(last)).days
           if last else None)
    horizon = ((_dt.date.fromisoformat(through) - _dt.date.fromisoformat(today)).days
               if through else None)
    if through is None:
        state = 'UNSWEPT'
    elif horizon is not None and horizon < 0:
        state = 'EXPIRED'
    elif age is not None and age > STALE_AFTER_DAYS:
        state = 'DECAYING'
    else:
        state = 'OK'
    return OrderedDict([
        ('state', state), ('through', through), ('horizon_days', horizon),
        ('last_sweep', last), ('sweep_age_days', age),
        ('universe', len(universe(cal))), ('sweeps_recorded', len(sweeps(cal))),
    ])


def worklist(cal=None, today=None, horizon_days=HORIZON_DAYS):
    """What the next sweep has to cover to get back to a full horizon."""
    cal = cal or load()
    today = _dt.date.fromisoformat(today or _dt.date.today().isoformat())
    target = today + _dt.timedelta(days=horizon_days)
    through = coverage_through(cal)
    start = (max(today, _dt.date.fromisoformat(through) + _dt.timedelta(days=1))
             if through else today)
    names = universe(cal)
    recur = cal['universe'].get('recurring_patterns', {})
    return OrderedDict([
        ('sweep_from', start.isoformat()),
        ('sweep_to', target.isoformat()),
        ('days_uncovered', max(0, (target - start).days + 1)),
        ('names', names),
        ('recurring_to_confirm', {k: v for k, v in recur.items() if k != '_note'}),
    ])


def _cli(argv):
    cmd = argv[1] if len(argv) > 1 else 'status'
    if cmd == 'status':
        st = status()
        print(f"catalyst sweep: {st['state']}")
        for k in ('through', 'horizon_days', 'last_sweep', 'sweep_age_days',
                  'universe', 'sweeps_recorded'):
            print(f'  {k:16} {st[k]}')
        if st['state'] != 'OK':
            print(f"\n  -> run: python3 {os.path.basename(__file__)} worklist")
        return 0 if st['state'] == 'OK' else 1
    if cmd == 'worklist':
        w = worklist()
        print(f"sweep {w['sweep_from']} -> {w['sweep_to']} "
              f"({w['days_uncovered']} uncovered days)")
        print(f"\n  {len(w['names'])} names:")
        ns = w['names']
        for i in range(0, len(ns), 10):
            print('    ' + ' '.join(f'{n:6}' for n in ns[i:i + 10]))
        print('\n  recurring patterns to confirm against IR:')
        for k, v in w['recurring_to_confirm'].items():
            print(f'    {k:6} {v[:88]}')
        print('\n  SWEEP WITH THESE, IN THIS ORDER:')
        print('    1. The weekly Catalyst Watch newsletter (day-by-day schedule).')
        print('    2. An events calendar (Wall-Street-Horizon style), day tabs.')
        print('    3. The broker earnings calendar, for the earnings layer only.')
        print('    4. Company IR - ONLY to confirm a specific event and its time.')
        print('\n  Web search is step 4, never step 1. On 2026-09-13 a general-search')
        print('  sweep of this exact window missed August Retail Sales, the Bank of')
        print('  England decision, Bessent\'s testimony, INTU\'s investor day, ON Semi\'s')
        print('  analyst day and the SEC 24-hour-trading roundtable. Search surfaces')
        print('  what got PRESS-RELEASED; it does not enumerate a schedule.')
        print('\n  look for: investor/analyst days, product events, conferences,')
        print('            macro releases, central-bank decisions, regulatory hearings,')
        print('            monthly sales/delivery reports, FDA dates, splits.')
        print('  then:     catalyst_sweep.record(through=..., method=..., found=[...])')
        return 0
    if cmd == 'sweeps':
        for s in sweeps():
            print(f"  {s.get('on')}  scope={s.get('scope'):9} through={s.get('through')}  "
                  f"found={len(s.get('found', []))}")
            print(f"      {s.get('method','')[:150]}")
        return 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(_cli(sys.argv))
