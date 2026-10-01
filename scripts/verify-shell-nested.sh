#!/usr/bin/env bash
#
# Load the Adaptive shell extension in a real GNOME Shell and exercise it.
#
# Every other shell check here is static (syntax, method names, pure helpers),
# because a GJS module only fails when it runs. This one runs it: a nested
# gnome-shell on a virtual X display, with its own session bus, HOME, dconf
# and caches, so nothing it does can reach the desktop you are sitting at.
# It needs no login, no restart and no display of its own.
#
#   scripts/verify-shell-nested.sh            run the checks
#   scripts/verify-shell-nested.sh --keep     keep the sandbox and its log
#   scripts/verify-shell-nested.sh --extra F  also source F inside the sandbox
#                                             (it can use check/call/shell_log)
#
# Needs xvfb-run, dbus-run-session and gnome-shell 42 (nested mode).
set -Euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UUID="adaptive-shell@local"
PROBE="adaptive-probe@local"
KEEP=0
EXTRA=""

while [ $# -gt 0 ]; do
    case "$1" in
        --keep) KEEP=1 ;;
        --extra) EXTRA="$(readlink -f "$2")"; shift ;;
        --inner) INNER=1 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

# ----------------------------------------------------------------- inner
# Runs inside xvfb-run + dbus-run-session, with HOME already the sandbox.

if [ "${INNER:-0}" = 1 ]; then
    failures=0
    # Results go to a file: the session's own stdout is full of the chatter of
    # every service D-Bus starts in the sandbox.
    exec >"$SANDBOX/results.txt"
    check() {
        if [ "$1" = 0 ]; then echo "OK   $2"; else echo "FAIL $2"; failures=$((failures + 1)); fi
    }
    call() {
        gdbus call --session -d org.gnome.Shell -o /org/adaptive/Shell \
            -m "org.adaptive.Shell.$1" "${@:2}" 2>&1
    }
    extensions() {
        gdbus call --session -d org.gnome.Shell.Extensions -o /org/gnome/Shell/Extensions \
            -m "org.gnome.Shell.Extensions.$1" "${@:2}" 2>&1
    }
    shell_log() { cat "$SANDBOX/shell.log"; }
    # probe '<js function body>' -> the JSON it returned (see nested-probe/).
    probe() {
        gdbus call --session -d org.gnome.Shell -o /org/adaptive/Probe \
            -m org.adaptive.Probe.Eval "$1" 2>&1 |
            python3 -c 'import ast,sys; print(ast.literal_eval(sys.stdin.read().strip())[0])' 2>/dev/null
    }
    project() {
        gdbus call --session -d org.adaptive.ProjectContext -o /org/adaptive/ProjectContext \
            -m "org.adaptive.ProjectContext.$1" "${@:2}" 2>&1
    }
    wait_for() {  # wait_for <seconds> <command...>
        local deadline=$((SECONDS + $1)); shift
        until "$@" >/dev/null 2>&1; do
            [ "$SECONDS" -ge "$deadline" ] && return 1
            sleep 0.5
        done
    }

    gsettings set org.gnome.shell disable-user-extensions false
    gsettings set org.gnome.shell disable-extension-version-validation true
    gsettings set org.gnome.shell enabled-extensions "['$UUID', '$PROBE']"

    # The project service on this private bus, against the sandbox registry,
    # so the modules that talk to it have something real to talk to.
    python3 "$REPO/services/project-context/main.py" >"$SANDBOX/project-service.log" 2>&1 &
    SERVICE_PID=$!

    gnome-shell --nested --wayland >"$SANDBOX/shell.log" 2>&1 &
    SHELL_PID=$!
    trap 'kill $SHELL_PID $SERVICE_PID 2>/dev/null' EXIT

    wait_for 40 gdbus call --session -d org.gnome.Shell -o /org/gnome/Shell \
        -m org.freedesktop.DBus.Peer.Ping
    check $? "gnome-shell started"
    wait_for 20 extensions GetExtensionInfo "$UUID"
    extensions EnableExtension "$UUID" >/dev/null
    extensions EnableExtension "$PROBE" >/dev/null
    wait_for 20 call ListWindows
    check $? "extension enabled and its bridge is on the bus"

    state="$(gnome-extensions info "$UUID" 2>/dev/null | sed -n 's/^ *State: //p')"
    [ "$state" = "ENABLED" ]; check $? "extension state is ENABLED (is: ${state:-unknown})"
    errors="$(extensions GetExtensionErrors "$UUID")"
    [ "$errors" = "(@as [],)" ]; check $? "extension reported no errors ($errors)"

    # The bridge: fixed action names only, JSON back.
    [[ "$(call ListWindows)" == "('["* ]]; check $? "ListWindows answers a JSON list"
    [ "$(call Run overview)" = "(true,)" ]; check $? "Run accepts a known action"
    call Run overview >/dev/null
    [ "$(call Run 'rm -rf /')" = "(false,)" ]; check $? "Run refuses an unknown action"
    [ "$(call ActivateWorkspace 99)" = "(false,)" ]; check $? "ActivateWorkspace refuses a missing workspace"
    [ "$(call ActivateWindow 4000000)" = "(false,)" ]; check $? "ActivateWindow refuses an unknown window"
    [[ "$(call ParkProject '')" == *'"ok":false'* ]]; check $? "ParkProject with no active project fails politely"

    # ---------------------------------------------------------- probe
    [ "$(probe 'return 1 + 1')" = 2 ]; check $? "probe can see inside the shell"

    SLEEP='const sleep = ms => new Promise(r => imports.gi.GLib.timeout_add(0, ms, () => { r(); return false; }));'
    LABELS='const labels = a => { const out = []; (function walk(x) { if (x.get_text) out.push(x.get_text()); x.get_children().forEach(walk); })(a); return out; };'

    for name in adaptive-usb adaptive-tasks adaptive-network adaptive-project; do
        [ "$(probe "return !!Main.panel.statusArea['$name']")" = true ]
        check $? "top bar has $name"
    done

    # ------------------------------------------------------ clipboard
    call ClipboardCopy 'nested check text' >/dev/null
    wait_for 5 sh -c "gdbus call --session -d org.gnome.Shell -o /org/adaptive/Shell \
        -m org.adaptive.Shell.ClipboardHistory | grep -q 'nested check text'"
    check $? "clipboard history records a copy"
    call ClipboardClear >/dev/null
    [ "$(call ClipboardHistory)" = "('[]',)" ]; check $? "clipboard history clears"

    # history_field <python expression over `items`> -> its value
    history_field() {
        call ClipboardHistory | python3 -c '
import ast, json, sys
items = json.loads(ast.literal_eval(sys.stdin.read().strip())[0])
print(eval(sys.argv[1]))' "$1" 2>/dev/null
    }
    has_text() { [ "$(history_field "any(i.get('text') == '$1' for i in items)")" = True ]; }

    call ClipboardCopy 'pin me' >/dev/null
    wait_for 5 has_text 'pin me'
    pin_id="$(history_field "next(i['id'] for i in items if i.get('text') == 'pin me')")"
    [ "$(call ClipboardPin "${pin_id:-0}" true)" = "(true,)" ]; check $? "a clipboard entry can be pinned (id ${pin_id:-none})"
    [ "$(call ClipboardPin 424242 true)" = "(false,)" ]; check $? "pinning an unknown entry is refused"
    call ClipboardCopy 'forget me' >/dev/null
    wait_for 5 has_text 'forget me'
    call ClipboardClear >/dev/null
    has_text 'pin me' && ! has_text 'forget me'; check $? "clear keeps what is pinned and forgets the rest"
    call ClipboardPin "${pin_id:-0}" false >/dev/null
    call ClipboardClear >/dev/null
    [ "$(call ClipboardHistory)" = "('[]',)" ]; check $? "unpinned, it clears like anything else"

    # An image: a real 3x2 PNG put on the clipboard, as an app would.
    png="$(python3 -c '
import struct, zlib
def chunk(kind, data):
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xffffffff)
raw = b"".join(b"\x00" + b"\xff\x00\x00" * 3 for _ in range(2))
png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 3, 2, 8, 2, 0, 0, 0)) \
    + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
print(",".join(str(b) for b in png))')"
    probe "const { St, GLib } = imports.gi;
        St.Clipboard.get_default().set_content(St.ClipboardType.CLIPBOARD, 'image/png',
            new GLib.Bytes(Uint8Array.from([$png]))); return true" >/dev/null
    has_image() { [ "$(history_field "any(i.get('kind') == 'image' for i in items)")" = True ]; }
    wait_for 5 has_image; check $? "a copied image is kept in the history"
    shape="$(history_field "next((i['width'], i['height']) for i in items if i.get('kind') == 'image')")"
    [ "$shape" = "(3, 2)" ]; check $? "the image's size is read from its header ($shape)"
    image_id="$(history_field "next(i['id'] for i in items if i.get('kind') == 'image')")"
    [ "$(call ClipboardCopyItem "${image_id:-0}")" = "(true,)" ]; check $? "an image is copied back by its id"
    [ "$(call ClipboardCopyItem 424242)" = "(false,)" ]; check $? "copying an unknown entry is refused"
    call ClipboardClear >/dev/null

    # ------------------------------------------------ project in the top bar
    [ "$(probe "return Main.panel.statusArea['adaptive-project'].container.visible")" = false ]
    check $? "project indicator is hidden with no active project"

    mkdir -p "$HOME/alpha" && git -C "$HOME/alpha" init -q -b main && touch "$HOME/alpha/notes.txt"
    pid="$(project AddProject "$HOME/alpha" "Alpha" | sed -n "s/^('\(.*\)',)$/\1/p")"
    [ -n "$pid" ]; check $? "project service registers a project ($pid)"
    project SetActiveProject "$pid" >/dev/null
    wait_for 8 sh -c "[ \"\$(gdbus call --session -d org.gnome.Shell -o /org/adaptive/Probe \
        -m org.adaptive.Probe.Eval \"return Main.panel.statusArea['adaptive-project'].container.visible\")\" = \"('true',)\" ]"
    check $? "project indicator appears when a project becomes active"
    sleep 1.5
    shown="$(probe "$LABELS return labels(Main.panel.statusArea['adaptive-project']).join('|')")"
    [[ "$shown" == *Alpha* && "$shown" == *"main ±1"* ]]
    check $? "project indicator shows the name and live git status ($shown)"

    # ------------------------------------------------------------ menus
    # A menu handler that calls a missing method fails the first time the
    # popup opens, so open every one of them.
    opened="$(probe "$SLEEP return (async () => { const out = {};
        for (const name of ['adaptive-project', 'adaptive-usb', 'adaptive-tasks', 'adaptive-network', 'dateMenu', 'aggregateMenu']) {
            const menu = Main.panel.statusArea[name].menu;
            menu.open(); await sleep(900);
            out[name] = menu.isOpen; menu.close(); await sleep(300);
        }
        return out; })();")"
    for name in adaptive-project adaptive-usb adaptive-tasks adaptive-network dateMenu aggregateMenu; do
        [[ "$opened" == *"\"$name\":true"* ]]; check $? "menu opens: $name"
    done
    # The Control Center's dropdowns (Wi-Fi, Bluetooth, power, ...) are built
    # when first opened, each from a different file of the class.
    pages="$(probe "$SLEEP return (async () => {
        const cc = adaptive.extension._shell._controlCenter;
        const menu = Main.panel.statusArea.aggregateMenu.menu;
        menu.open(); await sleep(800);
        const opened = [];
        for (const name of Object.keys(cc._pages)) {
            cc._openDropdown(name); await sleep(700);
            if (cc._open === name)
                opened.push(name);
        }
        cc._openDropdown(null); menu.close(); await sleep(300);
        return { total: Object.keys(cc._pages).length, opened }; })();")"
    total="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(d["total"], len(d["opened"]))' "$pages" 2>/dev/null)"
    [ -n "$total" ] && [ "${total% *}" -ge 4 ] && [ "${total% *}" = "${total#* }" ]
    check $? "every Control Center dropdown opens ($pages)"

    items="$(probe "$SLEEP $LABELS return (async () => {
        const menu = Main.panel.statusArea['adaptive-project'].menu;
        menu.open(); await sleep(700);
        const text = labels(menu.actor).join('|'); menu.close(); return text; })();")"
    [[ "$items" == *"Open in Terminal"* && "$items" == *"Park Project"* && "$items" == *"1 uncommitted"* ]]
    check $? "project menu lists its actions and git summary"
    [[ "$items" == *"Tasks…"* && "$items" == *"Search in Project…"* && "$items" == *"Switch Branch…"* ]]
    check $? "project menu leads into the palette's task, search and branch modes"
    [[ "$items" != *"Run Startup Command"* ]]; check $? "no startup entry for a project with no startup commands"

    # A startup command: offered in the menu, and run when the project resumes.
    STARTED="$SANDBOX/startup-ran"
    project UpdateProject "$pid" "{\"metadata\": {\"startup\": [{\"command\": \"touch $STARTED\", \"terminal\": false}]}}" >/dev/null
    sleep 1
    items="$(probe "$SLEEP $LABELS return (async () => {
        const menu = Main.panel.statusArea['adaptive-project'].menu;
        menu.open(); await sleep(700);
        const text = labels(menu.actor).join('|'); menu.close(); return text; })();")"
    [[ "$items" == *"Run Startup Command"* ]]; check $? "a project with a startup command offers to run it"

    # ----------------------------------------------------- park and resume
    # gedit: a .deb, so it runs with the sandbox HOME (a snap would not).
    APP=org.gnome.gedit.desktop
    has_window() {
        gdbus call --session -d org.gnome.Shell -o /org/adaptive/Shell \
            -m org.adaptive.Shell.ListWindows | grep -q "$APP"
    }
    no_window() { ! has_window; }
    # In a real Wayland session the session manager hands WAYLAND_DISPLAY to
    # everything started in it. Nested, there is none, and an app would open
    # on the virtual X display behind the shell instead of inside it - so tell
    # both the shell (what it spawns) and the bus (what it activates).
    dbus-update-activation-environment WAYLAND_DISPLAY=wayland-0 GDK_BACKEND=wayland
    probe "const GLib = imports.gi.GLib;
        GLib.setenv('WAYLAND_DISPLAY', 'wayland-0', true); GLib.setenv('GDK_BACKEND', 'wayland', true);
        imports.gi.Shell.AppSystem.get_default().lookup_app('$APP').activate(); return true" >/dev/null
    if wait_for 25 has_window; then
        check 0 "an app window opened in the sandbox"
        parked="$(call ParkProject '')"
        [[ "$parked" == *'"ok":true'* && "$parked" == *'"count":1'* ]]; check $? "park records the window ($parked)"
        wait_for 10 no_window; check $? "park closes the window"
        [ -s "$HOME/.config/adaptive-desktop/snapshots/$pid.json" ]; check $? "park writes the snapshot"
        resumed="$(call ResumeProject '')"
        [[ "$resumed" == *'"ok":true'* ]]; check $? "resume relaunches it ($resumed)"
        wait_for 25 has_window; check $? "the window is back after resume"
        wait_for 10 test -e "$STARTED"; check $? "resume runs the project's startup command"
        [ ! -e "$HOME/.config/adaptive-desktop/snapshots/$pid.json" ]; check $? "resume clears the snapshot"
        [[ "$(call ResumeProject '')" == *'"ok":false'* ]]; check $? "resume with nothing parked fails politely"
    else
        echo "SKIP park/resume: $APP did not open a window in the sandbox"
    fi

    # ------------------------------------------------ drop-down terminal
    mkdir -p "$HOME/.config/adaptive-desktop"
    echo '{"terminal": "gnome-terminal", "height": 0.5}' >"$HOME/.config/adaptive-desktop/dropdown.json"
    DROPDOWN='const w = global.display.get_tab_list(imports.gi.Meta.TabList.NORMAL_ALL, null)
        .find(x => /gnome-terminal/i.test(x.get_wm_class() || ""));'
    if command -v gnome-terminal >/dev/null; then
        [ "$(call Run dropdown-terminal)" = "(true,)" ]; check $? "the drop-down terminal starts"
        terminal_up() { [ "$(probe "$DROPDOWN return !!w")" = true ]; }
        if wait_for 20 terminal_up; then
            sleep 1.5
            placed="$(probe "$DROPDOWN
                const area = global.workspace_manager.get_active_workspace().get_work_area_for_monitor(w.get_monitor());
                const r = w.get_frame_rect();
                // A terminal sizes itself in whole character cells, so it can
                // be up to one cell narrower than the screen.
                return [r.x === area.x, r.y === area.y, area.width - r.width >= 0 && area.width - r.width < 40,
                    w.is_above(), w.has_focus()];")"
            [ "$placed" = "[true,true,true,true,true]" ]
            check $? "it sits across the top of the screen, above other windows, focused ($placed)"
            call Run dropdown-terminal >/dev/null; sleep 1
            [ "$(probe "$DROPDOWN return w.minimized")" = true ]; check $? "the shortcut again hides it"
            call Run dropdown-terminal >/dev/null; sleep 1
            [ "$(probe "$DROPDOWN return [w.minimized, w.has_focus()]")" = "[false,true]" ]
            check $? "and again brings it back, focused"
            probe "$DROPDOWN w.delete(global.get_current_time()); return true" >/dev/null
            terminal_gone() { ! terminal_up; }
            wait_for 10 terminal_gone; check $? "closing it is noticed"
        else
            echo "SKIP drop-down terminal: gnome-terminal opened no window in the sandbox"
        fi
    fi

    # ------------------------------------------------------- lock screen
    # Lock for real: the shell switches to unlock-dialog mode, the extension
    # dresses the lock screen, and unlocking has to bring the desktop back.
    locked="$(probe "$SLEEP return (async () => { Main.screenShield.lock(false); await sleep(3000);
        return [Main.sessionMode.currentMode, Main.sessionMode.isLocked,
            Main.screenShield._dialog ? Main.screenShield._dialog.constructor.name : '']; })();")"
    [ "$locked" = '["unlock-dialog",true,"UnlockDialog"]' ]; check $? "the session locks ($locked)"
    grep -q 'lock screen clock extended' "$SANDBOX/shell.log"; check $? "the Adaptive lock screen is built"
    unlocked="$(probe "$SLEEP return (async () => { Main.screenShield.deactivate(false); await sleep(3000);
        return [Main.sessionMode.currentMode, Main.sessionMode.isLocked,
            !!Main.panel.statusArea['adaptive-project']]; })();")"
    [ "$unlocked" = '["user",false,true]' ]; check $? "unlocking brings the desktop back ($unlocked)"
    [[ "$(call ListWindows)" == "('["* ]]; check $? "the bridge still answers after unlock"

    # ---------------------------------------------------------- watchdog
    WATCHDOG="$HOME/.cache/adaptive-desktop/shell-watchdog.json"
    grep -q '"tripped":false' "$WATCHDOG"; check $? "watchdog recorded this start"

    if [ -n "$EXTRA" ]; then
        # shellcheck disable=SC1090
        . "$EXTRA"
    fi

    # Disable and enable again: detach() has to undo everything attach() did,
    # and a module that leaves something behind fails on the second enable.
    extensions DisableExtension "$UUID" >/dev/null
    sleep 2
    ! call ListWindows >/dev/null 2>&1; check $? "disable removes the bridge"
    grep -q '"starts":\[\]' "$WATCHDOG"; check $? "a clean disable clears the watchdog record"
    extensions EnableExtension "$UUID" >/dev/null
    wait_for 20 call ListWindows
    check $? "extension enables a second time"
    errors="$(extensions GetExtensionErrors "$UUID")"
    [ "$errors" = "(@as [],)" ]; check $? "no errors after disable and enable ($errors)"

    # Tripped: the desktop must not be built, and re-arming brings it back.
    extensions DisableExtension "$UUID" >/dev/null; sleep 2
    echo '{"starts":[],"tripped":true}' >"$WATCHDOG"
    extensions EnableExtension "$UUID" >/dev/null; sleep 3
    [ "$(probe "return !!Main.panel.statusArea['adaptive-project']")" = false ]
    check $? "a tripped watchdog leaves stock GNOME in place"
    extensions DisableExtension "$UUID" >/dev/null; sleep 2
    rm -f "$WATCHDOG"
    extensions EnableExtension "$UUID" >/dev/null
    wait_for 20 call ListWindows; check $? "re-armed, the desktop builds again"

    kill -0 "$SHELL_PID" 2>/dev/null; check $? "gnome-shell is still running"

    # Anything the extension threw lands in the shell's log with its path.
    thrown="$(grep -cE "JS ERROR|$UUID.*(Error|error)" "$SANDBOX/shell.log" || true)"
    [ "$thrown" = 0 ]; check $? "no JS errors in the shell log ($thrown)"
    if [ "$thrown" != 0 ]; then
        grep -nE -A6 "JS ERROR|$UUID.*(Error|error)" "$SANDBOX/shell.log" | head -60
    fi

    echo
    if [ "$failures" != 0 ]; then
        echo "$failures nested shell check(s) failed"
        exit 1
    fi
    echo "Nested shell checks passed"
    exit 0
fi

# ----------------------------------------------------------------- outer

for tool in xvfb-run dbus-run-session gnome-shell gdbus; do
    if ! command -v "$tool" >/dev/null; then
        echo "SKIP nested shell: $tool is not installed"
        exit 0
    fi
done

SANDBOX="$(mktemp -d "${TMPDIR:-/tmp}/adaptive-nested.XXXXXX")"
cleanup() {
    if [ "$KEEP" = 1 ]; then
        echo "Sandbox kept: $SANDBOX"
    else
        rm -rf "$SANDBOX" 2>/dev/null || { sleep 2; rm -rf "$SANDBOX"; }
    fi
}
trap cleanup EXIT

mkdir -p "$SANDBOX/home/.local/share/gnome-shell/extensions" "$SANDBOX/home/.config" \
    "$SANDBOX/home/.cache" "$SANDBOX/run"
chmod 700 "$SANDBOX/run"
cp -r "$REPO/shell/$UUID" "$SANDBOX/home/.local/share/gnome-shell/extensions/"
cp -r "$REPO/scripts/nested-probe/$PROBE" "$SANDBOX/home/.local/share/gnome-shell/extensions/"
# The shell modules find their scripts under ~/adaptive-desktop.
ln -s "$REPO" "$SANDBOX/home/adaptive-desktop"

env -u DCONF_PROFILE -u WAYLAND_DISPLAY -u GNOME_SHELL_SESSION_MODE \
    -u XDG_CURRENT_DESKTOP -u DESKTOP_SESSION -u XDG_CONFIG_HOME -u XDG_DATA_HOME \
    -u XDG_CACHE_HOME \
    HOME="$SANDBOX/home" SANDBOX="$SANDBOX" ADAPTIVE_NESTED_SANDBOX="$SANDBOX" INNER=1 \
    XDG_SESSION_TYPE=wayland XDG_RUNTIME_DIR="$SANDBOX/run" \
    timeout 180 xvfb-run -a -s "-screen 0 1600x1000x24" \
    dbus-run-session -- "$0" --inner ${EXTRA:+--extra "$EXTRA"} >"$SANDBOX/session.log" 2>&1
status=$?
cat "$SANDBOX/results.txt" 2>/dev/null || echo "FAIL the sandbox session did not start (see session.log with --keep)"

if [ "$status" != 0 ] && [ "$KEEP" = 0 ]; then
    echo "--- last lines of the shell log"
    tail -25 "$SANDBOX/shell.log" 2>/dev/null
fi
exit "$status"
