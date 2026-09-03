#!/usr/bin/env python3
"""Render the daily candle charts the reports embed.

    python3 make_charts.py 2026-09-03 SNOW TSLA AVGO NTAP HPE
    python3 make_charts.py 2026-09-03 --pre QQQ IWM      # premarket variant

Writes charts/<SYM>_<date>.png (or <SYM>_<date>-pre.png with --pre), which is
exactly the path the report data files reference.

Until now these were produced outside the repo, so a report could name a chart
that nothing in version control knew how to rebuild. This is that missing half:
same dark styling, same reference lines, same Strat numbering.

Reference lines are drawn from the perspective of the report date - PDH/PDL is
the session BEFORE it, i.e. the levels that date actually traded against, and
PWH/PWL and PMH/PML are the prior completed week and month on the same logic.

Daily bars come from yfinance, verified 2026-09-03 against the Robinhood
close for every settled session in the window (SPY/DELL/SNOW matched to the
cent). The current, unsettled session can differ by a few cents - consolidated
tape versus a single venue's close - so prose numbers should still come from
the broker, not from here.
"""
from __future__ import annotations

import argparse
import os
import sys
import warnings

warnings.filterwarnings('ignore')

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
import yfinance as yf

BG      = '#12151c'
UP      = '#26a69a'
DOWN    = '#ef5350'
GRID    = '#2a2e39'
TEXT    = '#b2b5be'
PD      = '#e3c341'   # prior day
PW      = '#2fb8e0'   # prior week
PM      = '#b06ec9'   # prior month

SESSIONS = 32         # candles shown
ANNOTATE = 12         # how many recent bars get a Strat number


def strat_number(h, l, ph, pl):
    """The Strat classification of one bar against the one before it."""
    if h <= ph and l >= pl:
        return '1', TEXT
    if h > ph and l < pl:
        return '3', PD
    if h > ph:
        return '2↑', UP
    return '2↓', DOWN


def levels(df, asof):
    """Prior day/week/month high-low pairs as of `asof` (exclusive)."""
    hist = df[df.index < asof]
    if hist.empty:
        return {}
    out = {}

    prior_day = hist.iloc[-1]
    out['PD'] = (float(prior_day['High']), float(prior_day['Low']))

    # Prior completed week / month: group, drop the bucket `asof` falls in,
    # take the last one before it. Using the report date's own bucket would
    # leak the very session the levels are supposed to precede.
    for key, freq in (('PW', 'W'), ('PM', 'ME')):
        buckets = hist.groupby(pd.Grouper(freq=freq))
        agg = buckets.agg({'High': 'max', 'Low': 'min'}).dropna()
        asof_bucket = pd.Timestamp(asof).to_period('W' if freq == 'W' else 'M')
        agg = agg[agg.index.to_period('W' if freq == 'W' else 'M') < asof_bucket]
        if not agg.empty:
            out[key] = (float(agg.iloc[-1]['High']), float(agg.iloc[-1]['Low']))
    return out


def fetch(symbol, date, lookback_days=120):
    end = pd.Timestamp(date) + pd.Timedelta(days=1)
    start = pd.Timestamp(date) - pd.Timedelta(days=lookback_days)
    df = yf.download(symbol, start=start.date().isoformat(), end=end.date().isoformat(),
                     interval='1d', progress=False, auto_adjust=False)
    if df.empty:
        raise SystemExit(f'{symbol}: no data returned for {date}')
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df[df.index <= pd.Timestamp(date)]


def draw(symbol, date, outpath):
    full = fetch(symbol, date)
    lv = levels(full, pd.Timestamp(date))
    df = full.tail(SESSIONS)
    if df.empty:
        raise SystemExit(f'{symbol}: no sessions on or before {date}')

    fig, (ax, vax) = plt.subplots(
        2, 1, figsize=(11.23, 8.82), dpi=100, sharex=True,
        gridspec_kw={'height_ratios': [3.05, 1], 'hspace': 0.0},
    )
    fig.patch.set_facecolor(BG)

    x = range(len(df))
    o = df['Open'].to_numpy(); c = df['Close'].to_numpy()
    h = df['High'].to_numpy(); l = df['Low'].to_numpy()
    v = df['Volume'].to_numpy()
    colors = [UP if c[i] >= o[i] else DOWN for i in x]

    for i in x:
        ax.plot([i, i], [l[i], h[i]], color=colors[i], linewidth=1.1, zorder=3)
        lo, hi = sorted((o[i], c[i]))
        ax.add_patch(plt.Rectangle((i - 0.32, lo), 0.64, max(hi - lo, (h[i] - l[i]) * 0.004 or 0.01),
                                   facecolor=colors[i], edgecolor=colors[i], zorder=4))
        vax.bar(i, v[i], width=0.64, color=colors[i], zorder=3)

    span = float(df['High'].max() - df['Low'].min()) or 1.0
    for i in list(x)[-ANNOTATE:]:
        if i == 0:
            continue
        label, col = strat_number(h[i], l[i], h[i - 1], l[i - 1])
        ax.text(i, h[i] + span * 0.022, label, color=col, fontsize=8.5,
                ha='center', va='bottom', zorder=6)

    style = {'PD': (PD, '--', 'PDH/PDL'), 'PW': (PW, '--', 'PWH/PWL'), 'PM': (PM, ':', 'PMH/PML')}
    handles = []
    for key in ('PD', 'PW', 'PM'):
        if key not in lv:
            continue
        col, ls, lab = style[key]
        hi, lo = lv[key]
        for price, suffix in ((hi, 'H'), (lo, 'L')):
            ax.axhline(price, color=col, linestyle=ls, linewidth=1.15, alpha=0.95, zorder=2)
            ax.text(len(df) - 0.2, price, f'  {key}{suffix}', color=col, fontsize=8.5,
                    fontweight='bold', va='center', ha='left', zorder=6)
        handles.append(plt.Line2D([], [], color=col, linestyle=ls, linewidth=1.2, label=lab))

    ax.text(len(df) * 0.40, float(df['High'].max()) - span * 0.02, symbol,
            color=TEXT, fontsize=13, ha='center', va='top', zorder=6)

    if handles:
        leg = ax.legend(handles=handles, loc='upper left', fontsize=8.5, framealpha=0.85,
                        facecolor='#1c2030', edgecolor='#39405a', labelcolor=TEXT)
        leg.set_zorder(7)

    for a in (ax, vax):
        a.set_facecolor(BG)
        a.grid(True, color=GRID, linestyle='--', linewidth=0.6, alpha=0.55)
        a.set_axisbelow(True)
        a.tick_params(colors=TEXT, labelsize=9)
        a.yaxis.tick_right(); a.yaxis.set_label_position('right')
        for s in a.spines.values():
            s.set_color(GRID)

    ax.set_ylabel('Price', color=TEXT, fontsize=10)
    ax.set_xlim(-1, len(df) + 3.2)
    pad = span * 0.09
    lows = [float(df['Low'].min())] + [lv[k][1] for k in lv]
    highs = [float(df['High'].max())] + [lv[k][0] for k in lv]
    ax.set_ylim(min(lows) - pad, max(highs) + pad)

    vax.set_ylabel('Volume  $10^6$', color=TEXT, fontsize=10)
    vax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f'{y / 1e6:.0f}'))

    ticks = [i for i in x if i % 5 == 0]
    vax.set_xticks(ticks)
    vax.set_xticklabels([df.index[i].strftime('%b %d') for i in ticks],
                        rotation=45, ha='right', color=TEXT)

    fig.tight_layout(pad=0.7)
    fig.savefig(outpath, facecolor=BG)
    plt.close(fig)
    return outpath


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('date')
    ap.add_argument('symbols', nargs='+')
    ap.add_argument('--pre', action='store_true', help='write the -pre premarket variant')
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    outdir = os.path.join(here, 'charts')
    os.makedirs(outdir, exist_ok=True)

    suffix = f'{args.date}-pre' if args.pre else args.date
    for sym in args.symbols:
        path = os.path.join(outdir, f'{sym}_{suffix}.png')
        draw(sym, args.date, path)
        print(f'WROTE charts/{os.path.basename(path)}  {os.path.getsize(path):,} bytes')


if __name__ == '__main__':
    sys.exit(main())
