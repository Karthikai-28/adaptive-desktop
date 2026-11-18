"""Guided 3D scanning inside Kinect Motion: the jobs behind the app's Scan section.

    choose subject -> frame -> capture -> reconstruct -> inspect -> export / save

One scan at a time. Its files live in a private temporary folder ($XDG_RUNTIME_DIR/kinect-scan/,
mode 700); the depth captures there are deleted as soon as the reconstruction ends (the worker
does it), the reconstructed geometry when the scan is discarded, saved or the service stops,
and every leftover folder when the service starts. Nothing is kept unless the person chooses
Save (into ~/Kinect Scans/<name>/, listed in the history) or Export (a download).

The camera: a scan reads depth in the infrared camera's own geometry, so while one is being
framed or captured the hub is leased into infrared (kinect_hub.py "lease"), renewed while the
scan needs it and released after. A scan cannot start while a workout or game is live unless
the person agrees to pause it (409 otherwise).

Captures and reconstructions run in scan_worker.py, a supervised process whose progress comes
back as JSON lines; Cancel stops it at once and cleans up.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
WORKER = HERE / "scan_worker.py"
SCANS = Path.home() / "Kinect Scans"
KINDS = ("object", "rotating", "person")
FORMATS = ("ply", "obj", "stl")
LEASE_S = 45.0

# What each kind wants from where it is: the depth band to start with, and the distances.
GUIDE = {
    "object": {"z": (0.5, 1.3), "near": 0.55, "best": (0.6, 1.0), "far": 1.3},
    "rotating": {"z": (0.5, 1.4), "near": 0.55, "best": (0.6, 1.0), "far": 1.4},
    "person": {"z": (1.0, 3.2), "near": 1.2, "best": (1.6, 2.6), "far": 3.2},
}


def root():
    base = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()) / "kinect-scan"
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(base, 0o700)
    return base


def clean_all():
    """Leftovers from a service that did not stop cleanly: no scan survives a restart unsaved."""
    shutil.rmtree(root(), ignore_errors=True)


class Job:
    def __init__(self, kind, segment):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.segment = dict(segment)
        self.dir = root() / self.id
        self.dir.mkdir(mode=0o700)
        self.state = "framing"
        self.stage = None
        self.progress = None
        self.message = None
        self.error = None
        self.result = None
        self.proc = None
        self.started = time.time()
        self.turn = None

    def to_dict(self):
        return {"id": self.id, "kind": self.kind, "state": self.state, "stage": self.stage,
                "progress": self.progress, "message": self.message, "error": self.error,
                "segment": self.segment, "turn": self.turn,
                "result": self.result, "background": bool(self.segment.get("background"))}


class Scanner:
    """The one scan job, its worker and the hub lease. emit(event) tells the pages."""

    def __init__(self, hub_post, emit, python=None):
        self.hub_post, self.emit = hub_post, emit
        self.python = python or str(REPO / ".local/air-venv/bin/python") if (REPO / ".local/air-venv/bin/python").exists() else sys.executable
        self.job = None
        self.lock = threading.Lock()
        self.leased_until = 0.0
        clean_all()

    # -- the camera
    def lease(self, seconds=LEASE_S):
        self.leased_until = time.monotonic() + seconds
        self.hub_post("lease", {"owner": "scan", "mode": "ir", "seconds": seconds})

    def release(self):
        self.leased_until = 0.0
        self.hub_post("lease", None)

    def keep_alive(self):
        """Renew the lease while a scan is framing or capturing (call every few seconds)."""
        j = self.job
        if j and j.state in ("framing", "background", "capturing") and time.monotonic() > self.leased_until - 15:
            self.lease()

    # -- jobs
    def create(self, kind, segment=None):
        if kind not in KINDS:
            raise ValueError("kind: object, rotating or person")
        self.discard()
        g = GUIDE[kind]
        seg = {"z_min": g["z"][0], "z_max": g["z"][1], **(segment or {})}
        self.job = Job(kind, seg)
        self.lease()
        return self.job

    def update(self, segment):
        j = self._need()
        for key in ("z_min", "z_max", "roi"):
            if key in segment:
                j.segment[key] = segment[key]
        if segment.get("background") is False:
            j.segment.pop("background", None)
        return j

    def _need(self):
        if self.job is None:
            raise LookupError("No scan under way")
        return self.job

    def run(self, what, **extra):
        """Start the worker: background, capture or reconstruct."""
        j = self._need()
        if j.proc is not None and j.proc.poll() is None:
            raise RuntimeError("The scan is busy")
        spec = {"job": what, "kind": j.kind, "dir": str(j.dir), "segment": j.segment, **extra}
        if what in ("background", "capture"):
            self.lease(LEASE_S + float(extra.get("seconds", 0) or 0) + (120 if j.kind == "person" else 0))
        j.state = {"background": "background", "capture": "capturing", "reconstruct": "reconstructing"}[what]
        j.stage, j.progress, j.error, j.message = what, 0.0, None, None
        j.proc = subprocess.Popen([self.python, str(WORKER), json.dumps(spec)], stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, start_new_session=True)
        threading.Thread(target=self._read, args=(j, what), daemon=True).start()
        return j

    def _read(self, j, what):
        result, error = None, None
        for line in j.proc.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if "result" in msg:
                result = msg["result"]
            elif "error" in msg:
                error = msg["error"]
            else:
                j.stage = msg.get("stage")
                total = msg.get("total") or 1
                j.progress = round(min(1.0, (msg.get("done") or 0) / total), 3)
                j.turn = {k: msg[k] for k in ("turn", "angle", "say", "still", "taken") if k in msg} or j.turn
                if msg.get("say"):
                    j.message = msg["say"]
            self.emit({"type": "scan", **j.to_dict()})
        j.proc.wait()
        if j is not self.job or j.state == "cancelled":
            return
        if error or j.proc.returncode:
            j.state, j.error = "failed", error or f"The scan worker stopped ({j.proc.returncode})"
            j.failed_stage = what
            if what == "capture":
                j.state = "framing"             # try the capture again
        elif what == "background":
            j.segment["background"] = result["background"]
            j.state, j.message = "framing", "Background captured: now bring the subject in"
        elif what == "capture":
            j.state = "captured"
            self.release()
            self.run("reconstruct")
            return
        else:
            j.state, j.result = "done", result
            self.release()
        j.progress = 1.0 if j.state == "done" else j.progress
        self.emit({"type": "scan", **j.to_dict()})

    def cancel(self):
        j = self.job
        if j is None:
            return
        j.state = "cancelled"
        if j.proc is not None and j.proc.poll() is None:
            try:
                os.killpg(j.proc.pid, 15)
                j.proc.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    os.killpg(j.proc.pid, 9)
                except OSError:
                    pass
        self.discard()

    def discard(self):
        j, self.job = self.job, None
        if j is None:
            return
        if j.proc is not None and j.proc.poll() is None:
            try:
                os.killpg(j.proc.pid, 9)
            except OSError:
                pass
        shutil.rmtree(j.dir, ignore_errors=True)
        self.release()

    # -- results
    def result_dir(self, scan_id):
        j = self._need()
        if j.id != scan_id or j.state != "done":
            raise LookupError("That scan is not ready")
        return j.dir / "result"

    def export(self, scan_id, fmt, units="mm", what="mesh"):
        """A file for download: (name, path). Units: mm or m (written into the file or beside it)."""
        import numpy as np
        sys.path.insert(0, str(REPO / "kinect/kinect-v1-ubuntu-scanner/src"))
        from kinectscan.storage import write_cloud, write_mesh
        if fmt not in FORMATS or units not in ("mm", "m"):
            raise ValueError("format: ply, obj or stl; units: mm or m")
        res = self.result_dir(scan_id)
        out = res / "export"
        out.mkdir(exist_ok=True)
        v, t = np.load(res / "vertices.npy"), np.load(res / "triangles.npy")
        name = f"kinect-scan-{self.job.kind}.{fmt}"
        path = out / name
        scale = 1000.0 if units == "mm" else 1.0
        if what == "points" or not len(t):
            if fmt == "stl":
                raise ValueError("STL needs a surface; this scan has points only")
            write_cloud(path, np.load(res / "points.npy") * scale)
        elif fmt == "stl":
            write_mesh(path, v, t, stl_units=units)
        else:
            write_mesh(path, v * scale, t)
            # PLY and OBJ say metres in their comment line; the units file is the record.
        units_note = {"coordinate_units": units, "meters_per_unit": 0.001 if units == "mm" else 1.0,
                      "frame": "X right, Y down, Z away from the Kinect, at the scan's first view"}
        (out / f"{name}.units.json").write_text(json.dumps(units_note, indent=2) + "\n")
        if fmt != "stl":
            text = path.read_text()
            unit_word = "millimetres" if units == "mm" else "metres"
            text = text.replace("units meters", f"units {unit_word}", 1)
            path.write_text(text)
        return name, path

    def save(self, scan_id, name, store=None):
        """Keep it: every format, the measurement report, in ~/Kinect Scans/<name>/."""
        import re
        res = self.result_dir(scan_id)
        safe = re.sub(r"[^\w\- ]+", "", name or "").strip()[:60] or time.strftime("Scan %Y-%m-%d %H%M")
        dest = SCANS / safe
        n = 2
        while dest.exists():
            dest = SCANS / f"{safe} ({n})"
            n += 1
        dest.mkdir(parents=True)
        for fmt in FORMATS:
            for units in (("mm",) if fmt == "stl" else ("m",)):
                try:
                    fname, path = self.export(scan_id, fmt, units)
                except ValueError:
                    continue
                shutil.copy(path, dest / fname)
                shutil.copy(path.parent / f"{fname}.units.json", dest / f"{fname}.units.json")
        report = json.loads((res / "report.json").read_text())
        (dest / "measurements.json").write_text(json.dumps(report, indent=2) + "\n")
        (dest / "measurements.txt").write_text(report_text(report))
        if store is not None:
            store.add_scan(safe, self.job.kind, dest, {k: report.get(k) for k in (
                "aabb_extent_mm", "pca_obb_extent_mm", "point_count", "triangles", "closed", "complete", "coverage")})
        return dest


def report_text(r):
    """The measurement report, in words, beside the files."""
    ext = r.get("aabb_extent_mm") or [0, 0, 0]
    obb = r.get("pca_obb_extent_mm") or [0, 0, 0]
    cov = r.get("coverage") or {}
    lines = [
        "Kinect scan: measurement report",
        "",
        f"Kind: {r.get('kind')}   Points: {r.get('point_count')}   Triangles: {r.get('triangles')}",
        f"Box along the camera's axes (mm): {ext[0]:.0f} wide x {ext[1]:.0f} high x {ext[2]:.0f} deep",
        f"Box along the scan's own axes (mm): {obb[0]:.0f} x {obb[1]:.0f} x {obb[2]:.0f}",
        f"Views fused: {cov.get('views')}" + (f" of {cov.get('of')}" if cov.get("of") else ""),
        f"Open edges (holes, rims): {r.get('open_edges')}   Closed surface: {'yes' if r.get('closed') else 'no'}",
        f"Complete: {'yes' if r.get('complete') else 'no: parts were not seen'}",
    ]
    if cov.get("missing"):
        lines.append(f"Not seen: {cov['missing']}")
    if cov.get("missing_angles"):
        lines.append("Turns that did not line up (left out): " + ", ".join(f"{a:.0f} deg" for a in cov["missing_angles"]))
    if r.get("alignment_failure"):
        f = r["alignment_failure"]
        lines.append(f"Views that did not line up: {', '.join(str(t + 1) for t in f['turns'])} of {f['of']} "
                     f"({f['why']}); {f['kept']}.")
    lines += ["", "Units: millimetres in the STL (see its .units.json), metres in PLY/OBJ.",
              "These are the extents of the surface the Kinect saw, not certified dimensions; "
              "nothing that was not seen has been filled in."]
    lines += [f"Note: {w}" for w in r.get("warnings", [])]
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ framing (the live preview)

def preview(depth, intrinsics, kind, segment, colours):
    """What the Frame step shows: the depth picture with the subject lit and the rest dimmed
    (a JPEG), and what to do next. depth: mm in the infrared camera's geometry."""
    import cv2
    import numpy as np
    sys.path.insert(0, str(REPO / "kinect/kinect-v1-ubuntu-scanner/src"))
    from kinectscan.geometry import Intrinsics, depth_to_xyz, segment_depth
    from kinectscan.storage import load_frame
    fx, fy, cx, cy = intrinsics
    k = Intrinsics(depth.shape[1], depth.shape[0], fx, fy, cx, cy, source="Kinect hub, infrared")
    bg = load_frame(segment["background"])[0] if segment.get("background") else None
    try:
        fg = segment_depth(depth, k, z_min=float(segment["z_min"]), z_max=float(segment["z_max"]),
                           roi=segment.get("roi"), background=bg, largest_component=True)
    except ValueError as err:
        return None, {"ok": False, "say": str(err)}
    mask = fg > 0
    d = depth.astype(np.float32)
    grey = np.clip(255 * (1 - (d - 400) / 3600), 0, 255).astype(np.uint8)
    grey[depth == 0] = 0
    img = cv2.cvtColor((grey * 0.35).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    lit = np.array(colours["subject"], np.float32)
    shade = (0.45 + 0.55 * grey[mask].astype(np.float32) / 255)[:, None]
    img[mask] = np.clip(lit[None, :] * shade, 0, 255).astype(np.uint8)
    edge = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)) > 0
    img[edge] = colours["edge"]
    if segment.get("roi"):
        x0, y0, x1, y1 = map(int, segment["roi"])
        cv2.rectangle(img, (x0, y0), (x1 - 1, y1 - 1), colours["edge"], 2)
    img = cv2.flip(img, 1)                            # a mirror, like the rest of the app
    ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 82])
    stats = guidance(mask, depth_to_xyz(fg, k), kind)
    return jpg.tobytes() if ok else None, stats


def guidance(mask, xyz, kind):
    """Is the subject framed well? -> {"ok", "say", "distance", "size_mm", ...}."""
    import numpy as np
    g = GUIDE[kind]
    n = int(mask.sum())
    if n < 400:
        return {"ok": False, "pixels": n, "say": "Nothing in the depth range: bring the subject in, or widen the range."}
    pts = xyz[mask]
    pts = pts[np.isfinite(pts).all(axis=1)]
    dist = float(np.median(pts[:, 2]))
    lo, hi = np.percentile(pts, [2, 98], axis=0)
    size = ((hi - lo) * 1000).round().tolist()
    rows, cols = np.nonzero(mask)
    edges = [name for name, hit in (("top", rows.min() <= 2), ("bottom", rows.max() >= mask.shape[0] - 3),
                                    ("left", cols.min() <= 2), ("right", cols.max() >= mask.shape[1] - 3)) if hit]
    out = {"pixels": n, "distance": round(dist, 2), "size_mm": size, "edges": edges}
    if dist < g["near"]:
        out.update(ok=False, say=f"Too close: the Kinect cannot measure nearer than about {g['near']:.1f} m. Move back.")
    elif len(edges) >= 2 and kind != "person":
        out.update(ok=False, say="It runs off the edges: that is the room, not the subject. Narrow the range or capture the background.")
    elif edges:
        side = {"top": "top", "bottom": "bottom", "left": "side", "right": "side"}[edges[0]]
        out.update(ok=False, say=f"Part of it is off the {side} of the picture: " +
                   ("step back" if kind == "person" else "move it towards the middle") + ".")
    elif dist > g["far"]:
        out.update(ok=False, say=f"Too far for detail: come closer (about {g['best'][1]:.1f} m is best).")
    elif dist > g["best"][1]:
        out.update(ok=True, say=f"Good. A little closer gives finer detail (about {g['best'][1]:.1f} m).")
    else:
        out.update(ok=True, say="Good: ready to capture.")
    return out
