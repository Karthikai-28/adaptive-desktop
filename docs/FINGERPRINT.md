# Fingerprint login, screen unlock and sudo

Ubuntu supports fingerprint authentication through fprintd, libfprint and
pam_fprintd. Adaptive uses those backends; it never reads fingerprint images or
templates and implements no fingerprint matching or authentication bypass.

Open **Adaptive Settings → Updates & Recovery → Fingerprint unlock → Manage
fingers**. Select an unregistered finger and press **Register finger**. A generic
fingerprint illustration fills smoothly only as the reader accepts samples;
retry scans leave progress unchanged. A scanning line, accepted-sample dots and
separate saved/verified/failure states explain progress. The illustration is
not a map of the user's biometric data. Reduced-motion settings are respected.
Register additional fingers in the same window. Select a registered finger and
use **Test recognition** to check it without locking the session. Scans stop when
cancelled, when the window closes, or after 90 seconds. Removing fingers opens
Ubuntu's Users panel, which owns deletion and its confirmation.

## Detection and installation

`bootstrap.sh` installs Ubuntu's `fprintd` and `libpam-fprintd` packages. Normal
`install.sh` and Settings query fprintd's actual device list. An empty list means
no *supported* reader was detected: the sensor may be absent, disabled in BIOS,
or unsupported by the installed driver. A service or permission failure is
reported separately. Neither condition enables authentication. This works with
readers supported by the installed driver, including non-USB readers; it is not
a promise of support for every laptop.

```sh
/usr/bin/python3 scripts/fingerprint.py              # status; no changes
/usr/bin/python3 scripts/fingerprint.py --json
./install.sh --status --only fingerprint
/usr/bin/python3 scripts/fingerprint.py --setup      # native Users enrollment
/usr/bin/python3 scripts/fingerprint.py --enable-sudo
```

Install missing packages with `sudo apt install fprintd libpam-fprintd python3-gi`.
The enrollment window uses the default reader chosen by fprintd, reports its
registered fingers, and does not overwrite already registered fingers. Reopen
or refresh Settings after attaching a new reader. Normal setup does not download
drivers, flash firmware or alter matching thresholds. The separate
[VFS7552 driver comparison](FINGERPRINT_DRIVER_TRIAL.md) describes an explicit,
temporary test of newer official releases.

GDM already provides `/etc/pam.d/gdm-fingerprint`. Fingerprint enrollment enables
the current session's writable GNOME fingerprint policy if needed; enforced
administrator policies are respected. A greeter can have its own policy. No
shell restart is needed. Password authentication stays available. A fingerprint
does not replace a disk-encryption passphrase or necessarily unlock the login
keyring after a fresh boot.

## sudo

**Enable fingerprint for sudo** opens the local administrator authorization
dialog and runs Ubuntu's `pam-auth-update --enable fprintd`. This preserves the
password modules and uses the distribution's PAM ordering. It also affects
other services that include `common-auth`. No sudoers permissions are added;
fingerprints authenticate only users who already have sudo rights. Local PAM
customizations are never forcibly overwritten.

Terminal PAM authentication is sequential. Scan first; if the scan fails or
times out, enter your password. On this laptop the installed profile allows
one attempt with a 10-second timeout. A cached sudo authorization can skip both
prompts. `sudo -k true` requests fresh authentication for a harmless command.
Test password fallback by leaving the reader untouched until the password
prompt. Enter passwords only in the local terminal or system authorization
dialog. To remove the shared fingerprint option:

```sh
sudo pam-auth-update --disable fprintd
```

## Verification

```sh
python3 scripts/verify-fingerprint.py
xvfb-run -a /usr/bin/python3 scripts/verify-fingerprint-ui.py
```

The virtual-display test uses fixture processes, including successful scans,
failed recognition, cancellation, timeout and closing an active enrollment.
Physical checks remain separate: recognition, lock/unlock, login after reboot,
and both fingerprint and password sudo authentication. Record those through
`scripts/record-live-verification.py` (`fingerprint_unlock`, `fingerprint_sudo`).

On 2026-11-14 this laptop's Validity VFS7552 (`138a:0091`) was recognized by
fprintd 1.94.2 / libfprint 1.94.3 and right-index-finger enrollment completed.
Both command-line verification and the operator's Settings recognition test
returned no match. The operator also enrolled and tested another finger, which
failed too; successful recognition and unlock have not been demonstrated.
This symptom is also documented in [VFS7552 bug 2032293](https://bugzilla.redhat.com/show_bug.cgi?id=2032293)
and the [driver author's small-sensor matching discussion](https://github.com/hmaarrfk/libfprint/issues/4).
These historical reports suggest a driver limitation; they do not prove the
cause on this particular machine. The shared PAM fingerprint
profile was enabled and its password fallback inspected. A local terminal
password-fallback check using `sudo -k true` completed with exit status 0.
Fingerprint sudo authentication remains unverified because recognition fails.

## Upstream references

- [Ubuntu fingerprint login](https://help.ubuntu.com/stable/ubuntu-help/session-fingerprint.html.en)
- [libfprint supported devices](https://fprint.freedesktop.org/supported-devices.html)
  describes the development version; runtime detection is authoritative here.
- [fprintd device API](https://fprint.freedesktop.org/fprintd-dev/Device.html)
- [Ubuntu pam_fprintd and its sequential authentication limitation](https://manpages.ubuntu.com/manpages/jammy/man8/pam_fprintd.8.html)
