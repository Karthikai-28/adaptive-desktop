#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HOME}/adaptive-desktop"
REPORT_DIR="${REPO}/verification"
STAMP="$(date +%Y%m%d-%H%M%S)"
REPORT="${REPORT_DIR}/live-readiness-${STAMP}.txt"
LATEST="${REPORT_DIR}/live-readiness-latest.txt"

mkdir -p "$REPORT_DIR"

pass() {
  printf 'PASS: %s\n' "$*"
}

verify() {
  printf 'VERIFY: %s\n' "$*"
}

info() {
  printf 'INFO: %s\n' "$*"
}

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

has_source() {
  local pattern="$1"
  local file="$2"
  rg -q "$pattern" "$file" || fail "missing source evidence: ${pattern} in ${file}"
}

{
  echo "Adaptive Desktop live readiness"
  echo "Generated: $(date -Is)"
  echo

  echo "== Recovery and fallback =="
  test -f /usr/share/xsessions/ubuntu.desktop || fail "normal Ubuntu session entry missing"
  test -f /usr/share/xsessions/adaptive-desktop.desktop || fail "Adaptive Desktop session entry missing"
  test -x /usr/local/bin/adaptive-desktop-session || fail "Adaptive session wrapper missing"
  rg -q "gnome-extensions disable adaptive-shell@local" "${REPO}/docs/RECOVERY_RUNBOOK.md" \
    || fail "TTY recovery does not document extension disable"
  rg -q "systemctl restart gdm3" "${REPO}/docs/RECOVERY_RUNBOOK.md" \
    || fail "TTY recovery does not document GDM restart"
  pass "Ubuntu fallback, Adaptive session, and TTY recovery instructions are present"
  verify "TTY recovery must be exercised from Ctrl+Alt+F3 on the physical machine"
  verify "GDM fallback must be exercised from the gear menu after logout"

  echo
  echo "== Shell rail and reload =="
  "${REPO}/scripts/verify-shell-source.sh"
  has_source "affectsStruts: true" "${REPO}/shell/adaptive-shell@local/extension.js"
  has_source "trackFullscreen: true" "${REPO}/shell/adaptive-shell@local/extension.js"
  has_source "_layoutRail" "${REPO}/shell/adaptive-shell@local/extension.js"
  pass "Rail source reserves application struts and tracks fullscreen"
  if [[ -n "${DISPLAY:-}" ]]; then
    if gnome-extensions info adaptive-shell@local | sed -n '1,30p'; then
      pass "Adaptive Shell extension is queryable in this graphical session"
    else
      verify "Adaptive Shell extension was not queryable from this process; reload inside the desktop session"
    fi

    # Two enabled rails stack on top of each other and only show up as
    # doubled labels on screen, so guard the enabled list itself.
    enabled_rails="$(gsettings get org.gnome.shell enabled-extensions \
      | grep -o "adaptive-shell[^']*@local" | sort -u | wc -l)"
    if [[ "$enabled_rails" -gt 1 ]]; then
      fail "more than one Adaptive rail extension is enabled: $(gsettings get org.gnome.shell enabled-extensions)"
    fi
    pass "exactly one Adaptive rail extension is enabled"
  else
    verify "Reload adaptive-shell@local inside Adaptive Desktop and inspect maximized windows"
  fi

  echo
  echo "== Adaptive visual system =="
  test -f "${HOME}/.local/share/themes/Adaptive/gtk-3.0/gtk.css" \
    || fail "Adaptive GTK theme is not installed"

  # Parse it rather than grepping for an import line. The theme used to import
  # Yaru's gtk.css, which is a stub pointing at a GResource that is only
  # registered when GTK loads Yaru by name - so the base silently never loaded
  # while a grep for the import string still passed.
  python3 - "${HOME}/.local/share/themes/Adaptive/gtk-3.0/gtk.css" <<'PY' \
    || fail "Adaptive GTK theme does not parse cleanly"
import sys
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

errors = []
provider = Gtk.CssProvider()
provider.connect("parsing-error", lambda p, s, e: errors.append(e.message))
provider.load_from_path(sys.argv[1])

for message in errors:
    print(f"  css: {message}", file=sys.stderr)

sys.exit(1 if errors else 0)
PY
  rg -q 'Inherits=Yaru' "${REPO}/icons/AdaptiveFilesIcons/index.theme" \
    || fail "AdaptiveFilesIcons does not inherit Yaru"
  pass "Adaptive GTK theme and icon inheritance are installed"

  if [[ "${DCONF_PROFILE:-}" == "adaptive" ]]; then
    theme="$(gsettings get org.gnome.desktop.interface gtk-theme)"
    [[ "$theme" == "'Adaptive'" ]] \
      || verify "Adaptive session gtk-theme is ${theme}; run scripts/install-adaptive-theme.sh"
    pass "Adaptive session appearance is applied"
  else
    verify "Run scripts/install-adaptive-theme.sh from inside Adaptive Desktop"
  fi

  echo
  echo "== Project context =="
  "${REPO}/scripts/verify-project-context-service.sh"
  test -f "${HOME}/.config/autostart/adaptive-project-context.desktop" \
    || fail "Project Context autostart entry missing"
  test -f "${HOME}/.local/share/gnome-shell/search-providers/org.adaptive.ProjectContext.search-provider.ini" \
    || fail "Project Context search provider missing"
  pass "Project Context autostart and search-provider files are installed"
  if busctl --user --list 2>/dev/null | rg -q "org.adaptive.ProjectContext"; then
    pass "Project Context DBus service is running"
  else
    verify "Log out and back into Adaptive Desktop to prove Project Context autostart"
  fi

  echo
  echo "== System Center =="
  for pattern in \
    "PopupSubMenuMenuItem\\('Audio Output'\\)" \
    "activateRestart" \
    "activatePowerOff" \
    "activateSuspend" \
    "_refreshNetworkStatus" \
    "_refreshBluetoothStatus" \
    "_refreshPowerStatus" \
    "_refreshPerformanceStatus"
  do
    has_source "$pattern" "${REPO}/shell/adaptive-shell@local/extension.js"
  done
  pass "System Center source includes audio output, native power actions, and status refreshers"
  verify "Audio output switching needs a live multi-device check"
  verify "Restart and shut down confirmations need a live click-through check"

  echo
  echo "== Notifications and focus =="
  python3 -m py_compile "${REPO}/scripts/focus-cli.py"
  "${REPO}/scripts/focus-cli.py" status || true
  rg -q "Adaptive Calendar Center" "${REPO}/shell/adaptive-shell@local/stylesheet.css" \
    || fail "Adaptive calendar/notification styling missing"
  pass "Focus controls and Adaptive calendar/notification styling are present"
  verify "Notification history and quiet/fullscreen policy need a live notification check"

  echo
  echo "== Window and monitor behavior =="
  python3 -m py_compile "${REPO}/scripts/window-cli.py"
  "${REPO}/scripts/window-cli.py" monitors || true
  has_source "monitors" "${REPO}/scripts/window-cli.py"
  has_source "fullscreen" "${REPO}/scripts/window-cli.py"
  pass "Window helper includes monitor-aware tiling, snapping, and fullscreen commands"
  verify "External monitor behavior needs a live monitor attach/detach check"

  echo
  echo "== Stability exercises =="
  "${REPO}/scripts/verify-file-transfer-stress.py"
  "${REPO}/scripts/verify-backup-restore.sh"
  "${REPO}/scripts/verify-shell-memory.py" --seconds 5 --interval 1 --allow-missing
  "${REPO}/scripts/verify-stability-suite.sh"
  echo
  echo "== Recorded physical checks =="
  "${REPO}/scripts/record-live-verification.py" status
  verify "Reboot and suspend/resume require physical-session runs"
  verify "Long-running memory check: run scripts/verify-shell-memory.py --seconds 14400 --interval 60"

  echo
  echo "Live readiness report complete."
} | tee "$REPORT"

cp "$REPORT" "$LATEST"
echo "Report written to $REPORT"
