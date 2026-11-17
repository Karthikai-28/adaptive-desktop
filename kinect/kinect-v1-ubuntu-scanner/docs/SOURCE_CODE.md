# Complete Ubuntu scanner source code

**Version:** 0.1.0  
**Hardware:** original Kinect v1  
**Date:** November 17, 2026

Every implementation, installer, configuration, and automated-test file is included below without abbreviation. The ZIP contains these files in their executable directory structure. Read the installation guide and validation report before connecting hardware. This code does not include an external library implementation, a proprietary SDK, firmware, or game assets.

## File index

- [pyproject.toml](#source-file-1)
- [requirements-ubuntu.txt](#source-file-2)
- [.gitignore](#source-file-3)
- [LICENSE](#source-file-4)
- [config/99-kinectscan.rules](#source-file-5)
- [scripts/install_ubuntu.sh](#source-file-6)
- [scripts/smoke_test.sh](#source-file-7)
- [src/kinectscan/__init__.py](#source-file-8)
- [src/kinectscan/__main__.py](#source-file-9)
- [src/kinectscan/capture.py](#source-file-10)
- [src/kinectscan/cli.py](#source-file-11)
- [src/kinectscan/geometry.py](#source-file-12)
- [src/kinectscan/reconstruct.py](#source-file-13)
- [src/kinectscan/storage.py](#source-file-14)
- [src/kinectscan/synthetic.py](#source-file-15)
- [tests/test_capture_binding.py](#source-file-16)
- [tests/test_geometry.py](#source-file-17)
- [tests/test_open3d_optional.py](#source-file-18)
- [tests/test_storage_cli.py](#source-file-19)

---

<a id="source-file-1"></a>
## `pyproject.toml`

`````toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "kinect-v1-ubuntu-scanner"
version = "0.1.0"
description = "Fixed Kinect v1 capture, observed-surface measurement, and multi-view reconstruction for Ubuntu"
readme = "README.md"
requires-python = ">=3.10"
license = {text = "MIT"}
dependencies = ["numpy>=1.26,<3", "scipy>=1.11,<2"]

[project.optional-dependencies]
reconstruction = ["open3d==0.19.0"]
gui = ["opencv-python==4.10.0.84"]
test = ["pytest>=8,<9"]

[project.scripts]
kinectscan = "kinectscan.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
`````

---

<a id="source-file-2"></a>
## `requirements-ubuntu.txt`

`````text
# Conservative Python 3.10-3.12 reference environment, not a claim of latest versions.
numpy==1.26.4
scipy==1.13.1
open3d==0.19.0
opencv-python==4.10.0.84
pytest==8.3.5
`````

---

<a id="source-file-3"></a>
## `.gitignore`

`````text
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
*.egg-info/
build/
dist/
runs/
!examples/
`````

---

<a id="source-file-4"></a>
## `LICENSE`

`````text
MIT License

Copyright (c) 2026 Contributors to this generated reference implementation

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
`````

---

<a id="source-file-5"></a>
## `config/99-kinectscan.rules`

`````text
# Access only these Kinect v1 USB functions; do not make all USB devices world writable.
# IDs cross-checked against upstream OpenKinect/platform/linux/udev/51-kinect.rules.
SUBSYSTEM=="usb", ATTR{idVendor}=="045e", ATTR{idProduct}=="02b0", MODE="0660", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="045e", ATTR{idProduct}=="02ad", MODE="0660", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="045e", ATTR{idProduct}=="02ae", MODE="0660", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="045e", ATTR{idProduct}=="02c2", MODE="0660", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="045e", ATTR{idProduct}=="02be", MODE="0660", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="045e", ATTR{idProduct}=="02bf", MODE="0660", GROUP="plugdev", TAG+="uaccess"
`````

---

<a id="source-file-6"></a>
## `scripts/install_ubuntu.sh`

`````bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ "$(id -u)" -eq 0 ]; then
  echo "Run this script as your normal desktop user, not with sudo. It asks sudo only for apt/udev changes." >&2
  exit 1
fi
. /etc/os-release
if [ "${ID:-}" != "ubuntu" ]; then
  echo "Reference installer targets Ubuntu 22.04/24.04. Review README for manual installation on another system." >&2
  exit 1
fi
case "${VERSION_ID:-}" in
  22.04) GLIB_PACKAGE="libglib2.0-0" ;;
  24.04) GLIB_PACKAGE="libglib2.0-0t64" ;;
  *) echo "Reference installer is limited to Ubuntu 22.04/24.04. Review manual setup for other releases." >&2; exit 1 ;;
esac
if [ "$(uname -m)" != "x86_64" ]; then
  echo "Reference full-stack wheels target x86-64. Review dependencies manually on other architectures." >&2
  exit 1
fi
PYTHON_BIN="${PYTHON_BIN:-python3}"
"$PYTHON_BIN" - <<'PY'
import sys
if not (3,10) <= sys.version_info[:2] <= (3,12):
    raise SystemExit('Reference full stack requires Python 3.10-3.12. Set PYTHON_BIN to an installed compatible interpreter; do not replace system Python.')
PY
sudo apt-get update
sudo apt-get install -y software-properties-common
sudo add-apt-repository -y universe
sudo apt-get update
sudo apt-get install -y python3-venv python3-dev libfreenect-dev libfreenect-bin libusb-1.0-0 usbutils libgl1 "$GLIB_PACKAGE"
if ! getent group plugdev >/dev/null; then sudo groupadd --system plugdev; fi
sudo usermod -aG plugdev "$(id -un)"
sudo install -m 0644 config/99-kinectscan.rules /etc/udev/rules.d/99-kinectscan.rules
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=usb --attr-match=idVendor=045e
"$PYTHON_BIN" -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install --only-binary=:all: -r requirements-ubuntu.txt
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python -m pip freeze > installed-versions.txt
echo "Installation complete. Log out/in for plugdev membership, then unplug/replug Kinect."
echo "Connect the Kinect v1 external power adapter. Do not run scanner as root."
echo "Next: source .venv/bin/activate && kinectscan doctor && kinectscan probe --out intrinsics.json"
`````

---

<a id="source-file-7"></a>
## `scripts/smoke_test.sh`

`````bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON_BIN="${PYTHON_BIN:-python3}"
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
OUT="${1:-runs/synthetic-smoke}"
"$PYTHON_BIN" -m pytest -q
"$PYTHON_BIN" -m kinectscan demo --out "$OUT/session" --step-deg 10
"$PYTHON_BIN" -m kinectscan snapshot --input "$OUT/session/frames/000000.npz" --out "$OUT/snapshot" --z-min 0.7 --z-max 2.0 --stride 1
"$PYTHON_BIN" -m kinectscan fuse-known --session "$OUT/session" --out "$OUT/fused-cloud"
echo "Synthetic smoke test complete. This does not validate USB hardware or Open3D TSDF."
`````

---

<a id="source-file-8"></a>
## `src/kinectscan/__init__.py`

`````python
"""Geometry-first Kinect v1 scanner. No hardware is opened at import time."""
__version__ = "0.1.0"
`````

---

<a id="source-file-9"></a>
## `src/kinectscan/__main__.py`

`````python
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
`````

---

<a id="source-file-10"></a>
## `src/kinectscan/capture.py`

`````python
"""libfreenect synchronous C API behind a killable worker process.

Using ctypes avoids relying on abandoned Python 2-era freenect wheels. No
hand-copied device-struct ABI and no guessed focal length are used.
"""
from __future__ import annotations
import ctypes as ct
import ctypes.util
import multiprocessing as mp
import time
import numpy as np
from .geometry import Intrinsics, median_depth

WIDTH, HEIGHT = 640, 480
FREENECT_DEPTH_MM = 5


def library_path():
    return ctypes.util.find_library("freenect_sync")


class _Native:
    def __init__(self, index: int):
        name = library_path()
        if not name:
            raise RuntimeError("libfreenect_sync not found. Install libfreenect-dev and libfreenect-bin, then run ldconfig if built from source.")
        self.lib = ct.CDLL(name)
        self.index = int(index)
        self.lib.freenect_sync_get_depth.argtypes = [ct.POINTER(ct.c_void_p),ct.POINTER(ct.c_uint32),ct.c_int,ct.c_int]
        self.lib.freenect_sync_get_depth.restype = ct.c_int
        self.lib.freenect_sync_stop.argtypes = []
        self.lib.freenect_sync_stop.restype = None

    def read(self):
        ptr = ct.c_void_p(); stamp = ct.c_uint32()
        rc = self.lib.freenect_sync_get_depth(ct.byref(ptr),ct.byref(stamp),self.index,FREENECT_DEPTH_MM)
        if rc != 0 or not ptr.value:
            raise RuntimeError(f"Kinect depth read failed ({rc}). Check external power, USB, udev permissions and other camera applications.")
        # Own the memory before requesting another frame; the native ring buffer is reused.
        data = np.ctypeslib.as_array(ct.cast(ptr,ct.POINTER(ct.c_uint16)),shape=(HEIGHT*WIDTH,)).reshape(HEIGHT,WIDTH).copy()
        data[(data == 0) | (data >= 10000)] = 0
        return data, int(stamp.value)

    def intrinsics(self):
        if not hasattr(self.lib,"freenect_sync_camera_to_world"):
            raise RuntimeError("This libfreenect lacks freenect_sync_camera_to_world. Supply independently calibrated --intrinsics JSON, or build a newer official libfreenect. No guessed intrinsics will be substituted.")
        f = self.lib.freenect_sync_camera_to_world
        f.argtypes = [ct.c_int,ct.c_int,ct.c_int,ct.POINTER(ct.c_double),ct.POINTER(ct.c_double),ct.c_int]
        f.restype = ct.c_int
        def world(u,v):
            x,y = ct.c_double(),ct.c_double()
            if f(u,v,1000,ct.byref(x),ct.byref(y),self.index) != 0:
                raise RuntimeError("Factory projection query failed")
            return x.value,y.value
        x0,y0 = world(320,240); x1,y1 = world(321,241)
        if abs(x1-x0)<1e-9 or abs(y1-y0)<1e-9:
            raise RuntimeError("Invalid factory ray mapping")
        fx,fy = 1000/(x1-x0),1000/(y1-y0)
        cx,cy = 320-x0*fx/1000,240-y0*fy/1000
        return Intrinsics(WIDTH,HEIGHT,fx,fy,cx,cy,
            source="libfreenect device-specific factory camera_to_world model; not independent metrology calibration")

    def close(self):
        self.lib.freenect_sync_stop()


def _worker(conn,index,override):
    native = None
    try:
        native = _Native(index)
        native.read()  # Initializes the device / factory registration.
        k = Intrinsics.from_dict(override) if override else native.intrinsics()
        if (k.width,k.height)!=(WIDTH,HEIGHT):
            raise ValueError("Kinect medium mode requires 640x480 IR intrinsics")
        conn.send(("ready",k.to_dict()))
        while True:
            cmd = conn.recv()
            if cmd == "stop": break
            if cmd != "read": raise ValueError("Unknown acquisition command")
            depth,stamp = native.read()
            conn.send(("frame",depth,stamp,time.monotonic()))
    except (EOFError,BrokenPipeError):
        pass
    except BaseException as exc:
        try: conn.send(("error",f"{type(exc).__name__}: {exc}"))
        except (BrokenPipeError,EOFError,OSError): pass
    finally:
        if native is not None:
            native.close()
        conn.close()


class KinectCapture:
    """One process owns one sensor. Reads time out instead of hanging the CLI."""
    def __init__(self,index=0,timeout=10.,intrinsics=None):
        if index < 0 or timeout <= 0: raise ValueError("Invalid device index or timeout")
        self.index=index; self.timeout=timeout; self.override=intrinsics
        self.process=None; self.conn=None; self.k=None; self.last_timestamp=None

    def __enter__(self):
        ctx=mp.get_context("spawn"); parent,child=ctx.Pipe()
        self.conn=parent
        self.process=ctx.Process(target=_worker,args=(child,self.index,
            self.override.to_dict() if self.override else None),daemon=True)
        self.process.start(); child.close()
        try:
            msg=self._receive()
            if msg[0]!="ready": raise RuntimeError(f"Unexpected worker reply: {msg[0]}")
            self.k=Intrinsics.from_dict(msg[1])
            return self
        except BaseException:
            self.close(); raise

    def _receive(self):
        if not self.conn.poll(self.timeout):
            raise TimeoutError("Kinect worker timed out. Check power, permissions and USB. The worker will be terminated on exit.")
        try: msg=self.conn.recv()
        except EOFError as exc: raise RuntimeError("Kinect worker exited unexpectedly") from exc
        if msg[0]=="error": raise RuntimeError(msg[1])
        return msg

    def read(self):
        for _ in range(5):
            self.conn.send("read"); msg=self._receive()
            if msg[0]!="frame": raise RuntimeError("Unexpected capture reply")
            depth,stamp,host=msg[1:]
            if stamp!=self.last_timestamp:
                self.last_timestamp=stamp
                return depth,stamp,host
        raise RuntimeError("Repeated device timestamp: no fresh depth frames")

    def median(self,samples=15,max_std_mm=None):
        if not 1 <= samples <= 120: raise ValueError("samples must be 1..120")
        frames=[]
        for _ in range(samples):
            depth,stamp,host=self.read(); frames.append(depth)
        return median_depth(frames,max_std_mm=max_std_mm),stamp,host

    def close(self):
        if self.conn is not None:
            try: self.conn.send("stop")
            except (BrokenPipeError,EOFError,OSError): pass
        if self.process is not None:
            self.process.join(timeout=1.)
            if self.process.is_alive():
                self.process.terminate(); self.process.join(timeout=2.)
            if self.process.is_alive():
                self.process.kill(); self.process.join(timeout=1.)
        if self.conn is not None: self.conn.close()
        self.process=None; self.conn=None

    def __exit__(self,*exc):
        self.close()
`````

---

<a id="source-file-11"></a>
## `src/kinectscan/cli.py`

`````python
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
`````

---

<a id="source-file-12"></a>
## `src/kinectscan/geometry.py`

`````python
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
`````

---

<a id="source-file-13"></a>
## `src/kinectscan/reconstruct.py`

`````python
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
    volume=o3d.pipelines.integration.ScalableTSDFVolume(voxel_length=voxel_m,
            sdf_trunc=voxel_m*4,color_type=o3d.pipelines.integration.TSDFVolumeColorType.NoColor,
            depth_sampling_stride=1)
    intrinsic=o3d.camera.PinholeCameraIntrinsic(k0.width,k0.height,k0.fx,k0.fy,k0.cx,k0.cy)
    dummy=o3d.geometry.Image(np.zeros((k0.height,k0.width,3),dtype=np.uint8))
    for (path,item),pose in zip(records,poses):
        depth,_,_=load_frame(path)
        rgbd=o3d.geometry.RGBDImage.create_from_color_and_depth(dummy,o3d.geometry.Image(depth),
              depth_scale=1000.,depth_trunc=9.9,convert_rgb_to_intensity=False)
        # Open3D integrates WORLD -> CAMERA, inverse of the stored pose.
        volume.integrate(rgbd,intrinsic,np.linalg.inv(pose))
    mesh=volume.extract_triangle_mesh()
    mesh.remove_degenerate_triangles(); mesh.remove_duplicated_triangles()
    mesh.remove_unreferenced_vertices(); mesh.compute_vertex_normals()
    vertices=np.asarray(mesh.vertices); triangles=np.asarray(mesh.triangles)
    if len(vertices)<3 or len(triangles)<1: raise RuntimeError("No surface reconstructed; inspect depth masks, scale, poses and voxel size")
    fused=volume.extract_point_cloud(); points=np.asarray(fused.points)
    if len(points)<3: points=vertices
    export_geometry(out,points,vertices,triangles,prefix="fused")
    report=measurement_report(points,"multi_view_observed_surface; coverage_not_certified")
    report.update({"mode":mode,"frames_integrated":len(poses),"voxel_m":voxel_m,
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
`````

---

<a id="source-file-14"></a>
## `src/kinectscan/storage.py`

`````python
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
`````

---

<a id="source-file-15"></a>
## `src/kinectscan/synthetic.py`

`````python
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
`````

---

<a id="source-file-16"></a>
## `tests/test_capture_binding.py`

`````python
import ctypes as ct
import numpy as np
from kinectscan import capture

class Fn:
    def __init__(self,f): self.f=f
    def __call__(self,*args): return self.f(*args)

class FakeLib:
    def __init__(self):
        self.data=np.full((480,640),1234,np.uint16)
        self.data[0,0]=10000
        self.freenect_sync_get_depth=Fn(self.read)
        self.freenect_sync_stop=Fn(lambda: None)
        self.freenect_sync_camera_to_world=Fn(self.project)
    def read(self,ptr,stamp,index,fmt):
        assert fmt==5
        ct.cast(ptr,ct.POINTER(ct.c_void_p))[0]=self.data.ctypes.data
        ct.cast(stamp,ct.POINTER(ct.c_uint32))[0]=77
        return 0
    def project(self,u,v,z,x,y,index):
        ct.cast(x,ct.POINTER(ct.c_double))[0]=(u-320)*z/580.
        ct.cast(y,ct.POINTER(ct.c_double))[0]=(v-240)*z/581.
        return 0

def test_native_binding_copy_and_factory_intrinsics(monkeypatch):
    fake=FakeLib()
    monkeypatch.setattr(capture,'library_path',lambda:'fake')
    monkeypatch.setattr(capture.ct,'CDLL',lambda name:fake)
    device=capture._Native(0)
    depth,stamp=device.read()
    assert stamp==77 and depth[0,0]==0
    fake.data[1,1]=900
    assert depth[1,1]==1234
    k=device.intrinsics()
    assert np.allclose([k.fx,k.fy,k.cx,k.cy],[580,581,320,240])

def test_missing_library(monkeypatch):
    monkeypatch.setattr(capture,'library_path',lambda:None)
    import pytest
    with pytest.raises(RuntimeError,match='not found'): capture._Native(0)
`````

---

<a id="source-file-17"></a>
## `tests/test_geometry.py`

`````python
import numpy as np
import pytest
from kinectscan.geometry import (Intrinsics, depth_to_xyz, median_depth, segment_depth,
    grid_mesh, transform_points, turntable_pose, rotation_axis_angle,
    fit_axis_circle, validate_transform, voxel_average, measurement_report)

@pytest.fixture
def k():
    return Intrinsics(8,6,100,100,3.5,2.5,source="test")

def test_projection_units(k):
    d=np.full((6,8),1000,np.uint16)
    p=depth_to_xyz(d,k)
    assert np.allclose(p[2,3],[-.005,-.005,1.])
    assert np.isclose(np.linalg.norm(p[2,3]-p[2,4]),.01)

@pytest.mark.parametrize("value",[0,10000,65535])
def test_invalid_depth_is_not_origin(k,value):
    d=np.full((6,8),value,np.uint16)
    assert np.isnan(depth_to_xyz(d,k)).all()

@pytest.mark.parametrize("fx",[0,-1,float('nan'),float('inf')])
def test_intrinsics_validation(fx):
    with pytest.raises(ValueError): Intrinsics(640,480,fx,580,320,240)

def test_depth_shape_type(k):
    with pytest.raises(ValueError): depth_to_xyz(np.ones((6,8)),k)
    with pytest.raises(ValueError): depth_to_xyz(np.ones((8,6),np.uint16),k)

def test_median_missing_values():
    frames=[np.array([[1000,0],[1000,1000]],np.uint16),
            np.array([[1002,0],[0,1300]],np.uint16),
            np.array([[998,1000],[1000,700]],np.uint16)]
    out=median_depth(frames,max_std_mm=10)
    assert out.tolist()==[[1000,0],[0,0]]

def test_segmentation_signed_background(k):
    d=np.full((6,8),1000,np.uint16); bg=np.full_like(d,900)
    assert not segment_depth(d,k,background=bg).any()
    bg[:]=1100; bg[0,0]=0
    out=segment_depth(d,k,background=bg)
    assert out[0,0]==0 and np.count_nonzero(out)==47

def test_roi_and_box(k):
    d=np.full((6,8),1000,np.uint16)
    out=segment_depth(d,k,roi=[2,1,6,5],box=[-.02,.02,-.02,.02,.8,1.2])
    assert np.count_nonzero(out)==16

def test_bad_roi_and_range(k):
    d=np.full((6,8),1000,np.uint16)
    with pytest.raises(ValueError): segment_depth(d,k,roi=[-1,0,4,5])
    with pytest.raises(ValueError): segment_depth(d,k,z_min=2,z_max=1)

def test_largest_component(k):
    d=np.zeros((6,8),np.uint16); d[:2,:2]=1000; d[4,6]=1000
    out=segment_depth(d,k,largest_component=True)
    assert np.count_nonzero(out)==4

def test_grid_mesh_plane(k):
    d=np.full((6,8),1000,np.uint16)
    v,t=grid_mesh(d,k,stride=1,max_edge_m=.02)
    assert len(v)==48 and len(t)==70
    normals=np.cross(v[t[:,1]]-v[t[:,0]],v[t[:,2]]-v[t[:,0]])
    assert (normals[:,2]<0).all()

def test_grid_mesh_does_not_bridge_step(k):
    d=np.full((6,8),1000,np.uint16); d[:,4:]=2000
    v,t=grid_mesh(d,k,stride=1,max_edge_m=.04)
    assert np.all(np.ptp(v[t][:,:,2],axis=1)==0)

def test_grid_mesh_does_not_fill_invalid(k):
    d=np.full((6,8),1000,np.uint16); d[:,3:5]=0
    v,t=grid_mesh(d,k,stride=1,max_edge_m=1.)
    assert len(t)>0
    assert (np.ptp(v[t][:,:,0],axis=1)<.02).all()

def test_turntable_inverse_transform():
    c=np.array([.02,.1,1.3]); axis=[0,-1,0]; angle=43
    r=rotation_axis_angle(axis,np.deg2rad(angle))
    original=np.array([[.12,.1,1.25],[-.2,0,1.4]])
    rotated=(original-c)@r.T+c
    assert np.allclose(transform_points(rotated,turntable_pose(angle,c,axis)),original)
    assert np.allclose(turntable_pose(360,c,axis),np.eye(4))

def test_transform_rejects_scale_and_reflection():
    t=np.eye(4); t[0,0]=2
    with pytest.raises(ValueError): validate_transform(t)
    t[0,0]=-1
    with pytest.raises(ValueError): validate_transform(t)

def test_axis_fit():
    theta=np.linspace(0,2*np.pi,12,endpoint=False)
    center=np.array([.1,.2,1.4])
    p=center+np.column_stack((.1*np.cos(theta),np.zeros(12),.1*np.sin(theta)))
    result=fit_axis_circle(p)
    assert np.allclose(result['center_m'],center)
    assert np.allclose(result['axis'],[0,-1,0])
    assert result['rms_residual_mm']<1e-6
    assert result['observed_arc_deg']>=329.9

def test_axis_fit_rejects_line():
    with pytest.raises(ValueError): fit_axis_circle(np.column_stack((np.arange(6),np.zeros(6),np.ones(6))))

def test_voxel_average():
    p=np.array([[.001,0,1],[.003,0,1],[-.001,0,1]])
    fused=voxel_average(p,.01)
    assert len(fused)==2
    assert np.allclose(np.sort(fused[:,0]),[-.001,.002])

def test_measurement_report_is_observed_only():
    p=np.array([[0,0,0],[.4,.3,.2],[.4,0,0],[0,.3,.2]])
    r=measurement_report(p)
    assert np.allclose(r['aabb_extent_mm'],[400,300,200])
    assert r['scope']=='observed_surfaces_only'
    assert 'volume' not in r
`````

---

<a id="source-file-18"></a>
## `tests/test_open3d_optional.py`

`````python
"""Executed only when Open3D is installed; absence must be reported, not hidden."""
import pytest
from kinectscan.synthetic import create_demo
from kinectscan.reconstruct import reconstruct


def test_open3d_known_pose_tsdf(tmp_path):
    pytest.importorskip('open3d',reason='Open3D unavailable: TSDF hardware-independent test not executed')
    create_demo(tmp_path/'session',step_deg=20)
    result=reconstruct(tmp_path/'session',tmp_path/'mesh','known',voxel_m=.008)
    assert result['frames_integrated']==19
    assert (tmp_path/'mesh/fused_mesh.stl').is_file()
    assert 350 < result['aabb_extent_mm'][0] < 450
`````

---

<a id="source-file-19"></a>
## `tests/test_storage_cli.py`

`````python
import json
from pathlib import Path
import struct
import numpy as np
import pytest
from kinectscan.geometry import Intrinsics
from kinectscan.storage import (save_frame,load_frame,write_mesh,write_cloud,new_directory,load_session,write_json)
from kinectscan.synthetic import create_demo
from kinectscan.reconstruct import fuse_known_clouds,reconstruct
from kinectscan.cli import main


def test_frame_roundtrip(tmp_path):
    k=Intrinsics(8,6,100,100,3.5,2.5)
    d=np.full((6,8),1200,np.uint16); p=tmp_path/'frame.npz'
    save_frame(p,d,k,raw=d,timestamp=123,pose=np.eye(4))
    dd,kk,pose=load_frame(p)
    assert np.array_equal(d,dd) and k==kk and np.allclose(pose,np.eye(4))

def test_stl_scale_and_binary_layout(tmp_path):
    v=np.array([[0.,0,0],[.1,0,0],[0,.2,0]]); t=np.array([[0,1,2]])
    p=tmp_path/'test.stl'; write_mesh(p,v,t)
    data=p.read_bytes()
    assert len(data)==134 and struct.unpack('<I',data[80:84])[0]==1
    values=struct.unpack('<12fH',data[84:])
    assert values[6]==100. and values[10]==200.
    assert json.loads(p.with_suffix('.stl.units.json').read_text())['coordinate_units']=='mm'

@pytest.mark.parametrize('ext',['ply','pcd','xyz'])
def test_cloud_exports(tmp_path,ext):
    p=tmp_path/f'cloud.{ext}'; write_cloud(p,np.array([[0,0,1],[1,2,3]]))
    assert 'meters' in p.read_text() and '3.000000000' in p.read_text()

@pytest.mark.parametrize('ext',['obj','ply'])
def test_mesh_exports(tmp_path,ext):
    p=tmp_path/f'mesh.{ext}'
    write_mesh(p,[[0,0,1],[.1,0,1],[0,.1,1]],[[0,1,2]])
    assert 'meters' in p.read_text()

def test_refuse_overwrite(tmp_path):
    (tmp_path/'existing').write_text('x')
    with pytest.raises(FileExistsError): new_directory(tmp_path)

def test_session_refuses_traversal(tmp_path):
    write_json(tmp_path/'session.json',{'schema_version':1,'frames':[{'path':'../secret.npz'}]})
    with pytest.raises(ValueError): load_session(tmp_path)

def test_synthetic_known_fusion(tmp_path):
    create_demo(tmp_path/'session',step_deg=20)
    report=fuse_known_clouds(tmp_path/'session',tmp_path/'out',.004)
    assert np.allclose(report['aabb_extent_mm'],[400,400,200],atol=15.)
    assert (tmp_path/'out'/'fused_known_points.ply').is_file()

def test_static_mode_refuses_rotating_scene_before_open3d_import(tmp_path):
    create_demo(tmp_path/'session',step_deg=20)
    with pytest.raises(ValueError,match='stationary'):
        reconstruct(tmp_path/'session',tmp_path/'out','static')

def test_snapshot_cli_without_hardware(tmp_path):
    create_demo(tmp_path/'session',step_deg=20)
    rc=main(['snapshot','--input',str(tmp_path/'session/frames/000000.npz'),
             '--out',str(tmp_path/'snapshot'),'--stride','1'])
    assert rc==0 and (tmp_path/'snapshot/observed_mesh.stl').is_file()
    rc=main(['measure','--input',str(tmp_path/'snapshot/frame.npz'),
             '--p1','75','60','--p2','85','60','--out',str(tmp_path/'distance.json')])
    assert rc==0
    assert json.loads((tmp_path/'distance.json').read_text())['distance_mm']>0

def test_invalid_measurement_fails(tmp_path):
    create_demo(tmp_path/'session',step_deg=20)
    assert main(['measure','--input',str(tmp_path/'session/frames/000000.npz'),
                 '--p1','0','0','--p2','1','1'])==2
`````
