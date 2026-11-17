# Kinect v1 + Ubuntu: installation, fixed scanning, measurement, and export

**Prepared:** November 17, 2026  
**Hardware:** original Kinect v1 / Xbox 360; not Kinect v2, Azure Kinect, or Orbbec  
**Code package:** `kinect-v1-ubuntu-scanner`, version 0.1.0

## 1. Status and interpretation

This guide accompanies an implemented Python command-line application, not pseudocode. Multi-view reconstruction is a **capture-then-process workflow**, not a live fusion interface. Its software-only validation is described in the validation report. **Physical USB acquisition and Open3D registration/fusion were not tested in the authoring environment.** Verify the stages below on your Ubuntu computer in order.

The earlier research archive is preserved separately. Windows applications such as ReconstructMe, RecFusion, and FaceFusion are historical research references; they are **not dependencies** of this Ubuntu implementation. Nor does this package port the earlier Windows-only games or skeleton SDKs to Linux.

The intended system is:

```text
Externally powered Kinect v1, physically fixed
        |
        +-- libfreenect: 640 x 480 metric IR-frame depth
        |
        +-- calibration + valid-depth filtering + foreground isolation
        |
        +-- snapshot:
        |      observed point cloud -> visible geometry / measurements
        |      observed grid triangles -> open surface mesh
        |
        +-- rotating subject:
               saved depth frames + relative poses
                  -> registration / known turntable poses
                  -> Open3D TSDF
                  -> mesh + point cloud + measurement report
```

A complete-looking model is not proof of complete measurement. Back faces, the underside, deep recesses, and occluded limbs require additional viewpoints. Mesh repair belongs in a separate, clearly identified printing workflow.

## 2. System requirements and version strategy

The reference installation targets Ubuntu 22.04/24.04 on x86-64 with Python 3.10–3.12. It deliberately uses a fixed Open3D 0.19.0 API and dependency set rather than automatically switching to whichever package is newest. Open3D's published installation matrix includes these Python versions and Linux support. [S4]

A reasonable starting machine has a multi-core CPU and enough RAM for the number of recorded frames; 8–16 GB is a practical planning suggestion, not a measured minimum for this package. CPU reconstruction is used; CUDA is not required by this implementation. A desktop session is needed for the preview/view commands, but capture, conversion, point fusion, and reconstruction do not depend on a graphical window.

For Ubuntu releases using a different default Python, create a separate compatible interpreter environment. **Do not replace the operating system's Python.** The installer deliberately rejects Python versions outside its full-stack reference range. An already installed compatible interpreter can be selected with `PYTHON_BIN`.

The Ubuntu repositories publish `libfreenect-dev` and `libfreenect-bin`; the package version may be older than upstream. [S2] The application uses libfreenect, not libfreenect2. [S1]

## 3. Hardware connection

Connect the Kinect to its original-compatible **external power and USB adapter**, then to the computer. Prefer a direct USB port for the first test. Do not begin with a long extension, an unpowered hub, a virtual machine, or a USB-over-network setup.

Keep the camera mechanically stationary during a session. Do not use its tilt motor to sweep while calling the scan “fixed.” Any mount/pitch change invalidates the captured background and the turntable-axis calibration.

The earlier room discussion contains an unresolved mounting ambiguity: “6–7 feet above the TV” is not necessarily “6–7 feet above the floor.” Record the actual camera height, pitch, and subject distance. The software uses camera-relative coordinates unless you supply a separately calibrated frame transformation.

## 4. Installation

Unpack the ZIP, open a terminal in the codebase directory, and inspect the installer:

```bash
cd kinect-v1-ubuntu-scanner
less scripts/install_ubuntu.sh
bash scripts/install_ubuntu.sh
```

The installer:

- Installs the Ubuntu libfreenect and supporting packages.
- Adds `config/99-kinectscan.rules` and `plugdev` access for the listed Kinect USB functions.
- Creates `.venv`, installs the fixed Python requirements, installs the local package, and records `installed-versions.txt`.

The rule intentionally uses group access and desktop `uaccess`, rather than broad access to arbitrary USB devices. The IDs are cross-checked against the upstream Kinect udev rules. [S3]

Log out and back in after group membership changes. Unplug/replug the powered Kinect. Activate the environment:

```bash
source .venv/bin/activate
kinectscan doctor
```

Do not run the scanner itself as root. `sudo` is used by the installer only for system package and device-permission changes.

### Manual alternative

For a compatible Ubuntu/Python environment:

```bash
# Select the GLib package name for the reference Ubuntu release.
. /etc/os-release
case "$VERSION_ID" in
  22.04) GLIB_PACKAGE=libglib2.0-0 ;;
  24.04) GLIB_PACKAGE=libglib2.0-0t64 ;;
  *) echo "Review package names for this release."; exit 1 ;;
esac
sudo apt-get update
sudo apt-get install -y \
  python3-venv python3-dev \
  libfreenect-dev libfreenect-bin \
  libusb-1.0-0 usbutils libgl1 "$GLIB_PACKAGE"

# Inspect the rules before installing them.
sudo install -m 0644 config/99-kinectscan.rules \
  /etc/udev/rules.d/99-kinectscan.rules
sudo usermod -aG plugdev "$USER"
sudo udevadm control --reload-rules

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install --only-binary=:all: -r requirements-ubuntu.txt
python -m pip install --no-deps -e .
```

The GLib package name differs between Ubuntu 22.04 and 24.04; the branch above follows the Ubuntu package records. [S9] [S10]

The manual path assumes the `universe` repository and `plugdev` group already exist; the script handles those checks. After permission changes, log out/in and reconnect the sensor.

Do not install a random `freenect` package from PyPI. The code calls the system C library via `ctypes`; it does not require the historical Cython wrapper.

## 5. First connection and calibration record

```bash
kinectscan probe --out intrinsics.json
```

Expected results are a nonzero valid-depth fraction and a device-specific intrinsics record. No fixed focal-length guess is silently substituted.

The acquisition mode is **`FREENECT_DEPTH_MM`**, whose values are millimeters in the IR/depth image frame, not RGB-aligned depth. This distinction is explicit in libfreenect's API. [S5]

The probe samples `freenect_sync_camera_to_world` to obtain the pinhole ray model corresponding to the device/library. The driver implementation uses the device's zero-plane parameters. [S6] This is a useful factory starting point, **not a complete independent calibration or depth-bias correction**.

### Separately calibrated intrinsics

A user-supplied file has this schema:

```json
{
  "width": 640,
  "height": 480,
  "fx": 580.0,
  "fy": 580.0,
  "cx": 320.0,
  "cy": 240.0,
  "source": "EXAMPLE ONLY - replace with your calibrated IR camera parameters",
  "distortion": [],
  "depth_format": "FREENECT_DEPTH_MM"
}
```

**The numbers above are schema examples, not recommended calibration values.** Normally, use the real `probe` output. To override it:

```bash
kinectscan probe \
  --intrinsics my_calibrated_ir_intrinsics.json \
  --out checked_intrinsics.json
```

Distortion coefficients, when supplied, use OpenCV's `[k1, k2, p1, p2, k3, ...]` convention. The application supports 4, 5, or 8 coefficients and rectifies with nearest-neighbor sampling. Provide coefficients for the **actual IR depth coordinate frame**, not the RGB camera.

No independent checkerboard-calibration capture tool is included. Measuring known objects is necessary even with factory intrinsics.

## 6. Preview and foreground selection

```bash
kinectscan preview --z-min 0.7 --z-max 3.5
```

Press `Q` or Escape to exit. Black pixels are missing or excluded depth.

ROI syntax is `x0 y0 x1 y1`; the end coordinates are exclusive. A 3D crop is `xmin xmax ymin ymax zmin zmax`, in meters:

```bash
kinectscan preview \
  --roi 100 40 540 450 \
  --box -0.4 0.4 -0.4 0.2 0.8 1.8 \
  --z-min 0.8 --z-max 1.8
```

These values are examples. Tune them while looking at your actual depth preview. With a high-mounted/tilted camera, camera `Y` is not necessarily vertical in the room.

### Empty-scene background

Keep the rotating platform and stationary surroundings in place, but remove the product or person:

```bash
mkdir -p runs
kinectscan background \
  --out runs/empty.npz \
  --samples 30 \
  --delay 3
```

The background is a robust temporal median; invalid measurements remain invalid. A candidate foreground point must be closer than valid background by the configured margin, 25 mm by default.

```bash
kinectscan preview \
  --background runs/empty.npz \
  --background-margin-mm 25 \
  --roi 100 40 540 450 \
  --z-min 0.8 --z-max 1.8
```

Pixels with no valid background are rejected rather than assumed to be foreground. This can remove genuine subject pixels where the background was too far away or reflective. Improve the background or use carefully bounded ROI/3D cropping instead.

The optional `--largest-component` retains one connected silhouette. It can remove disconnected limbs or multiple products; leave it off for a person until you inspect the mask.

**This is not semantic object segmentation.** Hands holding a product may be included. Use a stand, remove the hands before capture, and inspect the support-plane boundary.

## 7. Stationary snapshot: immediate geometry and measurements

```bash
kinectscan snapshot \
  --background runs/empty.npz \
  --roi 100 40 540 450 \
  --z-min 0.8 --z-max 1.8 \
  --samples 15 \
  --out runs/product_front
```

The subject must stay still during the median capture. With temporal rejection:

```bash
kinectscan snapshot \
  --roi 100 40 540 450 \
  --samples 20 \
  --max-std-mm 10 \
  --out runs/stable_front
```

The threshold is a tunable capture criterion, not a claim of 10 mm accuracy.

### Files produced

| File | Meaning |
|---|---|
| `frame.npz` | Processed metric depth, intrinsics, timestamps, and pre-segmentation captured depth |
| `capture_intrinsics.json` | Original capture calibration metadata |
| `observed_points.ply` | Visible 3D points, meters |
| `observed_points.pcd` | Same point geometry, meters |
| `observed_points.xyz` | Same points as text, meters |
| `observed_mesh.ply` | Grid-triangulated observed surface, meters |
| `observed_mesh.obj` | Geometry-only mesh, meters |
| `observed_mesh.stl` | Geometry-only mesh, millimeter coordinates |
| `observed_mesh.stl.units.json` | Explicit companion unit information |
| `measurements.json` | AABB/PCA/percentile extents with limitations |

The mesh connects neighboring valid depth pixels only. It refuses triangles whose edges exceed `--max-edge-m`; the default is 0.04 m. It does not cap silhouettes, bridge missing samples, or invent the back surface. The output can therefore be open. Lowering `--stride` from 2 to 1 increases sampling density, **not sensor accuracy**.

The bounding box describes the included observations. A front scan of a bottle does not establish its unseen depth. The PCA box is data-oriented; it is not guaranteed to align with the intended product length/width/height. Percentile extents intentionally discard extremes and may understate physical size.

### Point-to-point distance

Select valid pixels from the saved, rectified depth image:

```bash
kinectscan measure \
  --input runs/product_front/frame.npz \
  --p1 250 220 --p2 390 220 \
  --out runs/product_front/distance.json
```

The default uses the exact pixels. `--radius 2` uses a 5×5 patch median while retaining the requested central ray. That assumes a locally uniform surface and should not be used across a depth discontinuity.

The output gives both endpoint coordinates and their Euclidean separation. Missing endpoints generate an error, not a guessed measurement.

## 8. Fixed camera with free rotation: automatic reconstruction

For an irregular rigid product, use a slow continuous rotation and foreground isolation:

```bash
kinectscan record \
  --background runs/empty.npz \
  --roi 100 40 540 450 \
  --z-min 0.8 --z-max 2.0 \
  --seconds 60 --fps 5 --delay 5 \
  --out runs/product_rotation
```

`--fps` is the requested saved-frame sampling rate, not a guarantee of hardware frame rate. Processing, compression, and storage can lower the achieved rate; device and host timestamps are retained.

The record contains:

```text
product_rotation/
  session.json
  frames/
    000000.npz
    000001.npz
    ...
```

The manifest is updated after each complete frame. An interrupted session remains available, marked incomplete.

Reconstruct:

```bash
kinectscan reconstruct \
  --session runs/product_rotation \
  --mode auto \
  --voxel-m 0.006 \
  --out runs/product_reconstruction
```

The implementation reuses Open3D's point-to-plane ICP at progressively finer scales. [S7] Each current cloud is registered into the previous cloud, then composed into the first-view reference frame. Cropping/background isolation happens **before** registration.

Frames are rejected when overlap, residual, or inter-frame motion fail configurable gates. On failure, `registration_failure.json` explains the first rejected frame and the command stops before TSDF fusion. It does not continue silently building a corrupted model.

### Optional full-loop constraint

Only use this after actually returning the subject to its original view:

```bash
kinectscan reconstruct \
  --session runs/product_rotation \
  --mode auto --close-loop \
  --out runs/product_loop_reconstruction
```

The code checks a last-to-first registration and uses an Open3D pose graph. A successful numerical check is not proof that a symmetric object was aligned correctly. Inspect the seam and known dimensions.

### Limits of automatic rotation

Smooth spheres, cylinders, repeated patterns, occlusion, large angle jumps, or a person changing pose can defeat rigid ICP. A low residual can still be the wrong correspondence. This reference implementation does not include robust non-rigid human tracking, semantic body isolation, or a globally guaranteed feature-based registration system.

For repeatable product scanning, prefer a measured turntable axis and controlled positions.

## 9. Indexed turntable workflow

The Kinect remains fixed; the product rotates on a stable platform. **No motor-control hardware is assumed or driven by this code.** Angles are entered through a manual indexed stop-and-hold sequence.

### 9.1 Measure the rotation axis

Place a small matte target away from the rotation axis and capture its center position at six or more angular positions spanning at least 180°, preferably around a full circle. Keep target height fixed.

One practical way to obtain XYZ positions is to make snapshots, locate the target pixel, and use `measure` with the same pixel for both endpoints:

```bash
kinectscan measure \
  --input runs/axis_view_01/frame.npz \
  --p1 300 210 --p2 300 210 \
  --out runs/axis_point_01.json
```

Extract `point1_m` from each result into a CSV:

```csv
x_m,y_m,z_m
0.12,0.10,1.25
0.09,0.10,1.32
...
```

Those rows only illustrate the file layout. Do not use the illustrative coordinates as your calibration.

Fit:

```bash
kinectscan axis-fit \
  --points runs/axis_points.csv \
  --skiprows 1 \
  --input-units m \
  --preferred-axis 0 -1 0 \
  --out runs/axis.json
```

`--preferred-axis` chooses the normal's sign, not an assumed exact physical direction. For a tilted camera, the fitted direction need not equal `[0, -1, 0]`.

The fit reports radius, residual, sample count, and angular coverage. It rejects collinear/short-arc data, coverage below 180°, and residual above the chosen threshold. These checks are not a calibration certificate.

### 9.2 Confirm direction

Positive angles follow the right-hand rule about `axis`. Viewed from the positive end of the axis toward its center, positive rotation is counter-clockwise.

Before a long scan, capture a small positive turn and inspect point alignment. A sign mistake makes the model unwind incorrectly. Camera tilt or a flipped axis can make everyday “clockwise” descriptions ambiguous; use the documented vector convention.

### 9.3 Capture at indexed stops

```bash
kinectscan turntable \
  --axis runs/axis.json \
  --step-deg 10 \
  --samples 15 \
  --settle-sec 0.7 \
  --background runs/empty.npz \
  --roi 100 40 540 450 \
  --z-min 0.8 --z-max 1.8 \
  --out runs/indexed_product
```

The program prompts at 0°, 10°, …, 360°. Set the physical platform to each mark, stop motion, and press Enter. Its timestamps do **not** verify that the platform reached the commanded angle.

### 9.4 Fuse points, then reconstruct the surface

First inspect point alignment without requiring Open3D:

```bash
kinectscan fuse-known \
  --session runs/indexed_product \
  --voxel-m 0.005 \
  --out runs/indexed_cloud
```

Then run TSDF:

```bash
kinectscan reconstruct \
  --session runs/indexed_product \
  --mode known \
  --voxel-m 0.006 \
  --out runs/indexed_mesh
```

Known-pose mode uses the calibrated axis and assumed indexed angles; it does not silently alter them with ICP. This helps diagnose axis, angle, and scale errors separately.

## 10. Why the relative transforms matter

All stored coordinates are in meters with camera axes **X right, Y down, Z forward**. The reconstruction world is the camera coordinate frame when the subject is at its initial orientation.

For an object rotating around center `c` with rotation `R(θ)`:

```text
p_camera(theta) = R(theta) * p_world + c - R(theta) * c

G(theta) = T_camera_from_world
T_world_from_camera = inverse(G(theta))
```

The physical camera does not move, but the **object-relative virtual camera pose changes**. Fusing every rotating frame with the identity transform is incorrect.

The session stores `T_world_from_camera`. Open3D's TSDF integration expects the inverse, `T_camera_from_world`; the code performs that inversion explicitly. [S8]

The `static` mode exists only for genuine stationary-scene averaging:

```bash
kinectscan record \
  --stationary \
  --seconds 5 --fps 5 \
  --roi 100 40 540 450 \
  --out runs/stationary_scene

kinectscan reconstruct \
  --session runs/stationary_scene \
  --mode static \
  --out runs/stationary_mesh
```

Do not apply this mode to a rotating person or product.

## 11. Self-scanning

Begin with a head/shoulders snapshot. Then attempt a slow seated or standing rotation with the camera fixed and the entire included body region moving as rigidly as possible.

Capture the empty background before the person enters. Choose an ROI and depth interval that include the whole desired subject region but exclude as much stationary furniture as possible. Use `record`, not a temporal median over an actively rotating person.

The automatic registration path may be useful for a cooperative bust scan, but **human pose changes violate its rigid-scene model**. It is not guaranteed to produce a faithful full-body model. Top-of-head, under-chin, armpit, between-leg, sole, and back coverage cannot be inferred from a front view.

For self-operation, the recording command has a start delay and fixed duration. Have another person operate the computer during early experiments. Do not use a tabletop product turntable for a person; use a safe human-rated platform or a safe controlled turn. This code does not operate powered motion hardware.

Full-body capture from a high room mount is a different geometry from close-up product measurement. Do not assume one permanent position is optimal for all subjects.

## 12. Export, inspection, and printing

Reconstruction produces `fused_points.*`, `fused_mesh.*`, `measurements.json`, `poses.json`, and `quality.json`.

```bash
kinectscan view --input runs/indexed_mesh/fused_mesh.ply

kinectscan mesh-check \
  --input runs/indexed_mesh/fused_mesh.ply \
  --out runs/indexed_mesh/topology.json
```

The topology command checks watertightness, manifold properties, and orientability. It does not certify completeness, measurement accuracy, or printer suitability.

### Unit-safe conversion

```bash
kinectscan convert \
  --input runs/indexed_mesh/fused_mesh.ply \
  --input-units m \
  --out runs/indexed_mesh/print_model.stl \
  --stl-units mm
```

STL geometry has no standardized embedded unit declaration. The code writes millimeter coordinates by default and supplies a sidecar. Verify a known dimension in the receiving slicer.

PLY/OBJ written by this application use meter coordinates and are geometry-only. A PCD/XYZ point cloud is not a surface mesh. A mesh with no triangles cannot be “converted” into STL by renaming it; the converter rejects such input.

**Not implemented:** texture atlases, textured OBJ/GLB, 3MF packaging, STEP/IGES, parametric feature fitting, automatic watertight repair, or an arbitrary-format exporter. Use an appropriate mesh/CAD tool for those downstream tasks. The earlier research discusses some formats that the delivered application deliberately does not claim to write.

Preserve the measurement copy. Make hole filling, smoothing, capping, or miniature scaling only on a separately named printing copy. Record the operations. Repaired regions are inferred geometry, not additional sensor observations.

## 13. Validation on your actual sensor

Use rigid, matte reference objects of independently known size. Scan five times with the same mount, settings, and range. Record extents and repeatability before any cosmetic repair.

Suggested acceptance worksheet:

| Check | Record |
|---|---|
| Sensor identification | Model/serial if available; adapter; USB port/controller |
| Environment | Ubuntu version; Python and package versions |
| Geometry | Camera height/pitch; target range; target size |
| Projection | Factory or independently calibrated intrinsics |
| Segmentation | ROI/3D bounds/background and rejected regions |
| Repeatability | Five independent scans and dimension spread |
| Bias | Mean dimension minus independent reference |
| Registration | Any rejected frames, seam mismatch, false alignments |
| Export scale | Dimension checked after opening STL in the slicer |
| Coverage | Which faces were actually observed; remaining holes |

Define your acceptable error **before** interpreting the results. A 6 mm TSDF voxel or a 10 mm gate is not a promised measurement accuracy. A high point count is not proof of precision. Do not use this unvalidated reference scanner for safety-critical inspection or medical decisions.

## 14. Troubleshooting

| Symptom | First checks |
|---|---|
| `libfreenect_sync not found` | Install Ubuntu's development/runtime packages; inspect `ldconfig -p`; do not install libfreenect2 |
| Sensor opens only as root | Inspect udev/group membership; log out/in; reconnect; do not use permanent root execution as the fix |
| Only motor function enumerates | Check the correct external adapter, power, USB cable/port, and sensor health |
| USB claim/busy error | Close other Kinect applications; check whether a kernel camera driver has claimed the device |
| Worker timeout after disconnect | Restore connection and rerun; the CLI terminates its acquisition worker instead of waiting indefinitely |
| All-zero depth | Inspect distance, surface, IR environment, power, and hardware health |
| Background removes real subject | Check background validity and margin; recapture or use carefully bounded spatial cropping |
| Floor/table merges into product | Narrow the ROI/3D box; remove the support region before registration |
| Rotating model smears or duplicates | Check background isolation, relative-pose mode, axis position, and angle sign |
| ICP fails | Reduce inter-frame rotation, improve overlap/geometry, avoid deforming subjects, or use calibrated indexed rotation |
| ICP appears good but wrong | Symmetry/planarity can give misleading residuals; inspect landmarks and independent dimensions |
| STL is 1000× too large/small | Agree on units in exporter/importer and read the units sidecar |
| GUI fails on a remote/headless system | Use non-GUI commands; run preview/view on a working local desktop |
| Python/Open3D installation fails | Use the documented Python 3.10–3.12 reference environment; do not replace system Python |

A kernel-driver conflict can require system-specific work. Inspect it before changing anything; this installer does not automatically unload modules or install permanent blacklists. Follow upstream libfreenect troubleshooting where appropriate. [S1]

## 15. Data, privacy, and reproducibility

Frames and geometry remain on disk locally. Body scans and room geometry can still be sensitive even without RGB. Obtain consent, select a private output directory, and delete unneeded recordings.

Use a new output directory for each run. The commands refuse nonempty output directories rather than overwrite earlier scans. Preserve the original frame session, calibration, manifest, package versions, and measurement report alongside any repaired printing asset.

The package includes a synthetic example for debugging. **Do not mix its synthetic intrinsics or geometry with hardware measurements.**

## 16. Command reference

```text
kinectscan doctor
kinectscan probe --out intrinsics.json
kinectscan preview [sensor and segmentation options]
kinectscan background --out empty.npz
kinectscan snapshot --out scan_directory [--input saved_frame.npz]
kinectscan measure --input frame.npz --p1 U V --p2 U V
kinectscan record --out session_directory [--stationary]
kinectscan axis-fit --points orbit.csv --out axis.json
kinectscan turntable --axis axis.json --out session_directory
kinectscan fuse-known --session session_directory --out cloud_directory
kinectscan reconstruct --session session_directory --mode auto|known|static --out mesh_directory
kinectscan view --input geometry.ply
kinectscan convert --input mesh.ply --input-units m --out mesh.stl
kinectscan mesh-check --input mesh.ply
kinectscan demo --out synthetic_session
```

Every command has `--help`. This guide's examples are proposals for a starting workflow; ROI, range, axis, and acceptance thresholds must be adapted to the actual installation.

## Sources for the Ubuntu implementation

[S1]: https://github.com/OpenKinect/libfreenect
[S2]: https://packages.ubuntu.com/source/noble/libfreenect
[S3]: https://github.com/OpenKinect/libfreenect/blob/master/platform/linux/udev/51-kinect.rules
[S4]: https://www.open3d.org/docs/0.19.0/getting_started.html
[S5]: https://sources.debian.org/src/libfreenect/1%3A0.1.2%2Bdfsg-6/include/libfreenect.h/
[S6]: https://sources.debian.org/src/libfreenect/1%3A0.5.3-1/src/registration.c
[S7]: https://www.open3d.org/docs/0.19.0/python_api/open3d.pipelines.registration.registration_icp.html
[S8]: https://www.open3d.org/docs/0.19.0/tutorial/pipelines/rgbd_integration.html
[S9]: https://packages.ubuntu.com/jammy/libglib2.0-0
[S10]: https://packages.ubuntu.com/noble/libglib2.0-0t64

- **[S1]** OpenKinect libfreenect: original-Kinect driver, build instructions, and project limitations.
- **[S2]** Ubuntu 24.04 package records for libfreenect.
- **[S3]** Upstream Kinect USB identifiers and udev rules.
- **[S4]** Open3D 0.19 installation/platform documentation.
- **[S5]** Original libfreenect depth-format API, including metric IR-frame versus registered depth.
- **[S6]** libfreenect factory camera-to-world projection implementation.
- **[S7]** Open3D ICP API.
- **[S8]** Open3D volumetric integration and inverse-pose convention.
- **[S9]** Ubuntu 22.04 GLib runtime package.
- **[S10]** Ubuntu 24.04 GLib runtime package.

The transformation equations, command organization, rejection policies, and test procedures in this guide describe the delivered implementation. They are not manufacturer accuracy guarantees.
