#!/usr/bin/env python3
"""Score VFS7552 research captures under several image pipelines.

analyze.py CAPDIR [--sheet]
Each pipeline turns the raw 112x112 frame + background into the 224x224 image
NBIS sees; vfs-score gives the bozorth3 matrix; we then simulate enrollment
(first K scans of a finger = template) and verification of the others.
"""
import itertools
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parents[2] / ".local/fingerprint-driver/research"
W = 112
THRESHOLD = 20  # the driver's bz3_threshold; never lowered


def scan_dirs(cap):
    """(finger, scan dir) in capture order: the background is carried forward,
    so order must follow the driver's frame sequence, not folder names."""
    out = []
    for fdir in (p for p in cap.iterdir() if p.is_dir() and not p.name.startswith("tmp")):
        for sdir in (p for p in fdir.iterdir() if p.is_dir()):
            raws = sorted(sdir.glob("*.raw"))
            if raws:
                out.append((int(raws[0].name.split("-")[0]), fdir.name, sdir))
    return [(f, d) for _, f, d in sorted(out)]


def load_scan(sdir, bg):
    """Return (background, captured frame, settled frame). The driver keeps one
    background per session, so the last one seen is carried across scans."""
    cap = None
    after = []
    for f in sorted(sdir.glob("*.raw")):
        data = np.frombuffer(f.read_bytes(), np.uint8).reshape(W, W).astype(np.float32)
        if "-bg-" in f.name:
            bg = data
        elif "-s6-" in f.name:
            after.append(data)
        else:
            cap = data  # last frame before AWAIT_FINGER_OFF = the one the driver used
    # settled: ~0.2 s after the driver's frame, while the finger is still down
    settled = after[min(SETTLE, len(after) - 1)] if after else cap
    return bg, cap, settled


SETTLE = 4


def driver_clean(bg, img):
    d = np.clip(bg - img, 0, None) * 4
    return np.clip(d, 0, 255)


def up_nearest(a):
    return np.kron(a, np.ones((2, 2), np.float32))


def up_bilinear(a):
    return np.asarray(Image.fromarray(a.astype(np.float32), "F").resize((2 * W, 2 * W), Image.BILINEAR))


def stretch(a, lo=1, hi=99):
    p1, p99 = np.percentile(a, [lo, hi])
    return np.clip((a - p1) / max(p99 - p1, 1e-3) * 255, 0, 255)


def destreak(a):
    """Remove per-row and per-column offsets (sensor line noise)."""
    a = a - np.median(a, axis=1, keepdims=True)
    a = a - np.median(a, axis=0, keepdims=True)
    return a


def local_norm(a, k=9):
    """Local mean/variance normalisation: ridge contrast independent of pressure."""
    from numpy.lib.stride_tricks import sliding_window_view as swv
    pad = k // 2
    p = np.pad(a, pad, mode="reflect")
    win = swv(p, (k, k))
    m = win.mean(axis=(-1, -2))
    s = win.std(axis=(-1, -2)) + 1e-3
    return (a - m) / s


PIPELINES = {
    # exactly what the shipped driver gives NBIS
    "driver": lambda bg, im: up_nearest(driver_clean(bg, im)),
    # same subtraction, no x4 clipping: full dynamic range
    "stretch": lambda bg, im: up_nearest(stretch(np.clip(bg - im, 0, None))),
    "stretch-bilinear": lambda bg, im: up_bilinear(stretch(np.clip(bg - im, 0, None))),
    "destreak": lambda bg, im: up_bilinear(stretch(destreak(bg - im))),
    "destreak-localnorm": lambda bg, im: up_bilinear(stretch(local_norm(destreak(bg - im)), 2, 98)),
    "raw-localnorm": lambda bg, im: up_bilinear(stretch(local_norm(destreak(-im)), 2, 98)),
}


def to_u8(a):
    return np.clip(a, 0, 255).astype(np.uint8)


def score(paths):
    out = subprocess.run([str(HERE / "vfs-score"), *map(str, paths)], capture_output=True, text=True, check=True).stdout
    n = len(paths)
    mins = [0] * n
    s = np.zeros((n, n), int)
    for line in out.splitlines():
        p = line.split()
        if p[0] == "M":
            mins[int(p[1])] = int(p[2])
        elif p[0] == "S":
            s[int(p[1]), int(p[2])] = int(p[3])
    return mins, s


def evaluate(labels, s, k):
    """Template = first k scans per finger; probes = rest + all other fingers."""
    fingers = sorted(set(labels))
    res = {}
    for f in fingers:
        idx = [i for i, l in enumerate(labels) if l == f]
        if len(idx) <= k:
            continue
        tmpl = idx[:k]
        gen = [max(s[p, t] for t in tmpl) for p in idx[k:]]
        imp = [max(s[p, t] for t in tmpl) for p, l in enumerate(labels) if l != f]
        res[f] = (gen, imp)
    return res


def main():
    cap = Path(sys.argv[1])
    scans = []
    bg = None
    for finger, sdir in scan_dirs(cap):
        bg, im, settled = load_scan(sdir, bg)
        if bg is None or im is None:
            print("skip", sdir)
            continue
        scans.append((finger, sdir.name, bg, im, settled))
    labels = [s[0] for s in scans]
    print(f"{len(scans)} scans: " + ", ".join(f"{f} x{labels.count(f)}" for f in sorted(set(labels))))

    # raw signal statistics
    for f, n, bg, im, _ in scans[:3]:
        d = bg - im
        print(f"  {f}/{n}: bg mean={bg.mean():.0f} sd={bg.std():.1f}  frame mean={im.mean():.0f} sd={im.std():.1f}"
              f"  diff p1/p50/p99={np.percentile(d, 1):.0f}/{np.percentile(d, 50):.0f}/{np.percentile(d, 99):.0f}"
              f"  clipped-by-x4={(np.clip(d,0,None)*4>255).mean()*100:.0f}%")

    tmp = Path(tempfile.mkdtemp(dir=cap))
    only = [a for a in sys.argv[2:] if not a.startswith("--")]
    variants = [(f"{pn}@{which}", fn, which) for pn, fn in PIPELINES.items() for which in ("cap", "settled")]
    for name, fn, which in variants:
        if only and not any(o in name for o in only):
            continue
        paths = []
        for i, (f, n, bg, im, st) in enumerate(scans):
            p = tmp / f"{name}-{i:03d}.pgm"
            Image.fromarray(to_u8(fn(bg, im if which == "cap" else st))).save(p)
            paths.append(p)
        mins, s = score(paths)
        print(f"\n== {name}: minutiae median {int(np.median(mins))} (min {min(mins)})")
        for k in (5, 8):
            res = evaluate(labels, s, k)
            for f, (gen, imp) in res.items():
                acc = sum(g >= THRESHOLD for g in gen)
                fa = sum(i >= THRESHOLD for i in imp)
                print(f"   K={k} {f:13s} genuine {acc}/{len(gen)} accepted  scores {sorted(gen)}"
                      f" | impostor max {max(imp) if imp else '-'} false-accepts {fa}/{len(imp)}")
    if "--sheet" in sys.argv:
        sheet = []
        for f, n, bg, im, _ in scans[:: max(1, len(scans) // 6)][:6]:
            row = [to_u8(PIPELINES[p](bg, im)) for p in PIPELINES]
            sheet.append(np.hstack(row))
        Image.fromarray(np.vstack(sheet)).save(cap / "sheet.png")
        print("sheet:", cap / "sheet.png", "columns:", list(PIPELINES))


if __name__ == "__main__":
    main()
