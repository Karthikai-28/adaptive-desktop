#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${ADAPTIVE_REPO:-$HOME/adaptive-desktop}"
PREFIX="$REPO/.local/adaptive-nautilus"
FORK="$PREFIX/bin/nautilus"
STOCK="/usr/bin/nautilus"

LOG_DIR="$HOME/.local/state/adaptive-desktop"
LOG_FILE="$LOG_DIR/files-dispatch.log"
mkdir -p "$LOG_DIR"

shell_env_has() {
    local expected="$1"
    local pid

    while read -r pid; do
        [[ -r "/proc/$pid/environ" ]] || continue

        if tr '\0' '\n' < "/proc/$pid/environ" \
            | grep -Fxq "$expected"; then
            return 0
        fi
    done < <(pgrep -u "$UID" -x gnome-shell 2>/dev/null || true)

    return 1
}

in_adaptive_session() {
    [[ "${DCONF_PROFILE:-}" == "adaptive" ]] \
        || [[ "${GDMSESSION:-}" == "adaptive-desktop" ]] \
        || [[ "${XDG_SESSION_DESKTOP:-}" == "adaptive-desktop" ]] \
        || shell_env_has "DCONF_PROFILE=adaptive" \
        || shell_env_has "GDMSESSION=adaptive-desktop" \
        || shell_env_has "XDG_SESSION_DESKTOP=adaptive-desktop"
}

prepare_adaptive_environment() {
    export PATH="$PREFIX/bin:${PATH:-/usr/local/bin:/usr/bin:/bin}"

    export LD_LIBRARY_PATH="$PREFIX/lib/x86_64-linux-gnu:$PREFIX/lib:${LD_LIBRARY_PATH:-}"

    export XDG_DATA_DIRS="$PREFIX/share:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"

    if [[ -d "$PREFIX/share/glib-2.0/schemas" ]]; then
        export GSETTINGS_SCHEMA_DIR="$PREFIX/share/glib-2.0/schemas"
    fi

    if [[ -d "$PREFIX/lib/x86_64-linux-gnu/girepository-1.0" ]]; then
        export GI_TYPELIB_PATH="$PREFIX/lib/x86_64-linux-gnu/girepository-1.0:${GI_TYPELIB_PATH:-}"
    fi

    if [[ -d "$PREFIX/share/themes/AdaptiveFiles" ]]; then
        export GTK_THEME="AdaptiveFiles"
    fi
}

if in_adaptive_session && [[ -x "$FORK" ]]; then
    WHICH="adaptive"
    BIN="$FORK"
    prepare_adaptive_environment
else
    WHICH="stock"
    BIN="$STOCK"
fi

printf '%s which=%s bin=%q args=' \
    "$(date -Is)" "$WHICH" "$BIN" >> "$LOG_FILE"
printf '%q ' "$@" >> "$LOG_FILE"
printf '\n' >> "$LOG_FILE"

exec "$BIN" "$@"
