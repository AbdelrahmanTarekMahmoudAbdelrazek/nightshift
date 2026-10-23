#!/usr/bin/env python3
"""Audio Check v2 analysis (22 Oct): what a listener hears at each cut, with fixed thresholds.

Reuses the PR #3132 rig's alignment (audio_seam_check.py, unchanged). Differences from the old 5 tests:
  1 holes      - only silent gaps AT a cut (+-30 ms) or longer than 1 ms anywhere. The test clip itself has
                 single-frame exact zeros (natural zero crossings), so the old test 1 failed on every build.
  2 continuity - same as the old test 2 (the export never jumps in the source between cuts).
  3 level      - same as the old test 3 (level at the worst cut >= 85% of the level around it).
  4 residual   - error of the export against the clean source around each cut, in dB, with an absolute limit
                 (-30 dB). The old test 4 ranked it against a baseline that is 0.000 (bit-exact away from the
                 cuts), so ANY difference at a cut failed.
  5 clicks     - a click at a cut that is NOT in the source at the same place (old test 5 counted any impulse).
Per cut it also reports: audio repeated / skipped (ms), longest gap (ms), level dip (%), residual (dB), click.
Self-checks: the export must be the test clip (correlation with the source) and have the expected cuts.

usage: seam_v2.py --dump dump.f32 --source ref.f32 --seams 6.01,11.0,... [--expect-cuts 6] [--json out.json]
"""
import argparse, json, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audio_seam_check import SR, load, local_align, offset_trace, refine_seam, test3_level  # noqa: E402

LIM = {'gap_ms': 1.0, 'jump_ms': 0.1, 'level_pct': 85.0, 'resid_db': -30.0, 'click_ratio': 4.0}


def zero_runs(L, R, lo=0, hi=None):
    z = (L[lo:hi] == 0) & (R[lo:hi] == 0)
    idx = np.flatnonzero(z)
    out = []
    if len(idx):
        st = prev = idx[0]
        for i in idx[1:]:
            if i - prev > 1:
                out.append((lo + st, prev - st + 1)); st = i
            prev = i
        out.append((lo + st, prev - st + 1))
    return out


def offset_near(dm, sm, i, side):
    """Source offset of a short window just before (side=-1) or just after (side=+1) sample i."""
    w = int(0.020 * SR)
    j = i - int(0.030 * SR) - w if side < 0 else i + int(0.010 * SR)
    r = local_align(dm, sm, max(0, j), w)
    return None if r is None or r[2] < 0.9 else r[0]


def residual_db(dm, sm, i, w=441):
    worst = None
    for o in (-5, -2.5, 0, 2.5, 5):
        k = int(i + o / 1000 * SR) - w // 2
        r = local_align(dm, sm, max(0, k), w)
        if r is None:
            continue
        a = dm[k:k + w]; b = sm[k + r[0]:k + r[0] + w]
        if len(b) != w or a.std() < 1e-6:
            continue
        g = float(np.dot(a, b) / max(np.dot(b, b), 1e-12))
        e = (a - g * b).std() / a.std()
        db = 20 * np.log10(max(e, 1e-6))
        worst = db if worst is None else max(worst, db)
    return worst


def click_ratio(dm, sm, i, off):
    """Biggest 2nd difference within +-5 ms of the cut, against the same spot in the source."""
    w = int(0.005 * SR)
    a = np.abs(np.diff(dm[max(0, i - w):i + w], 2))
    if off is None or not len(a):
        return None
    b = np.abs(np.diff(sm[max(0, i - w + off):i + w + off], 2))
    if not len(b):
        return None
    return float(a.max() / max(b.max(), 1e-6))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dump', required=True); ap.add_argument('--source', required=True)
    ap.add_argument('--seams', default=''); ap.add_argument('--expect-cuts', type=int, default=0)
    ap.add_argument('--json', default='')
    ap.add_argument('--lossy', action='store_true', help='the dump was decoded from the exported (AAC) file, not the mixer tap: '
                    'the error limit is -24 dB instead of -30 dB (AAC alone costs about -32 dB on a clean cut)')
    a = ap.parse_args()
    if a.lossy:
        LIM['resid_db'] = -24.0
    L, R, dm = load(a.dump)
    _, _, sm = load(a.source)
    res = {'version': 2, 'limits': LIM, 'lossy': bool(a.lossy), 'dumpSeconds': len(dm) / SR, 'sourceSeconds': len(sm) / SR, 'selfcheck': [], 'cuts': []}

    # ---- self-checks (step 6): is this the test clip, with its cuts?
    head = local_align(dm, sm, int(0.5 * SR), int(0.5 * SR))
    if head is None or head[2] < 0.9:
        res['selfcheck'].append('the export does not match the test clip (correlation %.2f)' % (head[2] if head else 0))
    if abs(res['dumpSeconds'] - res['sourceSeconds']) > 2:
        res['selfcheck'].append('the export is %.1f s, the test clip %.1f s' % (res['dumpSeconds'], res['sourceSeconds']))
    given = [float(x) for x in a.seams.split(',') if x.strip()]
    if a.expect_cuts and len(given) != a.expect_cuts:
        res['selfcheck'].append('%d cuts reached the engine, %d expected' % (len(given), a.expect_cuts))
    seams = [refine_seam(L, R, dm, g)[0] for g in given]

    # ---- per cut (step 3)
    lv = {c: d for c, _, d in test3_level(dm, sm, seams, 0)}
    for c in seams:
        i = int(c * SR)
        ob, oa = offset_near(dm, sm, i, -1), offset_near(dm, sm, i, +1)
        jump = None if ob is None or oa is None else (oa - ob) / SR * 1000      # + = audio skipped, - = repeated
        gaps = [l for s, l in zero_runs(L, R, max(0, i - int(.03 * SR)), i + int(.03 * SR))]
        gap = max(gaps) / SR * 1000 if gaps else 0.0
        rdb = residual_db(dm, sm, i)
        clk = click_ratio(dm, sm, i, oa if oa is not None else ob)
        row = {'t': round(c, 4), 'jumpMs': None if jump is None else round(jump, 3), 'gapMs': round(gap, 3),
               'levelPct': None if lv.get(c) is None else round(lv[c], 1),
               'residDb': None if rdb is None else round(rdb, 1), 'click': None if clk is None else round(clk, 2)}
        bad = []
        if jump is not None and abs(jump) > LIM['jump_ms']:
            bad.append('%s %.1f ms' % ('skipped' if jump > 0 else 'repeated', abs(jump)))
        if gap > LIM['gap_ms']:
            bad.append('silent %.1f ms' % gap)
        if row['levelPct'] is not None and row['levelPct'] < LIM['level_pct']:
            bad.append('level dips to %.0f%%' % row['levelPct'])
        if rdb is not None and rdb > LIM['resid_db']:
            bad.append('error %.0f dB' % rdb)
        if clk is not None and clk > LIM['click_ratio']:
            bad.append('click x%.1f' % clk)
        row['ok'] = bool(not bad); row['problems'] = bad
        res['cuts'].append(row)

    # ---- the 5 tests
    long_gaps = [(s / SR, l / SR * 1000) for s, l in zero_runs(L, R, 2000, len(L) - int(0.25 * SR)) if l / SR * 1000 > LIM['gap_ms']]
    cut_gaps = [r for r in res['cuts'] if r['gapMs'] > LIM['gap_ms']]
    tr = offset_trace(dm, sm)
    steps, prev = [], None
    for t, o, cc in tr:
        if cc < 0.95:
            continue
        if prev is not None and abs(o - prev) > 3:
            steps.append((t, o - prev))
        prev = o
    lvs = [r['levelPct'] for r in res['cuts'] if r['levelPct'] is not None]
    rds = [r['residDb'] for r in res['cuts'] if r['residDb'] is not None]
    cks = [r for r in res['cuts'] if r['click'] is not None and r['click'] > LIM['click_ratio']]
    T = []
    T.append({'n': 1, 'name': 'silent gaps (at cuts or > 1 ms)', 'pass': not long_gaps and not cut_gaps,
              'detail': ('%d at cuts, %d long elsewhere' % (len(cut_gaps), len(long_gaps))) + (
                  ' · longest %.1f ms at %.2f s' % max(((l, s) for s, l in long_gaps), default=(0, 0)) if long_gaps else '')})
    T.append({'n': 2, 'name': 'seam continuity', 'pass': not steps,
              'detail': '%d jump(s) in the source' % len(steps) + ('' if not steps else ' · ' + ', '.join('%+.1f ms at %.1f s' % (s / SR * 1000, t) for t, s in steps[:4]))})
    T.append({'n': 3, 'name': 'level across cuts (>= 85%)', 'pass': (min(lvs) if lvs else 100) >= LIM['level_pct'],
              'detail': 'worst cut %.0f%%' % (min(lvs) if lvs else 100)})
    T.append({'n': 4, 'name': 'error at cuts (<= %d dB)' % LIM['resid_db'], 'pass': (max(rds) if rds else -99) <= LIM['resid_db'],
              'detail': 'worst cut %.0f dB' % (max(rds) if rds else -99)})
    T.append({'n': 5, 'name': 'clicks at cuts', 'pass': not cks,
              'detail': '%d cut(s) with a click not in the source' % len(cks)})
    res['tests'] = T
    res['passed'] = sum(t['pass'] for t in T)
    res['cutsOk'] = sum(r['ok'] for r in res['cuts'])
    for t in T:
        print('TEST %d  %-34s %s   %s' % (t['n'], t['name'], 'PASS' if t['pass'] else 'FAIL', t['detail']))
    for r in res['cuts']:
        print('cut %7.3f s  %s' % (r['t'], 'clean' if r['ok'] else '; '.join(r['problems'])))
    for s in res['selfcheck']:
        print('SELFCHECK ' + s)
    print('%d/5 tests passed · %d/%d cuts clean' % (res['passed'], res['cutsOk'], len(res['cuts'])))
    if a.json:
        def conv(o):                                   # numpy bool / numbers -> plain JSON
            if isinstance(o, np.generic):
                return o.item()
            raise TypeError(type(o).__name__)
        tmp = a.json + '.tmp'
        json.dump(res, open(tmp, 'w'), indent=1, default=conv)
        os.replace(tmp, a.json)


if __name__ == '__main__':
    main()
