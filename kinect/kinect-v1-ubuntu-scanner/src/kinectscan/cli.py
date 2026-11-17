"""Command-line entry point. Hardware and graphical imports are lazy."""
from __future__ import annotations
import argparse
from dataclasses import replace
import importlib.metadata
import json
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import time
import numpy as np
from .capture import KinectCapture,library_path
from .geometry import (Intrinsics,rectify_depth,segment_depth,depth_to_xyz,grid_mesh,
                        measurement_report,fit_axis_circle,turntable_pose)
from .storage import (new_directory,save_frame,load_frame,write_json,export_geometry,
                       write_mesh)


def _sensor(args):
    k=Intrinsics.load(args.intrinsics) if args.intrinsics else None
    return KinectCapture(index=args.device,timeout=args.timeout,intrinsics=k)


def _processed(depth,k,args):
    rectified=rectify_depth(depth,k)
    rk=replace(k,distortion=())
    bg=None
    if args.background:
        bg,bk,_=load_frame(args.background)
        if (bk.width,bk.height)!=(rk.width,rk.height) or not np.allclose(bk.matrix,rk.matrix):
            raise ValueError("Background and capture intrinsics differ; recapture the background")
        if bk.distortion and not np.allclose(bk.distortion,0):
            raise ValueError("Background must already be rectified")
    filtered=segment_depth(rectified,rk,z_min=args.z_min,z_max=args.z_max,roi=args.roi,
            box=args.box,background=bg,background_margin_mm=args.background_margin_mm,
            largest_component=args.largest_component)
    return filtered,rk


def _summary(data):
    print(json.dumps(data,indent=2,allow_nan=False))


def doctor(args):
    versions={}
    for name in ("numpy","scipy","open3d","opencv-python"):
        try: versions[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: versions[name]="not installed"
    usb="lsusb not installed"
    if shutil.which("lsusb"):
        result=subprocess.run(["lsusb"],capture_output=True,text=True,timeout=5,check=False)
        usb="\n".join(line for line in result.stdout.splitlines() if "045e:" in line) or "No Microsoft USB devices listed"
    _summary({"system":platform.platform(),"python":sys.version,"packages":versions,
        "libfreenect_sync":library_path(),"microsoft_usb_devices":usb,
        "note":"This does not open the camera. Run probe for a live connection test."})


def probe(args):
    with _sensor(args) as camera:
        for _ in range(5): depth,stamp,host=camera.read()
        k=camera.k
        valid=(depth>0)&(depth<10000)
        if not valid.any(): raise RuntimeError("Device opened but depth is all invalid. Check range, IR conditions and power.")
        if args.out:
            if Path(args.out).exists(): raise FileExistsError(args.out)
            k.save(args.out)
        _summary({"intrinsics":k.to_dict(),"valid_fraction":float(valid.mean()),
                  "median_depth_m":float(np.median(depth[valid])/1000),"timestamp":stamp,
                  "warning":"Connection success is not a calibration/accuracy certificate."})


def background(args):
    path=Path(args.out)
    if path.exists(): raise FileExistsError(path)
    with _sensor(args) as camera:
        print("Keep the scan region empty and the sensor/support/background fixed.")
        time.sleep(args.delay)
        raw,stamp,host=camera.median(args.samples,max_std_mm=args.max_std_mm)
        depth=rectify_depth(raw,camera.k); k=replace(camera.k,distortion=())
        save_frame(path,depth,k,raw=raw,timestamp=stamp,host_time=host)
        write_json(path.with_suffix(".metadata.json"),{"capture_intrinsics":camera.k.to_dict(),
            "samples":args.samples,"description":"Empty scene; median depth; zeros remain unobserved."})
        _summary({"saved":str(path),"valid_fraction":float((depth>0).mean())})


def _snapshot_write(out,raw,k,stamp,host,args):
    filtered,rk=_processed(raw,k,args)
    xyz=depth_to_xyz(filtered,rk).reshape(-1,3); xyz=xyz[np.isfinite(xyz).all(axis=1)]
    if len(xyz)<args.min_points: raise ValueError("Too few foreground points. Inspect preview/ROI/depth range/background.")
    out=new_directory(out)
    vertices,triangles=grid_mesh(filtered,rk,stride=args.stride,max_edge_m=args.max_edge_m)
    save_frame(out/"frame.npz",filtered,rk,raw=raw,timestamp=stamp,host_time=host)
    k.save(out/"capture_intrinsics.json")
    export_geometry(out,xyz,vertices,triangles)
    report=measurement_report(xyz)
    report["mesh_is_observed_surface_only"]=True
    report["mesh_triangles"]=len(triangles)
    report["print_readiness"]="Not guaranteed; front-surface mesh is generally open. Hidden surfaces are not fabricated."
    write_json(out/"measurements.json",report)
    _summary(report)


def snapshot(args):
    if args.input:
        depth,k,_=load_frame(args.input)
        _snapshot_write(args.out,depth,k,0,0.,args)
    else:
        with _sensor(args) as camera:
            time.sleep(args.delay)
            depth,stamp,host=camera.median(args.samples,max_std_mm=args.max_std_mm)
            _snapshot_write(args.out,depth,camera.k,stamp,host,args)


def preview(args):
    try: import cv2
    except ImportError as exc: raise RuntimeError("Install opencv-python / the gui extra") from exc
    with _sensor(args) as camera:
        try:
            while True:
                raw,_,_=camera.read(); depth,k=_processed(raw,camera.k,args)
                scale=np.clip((depth.astype(float)/1000-args.z_min)/(args.z_max-args.z_min),0,1)
                image=cv2.applyColorMap((255*scale).astype(np.uint8),cv2.COLORMAP_TURBO)
                image[depth==0]=0
                cv2.putText(image,f"Valid {(depth>0).mean():.1%} | depth mm | Q/ESC exits",(12,24),
                            cv2.FONT_HERSHEY_SIMPLEX,.55,(255,255,255),1)
                if args.roi:
                    x0,y0,x1,y1=args.roi; cv2.rectangle(image,(x0,y0),(x1-1,y1-1),(255,255,255),1)
                cv2.imshow("Kinect v1 depth (X right, Y down)",image)
                key=cv2.waitKey(1)&255
                if key in (ord("q"),27): break
        finally: cv2.destroyAllWindows()


def _manifest(k,args,motion):
    return {"schema_version":1,"synthetic":False,"subject_motion":motion,
        "foreground_isolated":bool(args.background or args.roi or args.box),
        "capture_intrinsics":k.to_dict(),"depth_unit":"millimeter",
        "pose_convention":"T_world_from_camera; world=angle-zero camera frame; meters",
        "segmentation":{"roi":args.roi,"box":args.box,"background":args.background,
                        "z_min":args.z_min,"z_max":args.z_max,"background_margin_mm":args.background_margin_mm,
                        "largest_component":args.largest_component},
        "frames":[],"completed":False,
        "warning":"Foreground_isolated records requested cropping, not successful semantic segmentation. Inspect every mask."}


def record(args):
    if args.seconds<=0 or not 0<args.fps<=30 or args.seconds*args.fps>1200:
        raise ValueError("Require duration>0, FPS in (0,30], and at most 1200 requested frames")
    out=new_directory(args.out); (out/"frames").mkdir()
    with _sensor(args) as camera:
        manifest=_manifest(camera.k,args,"stationary" if args.stationary else "unknown_rotating_subject")
        write_json(out/"session.json",manifest)
        time.sleep(args.delay); start=time.monotonic(); i=0
        try:
            while time.monotonic()-start<args.seconds:
                raw,stamp,host=camera.read(); depth,k=_processed(raw,camera.k,args)
                if np.count_nonzero(depth)<args.min_points:
                    raise RuntimeError(f"Frame {i} has too few foreground points; stopped rather than record an unusable session")
                rel=f"frames/{i:06d}.npz"
                save_frame(out/rel,depth,k,raw=raw,timestamp=stamp,host_time=host)
                manifest["frames"].append({"path":rel,"device_timestamp":stamp,"host_monotonic_s":host})
                write_json(out/"session.json",manifest)
                i+=1; print(f"Captured {i} frames",end="\r",flush=True)
                time.sleep(max(0,start+i/args.fps-time.monotonic()))
            manifest["completed"]=True
        finally:
            write_json(out/"session.json",manifest); print()
    _summary({"session":str(out),"frames":len(manifest["frames"]),"completed":manifest["completed"]})


def turntable(args):
    if not 0<args.step_deg<=20 or not np.isclose(360/args.step_deg,round(360/args.step_deg)):
        raise ValueError("Use a positive angle <=20 degrees that divides 360")
    axis=json.loads(Path(args.axis).read_text())
    if axis.get("observed_arc_deg",0)<180:
        raise ValueError("Axis calibration must cover at least 180 degrees")
    # Validate axis/center before creating a recording.
    turntable_pose(0,axis["center_m"],axis["axis"])
    out=new_directory(args.out); (out/"frames").mkdir()
    with _sensor(args) as camera:
        manifest=_manifest(camera.k,args,"known_turntable")
        manifest["turntable_axis"]=axis
        manifest["angle_source"]="manual indexed stop-and-hold; commanded angles are assumed, not encoder-measured"
        write_json(out/"session.json",manifest)
        try:
            angles=np.linspace(0,360,int(round(360/args.step_deg))+1)
            for i,angle in enumerate(angles):
                input(f"Place object at {angle:.1f} deg using the documented right-hand sign; stop motion; press Enter: ")
                time.sleep(args.settle_sec)
                raw,stamp,host=camera.median(args.samples,max_std_mm=args.max_std_mm)
                depth,k=_processed(raw,camera.k,args)
                if np.count_nonzero(depth)<args.min_points: raise RuntimeError("Too few foreground samples")
                rel=f"frames/{i:06d}.npz"; pose=turntable_pose(angle,axis["center_m"],axis["axis"])
                save_frame(out/rel,depth,k,raw=raw,timestamp=stamp,host_time=host,pose=pose)
                manifest["frames"].append({"path":rel,"angle_deg":float(angle),"device_timestamp":stamp,"host_monotonic_s":host})
                write_json(out/"session.json",manifest)
            manifest["completed"]=True
        finally: write_json(out/"session.json",manifest)
    _summary({"session":str(out),"frames":len(manifest["frames"])})


def axis_fit(args):
    points=np.loadtxt(args.points,delimiter=",",skiprows=args.skiprows,ndmin=2)
    if args.input_units=="mm": points=points/1000.
    result=fit_axis_circle(points,args.preferred_axis)
    if result["observed_arc_deg"]<180: raise ValueError("Orbit coverage <180 degrees; acquire more viewpoints")
    if result["rms_residual_mm"]>args.max_rms_mm: raise ValueError(f"Axis fit residual is {result['rms_residual_mm']:.2f} mm; exceeds threshold")
    if Path(args.out).exists(): raise FileExistsError(args.out)
    write_json(args.out,result); _summary(result)


def measure(args):
    depth,k,_=load_frame(args.input)
    if k.distortion and not np.allclose(k.distortion,0):
        raise ValueError("Select points on a rectified captured frame")
    def point(pixel):
        u,v=pixel
        if not 0<=u<k.width or not 0<=v<k.height: raise ValueError("Pixel outside frame")
        r=args.radius
        patch=depth[max(0,v-r):min(k.height,v+r+1),max(0,u-r):min(k.width,u+r+1)]
        good=patch[(patch>0)&(patch<10000)]
        if not len(good): raise ValueError(f"No valid depth at pixel {pixel}; no hidden/nearby point is guessed")
        z=float(np.median(good))/1000
        return np.array([(u-k.cx)*z/k.fx,(v-k.cy)*z/k.fy,z])
    p1,p2=point(args.p1),point(args.p2)
    result={"point1_m":p1.tolist(),"point2_m":p2.tolist(),"distance_mm":float(np.linalg.norm(p2-p1)*1000),
            "pixel1":args.p1,"pixel2":args.p2,"patch_radius":args.radius,
            "warning":"Visible-point Euclidean distance. A patch median assumes locally uniform depth; avoid boundaries."}
    if args.out: write_json(args.out,result)
    _summary(result)


def reconstruct_command(args):
    from .reconstruct import reconstruct
    _summary(reconstruct(args.session,args.out,args.mode,voxel_m=args.voxel_m,
          min_fitness=args.min_fitness,max_rmse_m=args.max_rmse_m,
          max_rotation_deg=args.max_rotation_deg,max_translation_m=args.max_translation_m,
          close_loop=args.close_loop))


def fuse_known(args):
    from .reconstruct import fuse_known_clouds
    _summary(fuse_known_clouds(args.session,args.out,args.voxel_m))


def demo(args):
    from .synthetic import create_demo
    manifest=create_demo(args.out,args.step_deg)
    _summary({"synthetic":True,"frames":len(manifest["frames"]),"out":args.out,
              "next":"Use fuse-known for point fusion or reconstruct --mode known with Open3D."})


def view(args):
    from .reconstruct import open3d_module
    o3d=open3d_module(); mesh=o3d.io.read_triangle_mesh(args.input)
    if len(mesh.triangles): mesh.compute_vertex_normals(); obj=mesh
    else: obj=o3d.io.read_point_cloud(args.input)
    if obj.is_empty(): raise ValueError("No displayable geometry")
    o3d.visualization.draw_geometries([obj],window_name="KinectScan geometry")


def convert(args):
    from .reconstruct import open3d_module
    if Path(args.out).exists(): raise FileExistsError(args.out)
    o3d=open3d_module(); mesh=o3d.io.read_triangle_mesh(args.input)
    if not len(mesh.triangles): raise ValueError("Input has no triangles. A point cloud is not an STL mesh.")
    scale=.001 if args.input_units=="mm" else 1.
    write_mesh(args.out,np.asarray(mesh.vertices)*scale,np.asarray(mesh.triangles),stl_units=args.stl_units)
    _summary({"output":args.out,"note":"Geometry-only conversion; no hole filling, texture conversion or CAD reverse engineering."})


def mesh_check(args):
    from .reconstruct import open3d_module
    o3d=open3d_module(); mesh=o3d.io.read_triangle_mesh(args.input)
    if not len(mesh.triangles): raise ValueError("No triangles")
    result={"vertices":len(mesh.vertices),"triangles":len(mesh.triangles),
            "edge_manifold_without_boundaries":bool(mesh.is_edge_manifold(allow_boundary_edges=False)),
            "vertex_manifold":bool(mesh.is_vertex_manifold()),"watertight":bool(mesh.is_watertight()),
            "orientable":bool(mesh.is_orientable()),
            "warning":"Topology checks do not prove measured coverage, dimensional accuracy, or printer suitability."}
    if args.out: write_json(args.out,result)
    _summary(result)


def _sensor_args(p):
    p.add_argument("--device",type=int,default=0)
    p.add_argument("--timeout",type=float,default=10.)
    p.add_argument("--intrinsics",help="Calibrated IR FREENECT_DEPTH_MM JSON; otherwise query device factory ray model")


def _segmentation_args(p):
    p.add_argument("--z-min",type=float,default=.7)
    p.add_argument("--z-max",type=float,default=3.5)
    p.add_argument("--roi",type=int,nargs=4,metavar=("X0","Y0","X1","Y1"))
    p.add_argument("--box",type=float,nargs=6,metavar=("XMIN","XMAX","YMIN","YMAX","ZMIN","ZMAX"))
    p.add_argument("--background",help="Empty-scene .npz from background command")
    p.add_argument("--background-margin-mm",type=float,default=25.)
    p.add_argument("--largest-component",action="store_true",help="Keep only largest connected depth silhouette; can discard disconnected limbs")
    p.add_argument("--min-points",type=int,default=200)


def _samples_args(p):
    p.add_argument("--samples",type=int,default=15)
    p.add_argument("--max-std-mm",type=float,default=None,help="Reject temporally unstable pixels; only use while subject is still")


def parser():
    p=argparse.ArgumentParser(description="Fixed Kinect v1 / Ubuntu geometry scanner. See README for limitations.")
    sub=p.add_subparsers(dest="command",required=True)
    q=sub.add_parser("doctor",help="Inspect environment without opening hardware"); q.set_defaults(func=doctor)
    q=sub.add_parser("probe",help="Connect and query factory ray intrinsics"); _sensor_args(q); q.add_argument("--out"); q.set_defaults(func=probe)
    q=sub.add_parser("preview",help="Live masked depth preview"); _sensor_args(q); _segmentation_args(q); q.set_defaults(func=preview)
    q=sub.add_parser("background",help="Capture an empty-scene background"); _sensor_args(q); _samples_args(q)
    q.add_argument("--out",required=True); q.add_argument("--delay",type=float,default=3.); q.set_defaults(func=background)
    q=sub.add_parser("snapshot",help="Observed points/mesh and measurements from one stationary view")
    _sensor_args(q); _segmentation_args(q); _samples_args(q)
    q.add_argument("--input",help="Offline .npz replay instead of hardware")
    q.add_argument("--out",required=True); q.add_argument("--delay",type=float,default=3.)
    q.add_argument("--stride",type=int,default=2); q.add_argument("--max-edge-m",type=float,default=.04); q.set_defaults(func=snapshot)
    q=sub.add_parser("record",help="Fixed camera, slowly rotating subject; estimate relative poses later")
    _sensor_args(q); _segmentation_args(q); q.add_argument("--out",required=True)
    q.add_argument("--seconds",type=float,default=60.); q.add_argument("--fps",type=float,default=5.)
    q.add_argument("--delay",type=float,default=5.); q.add_argument("--stationary",action="store_true",help="Assert BOTH camera and subject remain stationary")
    q.set_defaults(func=record)
    q=sub.add_parser("axis-fit",help="Fit turntable axis from tracked off-axis target XYZ samples")
    q.add_argument("--points",required=True); q.add_argument("--out",required=True)
    q.add_argument("--skiprows",type=int,default=1); q.add_argument("--input-units",choices=("m","mm"),default="m")
    q.add_argument("--preferred-axis",type=float,nargs=3,default=[0.,-1.,0.])
    q.add_argument("--max-rms-mm",type=float,default=10.); q.set_defaults(func=axis_fit)
    q=sub.add_parser("turntable",help="Manually indexed step-and-hold product scan; no motor driver")
    _sensor_args(q); _segmentation_args(q); _samples_args(q)
    q.add_argument("--axis",required=True); q.add_argument("--out",required=True)
    q.add_argument("--step-deg",type=float,default=10.); q.add_argument("--settle-sec",type=float,default=.7)
    q.set_defaults(func=turntable)
    q=sub.add_parser("measure",help="Distance between two visible pixels in a saved frame")
    q.add_argument("--input",required=True); q.add_argument("--p1",type=int,nargs=2,required=True)
    q.add_argument("--p2",type=int,nargs=2,required=True); q.add_argument("--radius",type=int,default=0)
    q.add_argument("--out"); q.set_defaults(func=measure)
    q=sub.add_parser("reconstruct",help="Open3D TSDF mesh with explicit relative-pose mode")
    q.add_argument("--session",required=True); q.add_argument("--out",required=True)
    q.add_argument("--mode",choices=("auto","known","static"),required=True)
    q.add_argument("--voxel-m",type=float,default=.006); q.add_argument("--min-fitness",type=float,default=.6)
    q.add_argument("--max-rmse-m",type=float,default=.02); q.add_argument("--max-rotation-deg",type=float,default=25.)
    q.add_argument("--max-translation-m",type=float,default=.30); q.add_argument("--close-loop",action="store_true")
    q.set_defaults(func=reconstruct_command)
    q=sub.add_parser("fuse-known",help="Known-pose multi-view point fusion without Open3D")
    q.add_argument("--session",required=True); q.add_argument("--out",required=True)
    q.add_argument("--voxel-m",type=float,default=.005); q.set_defaults(func=fuse_known)
    q=sub.add_parser("demo",help="Create clearly labeled synthetic test session; no camera required")
    q.add_argument("--out",required=True); q.add_argument("--step-deg",type=int,default=10); q.set_defaults(func=demo)
    q=sub.add_parser("view",help="Open a point cloud or mesh with Open3D")
    q.add_argument("--input",required=True); q.set_defaults(func=view)
    q=sub.add_parser("convert",help="Convert geometry mesh formats with explicit input units")
    q.add_argument("--input",required=True); q.add_argument("--out",required=True)
    q.add_argument("--input-units",choices=("m","mm"),required=True); q.add_argument("--stl-units",choices=("m","mm"),default="mm")
    q.set_defaults(func=convert)
    q=sub.add_parser("mesh-check",help="Check topology; does not certify printing or measurements")
    q.add_argument("--input",required=True); q.add_argument("--out"); q.set_defaults(func=mesh_check)
    return p


def main(argv=None):
    p=parser(); args=p.parse_args(argv)
    try:
        for name in ("delay","settle_sec","radius","skiprows"):
            if hasattr(args,name) and getattr(args,name)<0: raise ValueError(f"{name} cannot be negative")
        if hasattr(args,"min_points") and args.min_points<3: raise ValueError("min_points must be >=3")
        args.func(args)
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted. Completed frame files/manifests are retained; acquisition is closed.",file=sys.stderr)
        return 130
    except (RuntimeError,ValueError,OSError,KeyError,EOFError) as exc:
        print(f"ERROR: {exc}",file=sys.stderr)
        return 2

if __name__=="__main__":
    raise SystemExit(main())
