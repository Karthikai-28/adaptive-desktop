#!/usr/bin/env bash
set -Eeuo pipefail

if grep -RhsE '^[[:space:]]*deb-src[[:space:]]+' \
  /etc/apt/sources.list /etc/apt/sources.list.d 2>/dev/null | grep -q .
then
  echo "deb-src entries: PRESENT"
  exit 0
fi

. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/adaptive-paths.sh"
cat <<EOF
deb-src entries: MISSING

To build the exact Ubuntu-patched Nautilus source, enable Ubuntu source
repositories first and run:

  sudo apt update

Then run:

  cd $ADAPTIVE_REPO
  ./scripts/prepare-nautilus-fork.sh

Do not remove the installed system Nautilus package.
EOF

exit 2
