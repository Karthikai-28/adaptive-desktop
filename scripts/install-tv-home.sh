#!/usr/bin/env bash
set -Eeuo pipefail

# Install Adaptive Home on the LG TV (apps/adaptive-tv): a launcher with every
# app on the TV, its inputs and its power, that runs on the TV by itself - the
# laptop is only needed to install it.
#
#   install-tv-home.sh --setup [TV_IP]   once: register the TV with the webOS tools
#   install-tv-home.sh                   package, install and open it on the TV
#   install-tv-home.sh --package         only build dist/tv-home/*.ipk
#   install-tv-home.sh --remove          take it off the TV
#
# On the TV, once: install "Developer Mode" from the LG Content Store, sign in
# with an LG developer account, turn Dev Mode Status on (the TV restarts),
# then turn Key Server on. --setup asks for the passphrase that app shows.
# A Developer Mode session runs out unless it is extended in that app; when
# it does, the TV removes apps installed this way and this puts it back.
#
# The webOS CLI is pinned and kept in .local/webos-cli (not tracked).
# Not part of ./install.sh: it installs onto the TV, not this computer.

. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/adaptive-paths.sh"
REPO="$ADAPTIVE_REPO"
CLI_VERSION="3.2.6"
CLI="$REPO/.local/webos-cli"
BIN="$CLI/node_modules/.bin"
DEVICE="adaptive-tv"
APP_ID="com.karthi.adaptivetv"
SOURCE="$REPO/apps/adaptive-tv"
OUT="$REPO/dist/tv-home"

MODE=install
TV_IP=""
case "${1:-}" in
    --setup) MODE=setup; TV_IP="${2:-}" ;;
    --package) MODE=package ;;
    --remove) MODE=remove ;;
    "") ;;
    -h|--help) sed -n '4,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
esac

if [ "$(cat "$CLI/VERSION" 2>/dev/null)" != "$CLI_VERSION" ]; then
    command -v npm >/dev/null || { echo "npm is needed for the webOS CLI" >&2; exit 1; }
    echo "Installing the webOS CLI $CLI_VERSION into .local/webos-cli"
    rm -rf "$CLI"
    npm install --prefix "$CLI" --no-fund --no-audit --loglevel=error "@webos-tools/cli@$CLI_VERSION"
    echo "$CLI_VERSION" > "$CLI/VERSION"
fi

# The TV Cast paired with, when no address is given.
paired_tv_ip() {
    python3 - <<'PY'
import json, pathlib
try:
    tvs = json.loads((pathlib.Path.home() / ".config/adaptive-desktop/cast.json").read_text()).get("tvs") or {}
    print(next(iter(tvs), ""))
except (OSError, ValueError):
    print("")
PY
}

package() {
    node "$REPO/scripts/verify-tv-home.js"
    rm -rf "$OUT"
    mkdir -p "$OUT"
    "$BIN/ares-package" --no-minify -o "$OUT" "$SOURCE/app" "$SOURCE/service" >/dev/null
    ls "$OUT"/*.ipk
}

need_device() {
    "$BIN/ares-setup-device" --list 2>/dev/null | grep -q "^$DEVICE " || {
        echo "The TV is not set up yet: $0 --setup [TV_IP]" >&2
        exit 1
    }
}

case "$MODE" in
    setup)
        TV_IP="${TV_IP:-$(paired_tv_ip)}"
        [ -n "$TV_IP" ] || { echo "Give the TV's address: $0 --setup 192.168.x.y" >&2; exit 2; }
        info=(--info "host=$TV_IP" --info "port=9922" --info "username=prisoner")
        if "$BIN/ares-setup-device" --list 2>/dev/null | grep -q "^$DEVICE "; then
            "$BIN/ares-setup-device" --modify "$DEVICE" "${info[@]}"
        else
            "$BIN/ares-setup-device" --add "$DEVICE" "${info[@]}"
        fi
        echo "Enter the passphrase shown in the TV's Developer Mode app (Key Server on)."
        "$BIN/ares-novacom" --device "$DEVICE" --getkey
        "$BIN/ares-device" --device "$DEVICE" --system-info
        ;;
    package)
        package
        ;;
    install)
        need_device
        ipk="$(package | tail -1)"
        "$BIN/ares-install" --device "$DEVICE" "$ipk"
        "$BIN/ares-launch" --device "$DEVICE" "$APP_ID"
        echo "Adaptive Home is open on the TV. The first time, choose Allow on the TV's prompt."
        ;;
    remove)
        need_device
        "$BIN/ares-install" --device "$DEVICE" --remove "$APP_ID"
        ;;
esac
