"""Metric geometry. Camera coordinates: +X right, +Y down, +Z forward."""
from __future__ import annotations
from dataclasses import dataclass, asdict
import json
from pathlib import Path
import warnings
import numpy as np
from scipy import ndimage

@dataclass(frozen=True)
class Intrinsics:
    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float
    source: str = "user-supplied"
    distortion: tuple[float, ...] = ()
    depth_format: str = "FREENECT_DEPTH_MM"

    def __post_init__(self):
        if self.width <= 1 or self.height <= 1:
            raise ValueError("Image dimensions must exceed one pixel")
        values = np.array([self.fx, self.fy, self.cx, self.cy], float)
        if not np.isfinite(values).all() or min(self.fx, self.fy) <= 0:
            raise ValueError("Invalid camera intrinsics")
        if self.depth_format != "FREENECT_DEPTH_MM":
            raise ValueError("This application accepts IR-frame metric depth, not registered RGB depth")
        if len(self.distortion) not in (0, 4, 5, 8):
            raise ValueError("Distortion must contain 0, 4, 5 or 8 OpenCV coefficients")
        if not np.isfinite(self.distortion).all():
            raise ValueError("Nonfinite distortion coefficients")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        fields = dict(data)
        fields["distortion"] = tuple(fields.get("distortion", ()))
        return cls(**fields)

    @classmethod
    def load(cls, path):
        return cls.from_dict(json.loads(Path(path).read_text()))

    def save(self, path):
        Path(path).write_text(json.dumps(self.to_dict(), indent=2) + "\n")

    @property
    def matrix(self):
        return np.array([[self.fx, 0., self.cx], [0., self.fy, self.cy], [0., 0., 1.]])


def validate_depth(depth, k: Intrinsics):
    depth = np.asarray(depth)
    if depth.shape != (k.height, k.width) or depth.dtype != np.uint16:
        raise ValueError(f"Expected uint16 depth {(k.height, k.width)}, received {depth.dtype} {depth.shape}")
    return depth


def median_depth(frames, min_fraction=0.7, max_std_mm=None):
    if not frames or not 0 < min_fraction <= 1:
        raise ValueError("Need frames and min_fraction in (0,1]")
    a = np.stack(frames).astype(np.float32)
    valid = (a > 0) & (a < 10000)
    a[~valid] = np.nan
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        med = np.nanmedian(a, axis=0)
        std = np.nanstd(a, axis=0)
    keep = valid.sum(axis=0) >= int(np.ceil(len(frames) * min_fraction))
    if max_std_mm is not None:
        if max_std_mm <= 0:
            raise ValueError("max_std_mm must be positive")
        keep &= std <= max_std_mm
    med[~keep | ~np.isfinite(med)] = 0
    return np.rint(med).astype(np.uint16)


def rectify_depth(depth, k: Intrinsics):
    """Nearest-neighbor remap: never interpolate across missing depth."""
    validate_depth(depth, k)
    if not k.distortion or np.allclose(k.distortion, 0):
        return depth.copy()
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("Install the gui extra / opencv-python to rectify calibrated distortion") from exc
    mx, my = cv2.initUndistortRectifyMap(k.matrix, np.asarray(k.distortion), None,
                                       k.matrix, (k.width, k.height), cv2.CV_32FC1)
    return cv2.remap(depth, mx, my, interpolation=cv2.INTER_NEAREST,
                     borderMode=cv2.BORDER_CONSTANT, borderValue=0)


def depth_to_xyz(depth, k: Intrinsics):
    """Input uint16 millimeters; output HxWx3 meters. Invalid points are NaN."""
    validate_depth(depth, k)
    v, u = np.indices(depth.shape, dtype=np.float64)
    z = depth.astype(np.float64) / 1000.
    points = np.stack(((u-k.cx)*z/k.fx, (v-k.cy)*z/k.fy, z), axis=-1)
    points[(depth == 0) | (depth >= 10000)] = np.nan
    return points


def segment_depth(depth, k: Intrinsics, *, z_min=0.7, z_max=3.5, roi=None,
                  box=None, background=None, background_margin_mm=25.,
                  largest_component=False, min_component_pixels=0):
    """ROI and foreground subtraction; not semantic object recognition."""
    validate_depth(depth, k)
    if not 0 < z_min < z_max < 10:
        raise ValueError("Require 0 < z_min < z_max < 10 meters")
    mask = (depth >= z_min*1000) & (depth <= z_max*1000)
    if roi is not None:
        x0, y0, x1, y1 = map(int, roi)
        if not (0 <= x0 < x1 <= k.width and 0 <= y0 < y1 <= k.height):
            raise ValueError("ROI must be x0 y0 x1 y1 inside the image; end coordinates are exclusive")
        rect = np.zeros_like(mask)
        rect[y0:y1, x0:x1] = True
        mask &= rect
    if background is not None:
        validate_depth(background, k)
        if background_margin_mm <= 0:
            raise ValueError("Background margin must be positive")
        # Unknown background stays unknown: do not silently label it foreground.
        mask &= (background > 0) & (background < 10000)
        mask &= background.astype(np.int32) - depth.astype(np.int32) > background_margin_mm
    if box is not None:
        if len(box) != 6:
            raise ValueError("Box order: xmin xmax ymin ymax zmin zmax, in meters")
        lo = np.array(box[::2], float); hi = np.array(box[1::2], float)
        if not np.isfinite(box).all() or not (hi > lo).all():
            raise ValueError("Invalid 3D crop box")
        xyz = depth_to_xyz(depth, k)
        mask &= ((xyz >= lo) & (xyz <= hi)).all(axis=-1)
    if largest_component or min_component_pixels:
        labels, n = ndimage.label(mask, structure=np.ones((3, 3)))
        if n:
            counts = np.bincount(labels.ravel()); counts[0] = 0
            if largest_component:
                mask &= labels == int(counts.argmax())
            else:
                mask &= counts[labels] >= int(min_component_pixels)
    result = depth.copy(); result[~mask] = 0
    return result


def grid_mesh(depth, k: Intrinsics, stride=2, max_edge_m=0.04):
    """Observed surface only. Never cap boundaries or bridge missing samples."""
    if stride < 1 or max_edge_m <= 0:
        raise ValueError("Positive stride and edge limit required")
    xyz = depth_to_xyz(depth, k)[::stride, ::stride]
    h, w = xyz.shape[:2]
    vertices = xyz.reshape(-1, 3)
    ids = np.arange(h*w).reshape(h, w)
    a, b, c, d = ids[:-1,:-1], ids[:-1,1:], ids[1:,:-1], ids[1:,1:]
    # Normals face the viewing camera (approximately negative Z).
    tri = np.concatenate((np.stack((a,c,b), -1).reshape(-1,3),
                          np.stack((b,c,d), -1).reshape(-1,3)))
    if not len(tri):
        return np.empty((0,3)), np.empty((0,3), dtype=np.int64)
    p = vertices[tri]
    finite = np.isfinite(p).all(axis=(1,2))
    edge = np.maximum.reduce([np.linalg.norm(p[:,0]-p[:,1],axis=1),
                              np.linalg.norm(p[:,1]-p[:,2],axis=1),
                              np.linalg.norm(p[:,2]-p[:,0],axis=1)])
    area2 = np.linalg.norm(np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0]),axis=1)
    tri = tri[finite & (edge <= max_edge_m) & (area2 > 1e-12)]
    if not len(tri):
        return np.empty((0,3)), np.empty((0,3), dtype=np.int64)
    used, inverse = np.unique(tri, return_inverse=True)
    return vertices[used], inverse.reshape(-1,3)


def transform_points(points, transform):
    t = validate_transform(transform)
    return np.asarray(points) @ t[:3,:3].T + t[:3,3]


def validate_transform(transform):
    t = np.asarray(transform, dtype=float)
    if t.shape != (4,4) or not np.isfinite(t).all():
        raise ValueError("Expected finite 4x4 rigid transform")
    if not np.allclose(t[3], [0,0,0,1], atol=1e-7):
        raise ValueError("Invalid homogeneous transform")
    r = t[:3,:3]
    if not np.allclose(r.T@r, np.eye(3), atol=1e-5) or not np.isclose(np.linalg.det(r), 1, atol=1e-5):
        raise ValueError("Transform must be rigid with determinant +1 (no scale/reflection)")
    return t


def rotation_axis_angle(axis, angle_radians):
    a = np.asarray(axis, float)
    if a.shape != (3,) or not np.isfinite(a).all() or np.linalg.norm(a)<1e-9:
        raise ValueError("Need a finite nonzero 3D axis")
    a /= np.linalg.norm(a)
    x,y,z = a; k = np.array([[0,-z,y],[z,0,-x],[-y,x,0]])
    return np.eye(3) + np.sin(angle_radians)*k + (1-np.cos(angle_radians))*(k@k)


def turntable_pose(angle_deg, center_m, axis):
    """Return T_world_from_camera for a rotating object and a physically fixed camera.

    World is the camera-coordinate frame at object angle zero. G maps the
    angle-zero object into its current camera pose; this returns inverse(G).
    """
    center = np.asarray(center_m, float)
    if center.shape != (3,) or not np.isfinite(center).all() or not np.isfinite(angle_deg):
        raise ValueError("Invalid angle or turntable center")
    r = rotation_axis_angle(axis, np.deg2rad(angle_deg))
    g = np.eye(4); g[:3,:3] = r; g[:3,3] = center-r@center
    return np.linalg.inv(g)


def fit_axis_circle(points, preferred_axis=(0.,-1.,0.)):
    """Fit an off-axis target's circular orbit. Input measurements are meters."""
    p = np.asarray(points, float)
    if p.ndim!=2 or p.shape[1]!=3 or len(p)<6 or not np.isfinite(p).all():
        raise ValueError("At least six finite XYZ orbit samples are required")
    mean = p.mean(axis=0); _, s, vh = np.linalg.svd(p-mean, full_matrices=False)
    if s[1] < 1e-4 or s[1]/s[0] < 0.15:
        raise ValueError("Orbit samples are collinear / cover too small an arc")
    xy = (p-mean) @ vh[:2].T
    a = np.column_stack((2*xy, np.ones(len(xy))))
    sol, *_ = np.linalg.lstsq(a, np.sum(xy*xy,axis=1), rcond=None)
    radius2 = sol[2] + sol[0]**2 + sol[1]**2
    if radius2 <= 0:
        raise ValueError("Invalid circle fit")
    center = mean + sol[:2] @ vh[:2]
    axis = vh[2]
    pref = np.asarray(preferred_axis,float)
    if pref.shape!=(3,) or np.linalg.norm(pref)<1e-9:
        raise ValueError("Preferred axis must be nonzero XYZ")
    if axis@pref < 0: axis = -axis
    v = p-center
    radial = np.linalg.norm(v-(v@axis)[:,None]*axis,axis=1)
    residual = np.sqrt((radial-np.sqrt(radius2))**2 + (v@axis)**2)
    angles = np.mod(np.arctan2(xy[:,1]-sol[1],xy[:,0]-sol[0]),2*np.pi)
    gaps = np.diff(np.r_[np.sort(angles), np.sort(angles)[0]+2*np.pi])
    coverage = np.rad2deg(2*np.pi-gaps.max())
    return {"center_m":center.tolist(), "axis":axis.tolist(), "radius_m":float(np.sqrt(radius2)),
            "rms_residual_mm":float(np.sqrt(np.mean(residual**2))*1000),
            "observed_arc_deg":float(coverage), "sample_count":len(p),
            "warning":"Fitted from depth measurements; independently verify axis and rotation sign."}


def voxel_average(points, voxel_m):
    p = np.asarray(points,float)
    p = p[np.isfinite(p).all(axis=1)]
    if voxel_m <= 0: raise ValueError("voxel_m must be positive")
    if not len(p): return p
    key = np.floor(p/voxel_m).astype(np.int64)
    _, inverse, count = np.unique(key,axis=0,return_inverse=True,return_counts=True)
    sums = np.zeros((len(count),3)); np.add.at(sums,inverse,p)
    return sums/count[:,None]


def measurement_report(points, scope="observed_surfaces_only"):
    p = np.asarray(points,float)
    if p.ndim!=2 or p.shape[1]!=3: raise ValueError("Expected Nx3 points")
    p = p[np.isfinite(p).all(axis=1)]
    if len(p)<3: raise ValueError("Too few valid points for measurement")
    lo,hi = p.min(axis=0),p.max(axis=0)
    qlo,qhi = np.percentile(p,[1,99],axis=0)
    mean = p.mean(axis=0)
    _,_,vh = np.linalg.svd(p-mean, full_matrices=False)
    axes = vh.T
    if np.linalg.det(axes)<0: axes[:,2] *= -1
    local = (p-mean)@axes
    return {"units":"meters", "point_count":int(len(p)), "scope":scope,
            "coordinate_frame":"X right, Y down, Z forward; reference camera at scan start",
            "aabb_min_m":lo.tolist(), "aabb_max_m":hi.tolist(), "aabb_extent_mm":((hi-lo)*1000).tolist(),
            "percentile_1_99_extent_mm":((qhi-qlo)*1000).tolist(),
            "pca_obb_extent_mm":(np.ptp(local,axis=0)*1000).tolist(),
            "pca_axes_columns":axes.tolist(),
            "warnings":["These are sampled-surface extents, not certified product dimensions.",
                        "Percentile extents deliberately discard outer samples and can understate size.",
                        "PCA axes are data-dependent; they are not necessarily engineering L/W/H.",
                        "No complete-object volume is inferred from an open or incomplete scan."]}
