"""Analytical box raycasts for tests. These are not Kinect measurements."""
from __future__ import annotations
import numpy as np
from .geometry import Intrinsics, turntable_pose, transform_points, depth_to_xyz, grid_mesh, measurement_report
from .storage import new_directory, save_frame, write_json, export_geometry


def raycast_boxes(k,pose,boxes):
    v,u=np.indices((k.height,k.width),dtype=float)
    rays=np.stack(((u-k.cx)/k.fx,(v-k.cy)/k.fy,np.ones_like(u)),axis=-1)
    direction=rays@pose[:3,:3].T; origin=pose[:3,3]
    best=np.full((k.height,k.width),np.inf)
    for lo,hi in boxes:
        lo=np.asarray(lo); hi=np.asarray(hi)
        parallel=np.abs(direction)<1e-12
        safe=np.where(parallel,1.,direction)
        ta=(lo-origin)/safe; tb=(hi-origin)/safe
        near=np.minimum(ta,tb); far=np.maximum(ta,tb)
        outside=parallel & ((origin<lo)|(origin>hi))
        near=np.where(parallel,-np.inf,near); far=np.where(parallel,np.inf,far)
        enter=near.max(axis=-1); leave=far.min(axis=-1)
        hit=(leave>=np.maximum(enter,0)) & ~outside.any(axis=-1)
        distance=np.where(enter>0,enter,leave)
        best=np.minimum(best,np.where(hit & (distance>0),distance,np.inf))
    depth=np.zeros(best.shape,dtype=np.uint16)
    good=np.isfinite(best)&(best<9.9)
    depth[good]=np.rint(best[good]*1000).astype(np.uint16)
    return depth


def create_demo(out,step_deg=10):
    if not 1<=step_deg<=45 or 360%step_deg:
        raise ValueError("Synthetic step must divide 360 and be between 1 and 45 degrees")
    out=new_directory(out); frames=out/"frames"; frames.mkdir()
    k=Intrinsics(160,120,150,150,79.5,59.5,source="synthetic analytic camera; not a Kinect calibration")
    center=[0,0,1.25]; axis=[0,-1,0]
    boxes=[([-0.20,-0.15,1.15],[0.20,0.15,1.35]),
           ([0.06,-0.25,1.18],[0.15,-0.15,1.28])]
    manifest={"schema_version":1,"synthetic":True,"subject_motion":"known_turntable",
              "foreground_isolated":True,"intrinsics":k.to_dict(),"frames":[],
              "truth":{"aabb_extent_mm":[400,400,200],"center_m":center,"axis":axis},
              "warning":"Synthetic data only. This demonstrates processing, not hardware compatibility or sensor accuracy."}
    first=None
    for i,angle in enumerate(range(0,361,step_deg)):
        pose=turntable_pose(angle,center,axis); depth=raycast_boxes(k,pose,boxes)
        rel=f"frames/{i:06d}.npz"; save_frame(out/rel,depth,k,timestamp=i*100,host_time=i*.1,pose=pose)
        manifest["frames"].append({"path":rel,"angle_deg":angle,"sample_index":i})
        if first is None: first=depth
    write_json(out/"session.json",manifest)
    obs=out/"first_view_observed"; obs.mkdir()
    xyz=depth_to_xyz(first,k).reshape(-1,3); xyz=xyz[np.isfinite(xyz).all(axis=1)]
    vertices,triangles=grid_mesh(first,k,stride=1,max_edge_m=.04)
    export_geometry(obs,xyz,vertices,triangles,prefix="synthetic_observed")
    write_json(obs/"measurements.json",measurement_report(xyz,"synthetic_single_view_only"))
    return manifest
