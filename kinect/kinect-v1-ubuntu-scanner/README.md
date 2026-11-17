# Kinect v1 Ubuntu Scanner

A local, geometry-first reference implementation for **the original Kinect v1 / Xbox 360 sensor**, a **fixed camera**, and either a stationary subject or a rotating subject.

**Validation status:** the delivered code passed **38 automated tests** and the synthetic end-to-end workflow in the execution environment. **One Open3D test was skipped because Open3D was not installed. No physical Kinect was available, and the Ubuntu installer, USB acquisition, graphical preview, real-object registration, and TSDF reconstruction were not exercised here.** Read [the validation report](docs/VALIDATION.md) before treating this as a deployed system.

This is implementation code, not a claim of tested plug-and-play hardware support. Multi-view reconstruction is capture-then-process, not a live fusion interface.

## What is implemented

| Capability | Command / implementation |
|---|---|
| Inspect dependencies and USB enumeration | `kinectscan doctor` |
| Connect to Kinect v1 and obtain device-specific factory projection parameters | `kinectscan probe` |
| Live depth preview | `kinectscan preview` |
| Empty-scene background capture | `kinectscan background` |
| Stationary-view point cloud, observed-surface mesh, measurements | `kinectscan snapshot` |
| Distance between two visible pixels | `kinectscan measure` |
| Fixed-camera recording of a slowly rotating subject | `kinectscan record` |
| Fit a turntable axis from an off-axis target's measured 3D orbit | `kinectscan axis-fit` |
| Manually indexed, stop-and-hold turntable recording | `kinectscan turntable` |
| Known-pose multi-view point-cloud fusion without Open3D | `kinectscan fuse-known` |
| Open3D registration and TSDF reconstruction | `kinectscan reconstruct` |
| Point-cloud/mesh viewing and mesh-format conversion | `kinectscan view`, `convert` |
| Topology checks | `kinectscan mesh-check` |
| Reproducible hardware-free example | `kinectscan demo` |

The code reuses **libfreenect** for acquisition and **Open3D** for ICP, pose-graph optimization, and TSDF reconstruction. NumPy/SciPy handle masks, coordinate transforms, lightweight geometry, and tests. [Sources and API references](docs/SOURCES.md).

## Scope boundaries

A stationary subject produces **only its visible surfaces**. A rotating subject exposes additional views; surfaces never observed are not manufactured as measurement data. An STL may be open and not printable. No automatic hole completion, textured mesh, STEP/BREP conversion, non-rigid human reconstruction, face recognition, skeleton-game integration, or motor controller is included.

`record --stationary` is valid only when **both** camera and subject stay still. The static reconstruction mode rejects sessions not explicitly marked stationary. The turntable mode assumes a measured axis and accurately indexed angles; it does not claim to measure those angles with an encoder.

All processing stays on your PC. No account, remote service, or cloud upload is used.

## Reference environment

Use **Ubuntu 22.04 or 24.04, x86-64, Python 3.10–3.12** for the full reference stack. These are conservative target environments, not a claim that a particular Ubuntu release is the latest. `requirements-ubuntu.txt` fixes the numerical, preview, reconstruction, and testing packages. The dependency-light core was tested here under a different environment recorded in `docs/VALIDATION.md`.

You need the **Kinect v1 external power/USB adapter**. A USB cable without the sensor's required external power is not enough. Do not install libfreenect2 or a Microsoft Windows SDK for this Ubuntu workflow.

## Install and connect

Read the script before running it. It changes apt packages, a Kinect-specific udev file, and your `plugdev` group membership. It does not disable Secure Boot, replace system Python, or make all USB devices world-writable.

```bash
cd kinect-v1-ubuntu-scanner
bash scripts/install_ubuntu.sh

# Log out and back in after group changes; reconnect the powered Kinect.
source .venv/bin/activate
kinectscan doctor
kinectscan probe --out intrinsics.json
kinectscan preview --z-min 0.7 --z-max 3.5
```

The probe does not invent a focal length. It derives the library's device-specific pinhole parameters from `freenect_sync_camera_to_world`. When that function is unavailable, it stops and asks for a separately calibrated `--intrinsics` file or an appropriate official libfreenect build.

**Factory projection is not independent metrology calibration.** Check physical dimensions against reference objects before relying on measurements.

## First product scan

Keep the sensor and background fixed. Remove the product for the background recording, then place it back. Adjust the example ROI to your scene.

```bash
mkdir -p runs
kinectscan background --out runs/empty.npz --samples 30

kinectscan snapshot \
  --background runs/empty.npz \
  --roi 100 40 540 450 \
  --z-min 0.8 --z-max 1.8 \
  --out runs/product_front
```

Outputs include PLY/PCD/XYZ point clouds, PLY/OBJ/STL observed-surface meshes, a saved depth frame, and a JSON measurement report. **PLY/PCD/XYZ/OBJ coordinates are meters; STL coordinates are millimeters**, accompanied by a units sidecar.

For complete dimensions, capture additional orientations. Do not interpret a front-surface bounding box as a complete object envelope.

## Rotating-subject scan

```bash
kinectscan record \
  --background runs/empty.npz \
  --roi 100 40 540 450 \
  --z-min 0.8 --z-max 2.0 \
  --seconds 60 --fps 5 --delay 5 \
  --out runs/product_rotation

kinectscan reconstruct \
  --session runs/product_rotation \
  --mode auto \
  --voxel-m 0.006 \
  --out runs/product_reconstruction
```

Rotate slowly while preserving shape. Do not move the sensor, table, or background. The automatic rigid-registration route is **experimental until tested on your scene**. It is not a non-rigid body scanner and cannot guarantee alignment for smooth, symmetric, or deforming subjects.

See [the complete guide](docs/INSTALL_AND_USAGE.md) for the calibrated turntable route, self-scanning precautions, transformations, outputs, and troubleshooting.

## Test without a Kinect

```bash
python -m pytest -q
kinectscan demo --out runs/synthetic_session
kinectscan fuse-known \
  --session runs/synthetic_session \
  --out runs/synthetic_cloud

# Requires Open3D:
kinectscan reconstruct \
  --session runs/synthetic_session \
  --mode known \
  --out runs/synthetic_mesh
```

The included `examples/synthetic_session` and its preview exports are **generated analytical test data, not real Kinect captures**.

## Code map

| File | Responsibility |
|---|---|
| `src/kinectscan/capture.py` | libfreenect ctypes binding, copied buffers, killable worker, read timeout |
| `src/kinectscan/geometry.py` | Intrinsics, invalid-depth handling, rectification, masks, rays, mesh, transformations, axis fitting |
| `src/kinectscan/storage.py` | Safe local records, manifests, PLY/PCD/XYZ/OBJ/STL writers, explicit units |
| `src/kinectscan/reconstruct.py` | Open3D ICP/pose graph/TSDF and known-pose point fusion |
| `src/kinectscan/synthetic.py` | Analytical raycasts and known-pose synthetic sessions |
| `src/kinectscan/cli.py` | All command-line workflows |
| `tests/` | Geometry, storage, CLI, mocked C binding, and optional Open3D tests |
| `config/99-kinectscan.rules` | Restricted Kinect v1 device access |
| `scripts/install_ubuntu.sh` | Reference Ubuntu installer |
| `scripts/smoke_test.sh` | Hardware-free workflow |

## License

The new glue/application code is MIT-licensed; see `LICENSE`. Third-party libraries and the independently linked repositories retain their own licenses. This package does not redistribute Microsoft SDKs, proprietary scanner applications, firmware, or third-party game assets.
