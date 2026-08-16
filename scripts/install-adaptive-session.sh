#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT="$HOME/adaptive-desktop"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$PROJECT/backups/session-$STAMP"

SESSION_ENTRY="/usr/share/xsessions/adaptive-desktop.desktop"
WRAPPER="/usr/local/bin/adaptive-desktop-session"
DCONF_PROFILE_FILE="/etc/dconf/profile/adaptive"

fail() {
    echo
    echo "ERROR: $*"
    exit 1
}

echo "=========================================="
echo " Adaptive Desktop - Session Installer"
echo "=========================================="
echo

# ------------------------------------------------------------
# Safety checks
# ------------------------------------------------------------

[[ "$EUID" -ne 0 ]] || fail "Run this as your normal user, not with sudo."

source /etc/os-release

[[ "${VERSION_ID:-}" == "22.04" ]] \
    || fail "This installer is intentionally restricted to Ubuntu 22.04."

[[ -x /usr/bin/gnome-session ]] \
    || fail "/usr/bin/gnome-session not found."

[[ -f /usr/share/gnome-session/sessions/ubuntu.session ]] \
    || fail "Ubuntu GNOME session definition not found."

[[ -f /usr/share/xsessions/ubuntu.desktop ]] \
    || fail "Ubuntu X11 session entry not found."

FREE_KB="$(df --output=avail / | tail -1 | tr -d ' ')"
FREE_GB=$((FREE_KB / 1024 / 1024))

echo "Detected Ubuntu: $PRETTY_NAME"
echo "Free root space: approximately ${FREE_GB} GB"

if (( FREE_GB < 25 )); then
    fail "Less than 25 GB free. Refusing to continue."
fi

mkdir -p "$BACKUP"

# ------------------------------------------------------------
# Back up anything we might replace
# ------------------------------------------------------------

for file in \
    "$SESSION_ENTRY" \
    "$WRAPPER" \
    "$DCONF_PROFILE_FILE"
do
    if sudo test -e "$file"; then
        echo "Backing up existing $file"
        sudo cp -a "$file" "$BACKUP/"
    fi
done

# Current normal-session facts
{
    echo "date=$(date -Is)"
    echo "ubuntu=$PRETTY_NAME"
    echo "desktop=${XDG_CURRENT_DESKTOP:-}"
    echo "session=${XDG_SESSION_DESKTOP:-}"
    echo "session_type=${XDG_SESSION_TYPE:-}"
} > "$BACKUP/original-session.txt"

# ------------------------------------------------------------
# Separate dconf profile
# ------------------------------------------------------------

TMP_PROFILE="$(mktemp)"

if [[ -f /etc/dconf/profile/user ]]; then
    # Preserve any existing system/site databases and policies,
    # but replace the writable user database with "adaptive".
    awk '
        BEGIN { replaced=0 }
        /^user-db:/ && replaced==0 {
            print "user-db:adaptive"
            replaced=1
            next
        }
        { print }
        END {
            if (replaced==0)
                print "user-db:adaptive"
        }
    ' /etc/dconf/profile/user > "$TMP_PROFILE"

    # Ensure the writable database is first.
    if ! head -1 "$TMP_PROFILE" | grep -q '^user-db:adaptive$'; then
        {
            echo "user-db:adaptive"
            grep -v '^user-db:adaptive$' "$TMP_PROFILE"
        } > "${TMP_PROFILE}.fixed"

        mv "${TMP_PROFILE}.fixed" "$TMP_PROFILE"
    fi
else
    echo "user-db:adaptive" > "$TMP_PROFILE"
fi

sudo install -d -m 0755 /etc/dconf/profile
sudo install -m 0644 "$TMP_PROFILE" "$DCONF_PROFILE_FILE"
rm -f "$TMP_PROFILE"

# ------------------------------------------------------------
# Session wrapper
# ------------------------------------------------------------

TMP_WRAPPER="$(mktemp)"

cat > "$TMP_WRAPPER" <<'WRAPPER'
#!/usr/bin/env bash
set -Eeuo pipefail

#
# Adaptive Desktop
#
# IMPORTANT:
# Ubuntu's normal session does NOT execute this wrapper.
# Therefore everything exported here is local to this login session.
#

export DCONF_PROFILE=adaptive
export GNOME_SHELL_SESSION_MODE=ubuntu
export XDG_CURRENT_DESKTOP=ubuntu:GNOME

#
# Put the Adaptive Nautilus prefix ahead of the system one so this session
# resolves the file manager's desktop entry, mime defaults, icons, themes and
# search provider to our build. D-Bus activation is handled separately by
# scripts/install-files-session-integration.sh, because the session bus fixes
# its service directories before this wrapper ever runs.
#
ADAPTIVE_FILES_SHARE="$HOME/adaptive-desktop/.local/adaptive-nautilus/share"

if [ -d "$ADAPTIVE_FILES_SHARE" ]; then
    export XDG_DATA_DIRS="${ADAPTIVE_FILES_SHARE}:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
fi

exec /usr/bin/gnome-session --session=ubuntu
WRAPPER

sudo install -m 0755 "$TMP_WRAPPER" "$WRAPPER"
rm -f "$TMP_WRAPPER"

# ------------------------------------------------------------
# GDM session entry
#
# Start from Ubuntu's own session entry so Jammy-specific
# keys remain intact.
# ------------------------------------------------------------

TMP_DESKTOP="$(mktemp)"

cp /usr/share/xsessions/ubuntu.desktop "$TMP_DESKTOP"

# Remove localized Ubuntu names/comments so GDM always displays
# our own session name.
sed -i -E \
    '/^(Name|Comment)\[[^]]+\]=/d' \
    "$TMP_DESKTOP"

sed -i -E \
    's/^Name=.*/Name=Adaptive Desktop/' \
    "$TMP_DESKTOP"

if grep -q '^Comment=' "$TMP_DESKTOP"; then
    sed -i -E \
        's/^Comment=.*/Comment=Reversible custom desktop experience/' \
        "$TMP_DESKTOP"
else
    echo 'Comment=Reversible custom desktop experience' >> "$TMP_DESKTOP"
fi

if grep -q '^Exec=' "$TMP_DESKTOP"; then
    sed -i \
        's|^Exec=.*|Exec=/usr/local/bin/adaptive-desktop-session|' \
        "$TMP_DESKTOP"
else
    echo 'Exec=/usr/local/bin/adaptive-desktop-session' >> "$TMP_DESKTOP"
fi

if grep -q '^TryExec=' "$TMP_DESKTOP"; then
    sed -i \
        's|^TryExec=.*|TryExec=/usr/local/bin/adaptive-desktop-session|' \
        "$TMP_DESKTOP"
else
    echo 'TryExec=/usr/local/bin/adaptive-desktop-session' >> "$TMP_DESKTOP"
fi

sudo install -m 0644 "$TMP_DESKTOP" "$SESSION_ENTRY"
rm -f "$TMP_DESKTOP"

# ------------------------------------------------------------
# Record installed state
# ------------------------------------------------------------

{
    echo "Installed: $(date -Is)"
    echo
    echo "[Session Entry]"
    cat "$SESSION_ENTRY"

    echo
    echo "[dconf Profile]"
    cat "$DCONF_PROFILE_FILE"

    echo
    echo "[Wrapper]"
    cat "$WRAPPER"

    echo
    echo "[Checksums]"
    sha256sum \
        "$SESSION_ENTRY" \
        "$DCONF_PROFILE_FILE" \
        "$WRAPPER"
} > "$PROJECT/config/adaptive-session-installed.txt"

echo
echo "=========================================="
echo " Installation complete"
echo "=========================================="
echo
echo "Nothing has been done to the normal Ubuntu session."
echo
echo "Backup:"
echo "  $BACKUP"
echo
echo "Next:"
echo "  Save your work and log out."
echo "  At GDM select the gear icon."
echo "  Select: Adaptive Desktop"
echo
