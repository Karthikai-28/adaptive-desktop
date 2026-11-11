#!/usr/bin/env bash
# Install Mario: the live Home on the desktop, the Mario panel (Super+Space) and Mario Hub.
#
#   scripts/install-mario.sh            install whatever is missing and start the hub
#   scripts/install-mario.sh --status   say what is missing; change nothing
#
# It installs: python3-aiohttp and WebKitGTK for Python (apt, asks for sudo), the
# adaptive-mario-hub user service (127.0.0.1:8791), the Mario Home autostart entry (Adaptive session
# only) and, if missing, ~/.config/adaptive-desktop/mario.json with the checkouts it finds.
# The Super+Space shortcut is in scripts/install-keybindings.sh. Optional, reported only: LOOM's
# backend (local answers with your memory), Ollama, Claude Code, the Thinking Space checkout.
# Undo with ./uninstall.sh. See docs/MARIO.md.
set -Eeuo pipefail

. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/adaptive-paths.sh"
REPO="$ADAPTIVE_REPO"
UNIT="adaptive-mario-hub.service"
UNIT_DIR="$HOME/.config/systemd/user"
AUTOSTART="$HOME/.config/autostart/adaptive-mario-home.desktop"
CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/adaptive-desktop/mario.json"

MODE=install
for arg in "$@"; do
    case "$arg" in
        --status) MODE=status ;;
        -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
    esac
done

ok() { printf '  ok       %s\n' "$*"; }
need() { printf '  needed   %s\n' "$*"; MISSING=$((MISSING + 1)); }
opt() { printf '  optional %s\n' "$*"; }
MISSING=0

webkit_pkg() {
    if python3 -c 'import gi; gi.require_version("WebKit2", "4.1")' 2>/dev/null; then echo ok
    elif python3 -c 'import gi; gi.require_version("WebKit2", "4.0")' 2>/dev/null; then echo ok
    else echo gir1.2-webkit2-4.1; fi
}

port() { python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('port',8791))" "$CONFIG" 2>/dev/null || echo 8791; }

check() {
    MISSING=0
    python3 -c 'import aiohttp' 2>/dev/null && ok "python3-aiohttp" || need "python3-aiohttp (apt)"
    [ "$(webkit_pkg)" = ok ] && ok "WebKitGTK for Python" || need "gir1.2-webkit2-4.1 (apt)"
    [ -f "$CONFIG" ] && ok "settings: $CONFIG" || need "settings file $CONFIG"
    [ -f "$UNIT_DIR/$UNIT" ] && ok "$UNIT installed" || need "$UNIT"
    systemctl --user is-active --quiet "$UNIT" 2>/dev/null && ok "Mario Hub running on 127.0.0.1:$(port)" || need "Mario Hub running"
    [ -f "$AUTOSTART" ] && ok "Mario Home starts at login (Adaptive session)" || need "Mario Home autostart entry"
    gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings 2>/dev/null | grep -q adaptive-mario \
        && ok "Super+Space opens Mario" || opt "Super+Space: run scripts/install-keybindings.sh"
    local ts
    ts="$(python3 -c "import json,os,sys;print(os.path.expanduser(json.load(open(sys.argv[1])).get('thinking_space','~/thinking-space')))" "$CONFIG" 2>/dev/null || echo "$HOME/thinking-space")"
    [ -d "$ts/boards" ] && ok "Thinking Space checkout: $ts" \
        || opt "Thinking Space checkout for the boards and reel cards: gh repo clone Karthikai-28/thinking-space $ts"
    curl -fsS -o /dev/null --max-time 2 http://127.0.0.1:8765/api/health 2>/dev/null && ok "LOOM backend answering" \
        || opt "LOOM backend (local answers with memory): cd LOOM/local-ai/app/backend && python3 -m uvicorn main:app --port 8765"
    curl -fsS -o /dev/null --max-time 2 http://127.0.0.1:11434/api/tags 2>/dev/null && ok "Ollama running" || opt "Ollama (local models)"
    command -v claude >/dev/null && ok "Claude Code for dev hand-offs" || opt "Claude Code: scripts/install-agent-office.sh installs it"
}

if [ "$MODE" = status ]; then
    check
    exit $((MISSING > 0))
fi

echo "Mario"
PKGS=()
python3 -c 'import aiohttp' 2>/dev/null || PKGS+=(python3-aiohttp)
[ "$(webkit_pkg)" = ok ] || PKGS+=("$(webkit_pkg)")
if [ "${#PKGS[@]}" -gt 0 ]; then
    echo "  installing ${PKGS[*]} (sudo)"
    sudo apt-get install -y "${PKGS[@]}"
fi

if [ ! -f "$CONFIG" ]; then
    mkdir -p "$(dirname "$CONFIG")"
    python3 - "$CONFIG" "$REPO" <<'PY'
import json, os, sys
config, repo = sys.argv[1], sys.argv[2]
home = os.path.expanduser("~")
found = [repo] + [p for p in (os.path.join(home, n) for n in ("LOOM", "loom", "thinking-space", "agent-brain"))
                  if os.path.isdir(os.path.join(p, ".git"))]
# the hub expands ~ itself; keep the file portable
repos = [("~" + p[len(home):]) if p.startswith(home + os.sep) else p for p in dict.fromkeys(found)]
json.dump({"repos": repos, "thinking_space": "~/thinking-space", "backup_at": "22:40"}, open(config, "w"), indent=2)
print(f"  wrote {config} with {len(repos)} checkout(s)")
PY
fi

chmod +x "$REPO/services/mario-hub/hub.py" "$REPO/apps/mario-home/host.py"
adaptive_record_repo
adaptive_render "$REPO/services/$UNIT" "$UNIT_DIR/$UNIT"
systemctl --user daemon-reload
systemctl --user enable --now "$UNIT" >/dev/null
systemctl --user restart "$UNIT"
adaptive_render "$REPO/apps/mario-home/adaptive-mario-home.desktop" "$AUTOSTART"

for _ in 1 2 3 4 5 6 7 8 9 10; do
    curl -fsS -o /dev/null --max-time 1 "http://127.0.0.1:$(port)/api/state" 2>/dev/null && break
    sleep 1
done
echo
check || true
echo
echo "  Home appears at the next Adaptive login, or now: $REPO/apps/mario-home/host.py &"
echo "  Super+Space opens Mario once scripts/install-keybindings.sh has run."
