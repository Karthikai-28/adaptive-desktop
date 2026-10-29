// Glass behind Files: the shell blurs what lies under each Files window, so
// the window's translucent background (extension/preview.css) reads as
// frosted glass instead of a see-through pane.
//
// GTK cannot blur what is behind its own window; only the compositor sees
// that. Each Files window actor gets blur actors as its bottom children, each
// carrying a Shell.BlurEffect in BACKGROUND mode, limited to the window's
// frame: the actor's buffer also holds GTK's client-side shadow, which must
// stay sharp. The window's corners are rounded and a blurred rectangle would
// show past them, so the blur is three bands - a strip between the top
// corners, the body, and a strip between the bottom corners.
//
// The bands sit at the buffer's origin at its full size and are cut down
// with a clip. A BACKGROUND blur on an actor offset inside its parent (GNOME
// 42) samples and paints with the offset applied twice, so a band placed at
// the frame left the top and left edges of the window unblurred.
//
// Clones (Overview thumbnails, the window switcher) paint children too, and a
// background blur inside a clone samples whatever the clone happens to sit
// on, so the blur hides while the Overview is open.

const { Meta, Shell, Clutter } = imports.gi;
const Main = imports.ui.main;

const WM_CLASSES = new Set(['org.gnome.Nautilus', 'Org.gnome.Nautilus', 'Nautilus']);
const RADIUS = 12;
const SIGMA = 32;
const BRIGHTNESS = 0.9;

var WindowGlass = class WindowGlass {
    constructor() {
        this._windows = new Map();
        this._ids = [];
    }

    attach() {
        if (!Shell.BlurEffect)
            return;
        this._ids.push([global.display, global.display.connect('window-created',
            (display, metaWindow) => this._watch(metaWindow))]);
        this._ids.push([Main.overview, Main.overview.connect('showing', () => this._relayout())]);
        this._ids.push([Main.overview, Main.overview.connect('hidden', () => this._relayout())]);
        for (const actor of global.get_window_actors())
            this._watch(actor.meta_window);
    }

    detach() {
        for (const [object, id] of this._ids)
            object.disconnect(id);
        this._ids = [];
        for (const metaWindow of [...this._windows.keys()])
            this._forget(metaWindow);
    }

    _watch(metaWindow) {
        if (!metaWindow || this._windows.has(metaWindow))
            return;
        // The class can arrive after the window does, so decide on each change.
        const entry = { ids: [], blur: null };
        this._windows.set(metaWindow, entry);
        entry.ids.push(metaWindow.connect('notify::wm-class', () => this._update(metaWindow)));
        entry.ids.push(metaWindow.connect('unmanaged', () => this._forget(metaWindow)));
        this._update(metaWindow);
    }

    _update(metaWindow) {
        const entry = this._windows.get(metaWindow);
        if (!entry)
            return;
        const wanted = WM_CLASSES.has(metaWindow.get_wm_class() || '');
        if (wanted && !entry.blur)
            this._add(metaWindow, entry);
        else if (!wanted && entry.blur)
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
            const blur = new Clutter.Actor({ reactive: false, visible: !Main.overview.visible });
            blur.add_effect(new Shell.BlurEffect({
                mode: Shell.BlurMode.BACKGROUND,
                sigma: SIGMA,
                brightness: BRIGHTNESS,
            }));
            actor.insert_child_at_index(blur, 0);
            return blur;
        };
        entry.actor = actor;
        entry.blur = [make(), make(), make()];
        entry.geometryIds = [
            metaWindow.connect('size-changed', () => this._layout(metaWindow)),
            metaWindow.connect('notify::maximized-horizontally', () => this._layout(metaWindow)),
            metaWindow.connect('notify::maximized-vertically', () => this._layout(metaWindow)),
            metaWindow.connect('notify::fullscreen', () => this._layout(metaWindow)),
        ];
        entry.destroyId = actor.connect('destroy', () => {
            entry.blur = null;
            entry.actor = null;
        });
        this._layout(metaWindow);
    }

    _layout(metaWindow) {
        const entry = this._windows.get(metaWindow);
        if (!entry || !entry.blur)
            return;
        const frame = metaWindow.get_frame_rect();
        const buffer = metaWindow.get_buffer_rect();
        const x = frame.x - buffer.x;
        const y = frame.y - buffer.y;
        const square = metaWindow.is_fullscreen() ||
            metaWindow.get_maximized() !== 0;
        const r = square ? 0 : Math.min(RADIUS, frame.width / 2, frame.height / 2);
        const w = frame.width, h = frame.height;
        const bands = [
            [x + r, y, w - 2 * r, r],
            [x, y + r, w, h - 2 * r],
            [x + r, y + h - r, w - 2 * r, r],
        ];
        entry.blur.forEach((band, i) => {
            const [bx, by, bw, bh] = bands[i];
            band.set_position(0, 0);
            band.set_size(buffer.width, buffer.height);
            band.set_clip(bx, by, Math.max(bw, 0), Math.max(bh, 0));
            band.visible = bw > 0 && bh > 0 && !Main.overview.visible;
        });
    }

    _remove(metaWindow, entry) {
        for (const id of entry.geometryIds || [])
            metaWindow.disconnect(id);
        entry.geometryIds = [];
        if (entry.actor && entry.destroyId)
            entry.actor.disconnect(entry.destroyId);
        for (const blur of entry.blur || [])
            blur.destroy();
        entry.blur = null;
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
