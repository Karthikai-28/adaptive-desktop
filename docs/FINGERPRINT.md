# Fingerprint login, screen unlock and sudo

Ubuntu supports fingerprint authentication through fprintd, libfprint and
pam_fprintd. Adaptive uses those backends unchanged: GDM's `gdm-fingerprint`
service, the lock screen, and sudo (through `common-auth`) all ask fprintd. The
password always keeps working. Adaptive never reads fingerprint images or
templates in its own code and adds no authentication bypass.

This laptop's reader, a Validity **VFS7552** (`138a:0091`), needs one more piece:
Ubuntu's libfprint cannot recognise fingers on it. The cause and the fix are below.

## Why the VFS7552 failed, and the fix

Measured on 2026-11-16 from 62 real scans of 7 of the operator's fingers
(recorded with `fingerprint/research/`, then deleted):

- **The sensor is fine.** Background-subtracted frames show sharp ridges. Windows
  works because Synaptics' driver matches the ridge *pattern*.
- **libfprint cannot match them.** It uses bozorth3, which compares minutiae
  (ridge endings and forks) and was designed for fingertip-sized images. The
  VFS7552 sees about 6 × 6 mm: ~12 minutiae per scan. Re-running libfprint's own
  pipeline on the recordings, 1 of 14 genuine scans matched a 5-touch enrollment,
  exactly the failure seen live. Better image cleanup did not change that.
  Upstream has no fix ([issue 373](https://gitlab.freedesktop.org/libfprint/libfprint/-/issues/373),
  open since 2021). Newer official releases fail the same way
  ([trial](FINGERPRINT_DRIVER_TRIAL.md)).
- **The driver also took the first frame** whose contrast crossed a threshold,
  often a finger still landing with a third of it on the reader, and left the
  sensor's horizontal line noise in the image.

`fingerprint/libfprint-vfs7552-pattern.patch` (on official libfprint v1.94.100)
changes four things, for this reader only:

1. **Pattern matcher** (`fpi-pattern.cpp`, OpenCV): SIFT keypoints describe the
   ridge texture; a score is the number of keypoint matches that agree on one
   rigid placement of the finger (RANSAC, scale 0.85-1.15). Two different
   fingers do not agree on a placement, so their score stays near zero. Other
   readers keep bozorth3.
2. **Settled capture**: after the finger is detected, the sharpest of the next 4
   frames (~190 ms) is used.
3. **Clean image**: signed difference from the empty-sensor background, per-line
   and per-column offsets removed, contrast stretched (`drivers/vfs7552_image.h`).
4. **12-touch enrollment** (was 5): the template covers the fingertip, not one spot.

### Measured accuracy (threshold 15)

| Recorded scans | Result |
| --- | --- |
| Operator's right index, each scan vs the other 11 | 12/12 accepted (lowest 32) |
| Operator's right middle, each scan vs the other 17 | 17/18 accepted (miss scored 12) |
| 5 other fingers vs 12-touch templates | 0/70 accepted (highest 4) |
| All wrong-finger scan pairs | 0/1932 at threshold (highest 5) |

The threshold (`VFS7552_PATTERN_THRESHOLD`) is 3x the highest wrong-finger score
ever seen. **Never lower it to make a finger pass: enroll that finger again.** A
genuine miss costs a second touch or the password; a lower threshold risks
letting someone else in. Re-measure with `fingerprint/research/` before
changing it.

## Install (this laptop)

```sh
fingerprint/build-driver.sh                  # no root: checksum-pinned tarball, patch, 11 libfprint tests
scripts/install-fingerprint-driver.sh        # administrator dialog
scripts/install-fingerprint-driver.sh --status
```

The installer copies the library to `/opt/adaptive-fingerprint/` (fprintd runs
with `ProtectHome`, so it cannot load from the checkout) and adds one drop-in,
`/etc/systemd/system/fprintd.service.d/50-adaptive-libfprint.conf`, that points
Ubuntu's own fprintd at it. It checks fprintd really loaded the library and
restores the packaged one if not. Ubuntu's fprintd, pam_fprintd, GDM and the PAM
stack are not modified; apt upgrades of them keep working. The library needs
OpenCV 4.5 (`libopencv-*4.5d`, kept installed by `python3-opencv`).

**Re-enroll afterwards.** Prints made by bozorth3 never match the new matcher
(they fail safely, as non-matches), and new prints never match Ubuntu's stock
library. Remove the old fingers, then register each finger with 12 touches.

Remove: `scripts/install-fingerprint-driver.sh --remove`, then enroll again if
you want the stock (non-working) matcher. If anything goes wrong, password login
and `sudo` with a password are unaffected; removing the drop-in by hand
(`sudo rm` the file above, `sudo systemctl daemon-reload`) is the full rollback.

## Enrolling and testing

Open **Adaptive Settings → Updates & Recovery → Fingerprint unlock → Manage
fingers**. Explicitly select an unregistered finger and press **Register finger**.
The scan heading names the finger throughout, and hints walk the fingertip
across the 12 touches: centre first, then the tip and upper part, then the edges.
A generic fingerprint illustration fills as fprintd accepts samples (not a map
of your biometric data); retries leave progress unchanged. Reduced-motion
settings are respected. Use **Test recognition** on a registered finger to
check it without locking the session; also test that a *different* finger is
rejected. Scans stop when cancelled, when the window closes, or after 90
seconds. Removing fingers opens Ubuntu's Users panel, or use
`fprintd-delete "$USER"` to remove all of them.

```sh
/usr/bin/python3 scripts/fingerprint.py              # status, incl. whether the matcher is needed/installed
/usr/bin/python3 scripts/fingerprint.py --json
./install.sh --status --only fingerprint
fprintd-verify -f right-index-finger                 # direct check of one finger
```

## Detection

`bootstrap.sh` installs Ubuntu's `fprintd` and `libpam-fprintd`. Settings and
`install.sh` query fprintd's device list. An empty list means no *supported*
reader was detected (absent, disabled in BIOS, or unsupported by the driver); a
service or permission failure is reported separately. Neither enables
authentication. Fingerprint enrollment enables the session's writable GNOME
fingerprint policy if needed; enforced administrator policies are respected.

## Login, lock screen and sudo

GDM ships `/etc/pam.d/gdm-fingerprint`; the lock screen and login screen offer
the fingerprint alongside the password. A fingerprint does not replace a
disk-encryption passphrase and does not unlock the login keyring after a fresh
boot (GNOME asks for the password once for that).

**Enable fingerprint for sudo** (Settings, or `scripts/fingerprint.py
--enable-sudo`) runs Ubuntu's `pam-auth-update --enable fprintd`: fingerprint
first, then `pam_unix` password. It applies to every service that includes
`common-auth` and adds no sudoers rights. Ubuntu's profile allows **one touch
with a 10-second timeout**, then asks for the password. Scan first, or leave the
reader untouched to get the password prompt. `sudo -k true` forces a fresh
check. To remove: `sudo pam-auth-update --disable fprintd`.

## Verification

```sh
python3 scripts/verify-fingerprint.py                      # detection, guards, matcher state, enrollment hints
xvfb-run -a /usr/bin/python3 scripts/verify-fingerprint-ui.py
fingerprint/build-driver.sh                                # 11 libfprint tests incl. VFS7552 replay
```

Measuring recognition again (needs the operator at the reader; images stay in a
private folder outside the repo; delete them afterwards):

```sh
fingerprint/research/build.sh
fingerprint/research/run-capture.sh /tmp/fp-genuine right-index:12 right-middle:12
fingerprint/research/run-capture.sh /tmp/fp-others left-index:5 left-thumb:5 right-thumb:5 right-ring:5
python3 fingerprint/research/c_check.py 15 /tmp/fp-genuine /tmp/fp-others
```

`c_check.py` runs the shipped C image processing and matcher on the recordings;
`analyze.py` compares libfprint's stock bozorth3 pipeline. Desktop notifications
say which finger to use and when to lift. The research build's frame dump is a
compile-time option (`-DVFS7552_RESEARCH_DUMP`); the installed library has none.

Physical checks stay separate from these: recognition, rejection, lock/unlock,
login after reboot, and fingerprint and password sudo. Record them with
`scripts/record-live-verification.py` (`fingerprint_unlock`, `fingerprint_sudo`).

## History

- 2026-11-14: VFS7552 detected, enrollment worked, recognition always failed,
  with the packaged stack and with the latest official releases
  ([trial](FINGERPRINT_DRIVER_TRIAL.md)). sudo PAM profile enabled; password
  fallback (`sudo -k true`) verified.
- 2026-11-16: cause measured (minutiae matcher vs 6 mm sensor), pattern matcher
  built and measured offline on the operator's scans (table above). Live
  install, re-enrollment and physical checks pending: see `docs/BACKLOG.md`.

## Upstream references

- [Ubuntu fingerprint login](https://help.ubuntu.com/stable/ubuntu-help/session-fingerprint.html.en)
- [libfprint supported devices](https://fprint.freedesktop.org/supported-devices.html)
- [VFS7552 false negatives, libfprint issue 373](https://gitlab.freedesktop.org/libfprint/libfprint/-/issues/373)
- [fprintd device API](https://fprint.freedesktop.org/fprintd-dev/Device.html)
- [pam_fprintd and its sequential authentication](https://manpages.ubuntu.com/manpages/jammy/man8/pam_fprintd.8.html)
