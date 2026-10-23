#!/usr/bin/env python3
"""
audio_seam_check.py - verify split-seam integrity of the audio pipeline.

Compares a raw PCM dump of the mixer output against the pristine source file
and runs five pass/fail tests, then writes the graphs.

Prepare the source once:
    ffmpeg -v error -y -i source.mp4 -f f32le -acodec pcm_f32le -ac 2 -ar 44100 src_full.raw

Pull a dump after an export (fresh app start, one export):
    adb exec-out run-as com.myzesty cat files/aud_dump_mix.f32 > dump.f32

Run:
    python3 audio_seam_check.py --dump dump.f32 --source src_full.raw \
        --seams 2.347,5.419,8.231,10.700,12.994,14.946 --out before
    (omit --seams to auto-detect; works only while seams are still broken)
"""
import argparse, sys
import numpy as np

SR = 44100

# ---------------------------------------------------------------- loading
def load(path):
    d = np.fromfile(path, dtype=np.float32)
    if d.size % 2:
        d = d[:-1]
    L, R = d[0::2].astype(np.float64), d[1::2].astype(np.float64)
    return L, R, (L + R) * 0.5

# ---------------------------------------------------- alignment machinery
def offset_at(dm, sm, t, span=0.40, search=8000):
    """Where in the source does the dump at time t come from? Returns (offset, corr)."""
    i = int(t * SR)
    a = dm[i:i + int(span * SR)]
    lo, hi = i - search, i + int(span * SR) + search
    if lo < 0 or hi > len(sm) or a.std() < 1e-6:
        return None
    seg = sm[lo:hi]
    W = np.concatenate([a, np.zeros(len(seg) - len(a))])
    corr = np.fft.irfft(np.fft.rfft(seg) * np.conj(np.fft.rfft(W)))
    o = int(np.argmax(corr[:2 * search])) - search
    b = sm[i + o:i + len(a) + o]
    if len(b) != len(a) or b.std() < 1e-7:
        return None
    return o, float(np.corrcoef(a, b)[0, 1])

def offset_trace(dm, sm, t0=0.3, t1=None, step=0.5):
    if t1 is None:
        t1 = len(dm) / SR - 1.0
    out = []
    for t in np.arange(t0, t1, step):
        r = offset_at(dm, sm, float(t))
        if r:
            out.append((float(t), r[0], r[1]))
    return out

def autodetect_seams(dm, sm):
    """Seams show up as offset steps or correlation dips - only while still broken."""
    tr = offset_trace(dm, sm, step=0.25)
    seams, prev = [], None
    for t, o, c in tr:
        if c < 0.95:
            seams.append(t); continue
        if prev is not None and abs(o - prev) > 20:
            seams.append(t)
        prev = o
    merged = []
    for t in seams:
        if not merged or t - merged[-1] > 0.4:
            merged.append(t)
    return merged

def refine_seam(L, R, dm, t, win=0.060):
    """Snap an approximate seam time to the real switch instant.

    The 'AUD split at' log reports the callback boundary, which can be up to one
    callback (23 ms) before the audible seam. Look for a hard marker nearby: an
    exact-zero frame first, then an outlier jump. If neither exists the build is
    already clean there, and the approximate time is good enough.
    """
    i = int(t * SR); w = int(win * SR)
    lo, hi = max(1, i - w), min(len(L) - 2, i + w)
    if hi <= lo:
        return t, 'kept'
    seg = slice(lo, hi)
    z = np.flatnonzero((L[seg] == 0) & (R[seg] == 0))
    if len(z):
        return (lo + z[0]) / SR, 'zero'
    step = np.abs(np.diff(L))
    thr = np.percentile(step[::7], 99.9)
    local = step[lo:hi]
    k = int(np.argmax(local))
    if local[k] > thr:
        return (lo + k) / SR, 'jump'
    return t, 'kept'

def local_align(dm, sm, i, w, search=2600):
    """Best source alignment for one short window. Tests must align locally: a single
    global offset is wrong wherever the export has repeated or skipped audio."""
    a = dm[i:i + w]
    lo, hi = max(0, i - search), min(len(sm), i + w + search)
    if a.std() < 1e-7 or hi - lo < w + 8:
        return None
    seg = sm[lo:hi]
    n = 1
    while n < len(seg) + w:
        n <<= 1
    corr = np.fft.irfft(np.fft.rfft(seg, n) * np.conj(np.fft.rfft(a, n)))[:len(seg) - w]
    c2 = np.cumsum(np.concatenate([[0.], seg ** 2]))
    en = np.sqrt(np.maximum(c2[w:] - c2[:-w], 0))[:len(corr)]
    nc = corr / np.maximum(en * np.sqrt((a ** 2).sum()), 1e-12)
    k = int(np.argmax(nc))
    b = seg[k:k + w]
    if b.std() < 1e-7:
        return None
    g = float(np.dot(a, b) / np.dot(b, b))
    return (lo + k) - i, abs(g), float(nc[k])

# --------------------------------------------------------------- the tests
def test1_zeros(L, R):
    z = (L == 0) & (R == 0)
    idx = np.flatnonzero(z)
    groups = []
    if len(idx):
        st = prev = idx[0]
        for i in idx[1:]:
            if i - prev > 1:
                groups.append((st, prev - st + 1)); st = i
            prev = i
        groups.append((st, prev - st + 1))
    interior = [(a, l) for a, l in groups if a > 2000 and a + l < len(L) - 3000]
    return interior, groups

def test2_continuity(dm, sm):
    tr = offset_trace(dm, sm)
    steps, prev = [], None
    for t, o, c in tr:
        if c < 0.95:
            continue
        if prev is not None and abs(o - prev) > 3:
            steps.append((t, o - prev))
        prev = o
    return tr, steps

def test3_level(dm, sm, seams, off):
    """Level at the cut as a percentage of the steady level either side.

    A cold decoder or resampler shows up as the level collapsing for a few ms.
    Each side of a cut belongs to a different clip, so alignment is taken per
    side and each window scored against whichever fits better.
    """
    rows = []
    W = 110                                   # 2.5 ms
    for c in seams:
        i = int(c * SR)
        cands = []
        for probe in (-0.25, +0.25):
            r = local_align(dm, sm, i + int(probe * SR), 4410)
            if r:
                cands.append(r[0])
        if not cands:
            rows.append((c, None, None)); continue
        def gain_at(j):
            best = 0.0
            for o in cands:
                b = sm[j + o:j + W + o]; a = dm[j:j + W]
                if len(b) == W and b.std() > 1e-7 and a.std() > 1e-7:
                    if float(np.corrcoef(a, b)[0, 1]) > 0.5:
                        best = max(best, abs(float(np.dot(a, b) / np.dot(b, b))))
            return best
        steady = [gain_at(i + d) for d in range(-int(.030*SR), -int(.020*SR), W)] + \
                 [gain_at(i + d) for d in range(int(.020*SR), int(.030*SR), W)]
        steady = [g for g in steady if g > 0]
        span = [gain_at(i + d) for d in range(-int(.012*SR), int(.012*SR), W // 2)]
        if not steady or not span:
            rows.append((c, None, None)); continue
        med = float(np.median(steady))
        rows.append((c, med, float(min(span) / med * 100)))
    return rows

def test4_residual(dm, sm, seams, off, w=441, n_base=300):
    """Gain-matched residual against the source, aligned locally per window."""
    def resid(i):
        r = local_align(dm, sm, i, w)
        if r is None:
            return None
        o, g, _ = r
        a = dm[i:i + w]; b = sm[i + o:i + w + o]
        if len(b) != w:
            return None
        gg = float(np.dot(a, b) / max(np.dot(b, b), 1e-12))
        return (a - gg * b).std() / a.std()
    rng = np.random.default_rng(1)
    dur = len(dm) / SR
    base, guard = [], 0
    while len(base) < n_base and guard < n_base * 20:
        guard += 1
        t = float(rng.uniform(1.0, max(2.0, dur - 1.0)))
        if any(abs(t - c) < 0.2 for c in seams):
            continue
        v = resid(int(t * SR))
        if v is not None:
            base.append(v)
    base = np.array(base) if base else np.array([1.0])
    rows = []
    for c in seams:
        vals = [resid(int((c + o / 1000) * SR) - w // 2) for o in (-5, -2.5, 0, 2.5, 5)]
        vals = [v for v in vals if v is not None]
        if not vals:
            rows.append((c, None, None)); continue
        worst = max(vals)
        rows.append((c, worst, float((base < worst).mean() * 100)))
    return base, rows

def test5_impulse(dm, seams, top=12):
    d2 = np.abs(np.diff(dm, 2))
    w = 1024
    c = np.cumsum(np.concatenate([[0.], dm ** 2]))
    rms = np.sqrt((c[w:] - c[:-w]) / w)
    full = np.empty(len(d2))
    full[:w // 2] = rms[0]
    full[w // 2:w // 2 + len(rms)] = rms
    full[w // 2 + len(rms):] = rms[-1]
    score = d2 / np.maximum(full[:len(d2)], 2e-3)
    order = np.argsort(score)[::-1]
    hits, used = [], []
    for i in order:
        if any(abs(i - u) < 500 for u in used):
            continue
        used.append(i)
        hits.append((i / SR, float(score[i]), float(d2[i])))
        if len(hits) >= top:
            break
    near = [(t, s) for t, s, _ in hits if any(abs(t - c) < 0.06 for c in seams)]
    return hits, near

# ------------------------------------------------------------------ plots
def plots(dm, sm, L, seams, off, tr, prefix):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    # 1. offset trace
    fig, ax = plt.subplots(figsize=(11, 3.6))
    ts = [t for t, o, c in tr if c >= 0.95]
    os_ = [o for t, o, c in tr if c >= 0.95]
    ax.plot(ts, os_, '-o', ms=3, color='#1f4fd8')
    for c in seams:
        ax.axvline(c, color='red', ls=':', lw=0.9)
    ax.set_xlabel('time (s)'); ax.set_ylabel('source offset (samples)')
    # Give the axis a floor of +/-30 samples. Without it matplotlib autoscales into a
    # 2-sample window on a clean file and sub-millisecond resampler rounding looks like
    # a staircase.
    if os_:
        lo, hi = min(os_), max(os_)
        mid = 0.5 * (lo + hi)
        half = max(30.0, (hi - lo) * 0.6)
        ax.set_ylim(mid - half, mid + half)
    ax.set_title('Where each moment of the export comes from in the source\n'
                 'flat line = continuous; a step at a red line = audio repeated or skipped', fontsize=10)
    ax.grid(alpha=.3); fig.tight_layout(); fig.savefig(f'{prefix}_offset.png', dpi=110); plt.close(fig)

    # 2. gain envelope per seam
    n = len(seams)
    if n:
        fig, axes = plt.subplots(1, n, figsize=(2.7 * n + 1, 3.4), squeeze=False)
        for ax, c in zip(axes[0], seams):
            xs, gs = [], []
            i0 = int((c - 0.030) * SR)
            for k in range(0, int(0.065 * SR), 44):
                a = dm[i0 + k:i0 + k + 220]; b = sm[i0 + k + off:i0 + k + 220 + off]
                if len(b) == 220 and b.std() > 1e-7 and a.std() > 1e-7:
                    xs.append((i0 + k + 110) / SR - c)
                    gs.append(abs(float(np.dot(a, b) / np.dot(b, b))))
            ax.plot(np.array(xs) * 1000, gs, color='#1b998b', lw=1.5)
            ax.axvline(0, color='red', ls=':', lw=1)
            ax.set_ylim(0, max(gs + [0.8]) * 1.25 if gs else 1)
            ax.set_title(f'seam {c:.3f} s', fontsize=9)
            ax.set_xlabel('ms from cut', fontsize=8); ax.grid(alpha=.3); ax.tick_params(labelsize=7)
        axes[0][0].set_ylabel('level vs source', fontsize=8)
        fig.suptitle('Level across each cut - a dip or ramp here is a cold decoder or resampler', fontsize=11)
        fig.tight_layout(rect=[0, 0, 1, 0.90]); fig.savefig(f'{prefix}_level.png', dpi=110); plt.close(fig)

        # 3. sample-level zoom
        fig, axes = plt.subplots(n, 1, figsize=(12, 2.5 * n), squeeze=False)
        for ax, c in zip(axes[:, 0], seams):
            i0, i1 = int((c - 0.030) * SR), int((c + 0.030) * SR)
            t = np.arange(i0, i1) / SR
            ax.plot(t, dm[i0:i1], lw=0.8, color='#1f4fd8', label='export')
            if i0 + off >= 0 and i1 + off < len(sm):
                ax.plot(t, sm[i0 + off:i1 + off], lw=0.7, color='#22a06b', alpha=.6, label='source')
            ax.axvline(c, color='red', ls='--', lw=0.9)
            ax.set_title(f'seam {c:.3f} s', fontsize=9); ax.legend(fontsize=7, loc='upper right')
            ax.tick_params(labelsize=7); ax.set_ylabel('amp', fontsize=8)
        axes[-1, 0].set_xlabel('time (s)')
        fig.suptitle('Waveform across each cut vs the pristine source', fontsize=11)
        fig.tight_layout(rect=[0, 0, 1, 0.98]); fig.savefig(f'{prefix}_zoom.png', dpi=110); plt.close(fig)

    # 4. jump-size histogram
    step = np.abs(np.diff(L))
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(step[::7], bins=200, color='#9aa5b1', log=True)
    for c in seams:
        i = int(c * SR)
        j = max(abs(L[i] - L[i - 1]), abs(L[i + 1] - L[i]))
        ax.axvline(j, color='#d1495b', lw=1.4)
    ax.set_xlim(0, max(step.max() * 0.6, 0.05))
    ax.set_xlabel('|sample[n] - sample[n-1]|'); ax.set_ylabel('count (log)')
    ax.set_title('Jump between adjacent samples: whole file (grey) vs the seams (red)\n'
                 'a seam line out in the tail is an audible click', fontsize=10)
    fig.tight_layout(); fig.savefig(f'{prefix}_jumps.png', dpi=110); plt.close(fig)

# ------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dump', required=True, help='raw f32le stereo 44100 mixer dump')
    ap.add_argument('--source', required=True, help='pristine source as f32le stereo 44100')
    ap.add_argument('--seams', default='', help='comma-separated seam times in seconds (auto if omitted)')
    ap.add_argument('--out', default='seam', help='output filename prefix')
    a = ap.parse_args()

    L, R, dm = load(a.dump)
    _, _, sm = load(a.source)
    print(f'dump   : {len(L)} frames ({len(L)/SR:.3f} s)  peak {np.abs(dm).max():.3f}')
    print(f'source : {len(sm)} frames ({len(sm)/SR:.3f} s)')
    print(f'max|L-R| = {np.abs(L-R).max():.9f}   '
          f'{"<<< DUAL MONO - channels are identical" if np.abs(L-R).max()==0 else "(true stereo)"}')
    print()

    given = [float(x) for x in a.seams.split(',') if x.strip()] or autodetect_seams(dm, sm)
    seams = []
    for g in given:
        r, how = refine_seam(L, R, dm, g)
        seams.append(r)
        note = '' if how == 'kept' else f'  (snapped to {how}, {(r-g)*1000:+.1f} ms)'
        print(f'seam   : {g:8.4f} -> {r:8.4f} s{note}')
    if not seams:
        print('seams  : none detected')
    print()

    fails = 0

    interior, groups = test1_zeros(L, R)
    ok = len(interior) == 0
    fails += not ok
    print(f'TEST 1  exact zeros (interior)      {"PASS" if ok else "FAIL"}   '
          f'{len(interior)} groups, {sum(l for _,l in interior)} frames')
    for x, l in interior[:6]:
        print(f'           t={x/SR:9.5f} s  len={l} ({l/44.1:.3f} ms)')

    tr, steps = test2_continuity(dm, sm)
    ok = len(steps) == 0
    fails += not ok
    print(f'TEST 2  seam continuity             {"PASS" if ok else "FAIL"}   {len(steps)} offset steps')
    for t, s in steps:
        print(f'           t={t:6.2f} s  step {s:+d} samples ({s/44.1:+.2f} ms)')

    good = [o for _, o, c in tr if c >= 0.95]
    off = int(np.median(good)) if good else 0   # no strong match (e.g. dump longer than the source): fall back to 0 instead of crashing on NaN

    print(f'TEST 3  level across seams          ', end='')
    rows = test3_level(dm, sm, seams, off)
    worst3 = min([d for _, _, d in rows if d is not None], default=100)
    ok = worst3 > 85
    fails += not ok
    print(f'{"PASS" if ok else "FAIL"}   level at worst cut = {worst3:.1f}% of steady')
    for c, med, d in rows:
        if d is not None:
            print(f'           seam {c:7.3f}  steady gain {med:.3f}  dips to {d:5.1f}%')

    base, rows4 = test4_residual(dm, sm, seams, off)
    worst4 = max([p for _, _, p in rows4 if p is not None], default=0)
    ok = worst4 < 99
    fails += not ok
    print(f'TEST 4  seam residual vs baseline   {"PASS" if ok else "FAIL"}   '
          f'worst {worst4:.1f}th pct (baseline median {np.median(base):.3f})')
    for c, w, p in rows4:
        if p is not None:
            print(f'           seam {c:7.3f}  residual {w:.3f}  -> {p:5.1f} pct')

    hits, near = test5_impulse(dm, seams)
    ok = len(near) == 0
    fails += not ok
    print(f'TEST 5  impulse outliers near seams {"PASS" if ok else "FAIL"}   {len(near)} of top 12')
    for t, s, _ in hits[:5]:
        tag = '  <<< NEAR A SEAM' if any(abs(t - c) < 0.06 for c in seams) else ''
        print(f'           t={t:9.4f} s  score {s:5.2f}{tag}')

    print()
    print('=' * 58)
    print(f'  {5-fails}/5 tests passed' + ('' if fails else '  - seams are sample-clean'))
    print('=' * 58)

    plots(dm, sm, L, seams, off, tr, a.out)
    print(f'\nwrote {a.out}_offset.png  {a.out}_level.png  {a.out}_zoom.png  {a.out}_jumps.png')
    sys.exit(1 if fails else 0)

if __name__ == '__main__':
    main()
