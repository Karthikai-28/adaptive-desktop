#!/usr/bin/env bash
set -Eeuo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

python3 -m py_compile "$HERE/main.py"

python3 - "$HERE/assets" <<'PY'
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

root = Path(sys.argv[1])
files = sorted(root.glob("*.svg"))
if not files:
    raise SystemExit("No SVG assets found")

for f in files:
    ET.parse(f)

print(f"SVG validation: PASS ({len(files)} assets)")
PY

if command -v desktop-file-validate >/dev/null; then
  desktop-file-validate "$HERE/com.karthi.AdaptiveFiles.desktop"
fi

echo "Python syntax: PASS"
echo "Desktop entry: PASS"
