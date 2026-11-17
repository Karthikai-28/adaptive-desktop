# Sources and implementation decisions

The research reports are preserved as historical text in `RESEARCH_ARCHIVE.md` and `research/`. Their claims were not all independently revalidated during the code-generation task. The sources below were consulted for the new Ubuntu implementation.

| Area | Primary source | Decision in this code |
|---|---|---|
| Original Kinect access | [OpenKinect/libfreenect](https://github.com/OpenKinect/libfreenect) | Use libfreenect, not libfreenect2 |
| Ubuntu driver packages | [Ubuntu 24.04 libfreenect](https://packages.ubuntu.com/source/noble/libfreenect) | Prefer the distro package for the baseline; diagnose missing functions explicitly |
| Device access | [Upstream udev identifiers](https://github.com/OpenKinect/libfreenect/blob/master/platform/linux/udev/51-kinect.rules) | Match only original-Kinect USB functions; use restricted group access |
| Metric depth format | [libfreenect API header](https://sources.debian.org/src/libfreenect/1%3A0.1.2%2Bdfsg-6/include/libfreenect.h/) | Request `FREENECT_DEPTH_MM`; do not treat raw 11-bit disparity as millimeters |
| Factory ray model | [libfreenect registration source](https://sources.debian.org/src/libfreenect/1%3A0.5.3-1/src/registration.c) | Query device factory ray mapping rather than copy internet focal lengths |
| C-wrapper API signature | [JavaCPP libfreenect API](https://javadoc.io/static/org.bytedeco/libfreenect/0.5.7-1.5.9/org/bytedeco/libfreenect/global/freenect.html) | Cross-check the exposed `freenect_sync_camera_to_world` signature |
| Acquisition buffer/API | [Upstream Python wrapper source](https://github.com/OpenKinect/libfreenect/blob/master/wrappers/python/freenect.pyx) | Cross-check synchronous depth call and data type; copy the returned ring buffer |
| Open3D environment | [Open3D 0.19 installation](https://www.open3d.org/docs/0.19.0/getting_started.html) | Conservative Python 3.10–3.12 reference environment |
| Registration | [Open3D ICP API](https://www.open3d.org/docs/0.19.0/python_api/open3d.pipelines.registration.registration_icp.html) | Reuse point-to-plane registration, not a new ICP implementation |
| TSDF | [Open3D ScalableTSDFVolume](https://www.open3d.org/docs/0.19.0/python_api/open3d.pipelines.integration.ScalableTSDFVolume.html) | Reuse the volume and surface extraction |
| Pose convention | [Open3D integration example](https://www.open3d.org/docs/0.19.0/tutorial/pipelines/rgbd_integration.html) | Invert `T_world_from_camera` for integration |
| GLib packages | [Ubuntu 22.04](https://packages.ubuntu.com/jammy/libglib2.0-0), [Ubuntu 24.04](https://packages.ubuntu.com/noble/libglib2.0-0t64) | Choose the package name by supported Ubuntu release |

## What is newly authored

The CLI, ctypes/process isolation, masks, record format, turntable integration, measurement reporting, simple geometry writers, and tests were authored for this delivery. They are not represented as a clone of a hardware-tested existing scanner.

The difficult general reconstruction algorithms are reused from Open3D. The low-level USB protocol implementation is reused from libfreenect. The code does not contain proprietary Kinect SDK binaries, firmware, or third-party game assets.

## Licensing

The new code is MIT-licensed. Consult each installed dependency's own license. libfreenect's upstream license choices and redistribution rules are in its repository; Open3D's license is in its repository. The earlier linked applications, data, games, Unity assets, and repositories remain separately licensed. A public repository URL is not automatic permission to redistribute every included asset.
