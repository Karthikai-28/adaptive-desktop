#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON_BIN="${PYTHON_BIN:-python3}"
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
OUT="${1:-runs/synthetic-smoke}"
"$PYTHON_BIN" -m pytest -q
"$PYTHON_BIN" -m kinectscan demo --out "$OUT/session" --step-deg 10
"$PYTHON_BIN" -m kinectscan snapshot --input "$OUT/session/frames/000000.npz" --out "$OUT/snapshot" --z-min 0.7 --z-max 2.0 --stride 1
"$PYTHON_BIN" -m kinectscan fuse-known --session "$OUT/session" --out "$OUT/fused-cloud"
echo "Synthetic smoke test complete. This does not validate USB hardware or Open3D TSDF."
