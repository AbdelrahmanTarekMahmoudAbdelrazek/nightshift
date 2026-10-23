#!/usr/bin/env python3
"""
Report silence holes in a mixer dump and attribute each one to a media slot.

  python3 silence_check.py DUMP.f32 --seams 4.8530,8.9861,12.4459,15.2091,18.4831

Seam times come from the 'AUD split at' lines in logcat (export clock).
"""
import sys, argparse, numpy as np
SR = 44100

ap = argparse.ArgumentParser()
ap.add_argument('dump')
ap.add_argument('--seams', required=True, help='comma-separated AUD split times, seconds')
ap.add_argument('--min-ms', type=float, default=20.0, help='ignore holes shorter than this')
a = ap.parse_args()

d = np.fromfile(a.dump, dtype=np.float32)
d = d[:len(d)//2*2].reshape(-1, 2).astype(np.float64)
total = len(d)/SR
seams = [float(x) for x in a.seams.split(',') if x.strip()]
bounds = [0.0] + seams + [total]

print(f"{a.dump}: {len(d)} frames = {total:.3f} s   peak {np.max(np.abs(d)):.4f}\n")

# ---- exact-zero runs -------------------------------------------------
z = (d[:,0] == 0) & (d[:,1] == 0)
zz = np.flatnonzero(z)
runs = []
if len(zz):
    st = prev = zz[0]
    for i in zz[1:]:
        if i - prev > 1:
            runs.append((st, prev)); st = i
        prev = i
    runs.append((st, prev))
holes = [(s/SR, (e+1)/SR) for s, e in runs if (e-s+1)/SR*1000 >= a.min_ms]

print(f"HOLES >= {a.min_ms:.0f} ms : {len(holes)}")
for s, e in holes:
    edge = "  (file head)" if s < 0.05 else ("  (file tail)" if e > total-0.05 else "")
    print(f"   {s:9.4f} -> {e:9.4f} s    {(e-s)*1000:9.1f} ms{edge}")

# ---- per-media accounting -------------------------------------------
print(f"\n{'media':>5s} {'slot start':>11s} {'slot end':>10s} {'slot':>8s} "
      f"{'audio':>8s} {'silence':>8s} {'silent%':>8s}  verdict")
for k, (t0, t1) in enumerate(zip(bounds[:-1], bounds[1:])):
    i0, i1 = int(t0*SR), min(int(t1*SR), len(d))
    if i1 <= i0: continue
    seg = z[i0:i1]
    sil = float(np.sum(seg))/SR
    slot = (i1-i0)/SR
    pct = 100.0*sil/slot
    if   pct > 95: v = "SILENT - budget spent before export"
    elif pct > 2:  v = f"HOLE - played ~{sil:.2f}s in preview?"
    else:          v = "clean"
    print(f"{k:5d} {t0:11.4f} {t1:10.4f} {slot:7.3f}s "
          f"{slot-sil:7.3f}s {sil:7.3f}s {pct:7.1f}%  {v}")

# ---- click check at each seam ---------------------------------------
m = d.mean(1)
d2 = np.abs(np.diff(m, 2)); w = 1024
c = np.cumsum(np.concatenate([[0.], m**2])); rms = np.sqrt((c[w:]-c[:-w])/w)
full = np.empty(len(d2))
full[:w//2] = rms[0]; full[w//2:w//2+len(rms)] = rms; full[w//2+len(rms):] = rms[-1]
score = d2/np.maximum(full[:len(d2)], 2e-3)
print(f"\n{'seam':>10s} {'impulse score':>14s}   (>3 = likely click)")
for t in seams:
    i = int(t*SR); lo, hi = max(0, i-int(0.03*SR)), min(len(score), i+int(0.03*SR))
    if hi <= lo: continue
    print(f"{t:10.4f} {score[lo:hi].max():14.2f}   {'CLICK' if score[lo:hi].max() > 3 else 'ok'}")
