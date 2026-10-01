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
    "scripts/session-cli.py",
    "scripts/record-live-verification.py",
]:
    path = repo / name
    compile(path.read_text(), str(path), "exec")
    print(f"OK {name}")
PYCHECK

# Every shell module, not just extension.js: they all load at gnome-shell start,
# so a syntax error in any one of them is a broken desktop.
for module in "${REPO}/shell/adaptive-shell@local/"*.js; do
    node --check "${module}"
done

# Syntax is not the only way a module breaks: GJS resolves method names at call
# time, so a deleted method loads fine and fails on first use.
python3 "${REPO}/scripts/verify-shell-methods.py" \
    "${REPO}/shell/adaptive-shell@local/"{shade,telemetry,notifications,sparkline,shellActions,clipboardHistory,projectSnapshots,projectIndicator,screenText,watchdog}.js
# The shell's one class is spread over several files; check them as one body.
python3 "${REPO}/scripts/verify-shell-methods.py" --class \
    "${REPO}/shell/adaptive-shell@local/"{extension,shellLock,shellDock,shellDockFeatures,shellDockDnd,shellDockAutohide,shellDisplays}.js
python3 "${REPO}/scripts/verify-shell-methods.py" --class \
    "${REPO}/shell/adaptive-shell@local/"{controlCenter,ccNetwork,ccBluetooth,ccMedia,ccSystem}.js
# A helper moved to another file is undefined where it used to be found, and
# only when that code is reached.
python3 "${REPO}/scripts/verify-shell-imports.py" "${REPO}/shell/adaptive-shell@local"
# The decisions inside the new shell modules (git status, the watchdog rule,
# battery health, clipboard bounds), checked on the shipped file under Node.
node "${REPO}/scripts/verify-shell-helpers.js"
python3 "${REPO}/scripts/verify-shell-memory.py" --seconds 5 --interval 1 --allow-missing

echo
echo "== Adaptive Settings =="
python3 "${REPO}/scripts/verify-adaptive-settings.py"

echo
echo "== Palette, quick notes, workspace names, phones =="
python3 "${REPO}/scripts/verify-feature-logic.py"

echo
echo "== Windows and shell, run for real on a virtual display =="
# The palette and Annotate windows, and the extension loaded into a nested
# GNOME Shell, each with its own bus and HOME: nothing here reaches this
# session. See scripts/verify-all.sh for the same checks without the
# machine-specific ones above.
python3 "${REPO}/scripts/verify-palette.py"
python3 "${REPO}/scripts/verify-annotate.py"
"${REPO}/scripts/verify-shell-nested.sh"
python3 "${REPO}/scripts/verify-files-inspector.py"

echo
echo "Stability suite complete."
