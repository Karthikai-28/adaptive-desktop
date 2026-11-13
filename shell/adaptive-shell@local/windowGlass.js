// Glass behind Files: the window's translucent background (extension/preview.src.css) sits on a
// picture of the wallpaper that was blurred once, so it reads as frosted glass.
//
// Nothing is blurred live. An earlier version gave each Files window a Shell.BlurEffect in
// BACKGROUND mode, which re-reads the screen behind the window on every repaint. The shell
// repaints only the part of the screen that changed, so with the pointer moving over the file
// grid (hover, a rubber-band selection, a drag) the blur sampled a mix of new and already
// composited pixels and smeared them around the pointer. It also cost a full-window blur per
// frame on the integrated GPU. The sandbox never showed it, because a nested shell repaints the
// whole frame every time.
//
// Now tools/glass_wallpaper.py crops the wallpaper to the screen's shape and blurs it into a
// small PNG whenever the wallpaper changes, and each Files window carries that picture as its
// bottom children, placed so it lines up with the screen: plain textured rectangles, nothing to
// recompute when the pointer moves. What is behind a Files window is therefore always the
// wallpaper's colours, not other windows; that is the material's definition, not a shortcut.
// Home's page uses the same file (services/mario-hub serves it), so the two backdrops match.
//
// The window's corners are rounded and a rectangle would show past them, so the picture is drawn
// as three bands: a strip between the top corners, the body, and a strip between the bottom
// corners. Each band clips a child that is the size of the monitor.

/* exported WindowGlass, glassPath */

const { Clutter, Cogl, GdkPixbuf, Gio, GLib, Meta, St } = imports.gi;
const Main = imports.ui.main;

const Me = imports.misc.extensionUtils.getCurrentExtension();

const WM_CLASSES = new Set(['org.gnome.Nautilus', 'Org.gnome.Nautilus', 'Nautilus']);
const RADIUS = 12;
const BACKGROUND_SCHEMA = 'org.gnome.desktop.background';

// One file for every reader: this module and Mario Hub (Home's backdrop).
function glassPath() {
    return GLib.build_filenamev([GLib.get_user_cache_dir(), 'adaptive-desktop', 'glass.png']);
}

var WindowGlass = class WindowGlass {
    constructor() {
        this._windows = new Map();
        this._ids = [];
        this._image = null;
        this._settings = null;
        this._source = '';
        this._making = null;
        this._again = false;
    }

    attach() {
        this._settings = new Gio.Settings({ schema_id: BACKGROUND_SCHEMA });
        for (const key of ['picture-uri', 'picture-uri-dark'])
            this._ids.push([this._settings, this._settings.connect(`changed::${key}`, () => this._refresh())]);
        this._ids.push([Main.layoutManager, Main.layoutManager.connect('monitors-changed', () => {
            this._refresh(true);
            this._relayout();
        })]);
        this._ids.push([global.display, global.display.connect('window-created',
            (display, metaWindow) => this._watch(metaWindow))]);
        // The picture from last time shows at once; a new one replaces it when it is ready.
        this._load();
        this._refresh();
        for (const actor of global.get_window_actors())
            this._watch(actor.meta_window);
    }

    detach() {
        for (const [object, id] of this._ids)
            object.disconnect(id);
        this._ids = [];
        this._settings = null;
        if (this._making) {
            this._making.force_exit();
            this._making = null;
        }
        for (const metaWindow of [...this._windows.keys()])
            this._forget(metaWindow);
        this._image = null;
    }

    // ---- the picture ---------------------------------------------------------------------

    _wallpaper() {
        // The session is dark, so the shell shows picture-uri-dark; fall back to the other key.
        for (const key of ['picture-uri-dark', 'picture-uri']) {
            const uri = this._settings.get_string(key);
            if (!uri)
                continue;
            const path = uri.startsWith('file://') ? Gio.File.new_for_uri(uri).get_path() : uri;
            if (path && GLib.file_test(path, GLib.FileTest.IS_REGULAR))
                return path;
        }
        return '';
    }

    _refresh(force = false) {
        if (!this._settings)
            return;
        const source = this._wallpaper();
        const exists = GLib.file_test(glassPath(), GLib.FileTest.IS_REGULAR);
        if (!source || (source === this._source && exists && !force))
            return;
        if (this._making) {
            // One at a time; whatever the wallpaper is when this one ends gets made next.
            this._again = true;
            return;
        }
        const monitor = Main.layoutManager.primaryMonitor;
        if (!monitor)
            return;
        const tool = Me.dir.get_child('tools').get_child('glass_wallpaper.py').get_path();
        let proc;
        try {
            proc = Gio.Subprocess.new(
                ['/usr/bin/python3', tool, source, `${monitor.width}`, `${monitor.height}`, glassPath()],
                Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE);
        } catch (e) {
            logError(e, 'Adaptive glass: could not start the backdrop helper');
            return;
        }
        this._making = proc;
        proc.wait_async(null, (object, result) => {
            let ok = false;
            try {
                object.wait_finish(result);
                ok = object.get_successful();
            } catch (e) {
                ok = false;
            }
            if (this._making !== object)
                return;          // detached meanwhile
            this._making = null;
            if (ok) {
                this._source = source;
                this._load();
            }
            if (this._again) {
                this._again = false;
                this._refresh();
            }
        });
    }

    _load() {
        const path = glassPath();
        if (!GLib.file_test(path, GLib.FileTest.IS_REGULAR))
            return;
        try {
            const pixbuf = GdkPixbuf.Pixbuf.new_from_file(path);
            const image = new Clutter.Image();
            image.set_bytes(pixbuf.read_pixel_bytes(),
                pixbuf.get_has_alpha() ? Cogl.PixelFormat.RGBA_8888 : Cogl.PixelFormat.RGB_888,
                pixbuf.get_width(), pixbuf.get_height(), pixbuf.get_rowstride());
            this._image = image;
        } catch (e) {
            logError(e, 'Adaptive glass: could not read the backdrop');
            return;
        }
        for (const entry of this._windows.values()) {
            for (const band of entry.bands || [])
                band.picture.set_content(this._image);
        }
    }

    // ---- the windows ---------------------------------------------------------------------

    _watch(metaWindow) {
        if (!metaWindow || this._windows.has(metaWindow))
            return;
        // The class and type can arrive after the window does, so decide on each change.
        const entry = { ids: [], bands: null };
        this._windows.set(metaWindow, entry);
        entry.ids.push(metaWindow.connect('notify::wm-class', () => this._update(metaWindow)));
        entry.ids.push(metaWindow.connect('notify::window-type', () => this._update(metaWindow)));
        entry.ids.push(metaWindow.connect('unmanaged', () => this._forget(metaWindow)));
        this._update(metaWindow);
    }

    _update(metaWindow) {
        const entry = this._windows.get(metaWindow);
        if (!entry)
            return;
        // Only the main windows are translucent. On X11 Files' menus, tooltips and dialogs carry
        // the same class and are opaque.
        const wanted = metaWindow.get_window_type() === Meta.WindowType.NORMAL &&
            WM_CLASSES.has(metaWindow.get_wm_class() || '');
        if (wanted && !entry.bands)
            this._add(metaWindow, entry);
        else if (!wanted && entry.bands)
            this._remove(metaWindow, entry);
    }

    _add(metaWindow, entry) {
        const actor = metaWindow.get_compositor_private();
        if (!actor) {
            // Not mapped yet: try again once it is shown.
            const id = metaWindow.connect('shown', () => {
                metaWindow.disconnect(id);
                entry.ids = entry.ids.filter(i => i !== id);
                this._update(metaWindow);
            });
            entry.ids.push(id);
            return;
        }
        const make = () => {
            // The band's own colour (stylesheet) is what shows until a picture exists, so the
            // window is never a see-through pane.
            const band = new St.Widget({
                style_class: 'adaptive-window-glass',
                reactive: false,
                clip_to_allocation: true,
                layout_manager: new Clutter.FixedLayout(),
            });
            band.picture = new Clutter.Actor({ reactive: false });
            band.picture.set_content_scaling_filters(
                Clutter.ScalingFilter.LINEAR, Clutter.ScalingFilter.LINEAR);
            if (this._image)
                band.picture.set_content(this._image);
            band.add_child(band.picture);
            actor.insert_child_at_index(band, 0);
            return band;
        };
        entry.actor = actor;
        entry.bands = [make(), make(), make()];
        entry.geometryIds = [
            metaWindow.connect('size-changed', () => this._layout(metaWindow)),
            metaWindow.connect('position-changed', () => this._layout(metaWindow)),
            metaWindow.connect('notify::maximized-horizontally', () => this._layout(metaWindow)),
            metaWindow.connect('notify::maximized-vertically', () => this._layout(metaWindow)),
            metaWindow.connect('notify::fullscreen', () => this._layout(metaWindow)),
        ];
        entry.destroyId = actor.connect('destroy', () => {
            entry.bands = null;
            entry.actor = null;
        });
        this._layout(metaWindow);
    }

    _layout(metaWindow) {
        const entry = this._windows.get(metaWindow);
        if (!entry || !entry.bands)
            return;
        const frame = metaWindow.get_frame_rect();
        const buffer = metaWindow.get_buffer_rect();
        const index = metaWindow.get_monitor();
        const monitor = index >= 0 ? global.display.get_monitor_geometry(index) : frame;
        const x = frame.x - buffer.x;
        const y = frame.y - buffer.y;
        const square = metaWindow.is_fullscreen() || metaWindow.get_maximized() !== 0;
        const r = square ? 0 : Math.min(RADIUS, frame.width / 2, frame.height / 2);
        const w = frame.width, h = frame.height;
        const rects = [
            [x + r, y, w - 2 * r, r],
            [x, y + r, w, h - 2 * r],
            [x + r, y + h - r, w - 2 * r, r],
        ];
        entry.bands.forEach((band, i) => {
            const [bx, by, bw, bh] = rects[i];
            band.visible = bw > 0 && bh > 0;
            band.set_position(bx, by);
            band.set_size(Math.max(bw, 0), Math.max(bh, 0));
            // The picture covers the monitor; shift it so it stays put on the screen while the
            // window moves over it.
            band.picture.set_position(monitor.x - buffer.x - bx, monitor.y - buffer.y - by);
            band.picture.set_size(monitor.width, monitor.height);
        });
    }

    _remove(metaWindow, entry) {
        for (const id of entry.geometryIds || [])
            metaWindow.disconnect(id);
        entry.geometryIds = [];
        if (entry.actor && entry.destroyId)
            entry.actor.disconnect(entry.destroyId);
        for (const band of entry.bands || [])
            band.destroy();
        entry.bands = null;
        entry.actor = null;
    }

    _forget(metaWindow) {
        const entry = this._windows.get(metaWindow);
        if (!entry)
            return;
        this._remove(metaWindow, entry);
        for (const id of entry.ids)
            metaWindow.disconnect(id);
        this._windows.delete(metaWindow);
    }

    _relayout() {
        for (const metaWindow of this._windows.keys())
            this._layout(metaWindow);
    }
};
