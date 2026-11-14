#!/usr/bin/env bash
# Install Mario: the live Home on the desktop, the Mario panel (Super+J) and Mario Hub.
#
#   scripts/install-mario.sh             install whatever is missing and start the hub
#   scripts/install-mario.sh --status    say what is missing; change nothing
#   scripts/install-mario.sh --mail      connect a Gmail account to the Mail card (IMAP, read-only);
#                                        run it again to add another; --main makes it the main one
#   scripts/install-mario.sh --calendar  connect the Today card (your calendar's private iCal address)
#   scripts/install-mario.sh --voice     install local English speech recognition
#
# It installs: python3-aiohttp and WebKitGTK for Python (apt, asks for sudo), the
# adaptive-mario-hub user service (127.0.0.1:8791), the Mario Home autostart entry (Adaptive session
# only) and, if missing, ~/.config/adaptive-desktop/mario.json with the checkouts it finds.
# The Super+J shortcut is in scripts/install-keybindings.sh. Optional, reported only: Claude Code
# (Mario answers with Claude first), the Antigravity CLI (Gemini when Claude is at its limit), LOOM's
# backend and Ollama (answers on the laptop when neither answers), the Thinking Space checkout.
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
        --mail) MODE=mail ;;
        --main) MAKE_MAIN=yes ;;
        --calendar) MODE=calendar ;;
        --voice) MODE=voice ;;
        -h|--help) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
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
        && ok "Super+J opens Mario" || opt "Super+J: run scripts/install-keybindings.sh"
    local ts
    ts="$(python3 -c "import json,os,sys;print(os.path.expanduser(json.load(open(sys.argv[1])).get('thinking_space','~/thinking-space')))" "$CONFIG" 2>/dev/null || echo "$HOME/thinking-space")"
    [ -d "$ts/boards" ] && ok "Thinking Space checkout: $ts" \
        || opt "Thinking Space checkout for the boards and reel cards: gh repo clone Karthikai-28/thinking-space $ts"
    command -v secret-tool >/dev/null && ok "secret-tool (keyring)" || need "libsecret-tools (apt)"
    [ -d "$REPO/.local/mario-pydeps/recurring_ical_events" ] && ok "calendar packages" || need "calendar packages (pip, .local/mario-pydeps)"
    local mail_users mail_user first=yes
    mail_users="$(python3 - "$REPO/services/mario-hub" <<'PY' 2>/dev/null || true
import sys
sys.path.insert(0, sys.argv[1])
import collectors, config
print("\n".join(a["user"] for a in collectors.mail_accounts(config.load())))
PY
)"
    [ -n "$mail_users" ] || opt "Mail card: scripts/install-mario.sh --mail"
    while IFS= read -r mail_user; do
        [ -n "$mail_user" ] || continue
        local tag=""; [ "$first" = yes ] && tag=" (main)"; first=no
        if secret-tool lookup service mario-mail account "$mail_user" >/dev/null 2>&1; then ok "Mail: $mail_user$tag"
        else opt "Mail: no app password for $mail_user: scripts/install-mario.sh --mail"; fi
    done <<< "$mail_users"
    secret-tool lookup service mario-calendar account ical >/dev/null 2>&1 && ok "Calendar connected" \
        || opt "Today card: scripts/install-mario.sh --calendar"
    curl -fsS -o /dev/null --max-time 2 http://127.0.0.1:8765/api/health 2>/dev/null && ok "LOOM backend answering" \
        || opt "LOOM backend (local answers with memory): cd LOOM/local-ai/app/backend && python3 -m uvicorn main:app --port 8765"
    curl -fsS -o /dev/null --max-time 2 http://127.0.0.1:11434/api/tags 2>/dev/null && ok "Ollama running" || opt "Ollama (local models)"
    command -v claude >/dev/null && ok "Claude Code: Mario's answers and dev hand-offs" || opt "Claude Code (Mario answers with it first): scripts/install-agent-office.sh installs it"
    command -v agy >/dev/null && ok "Antigravity CLI: Gemini answers when Claude is at its limit" \
        || opt "Antigravity CLI (agy), Gemini when Claude is at its limit: curl -fsSL https://antigravity.google/cli/install.sh | bash"
}

if [ "$MODE" = status ]; then
    check
    exit $((MISSING > 0))
fi

if [ "$MODE" = voice ]; then
    exec "$REPO/scripts/install-mario-voice.sh"
fi

if [ "$MODE" = mail ]; then
    command -v secret-tool >/dev/null || sudo apt-get install -y libsecret-tools
    cat <<'TXT'
Mail card: unread mail from your Gmail inboxes, read over IMAP with a Google app password.
It only reads headers (from, subject, date) and never marks anything read. Each run adds one
account (or saves a new password for one you have); the main account is the one Home shows first.

  1. Gmail settings > Forwarding and POP/IMAP: IMAP is on.
  2. https://myaccount.google.com/apppasswords (needs 2-Step Verification): create one named "Mario".
  3. Paste it below. It goes into your GNOME keyring only; nothing writes it to a file.
TXT
    read -r -p "Gmail address: " ADDR
    ADDR="$(printf '%s' "$ADDR" | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')"
    [ -n "$ADDR" ] || { echo "No address; nothing changed."; exit 1; }
    if [ -z "${MAKE_MAIN:-}" ]; then
        read -r -p "Make $ADDR the main account (shown first on Home)? [Y/n] " yn
        case "$yn" in [Nn]*) MAKE_MAIN=no ;; *) MAKE_MAIN=yes ;; esac
    fi
    secret-tool store --label="Mario mail $ADDR (IMAP app password)" service mario-mail account "$ADDR"
    python3 - "$CONFIG" "$ADDR" "$MAKE_MAIN" <<'PY'
import json, sys, os
path, addr, main = sys.argv[1], sys.argv[2], sys.argv[3] == "yes"
os.makedirs(os.path.dirname(path), exist_ok=True)
try:
    cfg = json.load(open(path))
except (OSError, ValueError):
    cfg = {}
mail = dict(cfg.get("mail") or {})
accounts = [a for a in mail.get("accounts") or [] if a]
if mail.get("user"):                      # the older one-account form becomes the account list
    accounts.append(mail.pop("user"))
names = [(a.get("user") if isinstance(a, dict) else a) for a in accounts]
if addr.lower() not in [str(n).lower() for n in names]:
    accounts.append(addr)
mail["accounts"] = accounts
mail.setdefault("imap_host", "imap.gmail.com")
if main or not mail.get("main"):
    mail["main"] = addr if main else (names[0] if names else addr)
cfg["mail"] = mail
json.dump(cfg, open(path, "w"), indent=2)
print(f"Accounts: {', '.join(str(a.get('user') if isinstance(a, dict) else a) for a in accounts)}; main: {mail['main']}")
PY
    # Try the login now, so a Google account password (which Gmail refuses over IMAP) is caught
    # here and not as an error on Home. Nothing about the password is printed.
    if ! python3 - "$REPO/services/mario-hub" "$ADDR" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
import collectors, config
addr = sys.argv[2]
host = next((a["imap_host"] for a in collectors.mail_accounts(config.load()) if a["user"] == addr), "imap.gmail.com")
out = collectors.mail_account(addr, host)
if out.get("unread") is None:
    print("Not connected: " + out.get("error", "unknown error"))
    if out.get("fix") == "app_password":
        print("That was your Google password. Make an app password at")
        print("  https://myaccount.google.com/apppasswords  and run this again with it.")
    sys.exit(1)
print(f"Mail connected ({addr}): {out['unread']} unread.")
PY
    then
        systemctl --user restart "$UNIT" 2>/dev/null || true
        exit 1
    fi
    systemctl --user restart "$UNIT" 2>/dev/null || true
    exit 0
fi

if [ "$MODE" = calendar ]; then
    command -v secret-tool >/dev/null || sudo apt-get install -y libsecret-tools
    cat <<'TXT'
Today card: today's events, read-only, from your calendar's private iCal address.

  1. Google Calendar (web) > Settings > your calendar > Integrate calendar.
  2. Copy "Secret address in iCal format".
  3. Paste it below. It goes into your GNOME keyring only. Anyone with that address can read
     the calendar, so it is never written to a file, a log or the hub's state.
TXT
    secret-tool store --label="Mario calendar (secret iCal address)" service mario-calendar account ical
    # Fetch it once now, so a wrong address shows here; the address itself is never printed.
    if ! python3 - "$REPO/services/mario-hub" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
import collectors, config
out = collectors.calendar(config.load())
if out.get("error"):
    print("Not connected: " + out["error"])
    sys.exit(1)
print(f"Calendar connected: {len(out.get('events') or [])} event(s) today.")
PY
    then
        systemctl --user restart "$UNIT" 2>/dev/null || true
        exit 1
    fi
    systemctl --user restart "$UNIT" 2>/dev/null || true
    exit 0
fi

echo "Mario"
PKGS=()
python3 -c 'import aiohttp' 2>/dev/null || PKGS+=(python3-aiohttp)
[ "$(webkit_pkg)" = ok ] || PKGS+=("$(webkit_pkg)")
command -v secret-tool >/dev/null || PKGS+=(libsecret-tools)
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

if [ ! -d "$REPO/.local/mario-pydeps/recurring_ical_events" ]; then
    echo "  installing calendar packages into .local/mario-pydeps"
    python3 -m pip install --quiet --upgrade --target "$REPO/.local/mario-pydeps" icalendar recurring-ical-events \
        || echo "  (calendar packages failed; the Today card still shows one-off events)"
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
echo "  Super+J opens Mario once scripts/install-keybindings.sh has run."
echo "  Connect Mail and Today: scripts/install-mario.sh --mail, then --calendar."
