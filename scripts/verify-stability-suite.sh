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
"${REPO}/scripts/verify-backup-restore.sh"

echo
echo "== Update compatibility =="
gnome-shell --version
REPO="$REPO" python3 - <<'PYCHECK'
import os
from pathlib import Path

# Resolved against REPO, not the caller's cwd: this suite has to give the same
# answer wherever it is run from.
repo = Path(os.environ["REPO"])
for name in [
    "services/project-context/main.py",
    "scripts/project-cli.py",
    "scripts/focus-cli.py",
]:
    path = repo / name
    compile(path.read_text(), str(path), "exec")
    print(f"OK {name}")
PYCHECK

# Every shell module, not just extension.js: they all load at gnome-shell start,
# so a syntax error in any one of them is a broken desktop.
for module in extension shade telemetry notifications sparkline; do
    node --check "${REPO}/shell/adaptive-shell@local/${module}.js"
done

# Syntax is not the only way a module breaks: GJS resolves method names at call
# time, so a deleted method loads fine and fails on first use.
python3 "${REPO}/scripts/verify-shell-methods.py" \
    "${REPO}/shell/adaptive-shell@local/"{shade,telemetry,notifications,sparkline}.js
python3 "${REPO}/scripts/verify-shell-memory.py" --seconds 5 --interval 1 --allow-missing

echo
echo "Stability suite complete."
