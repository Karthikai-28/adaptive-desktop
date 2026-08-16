#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
PREFIX="${REPO}/.local/adaptive-nautilus"
THEME="${PREFIX}/share/icons/AdaptiveFilesIcons"

echo "STEP 1 — FILE TYPE ICONS"
echo

required=(
  "text-x-python.svg"
  "text-x-csrc.svg"
  "text-x-c++src.svg"
  "application-javascript.svg"
  "text-x-typescript.svg"
  "text-x-java.svg"
  "text-x-rust.svg"
  "text-x-go.svg"
  "text-x-shellscript.svg"
  "application-json.svg"
  "text-x-yaml.svg"
  "text-x-cmake.svg"
  "application-x-ipynb+json.svg"
  "text-x-arduino.svg"
  "text-x-cuda.svg"
  "text-x-makefile.svg"
  "text-x-dockerfile.svg"
)

for icon in "${required[@]}"; do
  test -f "${THEME}/scalable/mimetypes/${icon}"
  printf "PASS  %s\n" "$icon"
done

echo
echo "Total Adaptive SVG icons:"
find "$THEME" -type f -name '*.svg' | wc -l

echo
echo "STEP 1: PASS"
