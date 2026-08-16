#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"

echo "== Environment =="
"${REPO}/scripts/verify-environment.sh"

echo
echo "== Session isolation =="
"${REPO}/scripts/verify-session-isolation.sh"

echo
echo "== Shell source =="
"${REPO}/scripts/verify-shell-source.sh"

echo
echo "== Project context =="
"${REPO}/scripts/verify-project-context-service.sh" || true

echo
echo "== Backup inventory =="
test -d "${REPO}/backups"
find "${REPO}/backups" -maxdepth 1 -mindepth 1 -type d | sort | tail -10

echo
echo "== Update compatibility =="
gnome-shell --version
python3 - <<'PY'
from pathlib import Path
for path in [
    "apps/adaptive-files/main.py",
    "apps/adaptive-settings/main.py",
    "services/project-context/main.py",
    "scripts/project-cli.py",
    "scripts/focus-cli.py",
]:
    compile(Path(path).read_text(), path, "exec")
    print(f"OK {path}")
PY
node --check "${REPO}/shell/adaptive-shell@local/extension.js"

echo
echo "Stability suite complete."
