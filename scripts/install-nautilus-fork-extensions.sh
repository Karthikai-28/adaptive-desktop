#!/usr/bin/env bash
set -Eeuo pipefail

# Link system Nautilus extensions into the fork's private extension directory.
#
# The fork only scans NAUTILUS_EXTENSIONDIR (its own prefix) and the legacy
# /usr/lib/nautilus/extensions-3.0 path - see src/nautilus-module.c. Ubuntu
# ships its extensions in the multiarch directory instead, so anything
# installed by apt is invisible to the fork. That is why "Open in Terminal"
# was missing from the right-click menu: the gnome-terminal extension was
# installed, just never loaded.
#
# Symlinks (not copies) so apt updates to the system extensions carry over.
# ninja install does not clear this directory, so the links survive a rebuild.

REPO="${ADAPTIVE_REPO:-$HOME/adaptive-desktop}"
PREFIX="$REPO/.local/adaptive-nautilus"
FORK_EXT_DIR="$PREFIX/lib/x86_64-linux-gnu/nautilus/extensions-3.0"
SYSTEM_EXT_DIR="/usr/lib/x86_64-linux-gnu/nautilus/extensions-3.0"

# Extensions to adopt from the system install. Keep this list explicit: the
# fork deliberately does not inherit everything apt happens to have installed.
WANTED=(
    libterminal-nautilus.so   # nautilus-extension-gnome-terminal: Open in Terminal
)

test -d "$FORK_EXT_DIR" || {
    echo "Fork extension dir missing: $FORK_EXT_DIR" >&2
    echo "Run ./scripts/install-nautilus-fork-local.sh first." >&2
    exit 1
}

missing=0

for ext in "${WANTED[@]}"; do
    src="$SYSTEM_EXT_DIR/$ext"
    dest="$FORK_EXT_DIR/$ext"

    if [[ ! -f "$src" ]]; then
        echo "skip $ext (not installed at $src)" >&2
        missing=1
        continue
    fi

    # A real file here means someone installed a fork-local build of the same
    # extension. Leave it alone rather than replacing it with a system link.
    if [[ -f "$dest" && ! -L "$dest" ]]; then
        echo "keep $ext (fork-local build already present)"
        continue
    fi

    ln -sfn "$src" "$dest"
    echo "link $ext -> $src"
done

echo
echo "Extension directory now:"
ls -1 "$FORK_EXT_DIR"

if (( missing )); then
    echo
    echo "Some extensions were not found. Install them with:" >&2
    echo "  sudo apt install nautilus-extension-gnome-terminal" >&2
    exit 1
fi

echo
echo "Restart Files for this to take effect:"
echo "  ./scripts/adaptive-files-dispatch.sh --quit"
