import numpy as np, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt
SR=44100
def load(p):
    x=np.fromfile(p,dtype=np.float32); return x[:len(x)//2*2].reshape(-1,2).astype(np.float64)
b=load("fixpoint4_dec.f32"); a=load("monofix.f32"); c=load("capcut.f32")
LAG={"before":0,"after":-580,"capcut":+439}      # measured by cross-correlation

t0,dur=30.0,0.012; n=int(dur*SR)
fig,ax=plt.subplots(3,2,figsize=(15,9),gridspec_kw={'width_ratios':[2,1]})
rows=[("BEFORE  (L+R)/2 written to both",b,"#c0392b","before"),
      ("AFTER   channels preserved",     a,"#1a7f37","after"),
      ("CapCut  reference",              c,"#6b6b6b","capcut")]
for row,(name,d,col,key) in enumerate(rows):
    i=int(t0*SR)+LAG[key]
    L,R=d[i:i+n,0],d[i:i+n,1]
    t=np.arange(n)/SR*1000
    p=ax[row,0]
    p.plot(t,L,lw=1.4,color=col,label="L"); p.plot(t,R,lw=1.0,color="#2b6cb0",ls="--",label="R")
    p.set_title(f"{name}   (lag {LAG[key]:+d} smp)    max|L-R| in window = {np.max(np.abs(L-R)):.6f}",
                fontsize=11,loc="left")
    p.set_ylabel("amplitude"); p.grid(alpha=.25); p.legend(loc="upper right",fontsize=9)
    p.set_xlim(0,dur*1000); p.set_ylim(-0.5,0.5)
    if row==2: p.set_xlabel(f"time (ms) from t={t0:.0f}s, lag-compensated")
    q=ax[row,1]; side=(d[:,0]-d[:,1])/2.0
    q.plot(np.arange(len(side))/SR,side,lw=.3,color=col)
    q.set_ylim(-.35,.35); q.grid(alpha=.25)
    q.set_title(f"side (L-R)/2, whole file   RMS={np.sqrt(np.mean(side**2)):.6f}",fontsize=10,loc="left")
    if row==2: q.set_xlabel("time (s)")
fig.suptitle("AudioNormalizer::Resample - stereo restored  (windows aligned by cross-correlation)",fontsize=14,y=.995)
fig.tight_layout(); fig.savefig("MONOFIX_stereo.png",dpi=110); print("wrote MONOFIX_stereo.png")
