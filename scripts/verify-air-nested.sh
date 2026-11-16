#!/usr/bin/env bash
# Sourced by verify-shell-nested.sh --extra; runs only in its isolated desktop.
#
# Air end to end, without a camera: services/adaptive-air/air.py --demo owns org.adaptive.Air on
# the sandbox's bus and plays its scripted hands through the real gesture engine. A stand-in
# window with one big button counts clicks. Checked from inside the shell: the HUD and the camera
# indicator appear, the real pointer follows the hand, the pinch clicks the button, the fist
# carries the window, a second fist grows it, the throw gives it the right half, the swipes change desktop and come
# back, the two-hand spread opens the overview and the collapse closes it, the drop of the hands
# disengages, and when the service stops everything is let go and the indicator leaves.
# AIR_SHOT_DIR=<dir> keeps a screenshot of the HUD there.
air_probe() { probe "$SLEEP return (async () => { $1 })();"; }
air_until() {  # air_until <seconds> <js expression>: true once it holds, else its last value
    air_probe "const air = adaptive.extension._shell._air;
        for (let i = 0; i < $1 * 20; i++) { if ($2) return true; await sleep(50); }
        return String($2);"
}

AIR_CLICKS="$SANDBOX/air-clicks.txt"
: >"$AIR_CLICKS"
WAYLAND_DISPLAY=wayland-0 GDK_BACKEND=wayland /usr/bin/python3 - "$AIR_CLICKS" \
        >"$SANDBOX/air-window.log" 2>&1 <<'PY' &
import sys
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
win = Gtk.Window(title="Air test window")
win.set_default_size(640, 420)
from gi.repository import Gdk
def note(text):
    with open(sys.argv[1], "a") as f:
        f.write(text + "\n")
def on_press(_w, ev):
    if ev.button == 3:
        note("right-click")
    return False
def on_scroll(_w, ev):
    ctrl = "ctrl-" if ev.state & Gdk.ModifierType.CONTROL_MASK else ""
    if ev.direction == Gdk.ScrollDirection.SMOOTH:
        ok, dx, dy = ev.get_scroll_deltas()
        note(ctrl + ("scroll-down" if dy > 0 else "scroll-up"))
    else:
        note(ctrl + {Gdk.ScrollDirection.UP: "scroll-up", Gdk.ScrollDirection.DOWN: "scroll-down"}
             .get(ev.direction, "scroll-side"))
    return True
button = Gtk.Button(label="Pinch me")
button.connect("clicked", lambda *_: note("click"))
button.connect("button-press-event", on_press)
button.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
button.connect("scroll-event", on_scroll)
win.add(button)
win.connect("destroy", Gtk.main_quit)
win.show_all()
Gtk.main()
PY
AIR_WINDOW_PID=$!
AIR_WIN='global.get_window_actors().map(a => a.meta_window).find(w => w.get_title() === "Air test window")'

[ "$(air_until 15 "$AIR_WIN")" = true ]; check $? "air: the stand-in window opened"
# Put it in the middle of the screen, where the demo's hand engages.
air_probe "const w = $AIR_WIN; const m = Main.layoutManager.primaryMonitor; const r = w.get_frame_rect();
    w.move_frame(true, m.x + Math.round((m.width - r.width) / 2), m.y + Math.round((m.height - r.height) / 2));
    w.activate(global.get_current_time()); return true;" >/dev/null

python3 "$REPO/services/adaptive-air/air.py" --demo >"$SANDBOX/air-demo.log" 2>&1 &
AIR_DEMO_PID=$!

[ "$(air_until 6 "air._engaged && air._chip.opacity > 0")" = true ]
check $? "air: an open palm held still engages (brackets, chip)"
[ "$(air_until 2 "!!Main.panel.statusArea['adaptive-air']")" = true ]
check $? "air: the top bar shows the camera indicator while Air runs"
seen="$(air_until 3 "air._reticle.visible && air._skeleton.visible && air._layer.visible")"
[ "$seen" = true ]; check $? "air: the reticle and the hand skeleton are drawn ($seen)"

if [ -n "${AIR_SHOT_DIR:-}" ]; then
    mkdir -p "$AIR_SHOT_DIR"
    air_probe "await sleep(500);
        const shot = new imports.gi.Shell.Screenshot();
        const file = imports.gi.Gio.File.new_for_path('$AIR_SHOT_DIR/air-hud.png');
        const stream = file.replace(null, false, 0, null);
        await new Promise(r => shot.screenshot(false, stream, (o, res) => { o.screenshot_finish(res); r(); }));
        stream.close(null); return true;" >/dev/null
fi

seen="$(air_until 2 "air._pointerAt && (([x, y]) => Math.abs(x - air._pointerAt[0]) <= 2 && Math.abs(y - air._pointerAt[1]) <= 2)(global.get_pointer())")"
[ "$seen" = true ]; check $? "air: the real pointer follows the hand ($seen)"

wait_for 6 grep -qx click "$AIR_CLICKS"; check $? "air: a pinch clicks the button under the pointer"
wait_for 4 grep -qx right-click "$AIR_CLICKS"; check $? "air: thumb on the middle finger right-clicks"
wait_for 4 grep -qx scroll-down "$AIR_CLICKS"; check $? "air: the V sign moved up scrolls the window down"
wait_for 4 grep -qx ctrl-scroll-up "$AIR_CLICKS"; check $? "air: the V sign pushed forward zooms in (Ctrl + wheel)"
seen="$(air_until 6 "air._resizedTo && air._resizedTo.width > 700")"
[ "$seen" = true ]; check $? "air: a second fist pulled away grows the held window ($seen)"

seen="$(air_until 6 "(w => { const r = w.get_frame_rect(); const a = Main.layoutManager.getWorkAreaForMonitor(w.get_monitor());
    return Math.abs(r.x - (a.x + Math.round(a.width / 2))) <= 2 && Math.abs(r.width - Math.round(a.width / 2)) <= 2; })($AIR_WIN)")"
[ "$seen" = true ]; check $? "air: a fist carries the window and a throw right gives it the right half ($seen)"

[ "$(air_until 4 "global.workspace_manager.get_active_workspace_index() === 1")" = true ]
check $? "air: a swipe left goes to the next desktop"
[ "$(air_until 3 "global.workspace_manager.get_active_workspace_index() === 0")" = true ]
check $? "air: a swipe right comes back"

seen="$(air_until 5 "air._history.filter(e => e === 'zoom').length >= 4")"
[ "$seen" = true ]; check $? "air: both hands pinching, pulled apart and back, zoom in and out ($seen)"
[ "$(air_until 5 "Main.overview.visible")" = true ]; check $? "air: both open palms pulled apart open the overview"
[ "$(air_until 4 "!Main.overview.visible")" = true ]; check $? "air: pushed together they close it"

[ "$(air_until 4 "!air._engaged && !air._buttonDown")" = true ]
check $? "air: hands out of view disengage and the button is up"

wait "$AIR_DEMO_PID" 2>/dev/null
[ "$(air_until 6 "!Main.panel.statusArea['adaptive-air'] && !air._layer.visible")" = true ]
check $? "air: when the service stops, the HUD and the indicator go"

kill "$AIR_WINDOW_PID" 2>/dev/null
