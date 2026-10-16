#!/usr/bin/env bash
set -Eeuo pipefail

. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/adaptive-paths.sh"
cd "$ADAPTIVE_REPO"
exec python3 apps/adaptive-projects/main.py "$@"
