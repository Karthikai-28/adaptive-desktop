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
  echo "== Power =="
  "${REPO}/scripts/adaptive-power-check.sh"
  "${REPO}/scripts/adaptive-screen-blank-check.sh" --check \
    || fail "the display is being forced off with no timer asking for it"

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
  echo "== System controls =="

  # These used to be a bespoke System Center on the rail. It is deliberately
  # gone: GNOME's own top-right menu owns network, bluetooth, audio and power,
  # because reimplementing them meant maintaining a worse copy of working code.
  # Assert the reimplementation has not crept back rather than asserting on it.
  for pattern in \
    "PopupSubMenuMenuItem\\('Audio Output'\\)" \
    "_refreshNetworkStatus" \
    "_refreshBluetoothStatus" \
    "_refreshPowerStatus"
  do
    if rg -q "$pattern" "${REPO}/shell/adaptive-shell@local/extension.js"; then
      fail "the shell reimplements a system control GNOME already owns: ${pattern}"
    fi
  done
  pass "System controls are GNOME's own; the shell does not reimplement them"

  has_source "_restoreGNOMEClock" "${REPO}/shell/adaptive-shell@local/extension.js"
  pass "GNOME clock and calendar are restored into the panel"
  verify "Audio output switching needs a live multi-device check"
  verify "Restart and shut down confirmations need a live click-through check"

  echo
  echo "== Notifications and focus =="
  python3 -m py_compile "${REPO}/scripts/focus-cli.py"
  "${REPO}/scripts/focus-cli.py" status || true
  rg -q "Adaptive Calendar Center" "${REPO}/shell/adaptive-shell@local/stylesheet.css" \
    || fail "Adaptive calendar/notification styling missing"
  rg -q "Adaptive Shade v2" "${REPO}/shell/adaptive-shell@local/stylesheet.css" \
    || fail "Adaptive Shade styling missing"
  pass "Focus controls and Adaptive calendar/notification styling are present"

  # The shade modules load at gnome-shell start, so a syntax error is a broken
  # desktop rather than a failed test. Parse them here instead of finding out
  # at the next login.
  for module in shade telemetry notifications sparkline; do
    node --check "${REPO}/shell/adaptive-shell@local/${module}.js" \
      || fail "shade module does not parse: ${module}.js"
  done
  pass "Adaptive Shade modules parse"

  # Parsing is not enough. GJS resolves method names at call time, so a method
  # that has been deleted or renamed still loads cleanly and only fails when
  # something calls it - for a menu handler, the first time the popup opens.
  python3 "${REPO}/scripts/verify-shell-methods.py" \
    "${REPO}/shell/adaptive-shell@local/"{shade,telemetry,notifications,sparkline}.js \
    || fail "a shell module calls a method it does not define"
  pass "Every internal method call in the shade modules resolves"

  # The shade rearranges actors gnome-shell owns. These two assertions are what
  # stands between "reparented" and "reimplemented": the message list has to be
  # GNOME's own instance, moved and handed back, never rebuilt.
  has_source "_messageList" "${REPO}/shell/adaptive-shell@local/shade.js"
  has_source "_origParent" "${REPO}/shell/adaptive-shell@local/shade.js"
  has_source "insert_child_at_index" "${REPO}/shell/adaptive-shell@local/shade.js"
  if rg -q "new Calendar\.CalendarMessageList|new MessageList" \
      "${REPO}/shell/adaptive-shell@local/shade.js"; then
    fail "the shade builds its own message list instead of reparenting GNOME's"
  fi
  pass "The shade reparents GNOME's message list and records how to put it back"

  # v2 is an information center. GNOME's aggregate menu owns every control, so
  # the shade must contain none - not even delegating ones. This is a stronger
  # and simpler property than v1.7's "delegate, don't reimplement".
  test ! -f "${REPO}/shell/adaptive-shell@local/tiles.js" \
    || fail "tiles.js is back; the shade is meant to hold no controls"
  for control in \
    "getRfkillManager" \
    "getMixerControl" \
    "Slider.Slider" \
    "wireless_enabled" \
    "set_boolean"
  do
    # The shade's own modules only. The Control Center (controlCenter.js) is
    # the aggregate menu rebuilt, so these are rightly its business.
    if rg -q "$control" "${REPO}/shell/adaptive-shell@local/"{shade,telemetry,notifications,sparkline}.js; then
      fail "the shade grew a control GNOME's aggregate menu already owns: ${control}"
    fi
  done
  pass "The shade holds no controls; GNOME's aggregate menu keeps them"

  # Notification grouping must stay a change of arrangement. The moment the
  # shade builds its own notification objects instead of GNOME's, delivery and
  # urgency stop being GNOME's problem and start being ours.
  has_source "Calendar.NotificationMessage" \
    "${REPO}/shell/adaptive-shell@local/notifications.js"
  has_source "Main.messageTray" \
    "${REPO}/shell/adaptive-shell@local/notifications.js"
  has_source "notificationGrouping" "${REPO}/shell/adaptive-shell@local/shade.js"
  has_source "_restoreStockNotifications" "${REPO}/shell/adaptive-shell@local/shade.js"
  pass "Notifications are regrouped, not rebuilt, and fall back to GNOME's list"

  # An Adaptive month/agenda/week calendar was built and then removed: the
  # stock GNOME calendar is what was wanted. Assert it stays stock. Touching
  # the event source at all is the tell that it is creeping back, and
  # requestRange in particular would fight GNOME's own month grid for the
  # shared calendar server's time range.
  test ! -f "${REPO}/shell/adaptive-shell@local/calendar-view.js" \
    || fail "calendar-view.js is back; the calendar column is meant to be stock"
  for symbol in "requestRange" "getEvents" "_eventSource" "dateMenu._calendar"; do
    if rg -q "$symbol" "${REPO}/shell/adaptive-shell@local/"*.js; then
      fail "the shade is reaching into GNOME's calendar again: ${symbol}"
    fi
  done
  pass "The calendar column is left stock"

  # GNOME stacks the empty-state placeholder over the message list with a
  # BinLayout, so in the shade's compressed list it landed on top of the Do Not
  # Disturb row. It is moved into normal flow, and must be put back on detach
  # like every other GNOME actor the shade rearranges.
  has_source "_unstackPlaceholder" "${REPO}/shell/adaptive-shell@local/shade.js"
  has_source "_restackPlaceholder" "${REPO}/shell/adaptive-shell@local/shade.js"
  pass "The empty-state placeholder is unstacked from the controls and restored on detach"

  # The system block has no natural bound - sixteen cores, eleven sensors and
  # five processes ran past the bottom of the screen before it could scroll.
  has_source "St.ScrollView" "${REPO}/shell/adaptive-shell@local/shade.js"
  has_source "_fitToMonitor" "${REPO}/shell/adaptive-shell@local/shade.js"
  pass "The shade sizes itself against the monitor and scrolls rather than overflowing"

  # The clarity fix was a type scale, and it regresses the moment one 9px rule
  # gets pasted back in.
  if awk '/Adaptive Shade v2/,0' \
      "${REPO}/shell/adaptive-shell@local/stylesheet.css" \
      | rg -q "font-size: ([0-9]|10)px"; then
    fail "the shade has font sizes below 11px again"
  fi
  pass "No shade text is smaller than 11px"

  # Sensors are found by reading what each device says it is. Hardcoded indices
  # survive exactly until the next boot reorders probing.
  # Strip comment lines first: the module's own header names `thermal_zone10`
  # and `card1` precisely to say it must not depend on them, and that sentence
  # should not fail the check it describes.
  if grep -vE '^[[:space:]]*(//|\*|/\*)' \
      "${REPO}/shell/adaptive-shell@local/telemetry.js" \
      | rg -q "thermal_zone[0-9]|/sys/class/drm/card[0-9]"; then
    fail "telemetry hardcodes a thermal zone or DRM card index"
  fi
  pass "Telemetry discovers sensors at runtime rather than hardcoding indices"

  verify "Notification history and quiet/fullscreen policy need a live notification check"
  verify "Open the shade and confirm telemetry and grouped notifications read correctly"
  verify "Disable the extension and confirm the stock GNOME date menu comes back intact"

  echo
  echo "== Window and monitor behavior =="
  python3 -m py_compile "${REPO}/scripts/window-cli.py"
  "${REPO}/scripts/window-cli.py" monitors || true
  has_source "monitors" "${REPO}/scripts/window-cli.py"
  has_source "fullscreen" "${REPO}/scripts/window-cli.py"
  pass "Window helper includes monitor-aware tiling, snapping, and fullscreen commands"

  python3 -m py_compile "${REPO}/scripts/adaptive-display-guard.py"
  has_source "_rescueStrandedWindows" "${REPO}/shell/adaptive-shell@local/extension.js"
  has_source "_runDisplayGuard" "${REPO}/shell/adaptive-shell@local/extension.js"
  pass "Displays changing triggers the ghost-output guard and the window rescue"

  if command -v node >/dev/null 2>&1; then
    node "${REPO}/scripts/verify-window-rescue.js"
  else
    verify "node is not installed; window rescue geometry was not checked"
  fi

  # A port that says "connected" with no EDID has nothing plugged into it.
  # Windows placed there are open, running, and impossible to reach.
  if [[ -n "${DISPLAY:-}" ]]; then
    if "${REPO}/scripts/adaptive-display-guard.py" --check; then
      pass "no ghost display is enabled"
    else
      fail "a connected output published no EDID and is still enabled"
    fi
  fi

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
