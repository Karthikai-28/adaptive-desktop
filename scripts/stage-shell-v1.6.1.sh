#!/usr/bin/env bash
set -Eeuo pipefail

OLD_UUID="adaptive-shell@local"
NEW_UUID="adaptive-shell-v16@local"

CURRENT="$(
  gsettings get \
    org.gnome.shell \
    enabled-extensions
)"

UPDATED="$(
  CURRENT="$CURRENT" \
  OLD_UUID="$OLD_UUID" \
  NEW_UUID="$NEW_UUID" \
  python3 - <<'PY'
import ast
import os

raw = os.environ["CURRENT"].strip()

if raw.startswith("@as "):
    raw = raw[4:].strip()

try:
    values = list(ast.literal_eval(raw))
except Exception:
    values = []

old_uuid = os.environ["OLD_UUID"]
new_uuid = os.environ["NEW_UUID"]

result = []

for value in values:
    if value in (old_uuid, new_uuid):
        continue
    if value not in result:
        result.append(value)

result.append(new_uuid)

print(repr(result))
PY
)"

echo "Current enabled extensions:"
echo "  $CURRENT"
echo
echo "Staged enabled extensions:"
echo "  $UPDATED"

gsettings set \
  org.gnome.shell \
  enabled-extensions \
  "$UPDATED"

if gsettings writable \
  org.gnome.shell \
  disable-user-extensions \
  >/dev/null 2>&1
then
  gsettings set \
    org.gnome.shell \
    disable-user-extensions \
    false
fi

echo
echo "Saved."
