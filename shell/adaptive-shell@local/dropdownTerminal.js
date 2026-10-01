// Adaptive drop-down terminal.
//
// One terminal that drops from the top of the screen on a shortcut and goes
// away on the same shortcut, in the active project's folder the first time it
// opens. It is an ordinary terminal window (Terminator if it is installed,
// otherwise GNOME Terminal); the shell only starts it, places it and toggles
// it, which is the part an outside script cannot do reliably.
//
//   gdbus call --session -d org.gnome.Shell -o /org/adaptive/Shell \
//       -m org.adaptive.Shell.Run dropdown-terminal
//
// Toggle: not there -> start it; there but hidden, behind or on another
// workspace -> bring it here and focus it; focused -> hide it.
//
// ~/.config/adaptive-desktop/dropdown.json may set {"terminal": "terminator" |
// "gnome-terminal", "height": 0.2 - 1.0}. The placement and the command line
// are adaptiveUtil's and checked under Node.

/* exported DropdownTerminal */

const { Gio, GLib, Meta } = imports.gi;
const Main = imports.ui.main;

const Me = imports.misc.extensionUtils.getCurrentExtension();
const Util = Me.imports.adaptiveUtil;

const CONFIG_PATH = GLib.build_filenamev(
    [GLib.get_user_config_dir(), 'adaptive-desktop', 'dropdown.json']);
// How long a started terminal has to show its window before we stop waiting.
const ADOPT_FOR_S = 15;

function readConfig() {
    try {
        const [ok, bytes] = GLib.file_get_contents(CONFIG_PATH);
        return ok ? JSON.parse(new TextDecoder().decode(bytes)) : {};
    } catch (e) {
        return {};
    }
}

var DropdownTerminal = class DropdownTerminal {
    constructor() {
        this._window = null;
        this._unmanagedId = 0;
        this._createdId = 0;
        this._expireId = 0;
        this._kind = '';
    }

    attach() {
    }

    detach() {
        this._stopWaiting();
        this._forget();
    }

    toggle() {
        const window = this._find();
        if (!window) {
            this._start();
            return true;
        }

        const here = global.workspace_manager.get_active_workspace();
        const shown = !window.minimized && window.get_workspace() === here;
        if (shown && global.display.focus_window === window) {
            window.minimize();
            return true;
        }
        this._present(window);
        return true;
    }

    // The window we started, or - after a shell restart on X11, where windows
    // outlive the shell - the one still carrying our role.
    _find() {
        if (this._window)
            return this._window;
        const window = global.display.get_tab_list(Meta.TabList.NORMAL_ALL, null)
            .find(w => w.get_role() === Util.DROPDOWN_ROLE);
        if (window)
            this._adopt(window, false);
        return this._window;
    }

    _start() {
        if (this._createdId)
            return;  // already starting one

        const config = readConfig();
        this._kind = Util.dropdownTerminalKind(config.terminal,
            name => !!GLib.find_program_in_path(name));
        if (!this._kind) {
            Main.notify('Drop-down terminal', 'Neither Terminator nor GNOME Terminal is installed.');
            return;
        }

        this._createdId = global.display.connect('window-created', (_d, window) => {
            // The window's class and role are not always set at creation.
            GLib.timeout_add(GLib.PRIORITY_DEFAULT, 250, () => {
                if (this._createdId && Util.isDropdownWindow(this._kind, window.get_wm_class(), window.get_role()))
                    this._adopt(window, true);
                return GLib.SOURCE_REMOVE;
            });
        });
        this._expireId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, ADOPT_FOR_S, () => {
            this._expireId = 0;
            this._stopWaiting();
            return GLib.SOURCE_REMOVE;
        });

        this._activeProjectFolder(folder => {
            try {
                GLib.spawn_async(folder, Util.dropdownArgv(this._kind, folder), null,
                    GLib.SpawnFlags.SEARCH_PATH, null);
            } catch (e) {
                logError(e, '[Adaptive Dropdown] starting the terminal');
                this._stopWaiting();
            }
        });
    }

    // The active project's folder, or home. Never fails: no service, no
    // project and a folder that has gone all mean home.
    _activeProjectFolder(done) {
        const home = GLib.get_home_dir();
        Gio.DBus.session.call(
            'org.adaptive.ProjectContext', '/org/adaptive/ProjectContext',
            'org.adaptive.ProjectContext', 'GetActiveProject', null, null,
            Gio.DBusCallFlags.NO_AUTO_START, 1000, null,
            (conn, res) => {
                let folder = home;
                try {
                    const [, , path] = conn.call_finish(res).deep_unpack();
                    if (path && GLib.file_test(path, GLib.FileTest.IS_DIR))
                        folder = path;
                } catch (e) {
                    folder = home;
                }
                done(folder);
            });
    }

    _adopt(window, place) {
        this._stopWaiting();
        this._window = window;
        this._unmanagedId = window.connect('unmanaged', () => this._forget());
        if (place)
            this._present(window);
    }

    _present(window) {
        const here = global.workspace_manager.get_active_workspace();
        if (window.get_workspace() !== here)
            window.change_workspace(here);
        if (window.minimized)
            window.unminimize();

        const config = readConfig();
        const area = here.get_work_area_for_monitor(global.display.get_current_monitor());
        const rect = Util.dropdownRect(area, config.height);
        try {
            if (window.get_maximized())
                window.unmaximize(Meta.MaximizeFlags.BOTH);
            window.move_resize_frame(true, rect.x, rect.y, rect.width, rect.height);
            if (!window.is_above())
                window.make_above();
        } catch (e) {
            logError(e, '[Adaptive Dropdown] placing the terminal');
        }
        Main.activateWindow(window);
    }

    _forget() {
        if (this._window && this._unmanagedId) {
            try {
                this._window.disconnect(this._unmanagedId);
            } catch (e) {
                // the window has already gone
            }
        }
        this._window = null;
        this._unmanagedId = 0;
    }

    _stopWaiting() {
        if (this._createdId) {
            global.display.disconnect(this._createdId);
            this._createdId = 0;
        }
        if (this._expireId) {
            GLib.source_remove(this._expireId);
            this._expireId = 0;
        }
    }
};
