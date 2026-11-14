# VFS7552 driver comparison

The operator reports flawless recognition in Windows. That supports investigating
the Linux capture/matching stack rather than treating the reader as defective.
Hardware detection and successful enrollment alone do not establish successful
recognition.

## Official upstream versions checked on 2026-11-14

| Component | Installed Ubuntu version | Latest upstream tag checked | Source commit |
| --- | --- | --- | --- |
| libfprint | 1.94.3 + Ubuntu TOD patches | v1.94.100 | `80a4b5ec612892c5c056c48dddaa561452cf37ec` |
| fprintd | 1.94.2 + Ubuntu patches | v1.94.5 | `b54a007ccf58ac0ae074c7151b223f35cbd17306` |

Sources were downloaded from the official GitLab project API, using the tagged
archives, into `.local/fingerprint-research/`. No third-party driver fork or
matching-threshold change was used.

- [libfprint releases](https://gitlab.freedesktop.org/libfprint/libfprint/-/releases)
- [libfprint v1.94.100 release notes](https://gitlab.freedesktop.org/libfprint/libfprint/-/blob/v1.94.100/NEWS)
- [fprintd v1.94.5 release notes](https://gitlab.freedesktop.org/libfprint/fprintd/-/blob/v1.94.5/NEWS)
- [VFS7552 false negatives, upstream issue 373](https://gitlab.freedesktop.org/libfprint/libfprint/-/issues/373)

The issue was still open, updated 2026-10-16, when queried through the public
API. The recent VFS7552-specific commits only change formatting; the newer
library does include shared verification changes. fprintd 1.94.3 fixed handling
of readers without internal storage, and 1.94.5 improves device-error handling.
These are reasons to test the new stack, not evidence that recognition is fixed.

## Isolated builds and checks

Both sources built unmodified on Ubuntu 22.04. Meson 1.3.2 lives in a local
virtual environment. Ubuntu development packages were downloaded and extracted
under `deps/`, without installing system packages. pkg-config, introspection and
loader search paths pointed to those local dependencies for the build/tests.

libfprint was built with `vfs7552,virtual_image,virtual_device,virtual_device_storage`
drivers, introspection enabled, and docs, installed tests, udev rules/hwdb and
GTK examples disabled. This is a reader-specific trial build, not a replacement
package for all hardware. fprintd uses prefix `/usr`, state directory `/var`,
configuration `/etc`, and has its PAM module, manpages and GTK docs disabled.
The existing installed PAM module remains in use.

Passed upstream tests:

- libfprint: `fpi-device`, `fpi-ssm`, `fpi-assembling`, `fp-context`, `fp-device`,
  and the VFS7552 recorded capture replay (6/6).
- fprintd: enumeration, CLI enrollment, rejection of a nonmatching finger,
  and no-storage reader center-finger retry, concurrent cancellation, and
  already-enrolled handling (6/6).

The first attempts inside the execution sandbox failed because it blocks USB
enumeration and local sockets. All twelve selected tests passed outside that
sandbox, using the upstream virtual devices/private mock buses. They do not
prove recognition on the physical laptop.

## Temporary physical trial

`bash scripts/fingerprint-driver-trial.sh` checks for these local build products:

- `.local/fingerprint-research/build/libfprint/libfprint-2.so.2.0.0`
- `.local/fingerprint-research/daemon-build/src/fprintd`

After local administrator authorization, it copies them as root-owned files to
`/run/adaptive-fingerprint-trial/` and adds only its own runtime systemd drop-in
for fprintd. It checks the daemon actually loaded the trial library. Neither
packaged binaries nor PAM configuration are replaced. The same system fprintd
storage and authorization policy remain in use; templates are never inspected,
exported or copied by this workflow.

The process restores the packaged daemon on exit, interruption or after ten
minutes. End it sooner with `bash scripts/fingerprint-driver-trial.sh --stop`.
The root-owned runtime files are removed during rollback. Existing unrelated
service drop-ins are preserved. A normal reboot also clears `/run`.

During the trial, first test an existing registered finger. If it fails, register
an unused finger with the new stack and verify that exact finger. Keep the finger
centered on the small reader. Do not log out or remove the password during a
trial. Only claim working unlock/sudo after successful physical recognition and
those separate checks. The physical result must be recorded in
`docs/FINGERPRINT.md` and the live verification record.
