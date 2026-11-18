#!/usr/bin/env python3
"""The 3D scan worker: one capture or one reconstruction, in its own process.

Kinect Motion (scan.py) starts it, reads its progress (JSON lines on stdout) and can stop it at
any moment; it never runs inside the server, so a long Open3D fusion or a stuck camera cannot
stall the live tracking. It reads the Kinect through the hub (the scanner's HubCapture: frames of
one camera geometry only), which scan.py has leased into infrared for the scan: the scanner's
geometry is the depth camera's own (FREENECT_DEPTH_MM).

    scan_worker.py '{"job": "background", "dir": "..."}'
    scan_worker.py '{"job": "capture", "kind": "object|rotating|person", "dir": "...", ...}'
    scan_worker.py '{"job": "reconstruct", "kind": ..., "dir": "...", "segment": {...}}'

Each line it prints is {"stage", "done", "total", ...}, then a last {"result": ...} or
{"error": ...}. Depth captures are temporary: a reconstruction deletes them when it ends,
whether it worked or not; nothing but the reviewed geometry is kept, and that only when the
person chooses Save or Export (scan.py).

Kinds:
    object    a still object: one depth snapshot (the median of a few frames). Its front
              surface only: the back is not seen, and is not made up.
    rotating  an object turned in place in twelve steps of about 30 degrees, let go of at each
    person    someone standing still who turns on the spot in eight steps of 45 degrees
              Each held view starts from its turn about the subject's own vertical axis (found
              from the first turn, with the direction it went) and is refined with ICP that may
              only nudge it; a view that does not line up is left out and named. Continuous
              frame-to-frame registration was tried first and drifted 50 to 110 mm over a turn
              of a flat-faced object in the checks; held turns stayed within 4 mm in height and
              10 to 37 mm in width and depth (scripts/verify-kinect-scan.py).
"""

import json
import math
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path[:0] = [str(REPO / "kinect/kinect-v1-ubuntu-scanner/src"), str(REPO / "services/adaptive-air")]

import numpy as np  # noqa: E402

TURNS = {"person": 8, "rotating": 12}
OBJECT_SAMPLES = 15
STILL_MM = 9.0          # mean frame-to-frame change on the subject below this = holding still
STILL_FOR = 0.8         # s
TURN_TIMEOUT = 12.0     # s to turn and settle before the view is taken anyway (and marked so)


def say(**kw):
    print(json.dumps(kw), flush=True)


def capture_source():
    from kinectscan.capture import HubCapture
    return HubCapture(timeout=8.0)


# ------------------------------------------------------------------ capture

def background(job):
    from kinectscan.geometry import rectify_depth
    from kinectscan.storage import save_frame
    out = Path(job["dir"])
    with capture_source() as cam:
        frames = []
        n = int(job.get("samples", 20))
        for i in range(n):
            frames.append(cam.read()[0])
            say(stage="background", done=i + 1, total=n)
        from kinectscan.geometry import median_depth
        depth = rectify_depth(median_depth(frames), cam.k)
        save_frame(out / "background.npz", depth, cam.k)
    say(result={"background": str(out / "background.npz"), "valid": float((depth > 0).mean())})


def _fg(depth, k, seg):
    from kinectscan.geometry import segment_depth
    from kinectscan.storage import load_frame
    bg = None
    if seg.get("background"):
        bg = load_frame(seg["background"])[0]
    return segment_depth(depth, k, z_min=seg.get("z_min", 0.5), z_max=seg.get("z_max", 1.5),
                         roi=seg.get("roi"), background=bg, largest_component=True)


def capture(job):
    from kinectscan.geometry import median_depth
    from kinectscan.storage import save_frame, write_json
    out = Path(job["dir"])
    frames_dir = out / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    kind = job["kind"]
    manifest = {"schema_version": 1, "synthetic": False, "frames": [], "kind": kind,
                "subject_motion": {"object": "stationary", "rotating": "unknown_rotating_subject",
                                   "person": "guided_turns"}[kind],
                "foreground_isolated": True, "segment": job.get("segment", {})}
    with capture_source() as cam:
        k = cam.k
        manifest["intrinsics"] = k.to_dict()
        manifest["epoch_mode"] = cam.mode
        if kind == "object":
            got = []
            for i in range(OBJECT_SAMPLES):
                got.append(cam.read()[0])
                say(stage="capture", done=i + 1, total=OBJECT_SAMPLES)
            save_frame(frames_dir / "000000.npz", median_depth(got), k)
            manifest["frames"].append({"path": "frames/000000.npz"})
        else:                                         # guided turns: a person, or an object
            seg = job.get("segment", {})
            turns = TURNS[kind]
            first = "Stand still, facing the TV" if kind == "person" else "Set it down and take your hands away"
            again = ("Turn a little more to your left, then hold still" if kind == "person" else
                     "Turn it anticlockwise (seen from above) about a twelfth of a turn, then let go")
            for turn in range(turns):
                angle = turn * 360 / turns
                say(stage="turn", done=turn, total=turns, turn=turn, angle=angle, say=first if turn == 0 else again)
                prev, still_since, start = None, None, time.monotonic()
                while True:
                    depth = cam.read()[0]
                    fg = _fg(depth, k, seg)
                    if prev is not None:
                        both = (fg > 0) & (prev > 0)
                        change = float(np.abs(fg[both].astype(np.int32) - prev[both]).mean()) if both.sum() > 500 else 999.0
                        if change < STILL_MM and (turn == 0 or time.monotonic() - start > 1.5):
                            still_since = still_since or time.monotonic()
                        else:
                            still_since = None
                    prev = fg
                    waited = time.monotonic() - start
                    if (still_since and time.monotonic() - still_since >= STILL_FOR) or waited > TURN_TIMEOUT:
                        break
                    say(stage="settle", done=turn, total=turns, turn=turn,
                        still=round(min(1.0, (time.monotonic() - still_since) / STILL_FOR), 2) if still_since else 0.0)
                views = [cam.read()[0] for _ in range(6)]
                rel = f"frames/{turn:06d}.npz"
                save_frame(out / rel, median_depth(views), k)
                manifest["frames"].append({"path": rel, "angle_deg": angle, "settled": waited <= TURN_TIMEOUT})
                say(stage="turn", done=turn + 1, total=turns, turn=turn, angle=angle, taken=True)
        manifest["completed"] = True
        manifest["skipped_other_geometry"] = cam.skipped
    write_json(out / "session.json", manifest)
    say(result={"frames": len(manifest["frames"]), "skipped_other_geometry": manifest["skipped_other_geometry"]})


# ------------------------------------------------------------------ reconstruct

def boundary_edges(triangles):
    """Edges used by exactly one triangle: the open edges of a surface (holes, the scan's rim)."""
    t = np.asarray(triangles, dtype=np.int64)
    if not len(t):
        return 0
    e = np.concatenate([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]])
    e.sort(axis=1)
    _, counts = np.unique(e, axis=0, return_counts=True)
    return int((counts == 1).sum())


def geometry_bin(path, points, vertices=None, triangles=None):
    """The preview the page draws: u32 points, u32 vertices, u32 triangles, then float32 points,
    float32 vertices, uint32 triangles (metres, camera frame: y down)."""
    p = np.asarray(points, np.float32).reshape(-1, 3)
    v = np.zeros((0, 3), np.float32) if vertices is None else np.asarray(vertices, np.float32)
    t = np.zeros((0, 3), np.uint32) if triangles is None else np.asarray(triangles, np.uint32)
    if len(p) > 200_000:
        p = p[np.linspace(0, len(p) - 1, 200_000).astype(int)]
    with open(path, "wb") as f:
        f.write(np.array([len(p), len(v), len(t)], np.uint32).tobytes())
        f.write(p.tobytes())
        f.write(v.tobytes())
        f.write(t.tobytes())


def _segmented_session(src, seg, kind):
    """The capture's frames, each cut down to the subject, as a scanner session."""
    from dataclasses import replace

    from kinectscan.geometry import rectify_depth
    from kinectscan.storage import load_frame, load_session, save_frame, write_json
    manifest, entries = load_session(src)
    out = src / "segmented"
    out.mkdir(exist_ok=True)
    seg_manifest = {**manifest, "frames": []}
    room = cut = 0
    for path, item in entries:
        depth, k, pose = load_frame(path)
        depth = rectify_depth(depth, k)
        k = replace(k, distortion=())
        fg = _fg(depth, k, seg)
        mask = fg > 0
        if mask.any():
            rows, cols = np.nonzero(mask)
            top, bottom = rows.min() <= 1, rows.max() >= mask.shape[0] - 2
            left, right = cols.min() <= 1, cols.max() >= mask.shape[1] - 2
            # Both sides, or three edges: that is the room. Top or bottom alone: a cut-off subject.
            room += (left and right) or (int(top) + int(bottom) + int(left) + int(right) >= 3)
            cut += bool(top or bottom)
        rel = f"frames/{Path(path).name}"
        save_frame(out / rel, fg, k, pose=pose)
        seg_manifest["frames"].append({**item, "path": rel})
    write_json(out / "session.json", seg_manifest)
    n = max(1, len(entries))
    return out, seg_manifest, room / n, cut / n


def _turn_poses(session_dir, manifest, note, kind="person"):
    """Each turn's view: first from its nominal turn about the subject's vertical axis, then
    refined with ICP to the views already placed. -> (accepted frame list, per-view quality).

    The axis: a person turns about the middle of their body, about 12 cm behind the surface the
    Kinect sees. An object's depth is unknown, so its axis is found from the first turn: the
    depth behind the surface whose turn lines up best."""
    import open3d as o3d

    from kinectscan.geometry import depth_to_xyz, rotation_axis_angle, validate_transform
    from kinectscan.storage import load_frame, save_frame
    reg = o3d.pipelines.registration

    def refine(source, target, guess, nudge=False):
        """Point-to-point ICP from the turn's own guess, coarse to fine, with a bounded reach:
        point-to-plane slides off on the flat parts of a body seen 45 degrees apart. Once the
        axis is known (nudge), only a small reach: a side never seen before (the back) has no
        true partner in the model, and a long reach drags it onto the front."""
        T = guess
        result = None
        steps = ((0.012, 0.02), (0.006, 0.012)) if nudge else ((0.03, 0.08), (0.015, 0.04), (0.01, 0.025))
        for size, reach in steps:
            s, t = source.voxel_down_sample(size), target.voxel_down_sample(size)
            result = reg.registration_icp(s, t, reach, T, reg.TransformationEstimationPointToPoint(),
                                          reg.ICPConvergenceCriteria(max_iteration=60))
            T = result.transformation
        return result
    clouds, placed, quality, kept = [], [], [], []
    centre = None
    voxel = 0.012 if kind == "person" else 0.006
    axis_found = False
    direction = 1.0           # +1: turned to its own left (anticlockwise seen from above)
    for i, item in enumerate(manifest["frames"]):
        note("register", i, len(manifest["frames"]))
        path = session_dir / item["path"]
        depth, k, _ = load_frame(path)
        p = depth_to_xyz(depth, k).reshape(-1, 3)
        p = p[np.isfinite(p).all(axis=1)]
        if len(p) < 500:
            quality.append({"turn": i, "accepted": False, "why": "too little of the person was seen"})
            continue
        if centre is None:
            # The turning axis runs through the middle of the body, about 12 cm behind the
            # surface the Kinect sees (objects: found from the first turn, below).
            centre = np.median(p, axis=0) + np.array([0.0, 0.0, 0.12])
            surface = np.median(p, axis=0)
        cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(p)).voxel_down_sample(voxel)
        cloud.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=voxel * 4, max_nn=40))
        # Turning to their left, seen from a camera with y down: about -Y through their centre.
        angle = math.radians(item.get("angle_deg", 0.0))

        def about(c, sign=None):
            g = np.eye(4)
            g[:3, :3] = rotation_axis_angle([0.0, -1.0, 0.0], -angle * (direction if sign is None else sign))
            g[:3, 3] = c - g[:3, :3] @ c
            return g
        guess = about(centre)
        if clouds and not axis_found:
            # The first turn: which way it went, and how deep its axis is (a person: about
            # 12 cm behind the surface; an object: anywhere up to 30 cm).
            # Judged by the fit and by how far ICP had to correct the turn (a nearly symmetric
            # object can fit the wrong way round almost as well); the way people were asked to
            # turn wins unless the other is clearly better.
            best = {}
            depths = (0.12,) if kind == "person" else np.arange(0.01, 0.31, 0.02)
            for sign in (1.0, -1.0):
                for depth_behind in depths:
                    c = surface + np.array([0.0, 0.0, depth_behind])
                    g = about(c, sign)
                    r_ = refine(cloud, clouds[0], g)
                    R = np.asarray(r_.transformation)[:3, :3] @ g[:3, :3].T
                    corr = math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(R) - 1) / 2))))
                    score = r_.fitness - 20 * r_.inlier_rmse - corr / 20
                    if sign not in best or score > best[sign][0]:
                        best[sign] = (score, c)
            direction = -1.0 if best[-1.0][0] > best[1.0][0] + 0.15 else 1.0
            centre = best[direction][1]
            axis_found = True
            guess = about(centre)
        if not clouds:
            pose, q = guess, {"turn": i, "accepted": True, "fitness": 1.0, "inlier_rmse_m": 0.0, "rotation_deg": 0.0}
        else:
            target = o3d.geometry.PointCloud()
            for c, T in zip(clouds, placed):
                target += o3d.geometry.PointCloud(c).transform(T)
            target = target.voxel_down_sample(voxel)
            result = refine(cloud, target, guess, nudge=len(placed) >= 2)
            pose = validate_transform(result.transformation)
            q = {"fitness": round(float(result.fitness), 3), "inlier_rmse_m": round(float(result.inlier_rmse), 4)}
            correction = math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(np.linalg.inv(guess) @ pose) - 2) / 2))))
            # How far the subject itself was moved from where its turn put it (its centre: a
            # turn a few degrees off about the right axis moves it hardly at all).
            moved = float(np.linalg.norm((pose[:3, :3] - guess[:3, :3]) @ centre + pose[:3, 3] - guess[:3, 3]))
            known = len(placed) >= 2                      # the axis is solved from placed turns
            enough = q["fitness"] >= 0.30 or (known and q["fitness"] >= 0.12 and correction <= 10 and moved <= 0.03)
            q.update(turn=i, correction_deg=round(correction, 1), moved_m=round(moved, 3),
                     accepted=enough and q["inlier_rmse_m"] <= 0.02 and correction <= 25
                     and moved <= (0.06 if known else 0.15))       # the first turn finds the axis
            if not q["accepted"]:
                q["why"] = (f"overlap {q['fitness']:.2f} (needs 0.30, or 0.12 with a small correction), {q['inlier_rmse_m'] * 1000:.0f} mm apart "
                            f"(needs under 20), {correction:.0f} degrees and {moved * 100:.0f} cm from where the "
                            f"{item.get('angle_deg', 0):.0f} degree turn should have put it (at most 25 degrees, 6 cm; 15 on the first)")
        quality.append(q)
        if not q["accepted"] and len(placed) < 2:
            axis_found = False                            # the first turn did not line up: search again
        if q["accepted"]:
            clouds.append(cloud)
            placed.append(pose)
            save_frame(path, depth, k, pose=pose)
            kept.append(item)
            if len(placed) >= 2:
                centre = _axis_centre(placed, centre)
    return kept, quality


def _axis_centre(poses, centre):
    """Where the turning axis really is, from the turns placed so far: each is a rotation R
    about the vertical axis through c, so its translation t = c - R c; least squares over all
    of them gives c (its height stays as it was: a vertical axis has none)."""
    rows, rhs = [], []
    for T in poses[1:]:
        R, t = T[:3, :3], T[:3, 3]
        rows.append((np.eye(3) - R)[[0, 2]][:, [0, 2]])
        rhs.append(t[[0, 2]] - (np.eye(3) - R)[[0, 2]][:, 1] * centre[1])
    A, b = np.vstack(rows), np.concatenate(rhs)
    if np.linalg.matrix_rank(A) < 2:
        return centre
    xz = np.linalg.lstsq(A, b, rcond=None)[0]
    return np.array([xz[0], centre[1], xz[1]])


def reconstruct(job):
    from kinectscan.geometry import depth_to_xyz, grid_mesh, measurement_report
    from kinectscan.reconstruct import reconstruct as fuse
    from kinectscan.storage import load_frame, write_json
    src = Path(job["dir"])
    out = src / "result"
    kind = job["kind"]
    seg = job.get("segment", {})

    def note(stage, done, total):
        say(stage=stage, done=done, total=total)

    try:
        session, manifest, room, cut = _segmented_session(src, seg, kind)
        if room > 0.5:
            raise RuntimeError("The subject runs off the sides of the picture in most views: it includes the room. "
                               "Narrow the depth range, or capture the empty background first.")
        if cut > 0.5:
            raise RuntimeError("Part of you was outside the picture in most turns: step back until all of you is in view."
                               if kind == "person" else
                               "Part of it was outside the picture in most views: move it towards the middle, or back a little.")
        coverage = {}
        if kind == "object":
            depth, k, _ = load_frame(session / manifest["frames"][0]["path"])
            xyz = depth_to_xyz(depth, k).reshape(-1, 3)
            points = xyz[np.isfinite(xyz).all(axis=1)]
            if len(points) < 300:
                raise RuntimeError("Too few points on the subject: move it into the depth range, or closer.")
            vertices, triangles = grid_mesh(depth, k, stride=2, max_edge_m=0.04)
            out.mkdir(exist_ok=True)
            report = measurement_report(points, "one view: the side facing the Kinect only")
            coverage = {"views": 1, "seen": "the side facing the Kinect", "missing": "the back and the underside: not seen, not made up"}
        else:
            kept, quality = _turn_poses(session, manifest, note, kind)
            coverage = {"views": len(kept), "of": len(manifest["frames"]),
                        "angles": [it.get("angle_deg") for it in kept],
                        "missing_angles": [it.get("angle_deg") for it in manifest["frames"] if it not in kept],
                        "registration": quality}
            if len(kept) < 2:
                raise RuntimeError("Fewer than two of the turns lined up, so there is nothing to fuse. " +
                                   ("Hold still longer at each turn, and keep your arms a little away from your body."
                                    if kind == "person" else
                                    "Turn it by about the same step each time, and take your hands away before it is taken."))
            write_json(session / "session.json", {**manifest, "frames": kept, "subject_motion": "known_poses"})
            rep = fuse(session, out, "known", voxel_m=0.008 if kind == "person" else 0.004, progress=note)
            import open3d as o3d
            mesh = o3d.io.read_triangle_mesh(str(out / "fused_mesh.ply"))
            vertices, triangles = np.asarray(mesh.vertices), np.asarray(mesh.triangles)
            pts = o3d.io.read_point_cloud(str(out / "fused_points.ply"))
            points = np.asarray(pts.points)
            report = rep
        open_edges = boundary_edges(triangles)
        failed = [q for q in coverage.get("registration") or [] if q.get("accepted") is False]
        report.update(kind=kind, coverage=coverage, open_edges=open_edges, closed=open_edges == 0,
                      triangles=int(len(triangles)), vertices=int(len(vertices)),
                      alignment_failure=None if not failed else {
                          "turns": [q["turn"] for q in failed], "of": len(manifest["frames"]),
                          "why": failed[0].get("why"), "kept": f"{coverage['views']} of {len(manifest['frames'])} views fused"})
        report["complete"] = bool(report["closed"] and kind != "object" and not coverage.get("missing_angles"))
        out.mkdir(exist_ok=True)
        write_json(out / "report.json", report)
        geometry_bin(out / "geometry.bin", points, vertices, triangles)
        np.save(out / "vertices.npy", np.asarray(vertices, np.float64))
        np.save(out / "triangles.npy", np.asarray(triangles, np.int64))
        np.save(out / "points.npy", np.asarray(points, np.float64))
        say(result=report)
    finally:
        # The depth captures are temporary: gone once there is a result (or none).
        for d in ("frames", "segmented"):
            shutil.rmtree(src / d, ignore_errors=True)
        (src / "session.json").unlink(missing_ok=True)


def main():
    job = json.loads(sys.argv[1])
    try:
        {"background": background, "capture": capture, "reconstruct": reconstruct}[job["job"]](job)
    except Exception as err:                         # noqa: BLE001 (reported, never silent)
        say(error=f"{err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
