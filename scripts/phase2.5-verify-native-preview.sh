#!/usr/bin/env bash
set -Eeuo pipefail

PREFIX="${HOME}/adaptive-desktop/.local/adaptive-nautilus"
BIN="${PREFIX}/bin/nautilus"
LOG="${HOME}/.cache/adaptive-files/preview-extension.log"

echo "===== ADAPTIVE FILES v1.4 ====="
"$BIN" --version

echo
echo "===== UBUNTU NATIVE PREVIEW PACKAGES ====="
for pkg in \
  gnome-sushi \
  evince \
  gir1.2-gnomedesktop-3.0 \
  gir1.2-gtksource-4 \
  libgtksourceview-4-0
do
  dpkg-query -W -f='${Package} ${Version}\n' "$pkg" 2>/dev/null \
    || echo "MISSING: $pkg"
done

echo
echo "===== SYSTEM THUMBNAILERS ====="
test -f /usr/share/thumbnailers/evince.thumbnailer \
  && echo "PASS: /usr/share/thumbnailers/evince.thumbnailer" \
  || echo "MISSING: evince.thumbnailer"

command -v evince-thumbnailer >/dev/null \
  && echo "PASS: $(command -v evince-thumbnailer)" \
  || echo "MISSING: evince-thumbnailer"

echo
echo "===== GNOME THUMBNAIL FACTORY ====="
grep -E "Native GNOME thumbnail factory initialized|Unable to initialize GNOME thumbnail factory" \
  "$LOG" 2>/dev/null | tail -5 || true

echo
echo "===== NATIVE PREVIEW ACTIVITY ====="
grep -E "Native thumbnail (cache hit|generated)|Native thumbnail worker failed" \
  "$LOG" 2>/dev/null | tail -20 || true

echo
echo "===== SOURCE LANGUAGE DETECTION ====="
grep -E "GtkSourceView language:" \
  "$LOG" 2>/dev/null | tail -20 || true

echo
echo "===== CSS ERRORS ====="
if grep -q "gtk-css-provider-error" "$LOG" 2>/dev/null; then
  echo "FAIL"
else
  echo "PASS: none"
fi

echo
echo "===== LAST LOG ====="
tail -140 "$LOG" 2>/dev/null || true
