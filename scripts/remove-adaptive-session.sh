#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT="$HOME/adaptive-desktop"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$PROJECT/backups/remove-$STAMP"

mkdir -p "$BACKUP"

echo "Removing Adaptive Desktop session registration..."

for file in \
    /usr/share/xsessions/adaptive-desktop.desktop \
    /usr/local/bin/adaptive-desktop-session \
    /etc/dconf/profile/adaptive
do
    if sudo test -e "$file"; then
        sudo cp -a "$file" "$BACKUP/"
        sudo rm -f "$file"
    fi
done

# Preserve custom settings instead of deleting them.
if [[ -f "$HOME/.config/dconf/adaptive" ]]; then
    cp -a \
        "$HOME/.config/dconf/adaptive" \
        "$BACKUP/adaptive-dconf-database"
fi

echo
echo "Adaptive Desktop session removed."
echo "Normal Ubuntu was not modified."
echo
echo "Backup:"
echo "$BACKUP"
