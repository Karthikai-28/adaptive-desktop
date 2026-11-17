"""Reuse Open3D ICP/pose graphs/TSDF rather than implement a fusion engine."""
from __future__ import annotations
import numpy as np
from .geometry import depth_to_xyz, transform_points, voxel_average, measurement_report, validate_transform
from .storage import load_session, load_frame, write_json, export_geometry, new_directory


def open3d_module():
    try: import open3d as o3d
    except ImportError as exc:
        raise RuntimeError("Open3D is required for reconstruction/viewing. Use the documented Ubuntu Python 3.10-3.12 environment and requirements-ubuntu.txt.") from exc
    return o3d


def _cloud(o3d,depth,k,voxel):
    points=depth_to_xyz(depth,k).reshape(-1,3)
    points=points[np.isfinite(points).all(axis=1)]
    cloud=o3d.geometry.PointCloud(o3d.utility.Vector3dVector(points))
    cloud=cloud.voxel_down_sample(voxel)
    if len(cloud.points)<100: raise ValueError("Too few segmented points for registration")
    cloud.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=voxel*4,max_nn=40))
    cloud.orient_normals_towards_camera_location(np.zeros(3))
    return cloud


def _icp(o3d,source,target,voxel,initial):
    transform=np.array(initial,copy=True)
    reg=o3d.pipelines.registration
    for factor,iterations in ((4,60),(2,40),(1,30)):
        size=voxel*factor
        src=source.voxel_down_sample(size); dst=target.voxel_down_sample(size)
        src.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=size*4,max_nn=40))
        dst.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=size*4,max_nn=40))
        result=reg.registration_icp(src,dst,size*3,transform,
              reg.TransformationEstimationPointToPlane(),
              reg.ICPConvergenceCriteria(max_iteration=iterations))
        transform=validate_transform(result.transformation)
    return result


def _quality(result):
    t=validate_transform(result.transformation)
    angle=float(np.degrees(np.arccos(np.clip((np.trace(t[:3,:3])-1)/2,-1,1))))
    return {"fitness":float(result.fitness),"inlier_rmse_m":float(result.inlier_rmse),
            "rotation_deg":angle,"translation_m":float(np.linalg.norm(t[:3,3]))}


def _uniform_volume(o3d,frames,k,voxel_m,max_resolution=384):
    """A UniformTSDFVolume covering every posed observation (plus the truncation band).
    The resolution is capped for memory; the voxel actually used may then be coarser."""
    lo,hi=np.full(3,np.inf),np.full(3,-np.inf)
    for depth,pose in frames:
        xyz=depth_to_xyz(depth,k).reshape(-1,3)
        xyz=xyz[np.isfinite(xyz).all(axis=1)]
        if len(xyz):
            pts=transform_points(xyz,pose)
            lo,hi=np.minimum(lo,pts.min(axis=0)),np.maximum(hi,pts.max(axis=0))
    if not np.isfinite(lo).all():
        raise RuntimeError("No valid depth to reconstruct")
    pad=voxel_m*6
    lo,hi=lo-pad,hi+pad
    length=float((hi-lo).max())
    resolution=int(min(max_resolution,max(16,np.ceil(length/voxel_m))))
    voxel=length/resolution
    return o3d.pipelines.integration.UniformTSDFVolume(length=length,resolution=resolution,
        sdf_trunc=max(voxel_m,voxel)*4,color_type=o3d.pipelines.integration.TSDFVolumeColorType.NoColor,
        origin=lo.reshape(3,1))


def reconstruct(session,out,mode,*,voxel_m=0.006,min_fitness=0.6,max_rmse_m=0.02,
                max_rotation_deg=25.,max_translation_m=0.30,close_loop=False):
    if mode not in ("known","auto","static"): raise ValueError("Invalid reconstruction mode")
    if not 0.001<=voxel_m<=0.05: raise ValueError("voxel_m must be 0.001..0.05")
    if not 0<min_fitness<=1 or max_rmse_m<=0: raise ValueError("Invalid registration thresholds")
    if close_loop and mode!="auto": raise ValueError("Loop closure applies only to auto mode")
    manifest,entries=load_session(session)
    if mode=="static" and manifest.get("subject_motion")!="stationary":
        raise ValueError("Static integration requires a recording explicitly marked stationary. Rotating people/objects cannot use identity poses.")
    if mode=="auto" and not manifest.get("foreground_isolated",False):
        raise ValueError("Auto mode requires ROI, 3D crop, or background isolation at capture time. Never register a rotating subject together with a stationary room.")
    if len(entries)>1200: raise ValueError("Session exceeds 1200-frame safety limit; split or subsample the recording")
    o3d=open3d_module(); out=new_directory(out)
    records=[]; poses=[]; clouds=[]; quality=[]; k0=None
    for i,(path,item) in enumerate(entries):
        depth,k,pose=load_frame(path)
        if k.distortion and not np.allclose(k.distortion,0):
            raise ValueError("Session depth must be rectified before TSDF integration")
        if k0 is None: k0=k
        if (k.width,k.height)!=(k0.width,k0.height) or not np.allclose(k.matrix,k0.matrix):
            raise ValueError("Mixed intrinsics in one session are unsupported")
        records.append((path,item))
        if mode=="known":
            if pose is None: raise ValueError(f"Known-pose mode requires T_world_from_camera in {path}")
            poses.append(pose)
        elif mode=="static": poses.append(np.eye(4))
        else:
            current=_cloud(o3d,depth,k,voxel_m)
            if i==0:
                poses.append(np.eye(4)); clouds.append(current); continue
            # Current camera-coordinate object cloud -> previous cloud.
            result=_icp(o3d,current,clouds[-1],voxel_m,np.eye(4))
            q=_quality(result); q["frame_index"]=i; quality.append(q)
            bad=(q["fitness"]<min_fitness or q["inlier_rmse_m"]>max_rmse_m or
                 q["rotation_deg"]>max_rotation_deg or q["translation_m"]>max_translation_m)
            if bad:
                write_json(out/"registration_failure.json",{"failed_frame":str(path),"quality":q,
                    "message":"Stopped before integration; no questionable frame was silently fused.",
                    "advice":"Slow rotation / denser captures / isolate subject / verify geometry. Thresholds do not prove accuracy."})
                raise RuntimeError(f"Registration rejected frame {i}: {q}. See registration_failure.json")
            poses.append(poses[-1]@result.transformation); clouds.append(current)
    if mode=="auto" and close_loop:
        if len(clouds)<10: raise ValueError("Loop closure requires at least 10 views and an actual return to the start pose")
        result=_icp(o3d,clouds[-1],clouds[0],voxel_m,poses[-1])
        q=_quality(result); q["edge"]="last_to_first"
        # Endpoint must physically overlap first view; a good local metric alone is not proof.
        if q["fitness"]<max(min_fitness,0.7) or q["inlier_rmse_m"]>max_rmse_m:
            write_json(out/"loop_failure.json",q)
            raise RuntimeError("Requested loop closure did not pass overlap/RMSE gates")
        reg=o3d.pipelines.registration; graph=reg.PoseGraph()
        for pose in poses: graph.nodes.append(reg.PoseGraphNode(pose))
        for i in range(1,len(poses)):
            rel=np.linalg.inv(poses[i-1])@poses[i]
            info=reg.get_information_matrix_from_point_clouds(clouds[i],clouds[i-1],voxel_m*3,rel)
            graph.edges.append(reg.PoseGraphEdge(i,i-1,rel,info,uncertain=False))
        info=reg.get_information_matrix_from_point_clouds(clouds[-1],clouds[0],voxel_m*3,result.transformation)
        graph.edges.append(reg.PoseGraphEdge(len(poses)-1,0,result.transformation,info,uncertain=True))
        reg.global_optimization(graph,reg.GlobalOptimizationLevenbergMarquardt(),
             reg.GlobalOptimizationConvergenceCriteria(),
             reg.GlobalOptimizationOption(max_correspondence_distance=voxel_m*3,
                                          edge_prune_threshold=0.25,reference_node=0))
        poses=[validate_transform(node.pose) for node in graph.nodes]; quality.append(q)
    intrinsic=o3d.camera.PinholeCameraIntrinsic(k0.width,k0.height,k0.fx,k0.fy,k0.cx,k0.cy)
    dummy=o3d.geometry.Image(np.zeros((k0.height,k0.width,3),dtype=np.uint8))
    frames=[(load_frame(path)[0],pose) for (path,_),pose in zip(records,poses)]

    def integrate(volume):
        for depth,pose in frames:
            rgbd=o3d.geometry.RGBDImage.create_from_color_and_depth(dummy,o3d.geometry.Image(depth),
                  depth_scale=1000.,depth_trunc=9.9,convert_rgb_to_intensity=False)
            # Open3D integrates WORLD -> CAMERA, inverse of the stored pose.
            volume.integrate(rgbd,intrinsic,np.linalg.inv(pose))
        return volume

    volume=integrate(o3d.pipelines.integration.ScalableTSDFVolume(voxel_length=voxel_m,
            sdf_trunc=voxel_m*4,color_type=o3d.pipelines.integration.TSDFVolumeColorType.NoColor,
            depth_sampling_stride=1))
    mesh=volume.extract_triangle_mesh()
    volume_kind="scalable"
    if len(mesh.triangles)==0:
        # Open3D 0.20 (pip, x86-64) returns no surface from ScalableTSDFVolume even for a flat
        # wall; UniformTSDFVolume works. Size a uniform volume to the posed observations.
        volume,volume_kind=_uniform_volume(o3d,frames,k0,voxel_m),"uniform"
        integrate(volume)
        mesh=volume.extract_triangle_mesh()
    mesh.remove_degenerate_triangles(); mesh.remove_duplicated_triangles()
    mesh.remove_unreferenced_vertices(); mesh.compute_vertex_normals()
    vertices=np.asarray(mesh.vertices); triangles=np.asarray(mesh.triangles)
    if len(vertices)<3 or len(triangles)<1: raise RuntimeError("No surface reconstructed; inspect depth masks, scale, poses and voxel size")
    fused=volume.extract_point_cloud(); points=np.asarray(fused.points)
    if len(points)<3: points=vertices
    export_geometry(out,points,vertices,triangles,prefix="fused")
    report=measurement_report(points,"multi_view_observed_surface; coverage_not_certified")
    report.update({"mode":mode,"frames_integrated":len(poses),"voxel_m":voxel_m,"tsdf_volume":volume_kind,
                   "closed_surface_check_performed":False,
                   "print_readiness":"Not guaranteed. Inspect holes, self-intersections, units and boundaries before printing.",
                   "color":"geometry_only; no RGB registration or texture atlas"})
    write_json(out/"measurements.json",report)
    write_json(out/"poses.json",{"convention":"T_world_from_camera; meters; world=first-view camera frame",
        "frames":[{"path":item["path"],"T_world_from_camera":p.tolist()} for (_,item),p in zip(records,poses)]})
    write_json(out/"quality.json",{"registration":quality,
         "warning":"Low ICP residual and a closed mesh do not establish metric accuracy or unseen-surface coverage."})
    return report


def fuse_known_clouds(session,out,voxel_m=0.005):
    """Dependency-light known-pose point fusion, with no inferred mesh."""
    manifest,entries=load_session(session); clouds=[]
    for path,item in entries:
        depth,k,pose=load_frame(path)
        if pose is None: raise ValueError("Every frame must contain a known relative pose")
        p=depth_to_xyz(depth,k).reshape(-1,3); p=p[np.isfinite(p).all(axis=1)]
        clouds.append(transform_points(p,pose))
    if not clouds: raise ValueError("No input frames")
    points=voxel_average(np.concatenate(clouds),voxel_m)
    out=new_directory(out); export_geometry(out,points,prefix="fused_known")
    report=measurement_report(points,"known_pose_multi_view_samples; coverage_not_certified")
    write_json(out/"measurements.json",report)
    return report
