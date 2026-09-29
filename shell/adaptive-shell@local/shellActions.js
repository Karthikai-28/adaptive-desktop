/* exported ShellActions */
'use strict';

// Shell-side actions for touchpad gestures (scripts/adaptive-gestures.py).
//
// GNOME's touchpad gestures only exist on Wayland, and on X11 the gesture
// daemon reads libinput itself. Most of what it triggers it can do from the
// outside (window focus, media keys), but not what only the shell can: the
// app grid, search, the Adaptive Shade and Control Center, and animated
// workspace switching. GNOME 41+ refuses its own ShowApplications and
// FocusSearch to other processes, so this exports one small method of our
// own on the shell's session connection:
//
//   gdbus call --session -d org.gnome.Shell -o /org/adaptive/Shell \
//       -m org.adaptive.Shell.Run app-grid
//
// Only the fixed action names below are accepted; nothing is evaluated.

const { Gio, GLib, Meta } = imports.gi;
const Main = imports.ui.main;

const PATH = '/org/adaptive/Shell';
const XML = `
<node>
  <interface name="org.adaptive.Shell">
    <method name="Run">
      <arg type="s" name="action" direction="in"/>
      <arg type="b" name="handled" direction="out"/>
    </method>
  </interface>
</node>`;

var ShellActions = class ShellActions {
    constructor() {
        this._export = null;
    }

    attach() {
        this._export = Gio.DBusExportedObject.wrapJSObject(XML, this);
        this._export.export(Gio.DBus.session, PATH);
    }

    detach() {
        if (this._export) {
            this._export.unexport();
            this._export = null;
        }
    }

    Run(action) {
        const handler = {
            'overview': () => Main.overview.toggle(),
            'app-grid': () => this._appGrid(),
            'search': () => this._search(),
            'notifications': () => this._toggleMenu('dateMenu'),
            'control-center': () => this._toggleMenu('aggregateMenu'),
            'workspace-left': () => this._workspace(Meta.MotionDirection.LEFT, false),
            'workspace-right': () => this._workspace(Meta.MotionDirection.RIGHT, false),
            'window-to-workspace-left': () => this._workspace(Meta.MotionDirection.LEFT, true),
            'window-to-workspace-right': () => this._workspace(Meta.MotionDirection.RIGHT, true),
        }[action];

        if (!handler)
            return false;

        try {
            handler();
        } catch (e) {
            logError(e, `[Adaptive Shell] gesture action ${action}`);
            return false;
        }
        return true;
    }

    _closeMenus() {
        Main.panel.statusArea.dateMenu?.menu.close();
        Main.panel.statusArea.aggregateMenu?.menu.close();
    }

    _toggleMenu(name) {
        const indicator = Main.panel.statusArea[name];
        if (!indicator)
            return;
        if (Main.overview.visible)
            Main.overview.hide();
        const other = name === 'dateMenu' ? 'aggregateMenu' : 'dateMenu';
        Main.panel.statusArea[other]?.menu.close();
        indicator.menu.toggle();
    }

    _appGrid() {
        this._closeMenus();
        const button = Main.overview.dash?.showAppsButton;
        if (Main.overview.visible && button?.checked) {
            Main.overview.hide();
            return;
        }
        // showApps() returns early when the Overview is already up; from the
        // window picker the page is switched through the dash's toggle, as
        // the dock's Applications button does.
        if (Main.overview.visible && button)
            button.checked = true;
        else
            Main.overview.showApps();
    }

    _search() {
        this._closeMenus();
        if (!Main.overview.visible)
            Main.overview.show();
        // Focus once the overview has taken the keyboard.
        GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
            Main.overview.searchEntry?.grab_key_focus();
            return GLib.SOURCE_REMOVE;
        });
    }

    _workspace(direction, takeWindow) {
        const manager = global.workspace_manager;
        const current = manager.get_active_workspace();
        const target = current.get_neighbor(direction);
        if (!target || target === current)
            return;

        const time = global.get_current_time();
        const window = takeWindow ? global.display.focus_window : null;
        if (window && !window.is_on_all_workspaces() &&
            window.get_window_type() === Meta.WindowType.NORMAL) {
            window.change_workspace(target);
            target.activate_with_focus(window, time);
        } else {
            target.activate(time);
        }
    }
};
