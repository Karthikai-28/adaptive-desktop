# Validation report

**Date:** November 17, 2026  
**Package:** Kinect v1 Ubuntu Scanner 0.1.0

## Result

**38 tests passed; 1 test skipped.**

The skipped test is the Open3D known-pose TSDF test. **Open3D was not installed in the execution environment, and a physical Kinect was not available.**

This report does not claim that the Ubuntu installer, sensor enumeration, real USB streaming, factory calibration query against a real device, graphical preview, or Open3D fusion has been successfully run on target hardware.

## Actual execution environment

| Component | Value |
|---|---|
| OS userspace | Debian GNU/Linux 13 |
| Kernel / architecture | Linux 6.18.57, x86-64 |
| Python | 3.13.5 |
| NumPy | 2.3.5 |
| SciPy | 1.17.0 |
| OpenCV Python | 4.13.0.92 |
| Open3D | Not installed |
| libfreenect_sync | Not installed |
| Physical Kinect | Not available |
| Network from code-execution container | Not available |

This differs from the target **Ubuntu 22.04/24.04 + Python 3.10–3.12** reference environment. It validates the dependency-light code paths, not installation of the pinned full stack.

## Commands executed

```bash
PYTHONPATH=src python3 -m pytest -q
python3 -m compileall -q src
bash -n scripts/install_ubuntu.sh scripts/smoke_test.sh
PYTHONPATH=src python3 -m kinectscan doctor
PYTHONPATH=src python3 -m kinectscan probe --timeout 2
bash scripts/smoke_test.sh /mnt/data/work/smoke
```

The negative probe exited with code **2** and an explicit missing-library message. It was an error-path check, not a successful connection:

```text
ERROR: RuntimeError: libfreenect_sync not found. Install libfreenect-dev and libfreenect-bin, then run ldconfig if built from source.
```

## What the automated tests cover

- Millimeter-to-meter projection, pixel geometry, and invalid-depth handling.
- Intrinsics, image-shape, rigid-transform, ROI, and depth-range validation.
- Temporal median behavior and rejection of missing/unstable samples.
- Signed foreground subtraction without unsigned integer underflow.
- Largest connected silhouette selection.
- Observed-surface triangles, normals, missing samples, and depth discontinuities.
- Turntable pose inversion and full-turn closure on analytic geometry.
- Axis-circle fitting and rejection of collinear data.
- Voxel point averaging and explicit observed-surface extent reporting.
- Frame serialization with pickle disabled.
- PLY, PCD, XYZ, OBJ, and binary STL structure.
- STL millimeter scaling and the units sidecar.
- Refusal to overwrite nonempty directories and rejection of manifest path traversal.
- Synthetic known-pose multi-view point fusion.
- Refusal to use static fusion on a rotating session.
- Offline snapshot/measurement CLI paths and missing-depth errors.
- A **mocked** libfreenect C binding, including copying its reusable memory buffer and deriving intrinsics from a known fake ray model.

## Synthetic end-to-end execution

A deterministic 160×120 analytical camera captured a rotating asymmetric box assembly at known poses. The software generated a session, exported a single observed-surface snapshot, and fused all known-pose views into a point cloud.

The example geometry is intentionally labeled **synthetic** in file names/manifests. It is not a real Kinect capture, not a scanned person or product, and not evidence of sensor accuracy.

## Not exercised here

| Component | Status |
|---|---|
| Ubuntu apt/pip installation | Script inspected and shell syntax checked; not executed on Ubuntu |
| udev / group changes | Not executed |
| Physical power, USB, and sensor streaming | Not tested |
| Factory parameters from a physical Kinect | Not tested |
| Preview GUI / Open3D viewer | Not tested |
| ICP on real rotating products or people | Not tested |
| Open3D pose-graph optimization | Not tested |
| Open3D TSDF and mesh extraction | Optional test skipped |
| `mesh-check` / Open3D-based conversion | Not tested |
| Calibration accuracy, physical repeatability, printability | Not measured |
| Full-body scanning quality | Not validated |

## Required target-machine acceptance sequence

Run the unit suite after installation. With Open3D present, the previously skipped synthetic TSDF test should execute rather than skip. Then run `probe`, inspect a depth preview, capture a stationary reference object, and validate dimensions against an independent measurement.

Only after that should you try known-axis product rotation, automatic registration, and cooperative self-scanning. Preserve diagnostics for failures rather than loosening every threshold until a model appears.

## Additional export and numerical checks

The dependency-light synthetic known-pose fusion produced **27,536 points**. Its
observed axis-aligned extents were approximately **400.94 x 399.96 x 200.88 mm**,
against the synthetic scene's analytic **400 x 400 x 200 mm** envelope. These
numbers validate this generated fixture and its coordinate/export path only;
they are not a Kinect accuracy or reconstruction benchmark.

An independent STL reader (`trimesh`, already present in the authoring
environment) successfully read the exported synthetic observed-surface STL:
**4,240 triangles**, with millimeter-coordinate bounds approximately
`[-195.5, -247.8, 1150.0]` to `[195.5, 149.5, 1200.0]`. This confirms that the
binary export is readable and uses the requested unit scale. It does not prove
watertightness, printability, hidden-surface coverage, or physical accuracy.
