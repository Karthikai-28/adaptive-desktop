#!/usr/bin/env bash
# Install and start Agent Office: a pixel office where Gemini agents (through agy, on the owner's
# Google AI Pro plan) do the work and Claude manages them. One command on a fresh machine:
#
#   scripts/install-agent-office.sh              install whatever is missing, start it, print the URL
#   scripts/install-agent-office.sh --autostart  also start it at every login
#   scripts/install-agent-office.sh --open       open it in the browser when done
#   scripts/install-agent-office.sh --status     say what is missing; change nothing
#
# It installs: bubblewrap (apt, asks for sudo), the Python packages (into .local/office-pydeps),
# the agy and claude command-line tools (their official installers), the `office` command, and the
# adaptive-agent-office user service. The two sign-ins it cannot do for you - Google for agy and
# Anthropic for claude - it checks and tells you how to do.
#
# What the office produces lives in ~/.local/share/adaptive-desktop/agent-office, outside the repo.
# Undo with ./uninstall.sh (your office data stays). See docs/AGENT_OFFICE.md.
set -Eeuo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$REPO/services/agent-office"
PYDEPS="$REPO/.local/office-pydeps"
UNIT="adaptive-agent-office.service"
UNIT_DIR="$HOME/.config/systemd/user"
BIN="$HOME/.local/bin"
PORT="$(python3 -c "import json;print(json.load(open('$APP/config.json'))['port'])")"
MODEL="$(python3 -c "import json;print(json.load(open('$APP/config.json'))['gemini_model'])")"
PY_MODULES="fastapi uvicorn websockets pydantic edge_tts"
PY_PACKAGES="fastapi>=0.110 uvicorn>=0.29 websockets>=12 pydantic>=2 edge-tts>=6.1"

MODE=install; AUTOSTART=0; OPEN=0
for arg in "$@"; do
    case "$arg" in
        --status) MODE=status ;;
        --autostart) AUTOSTART=1 ;;
        --open) OPEN=1 ;;
        -h|--help) sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
    esac
done
export PATH="$BIN:$HOME/bin:$PATH"

ok() { printf '  ok       %s\n' "$*"; }
need() { printf '  needed   %s\n' "$*"; MISSING=$((MISSING + 1)); }
MISSING=0

have_py() { PYTHONPATH="$PYDEPS" python3 -c "import ${PY_MODULES// /, }" 2>/dev/null; }
agy_signed_in() { agy models 2>/dev/null | grep -q '^gemini-'; }
claude_signed_in() { claude auth status --json 2>/dev/null | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("loggedIn") else 1)' 2>/dev/null; }
server_up() { curl -fsS -o /dev/null "http://127.0.0.1:$PORT/api/state" 2>/dev/null; }

check() {
    MISSING=0
    command -v bwrap >/dev/null && ok "bubblewrap (agent sandbox)" || need "bubblewrap: sudo apt install bubblewrap"
    have_py && ok "Python packages" || need "Python packages ($PY_PACKAGES)"
    command -v agy >/dev/null && ok "agy $(agy --version 2>/dev/null)" || need "agy (Antigravity CLI)"
    if command -v agy >/dev/null; then
        if agy_signed_in; then
            agy models 2>/dev/null | grep -q "^$MODEL\b" && ok "agy signed in, $MODEL available" ||
                need "$MODEL is not offered to this account (agy models lists what is; set gemini_model in $APP/config.json)"
        else need "agy sign-in: run 'agy' once and sign in with the Google account that has AI Pro"; fi
    fi
    command -v claude >/dev/null && ok "claude $(claude --version 2>/dev/null | cut -d' ' -f1)" || need "claude (Claude Code CLI)"
    if command -v claude >/dev/null; then
        claude_signed_in && ok "claude signed in" || need "claude sign-in: run 'claude' once and log in"
    fi
    command -v edge-tts >/dev/null || PYTHONPATH="$PYDEPS" python3 -c "import edge_tts" 2>/dev/null &&
        ok "voices (edge-tts)" || need "edge-tts (agent voices)"
    [ -x "$BIN/office" ] && ok "office command" || need "office command in $BIN"
    [ -f "$UNIT_DIR/$UNIT" ] && ok "user service installed" || need "user service $UNIT"
    server_up && ok "running at http://127.0.0.1:$PORT" || need "the office is not running"
}

if [ "$MODE" = status ]; then
    check
    [ "$MISSING" = 0 ] && echo "Agent Office is installed and running." || echo "$MISSING thing(s) missing: scripts/install-agent-office.sh"
    exit 0
fi

echo "== system packages"
if ! command -v bwrap >/dev/null || ! command -v curl >/dev/null || ! python3 -m pip --version >/dev/null 2>&1; then
    pkgs=(); command -v bwrap >/dev/null || pkgs+=(bubblewrap); command -v curl >/dev/null || pkgs+=(curl)
    python3 -m pip --version >/dev/null 2>&1 || command -v uv >/dev/null || pkgs+=(python3-pip)
    if [ "${#pkgs[@]}" != 0 ]; then
        echo "   installing ${pkgs[*]} (sudo)"
        sudo apt-get install -y "${pkgs[@]}"
    fi
fi
echo "   ok"

echo "== Python packages"
if ! have_py; then
    mkdir -p "$PYDEPS"
    if python3 -m pip --version >/dev/null 2>&1; then
        # shellcheck disable=SC2086 # one word per package
        python3 -m pip install --quiet --upgrade --target "$PYDEPS" $PY_PACKAGES
    else
        # shellcheck disable=SC2086
        uv pip install --quiet --python python3 --target "$PYDEPS" $PY_PACKAGES
    fi
fi
have_py || { echo "   could not import: $PY_MODULES (PYTHONPATH=$PYDEPS)" >&2; exit 1; }
echo "   ok ($PYDEPS)"

echo "== agy (Antigravity CLI, the Gemini agents)"
if ! command -v agy >/dev/null; then
    curl -fsSL https://antigravity.google/cli/install.sh | bash
    hash -r
fi
command -v agy >/dev/null || { echo "   agy did not install; see https://antigravity.google" >&2; exit 1; }
echo "   ok ($(command -v agy))"

echo "== claude (Claude Code, the manager)"
if ! command -v claude >/dev/null; then
    curl -fsSL https://claude.ai/install.sh | bash
    hash -r
fi
command -v claude >/dev/null || { echo "   claude did not install; see https://docs.claude.com/claude-code" >&2; exit 1; }
echo "   ok ($(command -v claude))"

echo "== office command"
mkdir -p "$BIN"
ln -sfn "$APP/bin/office" "$BIN/office"
echo "   ok ($BIN/office)"

echo "== user service"
mkdir -p "$UNIT_DIR"
# the unit names the repo by its usual place; point it at wherever this checkout really is
sed "s|%h/adaptive-desktop|$REPO|g" "$REPO/services/$UNIT" > "$UNIT_DIR/$UNIT"
chmod 0644 "$UNIT_DIR/$UNIT"
systemctl --user daemon-reload
if [ "$AUTOSTART" = 1 ]; then systemctl --user enable "$UNIT" >/dev/null 2>&1; echo "   starts at login"; fi
systemctl --user restart "$UNIT"
for _ in $(seq 1 30); do server_up && break; sleep 0.5; done
server_up || { echo "   the service did not come up:" >&2; journalctl --user -u "$UNIT" -n 30 --no-pager >&2; exit 1; }
echo "   running at http://127.0.0.1:$PORT"

echo
echo "== check"
check
echo
if [ "$MISSING" = 0 ]; then
    echo "Agent Office is ready: http://127.0.0.1:$PORT  (Chrome for voice input)"
else
    echo "Installed. $MISSING thing(s) above still need you - usually the two sign-ins:"
    echo "  agy      run 'agy', sign in with the Google account that has AI Pro, then quit it"
    echo "  claude   run 'claude' and log in"
    echo "Then: scripts/install-agent-office.sh --status"
fi
[ "$OPEN" = 1 ] && { xdg-open "http://127.0.0.1:$PORT" >/dev/null 2>&1 || true; }
exit 0
