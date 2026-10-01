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
//
// The same object is the Command palette's way into the shell, for what only
// the shell can do or hold: the open windows, switching workspace, the
// clipboard history (and owning the clipboard after the palette has closed),
// parking and resuming projects, and reading text off the screen. Results
// come back as JSON strings.

const { Gio, GLib, Meta, Shell } = imports.gi;
const Main = imports.ui.main;

const PATH = '/org/adaptive/Shell';
const XML = `
<node>
  <interface name="org.adaptive.Shell">
    <method name="Run">
      <arg type="s" name="action" direction="in"/>
      <arg type="b" name="handled" direction="out"/>
    </method>
    <method name="ListWindows">
      <arg type="s" name="json" direction="out"/>
    </method>
    <method name="ActivateWindow">
      <arg type="u" name="id" direction="in"/>
      <arg type="b" name="handled" direction="out"/>
    </method>
    <method name="ActivateWorkspace">
      <arg type="i" name="index" direction="in"/>
      <arg type="b" name="handled" direction="out"/>
    </method>
    <method name="ClipboardHistory">
      <arg type="s" name="json" direction="out"/>
    </method>
    <method name="ClipboardCopy">
      <arg type="s" name="text" direction="in"/>
      <arg type="b" name="handled" direction="out"/>
    </method>
    <method name="ClipboardClear">
      <arg type="b" name="handled" direction="out"/>
    </method>
    <method name="ParkProject">
      <arg type="s" name="id" direction="in"/>
      <arg type="s" name="json" direction="out"/>
    </method>
    <method name="ResumeProject">
      <arg type="s" name="id" direction="in"/>
      <arg type="s" name="json" direction="out"/>
    </method>
    <method name="CopyScreenText">
      <arg type="b" name="handled" direction="out"/>
    </method>
  </interface>
</node>`;

var ShellActions = class ShellActions {
    // services: { clipboard, snapshots, screenText }, any of which may be null
    // if it failed to start; its methods then answer as unavailable.
    constructor(services = {}) {
        this._export = null;
        this._clipboard = services.clipboard || null;
        this._snapshots = services.snapshots || null;
        this._screenText = services.screenText || null;
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

    // ------------------------------------------------------ palette bridge

    ListWindows() {
        const tracker = Shell.WindowTracker.get_default();
        const focused = global.display.focus_window;
        const windows = global.display.get_tab_list(Meta.TabList.NORMAL_ALL, null)
            .filter(w => !w.is_skip_taskbar())
            .map(w => {
                const app = tracker.get_window_app(w);
                const workspace = w.get_workspace();
                const index = workspace ? workspace.index() : -1;
                return {
                    id: w.get_stable_sequence(),
                    title: w.get_title() || '',
                    app: app ? app.get_id() : '',
                    appName: app ? app.get_name() : (w.get_wm_class() || ''),
                    workspace: index,
                    workspaceName: index >= 0 ? Meta.prefs_get_workspace_name(index) : '',
                    focused: w === focused,
                    minimized: w.minimized,
                };
            });
        return JSON.stringify(windows);
    }

    ActivateWindow(id) {
        const window = global.display.get_tab_list(Meta.TabList.NORMAL_ALL, null)
            .find(w => w.get_stable_sequence() === id);
        if (!window)
            return false;
        Main.activateWindow(window);
        return true;
    }

    ActivateWorkspace(index) {
        const workspace = global.workspace_manager.get_workspace_by_index(index);
        if (!workspace)
            return false;
        workspace.activate(global.get_current_time());
        return true;
    }

    ClipboardHistory() {
        return JSON.stringify(this._clipboard ? this._clipboard.history() : []);
    }

    ClipboardCopy(text) {
        if (this._clipboard)
            return this._clipboard.copy(text);
        return false;
    }

    ClipboardClear() {
        if (!this._clipboard)
            return false;
        this._clipboard.clear();
        return true;
    }

    ParkProjectAsync([id], invocation) {
        this._snapshotCall(this._snapshots ? this._snapshots.park(id) : null, invocation);
    }

    ResumeProjectAsync([id], invocation) {
        this._snapshotCall(this._snapshots ? this._snapshots.resume(id) : null, invocation);
    }

    _snapshotCall(promise, invocation) {
        const reply = result => invocation.return_value(
            new GLib.Variant('(s)', [JSON.stringify(result)]));
        if (!promise) {
            reply({ ok: false, message: 'Project snapshots are unavailable' });
            return;
        }
        promise.then(reply, e => reply({ ok: false, message: e.message }));
    }

    CopyScreenText() {
        return this._screenText ? this._screenText.start() : false;
    }

    // --------------------------------------------------------- gestures

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
