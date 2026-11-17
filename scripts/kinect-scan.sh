#!/usr/bin/env bash
# The Kinect v1 scanner (kinect/kinect-v1-ubuntu-scanner) from this checkout, in the Air venv.
#
#   scripts/kinect-scan.sh doctor
#   scripts/kinect-scan.sh snapshot --out ~/Kinect\ Scans/mug --z-min 0.6 --z-max 1.5
#   scripts/kinect-scan.sh record --out ~/Kinect\ Scans/turn --seconds 40 --fps 5 --delay 5
#   scripts/kinect-scan.sh reconstruct --session ~/Kinect\ Scans/turn --mode auto --out ~/Kinect\ Scans/turn-mesh
#
# Every command has --help. It reads the Kinect through the hub when the hub runs (so Air,
# Kinect Studio and Kinect Fitness can stay open), else directly through .local/libfreenect.
# Guide: kinect/kinect-v1-ubuntu-scanner/docs/INSTALL_AND_USAGE.md; notes: docs/KINECT_MOTION.md.
set -Eeuo pipefail
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/adaptive-paths.sh"
PKG="$ADAPTIVE_REPO/kinect/kinect-v1-ubuntu-scanner"
PYTHONPATH="$PKG/src${PYTHONPATH:+:$PYTHONPATH}" exec "$ADAPTIVE_REPO/.local/air-venv/bin/python" -m kinectscan "$@"
