#!/usr/bin/env bash
#
# Set up Adaptive Desktop on a fresh Ubuntu 22.04 machine - everything, from
# the apt packages to the phone - in one command. install.sh keeps an
# installed machine current; this is the step before it, for a computer that
# has never had any of it.
#
#   git clone https://github.com/Karthikai-28/adaptive-desktop.git ~/adaptive-desktop
#   ~/adaptive-desktop/bootstrap.sh
#
#   ./bootstrap.sh                    run every stage (asks for sudo once)
#   ./bootstrap.sh --restore FILE     also bring settings from the old machine
#                                     (made there with scripts/adaptive-backup.py export)
#   ./bootstrap.sh --link-cloud FILE  the Adaptive Link Google project's five values
#                                     (link-cli.py setup FILE) for pairing away from home
#   ./bootstrap.sh --skip A,B         leave stages out (see --list); e.g. --skip ollama,terminal
#   ./bootstrap.sh --only NAME        one stage
#   ./bootstrap.sh --redo             run stages again that already finished
#   ./bootstrap.sh --status           what has run, and install.sh --status
#   ./bootstrap.sh --list             the stages, in order
#   ./bootstrap.sh --finish           the last part, run at the first Adaptive Desktop
#                                     login: sign-ins, pairing the phone, checks
#
# Every stage is safe to run again. A stage that finished is skipped on the
# next run unless --redo is given; one that failed is tried again. The normal
# Ubuntu session is never changed: Adaptive's GNOME settings are written to
# the Adaptive session's own dconf database, and stock Nautilus stays.
# Log: ~/.local/state/adaptive-desktop/bootstrap.log. Guide: docs/NEW_MACHINE.md.
set -Euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$HOME/adaptive-desktop"
S="$REPO/scripts"
STATE="$HOME/.local/state/adaptive-desktop/bootstrap"
LOG="$HOME/.local/state/adaptive-desktop/bootstrap.log"
UUID="adaptive-shell@local"
HOOK="$HOME/.config/autostart/adaptive-first-login.desktop"
LINK_DIR="$HOME/.config/adaptive-desktop/link"

# name | what it is | optional (can be skipped and fails softly)
STAGES=(
    "preflight|Check the machine: Ubuntu 22.04, GNOME 42, disk, network|no"
    "packages|System packages (apt), including GNOME if it is missing|no"
    "groups|plugdev and input groups (USB switches, touchpad gestures)|no"
    "python|Python packages the link needs for video and away access|no"
    "terminal|KTERM: Terminator, Zsh and the Nerd Font|yes"
    "files-fork|Build the Adaptive Files fork of Nautilus 42.6 (10-20 min)|yes"
    "session|The Adaptive Desktop login session (GDM entry, own dconf profile)|no"
    "restore|Settings from the old machine (--restore FILE)|yes"
    "desktop|Shell, theme, shortcuts, apps, services, Files, Link, Agent Office|no"
    "gnome|Turn the shell on and Ubuntu Dock off, in the Adaptive session only|no"
    "link-extras|Phone as webcam, extra display, drawing pen, USB switches|yes"
    "link-cloud|Adaptive Link's Google project (--link-cloud FILE)|yes"
    "ollama|Ollama and the Agent Office's local model|yes"
    "tailscale|Tailscale (the network tile in Control Center)|yes"
    "first-login|Finish setup at the first Adaptive Desktop login|no"
)

MODE=run
ONLY=""
SKIP=","
REDO=0
RESTORE=""
LINK_CLOUD=""
while [ $# -gt 0 ]; do
    case "$1" in
        --status) MODE=status ;;
        --list) MODE=list ;;
        --finish) MODE=finish ;;
        --first-login) MODE=first-login ;;
        --redo) REDO=1 ;;
        --only) ONLY="${2:-}"; shift ;;
        --skip) SKIP=",${2:-},"; shift ;;
        --restore) RESTORE="$(realpath -m "${2:-}")"; shift ;;
        --link-cloud) LINK_CLOUD="$(realpath -m "${2:-}")"; shift ;;
        -h|--help) sed -n '2,29p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
    esac
    shift
done

# ---------------------------------------------------------------- helpers

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
note() { printf '   %s\n' "$*"; }
warn() { printf '   \033[33m! %s\033[0m\n' "$*"; }
die() { printf '\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }
mark() { mkdir -p "$STATE"; date -Is > "$STATE/$1.done"; }
is_done() { [ -f "$STATE/$1.done" ]; }

in_adaptive_session() {
    [ "${DCONF_PROFILE:-}" = adaptive ] || [ "${GDMSESSION:-}" = adaptive-desktop ] ||
        [ "${XDG_SESSION_DESKTOP:-}" = adaptive-desktop ]
}

# gsettings for the Adaptive session's own database. dconf picks the database
# from DCONF_PROFILE, so this works from any session once the session stage
# has put /etc/dconf/profile/adaptive in place - and the normal Ubuntu
# session's settings are never touched.
adaptive_gsettings() { DCONF_PROFILE=adaptive gsettings "$@"; }

# Add one entry to a string-list setting, keeping what is there.
list_add() {
    local schema="$1" key="$2" value="$3"
    DCONF_PROFILE=adaptive python3 - "$schema" "$key" "$value" <<'PY'
import ast, subprocess, sys
schema, key, value = sys.argv[1:]
raw = subprocess.check_output(["gsettings", "get", schema, key], text=True).strip()
raw = raw[4:] if raw.startswith("@as ") else raw
values = list(ast.literal_eval(raw))
if value not in values:
    values.append(value)
    subprocess.run(["gsettings", "set", schema, key, repr(values)], check=True)
PY
}

list_remove() {
    local schema="$1" key="$2" value="$3"
    DCONF_PROFILE=adaptive python3 - "$schema" "$key" "$value" <<'PY'
import ast, subprocess, sys
schema, key, value = sys.argv[1:]
raw = subprocess.check_output(["gsettings", "get", schema, key], text=True).strip()
raw = raw[4:] if raw.startswith("@as ") else raw
values = list(ast.literal_eval(raw))
if value in values:
    subprocess.run(["gsettings", "set", schema, key, repr([v for v in values if v != value])], check=True)
PY
}

apt_install() {
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "$@"
}

ask_yes() {  # ask_yes "question" -> 0 for yes; default no; no terminal means no
    local answer
    [ -t 0 ] || return 1
    read -r -p "   $1 [y/N] " answer
    [[ "$answer" =~ ^[Yy] ]]
}

secure_boot_on() { mokutil --sb-state 2>/dev/null | grep -qi 'SecureBoot enabled'; }

# ----------------------------------------------------------------- stages

stage_preflight() {
    [ "$EUID" -ne 0 ] || die "Run this as your normal user, not with sudo. It asks for sudo itself."
    # shellcheck disable=SC1091
    . /etc/os-release
    [ "${VERSION_ID:-}" = "22.04" ] || [ -n "${ADAPTIVE_ALLOW_OS_OVERRIDE:-}" ] ||
        die "This is $PRETTY_NAME. Adaptive Desktop runs on Ubuntu 22.04 only (GNOME 42, X11); install 22.04 first (docs/NEW_MACHINE.md)."
    note "$PRETTY_NAME, $(uname -m)"
    [ "$(uname -m)" = x86_64 ] || die "x86_64 only (the Files fork and its extensions are built for it)."

    if command -v gnome-shell >/dev/null; then
        local shell_version
        shell_version="$(gnome-shell --version 2>/dev/null | awk '{print $3}')"
        note "GNOME Shell $shell_version"
        [[ "$shell_version" == 42.* ]] || die "GNOME Shell 42 is needed; this has $shell_version."
    else
        note "GNOME Shell is not installed yet; the packages stage installs it."
    fi

    local free_gb
    free_gb=$(( $(df --output=avail / | tail -1 | tr -d ' ') / 1024 / 1024 ))
    note "about $free_gb GB free"
    [ "$free_gb" -ge 30 ] || die "Needs at least 30 GB free on / (the session installer alone refuses below 25)."

    systemctl --user show-environment >/dev/null 2>&1 ||
        die "No user session manager here. Run this from a terminal in your desktop (not through su or a bare SSH login)."

    curl -fsS -o /dev/null --max-time 15 http://archive.ubuntu.com/ubuntu/ ||
        die "Cannot reach archive.ubuntu.com; connect to the internet first."
    note "network ok"

    # Every script finds the repo at ~/adaptive-desktop (the systemd units say
    # %h/adaptive-desktop), so a checkout elsewhere gets that name as a link.
    if [ "$HERE" != "$REPO" ]; then
        if [ -L "$REPO" ] && [ "$(readlink -f "$REPO")" = "$HERE" ]; then
            note "$REPO -> $HERE"
        elif [ -e "$REPO" ]; then
            die "$REPO exists and is not this checkout ($HERE). Move one of them."
        else
            ln -s "$HERE" "$REPO"
            note "linked $REPO -> $HERE"
        fi
    fi
    note "Secure Boot: $(secure_boot_on && echo on || echo 'off or unknown')"
}

PACKAGES=(
    # tools the shell, palette, link and scripts call
    git curl rsync unzip openssl sqlite3 xdotool xclip wmctrl x11-utils x11-xserver-utils xauth
    libinput-tools plocate lm-sensors zenity libnotify-bin imagemagick qrencode adb bluez
    dconf-cli desktop-file-utils gnome-terminal nautilus nautilus-extension-gnome-terminal
    gnome-shell-extension-prefs tesseract-ocr tesseract-ocr-eng fonts-inter mokutil
    libgdk-pixbuf2.0-bin ffmpegthumbnailer evince
    # phone apps run in a private display of their own
    xvfb xfwm4 dbus
    # Python, and the GObject libraries the apps import
    python3 python3-pip python3-gi python3-gi-cairo python3-cairo python3-pil python3-numpy
    python3-aiohttp python3-cryptography python3-nautilus
    gir1.2-gtk-3.0 gir1.2-gtk-4.0 gir1.2-gdkpixbuf-2.0 gir1.2-gnomedesktop-3.0 gir1.2-gtksource-4
    gir1.2-handy-1 gir1.2-secret-1 gir1.2-vte-2.91 gir1.2-nm-1.0 gir1.2-nautilus-3.0
    gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0
    gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-pulseaudio gstreamer1.0-tools gstreamer1.0-x
    # Agent Office's sandbox
    bubblewrap
)

stage_packages() {
    note "enabling the universe component"
    sudo add-apt-repository -y universe >/dev/null 2>&1 || apt_install software-properties-common
    sudo add-apt-repository -y universe >/dev/null
    sudo apt-get update -q
    if ! command -v gnome-shell >/dev/null || ! [ -f /usr/share/xsessions/ubuntu.desktop ]; then
        note "installing the Ubuntu GNOME desktop"
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y ubuntu-desktop-minimal gdm3
    fi
    apt_install "${PACKAGES[@]}"
    # Kernel headers for the link's camera and display modules (dkms).
    apt_install "linux-headers-$(uname -r)" 2>/dev/null || warn "no headers for $(uname -r); the camera and display modules may not build"
    sudo updatedb 2>/dev/null || true
    [[ "$(gnome-shell --version | awk '{print $3}')" == 42.* ]] || die "GNOME Shell is not 42 after installing."
}

stage_groups() {
    local group changed=0
    for group in plugdev input; do
        if id -nG "$USER" | tr ' ' '\n' | grep -qx "$group"; then
            note "already in $group"
        else
            sudo usermod -aG "$group" "$USER"
            note "added to $group (takes effect at the next login)"
            changed=1
        fi
    done
    [ "$changed" = 0 ] || note "input lets the gesture service read the touchpad (docs/ADAPTIVE_LINK.md explains why the pen does not use it)"
}

stage_python() {
    local pydeps="$REPO/.local/link-pydeps"
    if PYTHONPATH="$pydeps" python3 -c "import aiortc, av" 2>/dev/null; then
        note "aiortc already in $pydeps"
    else
        mkdir -p "$pydeps"
        python3 -m pip install --quiet --upgrade --target "$pydeps" aiortc
        PYTHONPATH="$pydeps" python3 -c "import aiortc, av" || die "aiortc did not install"
        note "aiortc (screen as video, away access) in $pydeps"
    fi
    python3 -c "import aiohttp, cryptography" || die "aiohttp and cryptography are missing (packages stage)"
}

stage_terminal() {
    bash "$REPO/terminal/install-kterm-ubuntu.sh"
}

stage_files_fork() {
    if [ -x "$REPO/.local/adaptive-nautilus/bin/nautilus" ] && [ "$REDO" = 0 ]; then
        note "the fork is already built"
    else
        # apt-get source needs the source repositories.
        if ! grep -RhsE '^[[:space:]]*deb-src[[:space:]]+' /etc/apt/sources.list /etc/apt/sources.list.d | grep -q .; then
            note "enabling Ubuntu's source repositories (deb-src)"
            sudo cp -a /etc/apt/sources.list "/etc/apt/sources.list.before-adaptive"
            sudo sed -i -E 's/^#[[:space:]]*deb-src[[:space:]]/deb-src /' /etc/apt/sources.list
            if ! grep -RhsE '^[[:space:]]*deb-src[[:space:]]+' /etc/apt/sources.list /etc/apt/sources.list.d | grep -q .; then
                grep -E '^[[:space:]]*deb[[:space:]]' /etc/apt/sources.list | sed -E 's/^([[:space:]]*)deb /\1deb-src /' |
                    sudo tee /etc/apt/sources.list.d/adaptive-deb-src.list >/dev/null
            fi
        fi
        "$S/install-nautilus-build-deps.sh"
        "$S/prepare-nautilus-fork.sh"
        "$S/build-nautilus-fork.sh"
    fi
    # Installs into the repo's .local prefix only, and links the system's
    # Open in Terminal and nautilus-python extensions into it.
    "$S/install-nautilus-fork-local.sh"
    "$S/install-files-session-integration.sh"
}

stage_session() {
    "$S/install-adaptive-session.sh"
    [ -f /etc/dconf/profile/adaptive ] || die "the Adaptive dconf profile was not installed"
}

stage_restore() {
    if [ -z "$RESTORE" ]; then
        note "nothing to restore (--restore FILE brings the old machine's settings)"
        return 0
    fi
    [ -f "$RESTORE" ] || die "no such file: $RESTORE"
    DCONF_PROFILE=adaptive "$S/adaptive-backup.py" import "$RESTORE"
}

stage_desktop() {
    # The theme, wallpaper and shortcut installers write GNOME settings; with
    # DCONF_PROFILE=adaptive those land in the Adaptive session's database,
    # exactly as if they were run from inside it.
    export DCONF_PROFILE=adaptive
    local failed=0
    "$REPO/install.sh" || failed=1
    # Starts at every login, so the office is there when the desktop is.
    "$S/install-agent-office.sh" --autostart || failed=1

    # The lid watcher (docs/POWER_POLICY.md): lock, then sleep, when the lid
    # closes - GNOME does neither while an external display is attached.
    mkdir -p "$HOME/.config/autostart"
    sed "s|/home/karthi/adaptive-desktop|$REPO|g" "$REPO/services/adaptive-lid-watch.desktop" \
        > "$HOME/.config/autostart/adaptive-lid-watch.desktop"
    note "lid watcher set to start at login"
    unset DCONF_PROFILE
    return "$failed"
}

stage_gnome() {
    list_add org.gnome.shell enabled-extensions "$UUID"
    list_remove org.gnome.shell disabled-extensions "$UUID"
    # Adaptive has its own dock. Ubuntu Dock stays installed and stays on in
    # the normal Ubuntu session.
    list_add org.gnome.shell disabled-extensions "ubuntu-dock@ubuntu.com"
    adaptive_gsettings set org.gnome.shell disable-user-extensions false
    note "in the Adaptive session: $UUID on, Ubuntu Dock off"
    note "enabled: $(adaptive_gsettings get org.gnome.shell enabled-extensions)"
    note "normal Ubuntu session unchanged: $(gsettings get org.gnome.shell enabled-extensions)"
}

stage_link_extras() {
    local failed=0
    if secure_boot_on; then
        warn "Secure Boot is on. The camera and display modules need a key enrolled once:"
        warn "apt will ask you to choose a password now; at the next reboot a blue"
        warn "'Perform MOK management' screen asks for it - choose Enroll MOK, Continue, Yes."
    fi
    # These run on the terminal itself (no log) so apt's Secure Boot questions can be answered.
    "$S/install-link-pen.sh" || { warn "pen: failed"; failed=1; }
    "$S/install-link-usb.sh" || { warn "USB switches: failed (needs the plugdev group from the groups stage, after a re-login)"; failed=1; }
    "$S/install-link-camera.sh" || { warn "phone camera: failed"; failed=1; }
    "$S/install-link-display.sh" || { warn "extra display: failed (often Secure Boot; it works after the reboot's key enrollment)"; failed=1; }
    return "$failed"
}

stage_link_cloud() {
    if [ -f "$LINK_DIR/cloud.json" ] && [ -z "$LINK_CLOUD" ]; then
        note "the Google project is set already (restored or set before)"
        return 0
    fi
    if [ -z "$LINK_CLOUD" ]; then
        note "no Google project given: pairing works by QR code on the same network."
        note "for away-from-home pairing later: scripts/link-cli.py setup FILE, then link-cli.py signin"
        return 0
    fi
    [ -f "$LINK_CLOUD" ] || die "no such file: $LINK_CLOUD"
    systemctl --user start adaptive-link.service 2>/dev/null || true
    sleep 1
    "$S/link-cli.py" setup "$LINK_CLOUD"
}

stage_ollama() {
    if ! command -v ollama >/dev/null; then
        curl -fsSL https://ollama.com/install.sh | sh
    fi
    local model
    model="$(python3 -c "import json;c=json.load(open('$REPO/services/agent-office/config.json'));print(next((p['model'] for p in c.get('providers',{}).values() if p['engine']=='ollama'),''))")"
    [ -n "$model" ] || { note "no local model in the office's config"; return 0; }
    for _ in $(seq 1 20); do curl -fsS -o /dev/null http://127.0.0.1:11434/api/version && break; sleep 1; done
    ollama pull "$model"
    note "local model $model ready"
}

stage_tailscale() {
    if ! command -v tailscale >/dev/null; then
        curl -fsSL https://tailscale.com/install.sh | sh
    fi
    note "installed; sign in during the first login (or: sudo tailscale up)"
}

stage_first_login() {
    mkdir -p "$(dirname "$HOOK")"
    cat > "$HOOK" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Finish Adaptive Desktop setup
Comment=Sign-ins, pairing the phone and checks; removes itself when done
Exec=$REPO/bootstrap.sh --first-login
NoDisplay=true
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=8
DESKTOP
    note "at the first Adaptive Desktop login a terminal opens to finish (it runs in no other session)"
}

# ----------------------------------------------------------- first login

first_login() {
    # Autostart entries run in every GNOME session; this one acts only in Adaptive.
    in_adaptive_session || exit 0
    exec gnome-terminal --title="Finish Adaptive Desktop setup" --wait -- \
        bash -c "'$REPO/bootstrap.sh' --finish; echo; read -r -p 'Press Enter to close. ' _"
}

finish() {
    in_adaptive_session || die "Run --finish from inside Adaptive Desktop (pick it with the gear on the login screen)."
    bold "Finishing Adaptive Desktop setup"
    echo

    bold "== services in this session"
    systemctl --user import-environment DISPLAY XAUTHORITY 2>/dev/null || true
    systemctl --user restart adaptive-link.service 2>/dev/null && note "Adaptive Link restarted with this display" ||
        warn "Adaptive Link did not start: journalctl --user -u adaptive-link -n 30"
    gnome-extensions info "$UUID" 2>/dev/null | grep -q 'State: ENABLED' && note "shell extension running" ||
        warn "shell extension not running yet: gnome-extensions enable $UUID, then log out and in"
    echo

    bold "== sign-ins (each needs you once)"
    export PATH="$HOME/.local/bin:$PATH"
    if command -v claude >/dev/null; then
        if claude auth status --json 2>/dev/null | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("loggedIn") else 1)' 2>/dev/null; then
            note "claude: signed in"
        elif ask_yes "Sign in to Claude Code now (the Agent Office's manager)?"; then
            claude auth login || claude || true
        fi
    fi
    if command -v agy >/dev/null; then
        if agy models 2>/dev/null | grep -q '^gemini-'; then
            note "agy: signed in"
        elif ask_yes "Sign in to agy now (Gemini agents; the Google account with AI Pro)? Quit it once signed in."; then
            agy || true
        fi
    fi
    if command -v tailscale >/dev/null; then
        if tailscale status >/dev/null 2>&1; then
            note "tailscale: connected"
        elif ask_yes "Connect this machine to your tailnet now?"; then
            sudo tailscale up || true
        fi
    fi
    if ! command -v codex >/dev/null; then
        note "optional: the Codex CLI (the office's first backup) is not installed; see docs/AGENT_OFFICE.md"
    fi
    echo

    bold "== your phone"
    local phones=0
    [ -s "$LINK_DIR/phones.json" ] && phones="$(python3 -c "import json;print(len(json.load(open('$LINK_DIR/phones.json'))['phones']))" 2>/dev/null || echo 0)"
    if [ "$phones" -gt 0 ]; then
        note "$phones device(s) paired already"
    else
        if [ -f "$LINK_DIR/cloud.json" ] && ask_yes "Sign this computer in to your Google account (pairing from anywhere)?"; then
            "$S/link-cli.py" signin || true
        fi
        if ask_yes "Pair your phone now? Open Adaptive Link on it, + (add computer), Scan pairing code."; then
            "$S/link-cli.py" pair || true
            note "when both screens show the same six digits, press Pair on this computer"
            read -r -p "   Press Enter once the phone shows it is connected. " _
        fi
    fi
    if ! is_done link-extras && ask_yes "Set up the phone's camera, display, pen and USB switches again? (they failed before the reboot)"; then
        stage_link_extras && mark link-extras
        systemctl --user restart adaptive-link.service 2>/dev/null || true
    fi
    if [ -s "$LINK_DIR/phones.json" ] && ! grep -q link-approve /etc/pam.d/sudo 2>/dev/null; then
        if ask_yes "Let your phone's fingerprint approve sudo here (password still works)?"; then
            "$S/install-link-sudo.sh" || true
        fi
    fi
    "$S/link-cli.py" status 2>/dev/null | sed 's/^/   /' || true
    echo

    bold "== checks"
    "$REPO/install.sh" --status
    echo
    "$S/verify-live-readiness.sh" 2>&1 | tail -15 || true
    echo

    rm -f "$HOOK"
    mark finish
    bold "Adaptive Desktop is set up."
    note "Alt+Space  command palette      Super+/  every shortcut"
    note "Agent Office  http://127.0.0.1:8790"
    note "Normal Ubuntu is still on the login screen's gear menu if anything misbehaves."
    note "Run '$REPO/bootstrap.sh --finish' again any time to redo this part."
}

# ------------------------------------------------------------------- main

stage_fn() { echo "stage_${1//-/_}"; }

if [ "$MODE" = list ]; then
    for entry in "${STAGES[@]}"; do
        IFS='|' read -r name what optional <<<"$entry"
        printf '  %-12s %s%s\n' "$name" "$what" "$([ "$optional" = yes ] && echo '  (optional)')"
    done
    exit 0
fi

if [ "$MODE" = first-login ]; then first_login; exit 0; fi
if [ "$MODE" = finish ]; then finish; exit 0; fi

if [ "$MODE" = status ]; then
    for entry in "${STAGES[@]}"; do
        IFS='|' read -r name what _ <<<"$entry"
        if is_done "$name"; then
            printf '  done     %-12s %s\n' "$name" "$(cat "$STATE/$name.done")"
        else
            printf '  pending  %-12s %s\n' "$name" "$what"
        fi
    done
    finish_state=pending
    if is_done finish; then finish_state="done"; fi
    printf '  %-8s %-12s %s\n' "$finish_state" finish "at the first Adaptive Desktop login"
    echo
    [ -x "$REPO/install.sh" ] && "$REPO/install.sh" --status
    exit 0
fi

if [ -n "$ONLY" ]; then
    printf '%s\n' "${STAGES[@]}" | cut -d'|' -f1 | grep -qx "$ONLY" || { echo "no stage called '$ONLY' (see --list)" >&2; exit 2; }
fi

mkdir -p "$(dirname "$LOG")" "$STATE"
{ echo; echo "===== bootstrap $(date -Is) $*"; } >>"$LOG"

bold "Adaptive Desktop bootstrap"
note "log: $LOG"
note "sudo is needed for packages, the login session and the link's kernel modules"
sudo -v || die "sudo is needed"
# Keep sudo's ticket fresh through the long stages (the Files build).
( while kill -0 "$$" 2>/dev/null; do sudo -n true 2>/dev/null; sleep 50; done ) &
KEEPALIVE=$!
trap 'kill "$KEEPALIVE" 2>/dev/null' EXIT
echo

failed=()
skipped=()
for entry in "${STAGES[@]}"; do
    IFS='|' read -r name what optional <<<"$entry"
    [ -z "$ONLY" ] || [ "$ONLY" = "$name" ] || continue
    if [[ "$SKIP" == *",$name,"* ]]; then
        [ "$optional" = yes ] || warn "$name is not optional; skipping it on request leaves the setup incomplete"
        skipped+=("$name"); continue
    fi
    if is_done "$name" && [ "$REDO" = 0 ] && [ -z "$ONLY" ] && [ "$name" != preflight ]; then
        printf '\033[2m== %s: done %s (--redo to run again)\033[0m\n' "$name" "$(cat "$STATE/$name.done")"
        continue
    fi
    bold "== $name: $what"
    status=0
    if [ "$name" = link-extras ]; then
        # On the terminal itself, for apt's Secure Boot dialog.
        ( set -Ee; "$(stage_fn "$name")" ) || status=$?
    else
        ( set -Ee; "$(stage_fn "$name")" ) 2>&1 | tee -a "$LOG"
        status=${PIPESTATUS[0]}
    fi
    if [ "$status" = 0 ]; then
        mark "$name"
        echo
    else
        echo "   $name failed (exit $status)." | tee -a "$LOG"
        echo
        failed+=("$name")
        [ "$optional" = yes ] || [ "$name" = desktop ] || {
            echo "Stopping here: later stages depend on '$name'. Fix the error above and run this again;"
            echo "finished stages are skipped."
            exit 1
        }
    fi
done

echo
if [ "${#failed[@]}" != 0 ]; then
    bold "Done, with ${#failed[@]} stage(s) to look at: ${failed[*]}"
    note "Run ./bootstrap.sh again to retry them (finished stages are skipped). Log: $LOG"
else
    bold "Done."
fi
[ "${#skipped[@]}" = 0 ] || note "skipped on request: ${skipped[*]}"
if [ -z "$ONLY" ]; then
    cat <<EOF

   Next:
     1. Reboot. (New groups, kernel modules$(secure_boot_on && echo ', and the Secure Boot key enrollment screen') need it.)
     2. On the login screen, pick your name, then the gear (bottom right) -> Adaptive Desktop.
     3. A terminal opens there to finish: sign-ins, pairing your phone, checks.
EOF
fi
[ "${#failed[@]}" = 0 ]
