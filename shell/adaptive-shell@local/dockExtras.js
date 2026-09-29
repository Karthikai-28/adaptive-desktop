// Adaptive dock extras
//
// The parts of the dock that stand on their own, so extension.js only wires
// them in:
//
//   - dock settings (icon size, magnification, auto-hide, extra items), kept in
//     ~/.config/adaptive-desktop/dock.json
//   - unread badges, progress bars and urgency from the Unity LauncherEntry
//     D-Bus API, which Slack, Chrome and most Electron apps already broadcast
//   - live window previews above an app's icon
//   - the Downloads stack and the Trash
//
// Nothing here polls: badges arrive as D-Bus signals, the Trash is a file
// monitor, and Downloads is read only when its stack is opened.

/* exported readDockConfig, writeDockConfig, ICON_SIZES, MAGNIFICATION,
   LauncherEntries, WindowPreviews, openDownloadsStack, TrashWatcher,
   confirmEmptyTrash */

const { Clutter, Gio, GLib, Pango, St } = imports.gi;
const Main = imports.ui.main;
const ModalDialog = imports.ui.modalDialog;
const Dialog = imports.ui.dialog;
const PopupMenu = imports.ui.popupMenu;

// ----------------------------------------------------------------- settings

const CONFIG_PATH = GLib.build_filenamev(
    [GLib.get_user_config_dir(), 'adaptive-desktop', 'dock.json']);

const DEFAULTS = {
    iconSize: 'medium',
    magnification: 'medium',
    // smart: hide only for a maximized or fullscreen window (the old rule)
    autoHide: 'smart',
    showRecent: false,
    showDownloads: true,
    showTrash: true,
    perMonitor: true,
};

// Icon size in pixels.
var ICON_SIZES = { small: 30, medium: 36, large: 44 };

// [hovered scale, hovered lift, neighbour scale, neighbour lift]
var MAGNIFICATION = {
    off: [1.0, 0, 1.0, 0],
    low: [1.1, -3, 1.04, -1],
    medium: [1.18, -5, 1.08, -1],
    high: [1.36, -10, 1.14, -3],
};

function readDockConfig() {
    let saved = {};
    try {
        const [ok, bytes] = GLib.file_get_contents(CONFIG_PATH);
        if (ok)
            saved = JSON.parse(new TextDecoder().decode(bytes)) || {};
    } catch (e) {
        // Missing or unreadable: defaults.
    }
    return Object.assign({}, DEFAULTS, saved);
}

function writeDockConfig(patch) {
    try {
        GLib.mkdir_with_parents(GLib.path_get_dirname(CONFIG_PATH), 0o755);
        let saved = {};
        try {
            const [ok, bytes] = GLib.file_get_contents(CONFIG_PATH);
            if (ok)
                saved = JSON.parse(new TextDecoder().decode(bytes)) || {};
        } catch (e) {
        }
        GLib.file_set_contents(CONFIG_PATH,
            `${JSON.stringify(Object.assign(saved, patch), null, 2)}\n`);
    } catch (e) {
        logError(e, '[Adaptive Dock] saving dock.json');
    }
}

// ---------------------------------------------------- badges and progress

// com.canonical.Unity.LauncherEntry.Update(s app_uri, a{sv} properties):
// count, count-visible, progress, progress-visible, urgent. Apps broadcast it
// on the session bus; this keeps the latest per app, forgets an app's entry
// when the process that sent it goes away, and calls onChange(desktopId).
var LauncherEntries = class LauncherEntries {
    constructor(onChange) {
        this._callbacks = { onChange };
        this._entries = new Map();
        this._senders = new Map();

        this._updateId = Gio.DBus.session.signal_subscribe(null,
            'com.canonical.Unity.LauncherEntry', 'Update', null, null,
            Gio.DBusSignalFlags.NONE,
            (_c, sender, _path, _iface, _signal, params) => {
                try {
                    const [uri, props] = params.deep_unpack();
                    this._update(sender, uri, props);
                } catch (e) {
                    logError(e, '[Adaptive Dock] launcher entry');
                }
            });

        this._ownerId = Gio.DBus.session.signal_subscribe('org.freedesktop.DBus',
            'org.freedesktop.DBus', 'NameOwnerChanged', '/org/freedesktop/DBus',
            null, Gio.DBusSignalFlags.NONE,
            (_c, _s, _p, _i, _sig, params) => {
                const [name, , newOwner] = params.deep_unpack();
                if (newOwner || !this._senders.has(name))
                    return;
                for (const id of this._senders.get(name)) {
                    this._entries.delete(id);
                    this._callbacks.onChange(id);
                }
                this._senders.delete(name);
            });
    }

    _update(sender, uri, props) {
        const id = uri.replace(/^application:\/\//, '');
        const entry = this._entries.get(id) || {};
        for (const [key, value] of Object.entries(props))
            entry[key] = value instanceof GLib.Variant ? value.deep_unpack() : value;
        this._entries.set(id, entry);

        if (!this._senders.has(sender))
            this._senders.set(sender, new Set());
        this._senders.get(sender).add(id);

        this._callbacks.onChange(id);
    }

    // Apps name themselves loosely: Slack's snap is slack_slack.desktop but it
    // reports slack.desktop. Match exactly, then on the name after a snap's
    // "<snap>_" prefix.
    lookup(app) {
        const id = app.get_id() || '';
        if (this._entries.has(id))
            return this._entries.get(id);

        const bare = id.replace(/\.desktop$/, '');
        for (const [key, entry] of this._entries) {
            const other = key.replace(/\.desktop$/, '');
            if (bare === other || bare.endsWith(`_${other}`) || other.endsWith(`_${bare}`))
                return entry;
        }
        return null;
    }

    matches(app, desktopId) {
        const entry = this._entries.get(desktopId);
        return !!entry && this.lookup(app) === entry;
    }

    destroy() {
        Gio.DBus.session.signal_unsubscribe(this._updateId);
        Gio.DBus.session.signal_unsubscribe(this._ownerId);
        this._entries.clear();
        this._senders.clear();
    }
};

// ---------------------------------------------------------- window previews

const PREVIEW_W = 200;
const PREVIEW_H = 124;
const PREVIEW_SHOW_MS = 550;
const PREVIEW_HIDE_MS = 280;
const PREVIEW_MAX = 6;

// Live thumbnails of an app's windows above its dock icon. Hovering an icon
// for a moment shows them; moving into the strip keeps it open; a click
// switches to that window, and the × closes it.
var WindowPreviews = class WindowPreviews {
    constructor({ onActivate, windowsFor, onShow = null }) {
        this._callbacks = { onActivate, windowsFor, onShow };
        this._actor = null;
        this._showId = 0;
        this._hideId = 0;
        this._button = null;
    }

    get hovered() {
        return !!(this._actor && this._actor.hover);
    }

    get visible() {
        return !!this._actor;
    }

    hoverStart(button, app) {
        this._cancelHide();
        this._cancelShow();
        if (this._actor && this._button === button)
            return;
        this._showId = GLib.timeout_add(GLib.PRIORITY_DEFAULT,
            this._actor ? 120 : PREVIEW_SHOW_MS, () => {
                this._showId = 0;
                if (button.hover && this._callbacks.windowsFor(app).length)
                    this.show(button, app);
                return GLib.SOURCE_REMOVE;
            });
    }

    hoverEnd() {
        this._cancelShow();
        this._scheduleHide();
    }

    _scheduleHide() {
        this._cancelHide();
        this._hideId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, PREVIEW_HIDE_MS, () => {
            this._hideId = 0;
            const onButton = this._button && this._button.hover;
            if (!this.hovered && !onButton)
                this.hide();
            return GLib.SOURCE_REMOVE;
        });
    }

    _cancelShow() {
        if (this._showId) {
            GLib.Source.remove(this._showId);
            this._showId = 0;
        }
    }

    _cancelHide() {
        if (this._hideId) {
            GLib.Source.remove(this._hideId);
            this._hideId = 0;
        }
    }

    show(button, app) {
        this.hide();
        const windows = this._callbacks.windowsFor(app).slice(0, PREVIEW_MAX);
        if (!windows.length)
            return;

        this._button = button;
        if (this._callbacks.onShow)
            this._callbacks.onShow();
        const strip = new St.BoxLayout({
            style_class: 'adaptive-dock-previews',
            reactive: true,
            track_hover: true,
        });
        strip.connect('notify::hover', () => {
            if (strip.hover)
                this._cancelHide();
            else
                this._scheduleHide();
        });

        for (const window of windows)
            strip.add_child(this._preview(app, window));

        Main.layoutManager.addChrome(strip);
        this._actor = strip;

        // Centred over the icon, kept on the icon's monitor.
        const [bx, by] = button.get_transformed_position();
        const [bw] = button.get_transformed_size();
        const [, width] = strip.get_preferred_width(-1);
        const [, height] = strip.get_preferred_height(width);
        const monitor = Main.layoutManager.findMonitorForActor(button) ||
            Main.layoutManager.primaryMonitor;
        let x = Math.round(bx + bw / 2 - width / 2);
        x = Math.max(monitor.x + 8, Math.min(x, monitor.x + monitor.width - width - 8));
        strip.set_position(x, Math.round(by - height - 10));

        strip.opacity = 0;
        strip.ease({ opacity: 255, duration: 120, mode: Clutter.AnimationMode.EASE_OUT_QUAD });
    }

    _preview(app, window) {
        const item = new St.Button({
            style_class: 'adaptive-dock-preview',
            can_focus: true,
            reactive: true,
            accessible_name: window.get_title() || app.get_name(),
        });
        const box = new St.BoxLayout({ vertical: true, style_class: 'adaptive-dock-preview-box' });
        item.set_child(box);

        const header = new St.BoxLayout({ style_class: 'adaptive-dock-preview-header' });
        const title = new St.Label({
            text: window.get_title() || app.get_name(),
            style_class: 'adaptive-dock-preview-title',
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        title.clutter_text.ellipsize = Pango.EllipsizeMode.END;
        header.add_child(title);

        const close = new St.Button({
            style_class: 'adaptive-dock-preview-close',
            can_focus: true,
            accessible_name: 'Close window',
            child: new St.Icon({ icon_name: 'window-close-symbolic' }),
        });
        close.connect('clicked', () => {
            try {
                window.delete(global.get_current_time());
            } catch (e) {
                logError(e, '[Adaptive Dock] close from preview');
            }
            item.destroy();
            if (this._actor && this._actor.get_n_children() === 0)
                this.hide();
        });
        header.add_child(close);
        box.add_child(header);

        const frame = new St.Widget({
            style_class: 'adaptive-dock-preview-frame',
            layout_manager: new Clutter.BinLayout(),
            width: PREVIEW_W,
            height: PREVIEW_H,
        });
        box.add_child(frame);

        // A minimized window has nothing to clone; show the app icon instead.
        const actor = window.get_compositor_private();
        if (actor && !window.minimized && actor.width > 0 && actor.height > 0) {
            const scale = Math.min(PREVIEW_W / actor.width, PREVIEW_H / actor.height, 1);
            frame.add_child(new Clutter.Clone({
                source: actor,
                width: Math.round(actor.width * scale),
                height: Math.round(actor.height * scale),
                x_align: Clutter.ActorAlign.CENTER,
                y_align: Clutter.ActorAlign.CENTER,
            }));
        } else {
            const icon = app.create_icon_texture(48);
            icon.x_align = Clutter.ActorAlign.CENTER;
            icon.y_align = Clutter.ActorAlign.CENTER;
            frame.add_child(icon);
        }

        item.connect('clicked', () => {
            this.hide();
            this._callbacks.onActivate(window);
        });
        return item;
    }

    hide() {
        this._cancelShow();
        this._cancelHide();
        if (this._actor) {
            Main.layoutManager.removeChrome(this._actor);
            this._actor.destroy();
            this._actor = null;
        }
        this._button = null;
    }

    destroy() {
        this.hide();
    }
};

// ---------------------------------------------------------- downloads stack

const STACK_MAX = 12;
const STACK_COLUMNS = 4;

// The macOS Downloads stack: the newest files in ~/Downloads as a grid over
// the dock icon, each opening in its default app. Read when opened, so a busy
// Downloads folder costs nothing the rest of the time.
function openDownloadsStack(button, menuManager, trackMenu) {
    const dirPath = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD) ||
        GLib.build_filenamev([GLib.get_home_dir(), 'Downloads']);
    const dir = Gio.File.new_for_path(dirPath);

    const menu = new PopupMenu.PopupMenu(button, 0.5, St.Side.BOTTOM);
    menu.actor.add_style_class_name('adaptive-dock-popup');
    menu.box.add_style_class_name('adaptive-dock-stack-menu');
    Main.uiGroup.add_actor(menu.actor);
    menu.actor.hide();
    menuManager.addMenu(menu);
    trackMenu(menu);

    const root = new St.BoxLayout({ vertical: true, style_class: 'adaptive-dock-stack' });
    menu.box.add_child(root);

    const header = new St.BoxLayout({ style_class: 'adaptive-dock-stack-header' });
    header.add_child(new St.Label({
        text: 'Downloads',
        style_class: 'adaptive-dock-stack-title',
        x_expand: true,
        y_align: Clutter.ActorAlign.CENTER,
    }));
    const openFolder = new St.Button({
        style_class: 'adaptive-dock-stack-link',
        label: 'Open in Files',
        can_focus: true,
    });
    openFolder.connect('clicked', () => {
        menu.close();
        Gio.AppInfo.launch_default_for_uri(dir.get_uri(), null);
    });
    header.add_child(openFolder);
    root.add_child(header);

    const grid = new St.Widget({
        style_class: 'adaptive-dock-stack-grid',
        layout_manager: new Clutter.GridLayout({ column_spacing: 6, row_spacing: 6 }),
    });
    root.add_child(grid);

    const status = new St.Label({ text: 'Loading…', style_class: 'adaptive-dock-stack-status' });
    root.add_child(status);

    const attrs = 'standard::name,standard::display-name,standard::icon,standard::is-hidden,' +
        'time::modified,thumbnail::path';
    dir.enumerate_children_async(attrs, Gio.FileQueryInfoFlags.NONE,
        GLib.PRIORITY_DEFAULT, null, (d, res) => {
            let files = [];
            try {
                const enumerator = d.enumerate_children_finish(res);
                let info;
                while ((info = enumerator.next_file(null)) !== null) {
                    if (!info.get_is_hidden())
                        files.push(info);
                }
                enumerator.close(null);
            } catch (e) {
                status.text = "Couldn't read Downloads.";
                return;
            }

            files.sort((a, b) =>
                b.get_attribute_uint64('time::modified') - a.get_attribute_uint64('time::modified'));
            files = files.slice(0, STACK_MAX);

            status.visible = files.length === 0;
            status.text = 'Downloads is empty.';

            files.forEach((info, i) => {
                const file = dir.get_child(info.get_name());
                const tile = new St.Button({
                    style_class: 'adaptive-dock-stack-item',
                    can_focus: true,
                    accessible_name: info.get_display_name(),
                });
                const box = new St.BoxLayout({ vertical: true, x_align: Clutter.ActorAlign.CENTER });
                tile.set_child(box);

                const thumbnail = info.get_attribute_byte_string('thumbnail::path');
                box.add_child(new St.Icon({
                    gicon: thumbnail
                        ? new Gio.FileIcon({ file: Gio.File.new_for_path(thumbnail) })
                        : info.get_icon(),
                    icon_size: 48,
                    style_class: 'adaptive-dock-stack-icon',
                    x_align: Clutter.ActorAlign.CENTER,
                }));
                const name = new St.Label({
                    text: info.get_display_name(),
                    style_class: 'adaptive-dock-stack-name',
                    x_align: Clutter.ActorAlign.CENTER,
                });
                name.clutter_text.ellipsize = Pango.EllipsizeMode.MIDDLE;
                box.add_child(name);

                tile.connect('clicked', () => {
                    menu.close();
                    try {
                        Gio.AppInfo.launch_default_for_uri(file.get_uri(), null);
                    } catch (e) {
                        logError(e, '[Adaptive Dock] opening a download');
                    }
                });
                grid.layout_manager.attach(tile, i % STACK_COLUMNS, Math.floor(i / STACK_COLUMNS), 1, 1);
            });
        });

    menu.open();
    return menu;
}

// -------------------------------------------------------------------- trash

// Whether the Trash holds anything, kept current by a file monitor on
// trash:///, calling onChange(count).
var TrashWatcher = class TrashWatcher {
    constructor(onChange) {
        this._callbacks = { onChange };
        this._file = Gio.File.new_for_uri('trash:///');
        this.count = 0;
        try {
            this._monitor = this._file.monitor_directory(Gio.FileMonitorFlags.NONE, null);
            this._monitorId = this._monitor.connect('changed', () => this.refresh());
        } catch (e) {
            this._monitor = null;
        }
        this.refresh();
    }

    refresh() {
        this._file.query_info_async('trash::item-count', Gio.FileQueryInfoFlags.NONE,
            GLib.PRIORITY_DEFAULT, null, (f, res) => {
                try {
                    this.count = f.query_info_finish(res).get_attribute_uint32('trash::item-count');
                } catch (e) {
                    this.count = 0;
                }
                this._callbacks.onChange(this.count);
            });
    }

    destroy() {
        if (this._monitor) {
            this._monitor.disconnect(this._monitorId);
            this._monitor.cancel();
            this._monitor = null;
        }
    }
};

// Emptying the Trash cannot be undone, so it asks first - as Files does.
function confirmEmptyTrash(count, onConfirm) {
    const dialog = new ModalDialog.ModalDialog({ styleClass: 'adaptive-dock-dialog' });
    const noun = count === 1 ? 'item' : 'items';
    dialog.contentLayout.add_child(new Dialog.MessageDialogContent({
        title: 'Empty Trash?',
        description: `${count} ${noun} will be permanently deleted. This can't be undone.`,
    }));
    dialog.addButton({
        label: 'Cancel',
        action: () => dialog.close(),
        key: Clutter.KEY_Escape,
    });
    dialog.addButton({
        label: 'Empty Trash',
        action: () => {
            dialog.close();
            onConfirm();
        },
        default: false,
    });
    dialog.open();
}
