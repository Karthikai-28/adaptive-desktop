#!/usr/bin/env bash
# Give Adaptive Link its own Tailscale node, so the phone reaches this
# computer by name from any network. No sudo: it runs as you, in userspace,
# beside (not instead of) any system Tailscale.
#
#   install-link-tailnet.sh            install, start, and sign in if needed
#   install-link-tailnet.sh --status   who is on the network
#   install-link-tailnet.sh --remove   stop and sign this computer out
#
# Signing in prints a link to open in a browser. Use the same account in the
# Tailscale app on the phone.
set -Eeuo pipefail
REPO="${ADAPTIVE_REPO:-$HOME/adaptive-desktop}"
UNIT_DIR="$HOME/.config/systemd/user"
SOCKET="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/adaptive-tailnet.sock"
ts() { tailscale --socket="$SOCKET" "$@"; }

if ! command -v tailscaled >/dev/null; then
    echo "Tailscale is not installed (https://tailscale.com/download/linux)." >&2
    exit 1
fi

case "${1:-}" in
    --status)
        ts status
        exit 0
        ;;
    --remove)
        ts logout 2>/dev/null || true
        systemctl --user disable --now adaptive-tailnet.service 2>/dev/null || true
        rm -f "$UNIT_DIR/adaptive-tailnet.service"
        systemctl --user daemon-reload
        echo "This computer's link node is signed out and stopped."
        exit 0
        ;;
esac

mkdir -p "$UNIT_DIR" "$HOME/.local/state/adaptive-desktop/tailnet"
chmod 700 "$HOME/.local/state/adaptive-desktop/tailnet"
install -m 0644 "$REPO/services/adaptive-tailnet.service" "$UNIT_DIR/"
systemctl --user daemon-reload
systemctl --user enable --now adaptive-tailnet.service
for _ in $(seq 1 20); do
    [ -S "$SOCKET" ] && break
    sleep 0.5
done

if ts status >/dev/null 2>&1; then
    echo "Signed in:"
    ts status | head -5
else
    # Prints a link to open; returns once the sign-in is done.
    ts up --qr=false --hostname="$(hostname)-link" --accept-dns=false
fi
# So the node keeps running after you log out of the desktop.
loginctl enable-linger "$USER" 2>/dev/null || true
systemctl --user restart adaptive-link.service 2>/dev/null || true
