#!/usr/bin/env python3
"""Check guided 3D scanning (services/kinect-motion/scan.py, scan_worker.py) without a Kinect.

Synthetic depth from boxes of known size, ray-cast through the Kinect's infrared lens (the
scanner's own synthetic raycaster), stands in for the camera, so every answer is known:

    snapshot      one view of a 300 x 200 x 150 mm box: its front face measured, the back
                  reported as not seen
    rotating      an object turned in twelve held steps of about 30 degrees (each off by up to
                  8 degrees, either way round): its axis and direction found, every view fused,
                  measured within the stated tolerance
    person        eight 45 degree turns of a body-sized box: each turn placed and refined;
                  a turn whose depth is missing is left out and named
    failures      a view knocked out of place (a dropped object): left out and named; a subject
                  that is really the room is refused
    export        PLY / OBJ in metres or millimetres, STL in millimetres with its units file
    cancel        a running worker stopped at once, its temporary folder gone

    scripts/verify-kinect-scan.py        (~1 minute; Open3D from .local/air-venv)
"""

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MOTION = REPO / "services/kinect-motion"
sys.path[:0] = [str(MOTION), str(REPO / "kinect/kinect-v1-ubuntu-scanner/src"), str(REPO / "services/adaptive-air")]

import numpy as np  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}" + ("" if ok else f"   [{detail}]"))
    if not ok:
        FAILED.append(name)


def run_worker(spec):
    """The worker in this process, its JSON lines collected."""
    import contextlib
    import io

    import scan_worker
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            {"capture": scan_worker.capture, "reconstruct": scan_worker.reconstruct,
             "background": scan_worker.background}[spec["job"]](spec)
        except Exception as err:          # noqa: BLE001
            print(json.dumps({"error": str(err)}))
    lines = [json.loads(x) for x in buf.getvalue().splitlines() if x.strip()]
    return lines, next((x["result"] for x in lines if "result" in x), None), next((x["error"] for x in lines if "error" in x), None)


def session(root, depths, k, kind, angles=None):
    from kinectscan.storage import save_frame, write_json
    (root / "frames").mkdir(parents=True)
    frames = []
    for i, d in enumerate(depths):
        rel = f"frames/{i:06d}.npz"
        save_frame(root / rel, d, k)
        item = {"path": rel}
        if angles is not None:
            item["angle_deg"] = angles[i]
        frames.append(item)
    write_json(root / "session.json", {"schema_version": 1, "synthetic": True, "kind": kind,
                                       "subject_motion": "test", "foreground_isolated": True,
                                       "intrinsics": k.to_dict(), "frames": frames})


def main():
    try:
        import open3d  # noqa: F401
    except ImportError:
        print("skip: Open3D is not in this Python (run with .local/air-venv/bin/python)")
        return 0
    from kinectscan.geometry import Intrinsics, turntable_pose
    from kinectscan.synthetic import raycast_boxes
    import scan as scanlib

    k = Intrinsics(640, 480, 575.8, 575.8, 314.5, 235.5, source="synthetic, the Kinect's infrared lens")
    tmp = Path(tempfile.mkdtemp(prefix="kinect-scan-check-"))
    seg = {"z_min": 0.5, "z_max": 1.3}
    box = ([-0.15, -0.10, 0.85], [0.15, 0.10, 1.00])         # 300 x 200 x 150 mm, 0.85 m away
    # Something to turn: the box with a handle on one side and a knob on top (asymmetric, like
    # a real object: four bare flat faces are the worst case for any registration).
    thing = [box, ([0.15, -0.06, 0.90], [0.22, 0.04, 0.95]), ([-0.05, -0.16, 0.89], [0.05, -0.10, 0.96])]

    print("Snapshot: one still object")
    d = raycast_boxes(k, np.eye(4), [box])
    root = tmp / "snap"
    session(root, [d], k, "object")
    _, res, err = run_worker({"job": "reconstruct", "kind": "object", "dir": str(root), "segment": seg})
    ext = res and res["aabb_extent_mm"]
    check("the face it shows is measured: 300 x 200 mm within 6 mm", res and abs(ext[0] - 300) < 6 and abs(ext[1] - 200) < 6, (err, ext))
    check("... and the back is reported as not seen, not filled in",
          res and res["coverage"]["missing"].startswith("the back") and not res["complete"], res and res["coverage"])
    check("the depth captures are deleted once there is a result", not (root / "frames").exists() and (root / "result/geometry.bin").exists())

    print("Turning object: twelve held turns")
    from kinectscan.geometry import rotation_axis_angle

    def turned(things, centre_, a):
        """The view of `things` turned by a degrees to its own left about a vertical axis."""
        g = np.eye(4)
        g[:3, :3] = rotation_axis_angle([0.0, 1.0, 0.0], np.radians(-a))
        g[:3, 3] = np.array(centre_) - g[:3, :3] @ np.array(centre_)
        return raycast_boxes(k, np.linalg.inv(g), things)
    rng = np.random.default_rng(3)
    centre = [0.0, 0.0, 0.925]
    nominal = [i * 30.0 for i in range(12)]
    for sign, label in ((1, "turned to its left"), (-1, "turned the other way")):
        true = [sign * (a + (rng.uniform(-8, 8) if a else 0)) for a in nominal]
        depths = [turned(thing, centre, a) for a in true]
        root = tmp / f"turn{sign}"
        session(root, depths, k, "rotating", nominal)
        lines, res, err = run_worker({"job": "reconstruct", "kind": "rotating", "dir": str(root), "segment": seg})
        ext = res["aabb_extent_mm"] if res else [0, 0, 0]
        truth = [370, 260, 150]                              # x (box + handle), y (box + knob), z
        errs = [a - b for a, b in zip(ext, truth)]
        if sign == 1:
            stages = {x.get("stage") for x in lines}
            check("registration, fusion and meshing report their progress", {"register", "fuse", "mesh"} <= stages, stages)
        check(f"{label}, each step up to 8 degrees off: all 12 views fused", res and res["coverage"]["views"] == 12,
              (err, res and res["coverage"]))
        check(f"... height within 6 mm, width and depth within 40 mm (flat faces register least well)",
              res and abs(errs[1]) <= 6 and abs(errs[0]) <= 40 and abs(errs[2]) <= 40, (err, ext))
        if res:
            print(f"        measured {ext[0]:.0f} x {ext[1]:.0f} x {ext[2]:.0f} mm, true 370 x 260 x 150: "
                  f"errors {errs[0]:+.0f} / {errs[1]:+.0f} / {errs[2]:+.0f} mm")

    print("Person: eight guided turns")
    # A body of boxes, 2.6 m away (camera y down, level): head, torso, arms a little out, legs.
    pcentre = [0, -0.05, 2.6]
    def part(x0, x1, y0, y1, z0, z1):
        return ([x0, y0, 2.6 + z0], [x1, y1, 2.6 + z1])
    body = [part(-0.09, 0.09, -0.95, -0.72, -0.10, 0.10), part(-0.19, 0.19, -0.70, -0.05, -0.12, 0.12),
            part(-0.33, -0.24, -0.68, -0.08, -0.05, 0.05), part(0.24, 0.33, -0.68, -0.08, -0.05, 0.05),
            part(-0.17, -0.03, -0.05, 0.85, -0.08, 0.08), part(0.03, 0.17, -0.05, 0.85, -0.08, 0.08)]
    pseg = {"z_min": 1.5, "z_max": 3.2}
    ang = [i * 45.0 for i in range(8)]
    # The person turns to their left: the object rotates by -angle about +y (camera y down).
    from kinectscan.geometry import rotation_axis_angle
    def view(a):
        g = np.eye(4); g[:3, :3] = rotation_axis_angle([0.0, 1.0, 0.0], np.radians(-a))
        g[:3, 3] = np.array(pcentre) - g[:3, :3] @ np.array(pcentre)
        return raycast_boxes(k, np.linalg.inv(g), body)
    depths = [view(a) for a in ang]
    depths[5] = np.zeros_like(depths[5])                    # nobody there for the sixth turn
    root = tmp / "person"
    session(root, depths, k, "person", ang)
    _, res, err = run_worker({"job": "reconstruct", "kind": "person", "dir": str(root), "segment": pseg})
    cov = res and res["coverage"]
    check("seven of eight turns line up and are fused", cov and cov["views"] == 7, (err, cov and cov.get("registration")))
    check("... the missing turn is named, and the scan is not called complete",
          cov and cov["missing_angles"] == [225.0] and not res["complete"], cov)
    if res:
        h = sorted(res["pca_obb_extent_mm"])[-1]
        check("the body's height comes out within 30 mm", abs(h - 1800) < 30, h)

    print("Failures, said as they are")
    knocked = [turned(thing, centre, a) for a in nominal]
    # The seventh view: knocked over (on its side, somewhere else).
    knocked[6] = raycast_boxes(k, turntable_pose(90, [0.1, 0.05, 0.95], [1, 0, 0]), thing)
    root = tmp / "knocked"
    session(root, knocked, k, "rotating", nominal)
    _, res, err = run_worker({"job": "reconstruct", "kind": "rotating", "dir": str(root), "segment": seg})
    fail = res and res.get("alignment_failure")
    check("a view knocked out of place is left out and named; the rest are fused",
          fail and fail["turns"] == [6] and res["coverage"]["views"] == 11 and 180.0 in res["coverage"]["missing_angles"]
          and not res["complete"], (err, fail))
    room = raycast_boxes(k, np.eye(4), [([-3, -2, 1.1], [3, 2, 1.2])])      # a wall inside the band
    root = tmp / "room"
    session(root, [room], k, "object")
    _, res, err = run_worker({"job": "reconstruct", "kind": "object", "dir": str(root), "segment": seg})
    check("a 'subject' that runs off the picture's edges (the room) is refused, with what to do",
          res is None and err and "room" in err, err)
    check("... and its captures are deleted too", not (root / "frames").exists())
    xyz_guides = {}
    for kind_, dist in (("object", 0.4), ("object", 0.8), ("object", 1.6)):
        from kinectscan.geometry import depth_to_xyz
        b = ([-0.1, -0.1, dist], [0.1, 0.1, dist + 0.1])
        dd = raycast_boxes(k, np.eye(4), [b])
        mask = dd > 0
        xyz_guides[dist] = scanlib.guidance(mask, depth_to_xyz(dd, k), kind_)
    check("framing advice: too close at 0.4 m, ready at 0.8 m, too far at 1.6 m",
          not xyz_guides[0.4]["ok"] and "close" in xyz_guides[0.4]["say"] and xyz_guides[0.8]["ok"]
          and not xyz_guides[1.6]["ok"], {d: g["say"] for d, g in xyz_guides.items()})

    print("Export and save: explicit units")
    events = []
    sc = scanlib.Scanner(lambda *a: None, events.append)
    os.environ.setdefault("XDG_RUNTIME_DIR", str(tmp))
    job = sc.create("rotating")
    shutil.rmtree(job.dir)
    shutil.copytree(tmp / "turn1", job.dir)
    job.state = "done"
    name, stl = sc.export(job.id, "stl", "mm")
    import struct
    raw = stl.read_bytes()
    n = struct.unpack("<I", raw[80:84])[0]
    tri = np.frombuffer(raw[84:], dtype=np.dtype([("n", "<f4", (3,)), ("v", "<f4", (3, 3)), ("a", "<u2")]), count=n)
    span = tri["v"].reshape(-1, 3).max(axis=0) - tri["v"].reshape(-1, 3).min(axis=0)
    units = json.loads((stl.parent / f"{name}.units.json").read_text())
    check("STL in millimetres: the box spans hundreds of units, and the units file says mm",
          span.max() > 250 and units["coordinate_units"] == "mm", (span, units))
    _, obj = sc.export(job.id, "obj", "m")
    vs = np.array([[float(x) for x in line.split()[1:]] for line in obj.read_text().splitlines() if line.startswith("v ")])
    check("OBJ in metres: under half a unit across, and it says metres", np.ptp(vs, axis=0).max() < 0.5 and "units metres" in obj.read_text()[:80])
    _, ply = sc.export(job.id, "ply", "mm")
    check("PLY in millimetres says millimetres", "units millimetres" in ply.read_text()[:200])
    scanlib.SCANS = tmp / "Kinect Scans"
    dest = sc.save(job.id, "Test box")
    check("Save keeps every format, the units files and the measurement report",
          {p.name for p in dest.iterdir()} >= {"kinect-scan-rotating.stl", "kinect-scan-rotating.obj",
                                               "kinect-scan-rotating.ply", "measurements.json", "measurements.txt"},
          sorted(p.name for p in dest.iterdir()))
    txt = (dest / "measurements.txt").read_text()
    check("... the report says what was not seen and that nothing was filled in", "not certified" in txt or "nothing that was not seen" in txt)
    sc.discard()
    check("discarding removes the scan's temporary folder", not job.dir.exists())

    print("Cancel: the worker stops and its files go")
    job = sc.create("rotating")
    shutil.rmtree(job.dir)
    shutil.copytree(tmp / "turn1" / "result", job.dir / "unused")      # some files to clean
    session(job.dir / "big", depths * 3, k, "person")                   # a slow job
    for p in (job.dir / "big").iterdir():
        shutil.move(str(p), str(job.dir / p.name))
    sc.run("reconstruct")
    time.sleep(1.5)
    running = job.proc.poll() is None
    t0 = time.monotonic()
    sc.cancel()
    check("a running reconstruction is stopped at once", running and time.monotonic() - t0 < 4 and job.proc.poll() is not None,
          (running, job.proc.poll()))
    check("... and its temporary folder is gone", not job.dir.exists())
    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILED:
        print(f"Kinect scanning: {len(FAILED)} check(s) FAILED")
        return 1
    print("Kinect scanning: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
