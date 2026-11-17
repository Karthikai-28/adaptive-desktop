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
