#!/usr/bin/env python3
"""Render an after-close report from its data file.

    python3 make_close.py 2026-08-31

Reads close/<date>.json, renders through report_lib, writes <date>.html, adds
the index row, advances the featured card, and validates. Same contract as
make_daily.py - the data file holds facts and prose, report_lib holds every
renderer, and a missing key raises instead of shipping a stale page.
"""
import sys, os, json, datetime as _dt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import report_lib as R


def prior_close(date, dirpath='.'):
    """Newest existing close report before `date` - used as the shell base."""
    d = _dt.date(*(int(x) for x in date.split('-')))
    for back in range(1, 15):
        cand = f'{(d - _dt.timedelta(days=back)).isoformat()}.html'
        if os.path.exists(os.path.join(dirpath, cand)):
            return cand
    raise FileNotFoundError(f'no close report within 14 days before {date}')


def main(date, base=None, dirpath=None):
    dirpath = dirpath or os.path.dirname(os.path.abspath(__file__))
    os.chdir(dirpath)
    src = os.path.join('close', f'{date}.json')
    if not os.path.exists(src):
        raise SystemExit(f'missing data file: {src}')
    data = json.load(open(src))
    if data.get('kind') != 'close':
        raise SystemExit(f"kind must be 'close', got {data.get('kind')!r}")

    base = base or prior_close(date)
    out = f'{date}.html'
    html = R.build_close(data, base)
    R.write(out, html, 'close')              # validates, adds row, promotes featured
    R.validate_index('.')

    print(f'WROTE {out}  {len(html):,} bytes')
    print(f'  base            {base}')
    print(f'  validate        PASS')
    print(f'  charts          {html.count(chr(60) + "img src=" + chr(34) + "charts/")}')
    print(f'  setup rows      {html.count("class=" + chr(34) + "setup-row")}')
    print(f'  sector bars     {data["sectors"] and len(data["sectors"]["rows"])}')
    print(f'  provenance      {html.count("class=" + chr(34) + "card-header" + chr(34))} '
          f'(must be 0)')
    return out


if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
