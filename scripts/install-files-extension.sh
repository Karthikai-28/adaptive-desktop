#!/usr/bin/env bash
set -Eeuo pipefail

# Install the Adaptive Files inspector and its stylesheet into the fork's
# prefix, where the fork's nautilus-python and adaptive-files-dispatch.sh
# look for them. Copies, not links, so an edit in the repo only reaches the
# running Files after this is run and Files is restarted:
#
#   ./scripts/install-files-extension.sh && nautilus -q
#
# The next Files window starts a fresh process with the new code.

REPO="${ADAPTIVE_REPO:-$HOME/adaptive-desktop}"
PREFIX="$REPO/.local/adaptive-nautilus"
EXT_DIR="$PREFIX/share/nautilus-python/extensions"
CSS_DIR="$PREFIX/share/adaptive-files"

test -d "$PREFIX" || {
    echo "Fork prefix missing: $PREFIX" >&2
    echo "Run ./scripts/install-nautilus-fork-local.sh first." >&2
    exit 1
}

for source in "$REPO/extension/adaptive_preview.py" "$REPO"/extension/adaptive_files/*.py; do
    python3 -c "import ast, sys; ast.parse(open(sys.argv[1]).read())" "$source"
done

mkdir -p "$EXT_DIR" "$CSS_DIR"
install -m 0755 "$REPO/extension/adaptive_preview.py" "$EXT_DIR/adaptive_preview.py"
# Helper package (models, archives, git, tags, cleanup, media). Replaced
# whole so a module deleted in the repo does not linger in the install.
rm -rf "$EXT_DIR/adaptive_files"
mkdir -p "$EXT_DIR/adaptive_files"
install -m 0644 "$REPO"/extension/adaptive_files/*.py "$EXT_DIR/adaptive_files/"
install -m 0644 "$REPO/extension/preview.css" "$CSS_DIR/preview.css"
install -m 0644 "$REPO/extension/adaptive-dark.xml" "$CSS_DIR/adaptive-dark.xml"
rm -rf "$EXT_DIR/__pycache__"

echo "Installed:"
echo "  $EXT_DIR/adaptive_preview.py"
echo "  $EXT_DIR/adaptive_files/"
echo "  $CSS_DIR/preview.css"
echo "  $CSS_DIR/adaptive-dark.xml"
