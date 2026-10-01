#!/usr/bin/env bash
# Rebuild the Command palette's index of your home folder.
#
# plocate's system database is rebuilt by a daily timer, so a file made this
# morning is not in it this afternoon. This keeps a second, private database
# of $HOME only - no root needed - that the palette searches as well
# (apps/adaptive-command/main.py, _fresh_index). services/adaptive-index.timer
# runs it every fifteen minutes; scripts/install-file-index.sh installs that.
#
#   adaptive-index.sh            rebuild
#   adaptive-index.sh --status   say how old the index is
set -Eeuo pipefail

DB_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/adaptive-desktop"
DB="${ADAPTIVE_INDEX_DB:-$DB_DIR/home.plocate.db}"
ROOT="${ADAPTIVE_INDEX_ROOT:-$HOME}"

# Folders that are never what a desktop search is for, and are most of the
# files on the disk.
PRUNE_NAMES=".git .hg .svn node_modules __pycache__ .venv venv .tox .mypy_cache .pytest_cache .cache .npm .cargo .rustup .gradle .m2 site-packages Trash"
PRUNE_PATHS="$HOME/snap $HOME/.local/share/Trash $HOME/.local/share/flatpak $HOME/.var"

if [ "${1:-}" = "--status" ]; then
    if [ -f "$DB" ]; then
        age=$(( $(date +%s) - $(stat -c %Y "$DB") ))
        echo "Home index: $(( age / 60 )) min old, $(du -h "$DB" | cut -f1)"
    else
        echo "Home index: not built yet"
    fi
    exit 0
fi

if ! command -v updatedb.plocate >/dev/null; then
    echo "updatedb.plocate is not installed (sudo apt install plocate)" >&2
    exit 1
fi

mkdir -p "$(dirname "$DB")"
chmod 700 "$(dirname "$DB")"
# -l 0: this database is yours alone, so plocate need not re-check each
# result's permissions as it would for the shared system one.
updatedb.plocate -l 0 -U "$ROOT" -o "$DB.tmp" \
    --prunenames "$PRUNE_NAMES" --prunepaths "$PRUNE_PATHS"
chmod 600 "$DB.tmp"
mv -f "$DB.tmp" "$DB"
