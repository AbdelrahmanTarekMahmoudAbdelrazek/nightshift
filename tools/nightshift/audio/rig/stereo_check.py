import sys, numpy as np
print(f"{'file':24s} {'frames':>9s} {'peak':>9s} {'clip':>6s} {'rms':>9s} {'max|L-R|':>10s} {'corr':>8s} {'sideRMS':>9s}")
for p in sys.argv[1:]:
    x = np.fromfile(p, dtype=np.float32)
    x = x[:len(x)//2*2].reshape(-1,2)
    L,R = x[:,0].astype(np.float64), x[:,1].astype(np.float64)
    d = L-R
    peak = float(np.max(np.abs(x))); clip = int(np.sum(np.abs(x)>=0.999999))
    rms  = float(np.sqrt(np.mean(x.astype(np.float64)**2)))
    lr   = float(np.max(np.abs(d)))
    side = float(np.sqrt(np.mean((d/2)**2)))
    corr = float(np.corrcoef(L,R)[0,1]) if lr>0 else 1.0
    print(f"{p.split('/')[-1]:24s} {len(x):9d} {peak:9.6f} {clip:6d} {rms:9.6f} {lr:10.6f} {corr:8.4f} {side:9.6f}")
