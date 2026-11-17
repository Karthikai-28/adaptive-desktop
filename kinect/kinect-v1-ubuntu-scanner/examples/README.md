# Synthetic example data

`synthetic_session/` is generated analytically by `kinectscan demo`. It is not a real sensor capture.

The camera is 160×120 with artificial intrinsics. The object is a box assembly with ideal full extents of 400×400×200 mm, rotated around a known axis. Pixel sampling and voxel averaging affect the observed extents.

Do not use this calibration on a real Kinect. The supplied PLY/STL preview in `first_view_observed/` is only the visible front surface, not a complete closed model.

From the repository root:

```bash
kinectscan fuse-known --session examples/synthetic_session --out runs/example_cloud
kinectscan reconstruct --session examples/synthetic_session --mode known --out runs/example_mesh
```

The second command requires Open3D. Its pipeline was not executed in the authoring environment; see `docs/VALIDATION.md`.
