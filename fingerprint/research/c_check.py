"""Accept/reject statistics of the shipped C pipeline on recorded scans.
c_check.py THRESHOLD GENUINE_CAPDIR IMPOSTOR_CAPDIR [--same RECORDED=ACTUAL ...]
GENUINE_CAPDIR holds the fingers to enroll (12 scans each, first 12 = template);
IMPOSTOR_CAPDIR holds other fingers. --same relabels a round that was recorded
under the wrong name (e.g. --same left-index=right-middle)."""
import subprocess, sys, numpy as np
from pathlib import Path
from analyze import scan_dirs, W
HERE=Path(__file__).resolve().parents[2] / ".local/fingerprint-driver/research"
def var_clean(bg, im): return np.var(np.clip(np.clip(bg-im,0,None)*4,0,255))
def entries(cap, relabel):
    out=[]; bgp=None
    for finger, sdir in scan_dirs(Path(cap)):
        bgs=sorted(sdir.glob("*-bg-*.raw")); bgp=bgs[-1] if bgs else bgp
        bg=np.frombuffer(bgp.read_bytes(),np.uint8).reshape(W,W).astype(np.float32)
        fr=[f for f in sorted(sdir.glob("*-frame-*.raw")) if "-s6-" not in f.name][-1:]+[f for f in sorted(sdir.glob("*-s6-*.raw"))][:3]
        def v(f):
            x=var_clean(bg,np.frombuffer(f.read_bytes(),np.uint8).reshape(W,W).astype(np.float32)); return x if 1200<x<4000 else -1
        out.append((relabel.get(finger,finger), bgp, max(fr,key=v)))
    return out
T=int(sys.argv[1])
same=dict(a.split("=",1) for a in sys.argv[4:] if "=" in a)
gen=entries(sys.argv[2],same); imp=entries(sys.argv[3],{})
allv=gen+imp; lst=Path(sys.argv[3])/"c_list.txt"
lst.write_text("".join(f"{l} {b} {f}\n" for l,b,f in allv))
out=subprocess.run([str(HERE/"pattern-check"),str(lst)],capture_output=True,text=True,check=True).stdout
n=len(allv); S=np.zeros((n,n),int); K=[0]*n
for line in out.splitlines():
    p=line.split()
    if p[0]=="S": S[int(p[1]),int(p[2])]=int(p[3])
    else: K[int(p[1])]=int(p[2])
print("keypoints per scan: min", min(K), "median", int(np.median(K)))
L=[e[0] for e in allv]; G=len(gen)
fa=0; fa_n=0; maxi=0
for f in sorted(set(L[:G])):
    idx=[i for i in range(G) if L[i]==f]; tm=idx[:12]
    loo=sorted(max(S[p,t] for t in idx if t!=p) for p in idx)
    held=sorted(max(S[p,t] for t in tm) for p in idx[12:])
    imps=[max(S[p,t] for t in tm) for p in range(n) if L[p]!=f]
    fa+=sum(x>=T for x in imps); fa_n+=len(imps); maxi=max(maxi,max(imps))
    print(f"{f}: genuine leave-one-out {loo} -> accepted {sum(x>=T for x in loo)}/{len(loo)}; held-out vs 12-touch {held}")
    print(f"   wrong-finger scans vs this 12-touch template: max {max(imps)}, accepted {sum(x>=T for x in imps)}/{len(imps)}")
single=[S[i,j] for i in range(n) for j in range(n) if i!=j and L[i]!=L[j]]
print(f"all single wrong-finger pairs: {len(single)}, max {max(single)}, at/above threshold {sum(x>=T for x in single)}")
print(f"THRESHOLD {T}: false accepts {fa}/{fa_n}")
