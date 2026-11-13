#!/usr/bin/env bash
# Sourced by verify-shell-nested.sh --extra; runs only in its isolated desktop.
#
# Glass behind Files (windowGlass.js): the backdrop is a picture of the wallpaper blurred once,
# never a live blur. Checked with a stand-in window that carries Files' application id:
# the picture is made from the wallpaper, the window gets its three bands, nothing on the window
# blurs live, the picture stays put on the screen when the window moves, and a new wallpaper
# makes a new picture.
glass_probe() { probe "return (async () => { $1 })();"; }

glass_wall() {  # glass_wall <file> <left colour> <right colour>
    /usr/bin/python3 - "$@" <<'PY'
import sys
from PIL import Image
image = Image.new("RGB", (640, 400), sys.argv[2])
image.paste(Image.new("RGB", (320, 400), sys.argv[3]), (320, 0))
image.save(sys.argv[1])
PY
}
glass_set_wall() {
    gsettings set org.gnome.desktop.background picture-uri "file://$1"
    gsettings set org.gnome.desktop.background picture-uri-dark "file://$1"
}
GLASS_FILE="$(glass_probe 'return adaptive.windowGlass.glassPath();' | tr -d '"')"
GLASS_WINDOW='global.get_window_actors().map(a => a.meta_window).find(w => w.get_wm_class() === "org.gnome.Nautilus" && w.get_window_type() === imports.gi.Meta.WindowType.NORMAL)'
GLASS_BANDS='(actor => actor.get_children().filter(c => c.style_class === "adaptive-window-glass"))'

if /usr/bin/python3 -c 'import PIL' 2>/dev/null; then
    glass_wall "$SANDBOX/wall-a.png" red blue
    glass_set_wall "$SANDBOX/wall-a.png"
    wait_for 15 test -s "$GLASS_FILE"; check $? "glass: the backdrop is made from the wallpaper"
    first_sum="$(md5sum < "$GLASS_FILE")"
    [ "$(/usr/bin/python3 -c 'import sys; from PIL import Image; i = Image.open(sys.argv[1]); print(i.size[0], i.size[0] > i.size[1])' "$GLASS_FILE")" = "640 True" ]
    check $? "glass: it is a small picture in the screen's shape"

    WAYLAND_DISPLAY=wayland-0 GDK_BACKEND=wayland /usr/bin/python3 - >"$SANDBOX/glass-window.log" 2>&1 <<'PY' &
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gio
app = Gtk.Application(application_id="org.gnome.Nautilus", flags=Gio.ApplicationFlags.NON_UNIQUE)
def activate(app):
    window = Gtk.ApplicationWindow(application=app, title="Glass stand-in")
    window.set_default_size(700, 480)
    window.show_all()
app.connect("activate", activate)
app.run([])
PY
    GLASS_PID=$!
    glass_ready() { [ "$(glass_probe "const w = $GLASS_WINDOW; return !!w && $GLASS_BANDS(w.get_compositor_private()).length === 3;")" = true ]; }
    wait_for 20 glass_ready; check $? "glass: a Files window gets its three bands"

    [ "$(glass_probe "const a = ($GLASS_WINDOW).get_compositor_private(); const bands = $GLASS_BANDS(a);
        return bands.every((b, i) => a.get_child_at_index(i) === b && b.picture && b.picture.get_content() !== null);")" = true ]
    check $? "glass: the bands sit under the window's content and carry the picture"

    [ "$(glass_probe "const a = ($GLASS_WINDOW).get_compositor_private();
        const blurs = actor => actor.get_effects().some(e => e instanceof imports.gi.Shell.BlurEffect);
        const walk = actor => blurs(actor) || actor.get_children().some(walk);
        return !walk(a);")" = true ]
    check $? "glass: nothing on the window blurs live"

    GLASS_ALIGNED="const w = $GLASS_WINDOW, a = w.get_compositor_private(), buffer = w.get_buffer_rect();
        const monitor = global.display.get_monitor_geometry(w.get_monitor());
        const ok = $GLASS_BANDS(a).every(b => Math.abs(buffer.x + b.x + b.picture.x - monitor.x) < 1 &&
            Math.abs(buffer.y + b.y + b.picture.y - monitor.y) < 1 &&
            b.picture.width === monitor.width && b.picture.height === monitor.height);"
    [ "$(glass_probe "$GLASS_ALIGNED return ok;")" = true ]
    check $? "glass: the picture covers the monitor and lines up with it"

    [ "$(glass_probe "$SLEEP const moved = $GLASS_WINDOW; const f = moved.get_frame_rect();
        moved.move_frame(true, f.x + 90, f.y + 70); await sleep(400);
        const g = moved.get_frame_rect(); $GLASS_ALIGNED return ok && (g.x !== f.x || g.y !== f.y);")" = true ]
    check $? "glass: the picture stays put on the screen when the window moves"

    glass_wall "$SANDBOX/wall-b.png" green yellow
    glass_set_wall "$SANDBOX/wall-b.png"
    glass_changed() { [ "$(md5sum < "$GLASS_FILE")" != "$first_sum" ]; }
    wait_for 15 glass_changed; check $? "glass: a new wallpaper makes a new backdrop"

    kill "$GLASS_PID" 2>/dev/null
    glass_gone() { [ "$(glass_probe "return !($GLASS_WINDOW);")" = true ]; }
    wait_for 10 glass_gone; check $? "glass: closing the window leaves nothing behind"
else
    echo "SKIP glass: Pillow is not installed for /usr/bin/python3"
fi
