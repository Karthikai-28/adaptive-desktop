"""Local-only records and explicit geometry formats/units. No pickle loading."""
from __future__ import annotations
import json
import os
from pathlib import Path
import struct
import numpy as np
from .geometry import Intrinsics, validate_depth, validate_transform


def write_json(path,data):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+".tmp")
    temp.write_text(json.dumps(data,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    os.replace(temp,path)


def new_directory(path):
    p=Path(path)
    if p.exists() and any(p.iterdir()):
        raise FileExistsError(f"Refusing to overwrite nonempty output directory: {p}")
    p.mkdir(parents=True,exist_ok=True)
    return p


def save_frame(path,depth,k,*,raw=None,timestamp=0,host_time=0.,pose=None):
    validate_depth(depth,k)
    arrays={"depth_mm":depth,"intrinsics_json":np.array(json.dumps(k.to_dict())),
            "device_timestamp":np.array(timestamp,dtype=np.uint32),
            "host_monotonic_s":np.array(host_time,dtype=float)}
    if raw is not None: arrays["raw_depth_mm"]=validate_depth(raw,k)
    if pose is not None: arrays["T_world_from_camera"]=validate_transform(pose)
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+".tmp")
    with temp.open("wb") as f: np.savez_compressed(f,**arrays)
    os.replace(temp,path)


def load_frame(path):
    with np.load(path,allow_pickle=False) as data:
        k=Intrinsics.from_dict(json.loads(str(data["intrinsics_json"].item())))
        depth=validate_depth(data["depth_mm"],k).copy()
        pose=validate_transform(data["T_world_from_camera"]).copy() if "T_world_from_camera" in data else None
        return depth,k,pose


def load_session(path):
    root=Path(path)
    manifest=json.loads((root/"session.json").read_text())
    if manifest.get("schema_version")!=1: raise ValueError("Unsupported session schema")
    frames=[]
    for item in manifest["frames"]:
        p=(root/item["path"]).resolve()
        if root.resolve() not in p.parents: raise ValueError("Unsafe frame path in manifest")
        if not p.is_file(): raise FileNotFoundError(p)
        frames.append((p,item))
    if not frames: raise ValueError("Session contains no frames")
    return manifest,frames


def _points(points):
    p=np.asarray(points,float)
    if p.ndim!=2 or p.shape[1]!=3 or not len(p) or not np.isfinite(p).all():
        raise ValueError("Need a nonempty finite Nx3 point array")
    return p


def write_cloud(path,points):
    p=_points(points); path=Path(path); ext=path.suffix.lower()
    if ext==".xyz":
        np.savetxt(path,p,fmt="%.9f",header="units=meters; X right Y down Z forward")
    elif ext==".ply":
        header=(f"ply\nformat ascii 1.0\ncomment units meters\nelement vertex {len(p)}\n"
                "property double x\nproperty double y\nproperty double z\nend_header\n")
        with path.open("w") as f:
            f.write(header); np.savetxt(f,p,fmt="%.9f")
    elif ext==".pcd":
        header=("# .PCD v0.7; units meters\nVERSION 0.7\nFIELDS x y z\nSIZE 8 8 8\nTYPE F F F\n"
                f"COUNT 1 1 1\nWIDTH {len(p)}\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS {len(p)}\nDATA ascii\n")
        with path.open("w") as f:
            f.write(header); np.savetxt(f,p,fmt="%.9f")
    else: raise ValueError("Point cloud format must be PLY, PCD, or XYZ")


def write_mesh(path,vertices,triangles,*,stl_units="mm"):
    v=_points(vertices); t=np.asarray(triangles,dtype=np.int64)
    if t.ndim!=2 or t.shape[1]!=3 or not len(t) or t.min()<0 or t.max()>=len(v):
        raise ValueError("Need valid nonempty triangle indices")
    path=Path(path); ext=path.suffix.lower()
    if ext==".obj":
        with path.open("w") as f:
            f.write("# units meters; geometry only; no texture\n")
            np.savetxt(f,v,fmt="v %.9f %.9f %.9f")
            np.savetxt(f,t+1,fmt="f %d %d %d")
    elif ext==".ply":
        with path.open("w") as f:
            f.write(f"ply\nformat ascii 1.0\ncomment units meters\nelement vertex {len(v)}\n"
                    "property double x\nproperty double y\nproperty double z\n"
                    f"element face {len(t)}\nproperty list uchar int vertex_indices\nend_header\n")
            np.savetxt(f,v,fmt="%.9f")
            np.savetxt(f,np.column_stack((np.full(len(t),3),t)),fmt="%d")
    elif ext==".stl":
        if stl_units not in ("m","mm"): raise ValueError("STL units must be m or mm")
        vv=v*(1000. if stl_units=="mm" else 1.)
        p=vv[t]; n=np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0])
        norm=np.linalg.norm(n,axis=1); n/=np.maximum(norm[:,None],1e-20)
        records=np.zeros(len(t),dtype=np.dtype([("normal","<f4",(3,)),("vertices","<f4",(3,3)),("attr","<u2")]))
        records["normal"]=n; records["vertices"]=p
        with path.open("wb") as f:
            f.write(f"KinectScan coordinates in {stl_units}; units require importer agreement".encode("ascii")[:80].ljust(80,b" "))
            f.write(struct.pack("<I",len(t))); f.write(records.tobytes())
        write_json(path.with_suffix(".stl.units.json"),{"coordinate_units":stl_units,
            "meters_per_unit":0.001 if stl_units=="mm" else 1.,
            "warning":"STL has no standard unit declaration. Select these units in the receiving application."})
    else: raise ValueError("Mesh format must be PLY, OBJ, or STL")


def export_geometry(out,points,vertices=None,triangles=None,prefix="observed"):
    out=Path(out); out.mkdir(parents=True,exist_ok=True)
    for ext in ("ply","pcd","xyz"): write_cloud(out/f"{prefix}_points.{ext}",points)
    if vertices is not None and len(vertices) and triangles is not None and len(triangles):
        for ext in ("ply","obj","stl"):
            write_mesh(out/f"{prefix}_mesh.{ext}",vertices,triangles)
