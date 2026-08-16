#!/usr/bin/env bash
set -Eeuo pipefail

cd "${HOME}/adaptive-desktop"
exec apps/adaptive-command/main.py "$@"
