// Adaptive project snapshots - park a project, resume it later.
//
// Park records every window on the project's workspace (its app, place, size
// and maximized state) to ~/.config/adaptive-desktop/snapshots/<id>.json and
// closes them. Resume relaunches each app on that workspace - a terminal in
// the project folder, a file manager or editor on the folder itself, anything
// else as it is - and puts each new window back where its parked one was.
//
// The project's workspace is its workspace_index from the Project Context
// Service; a project without one parks the workspace you are on.
//
// Only windows that can be brought back are closed. A window with no app
// behind it (no .desktop file to relaunch) is left open and counted, so
// parking can never lose something it cannot resume. Closing asks politely
// (Meta.Window.delete), so an app with unsaved work still gets to ask.
//
// Apps relaunch fresh: a browser comes back as a new window, with its tabs only
// if the browser restores its own session.

/* exported ProjectSnapshots */

const { Gio, GLib, Meta, Shell } = imports.gi;
const Main = imports.ui.main;

const Me = imports.misc.extensionUtils.getCurrentExtension();
const Util = Me.imports.adaptiveUtil;

const SNAPSHOT_DIR = GLib.build_filenamev(
    [GLib.get_user_config_dir(), 'adaptive-desktop', 'snapshots']);
// How long a resumed app has to open its window before it is left where the
// app put it.
const ADOPT_FOR_S = 60;
// A new window's app is not always known at window-created; look a moment later.
const ADOPT_DELAY_MS = 350;
// Adaptive's own tools are never parked: Settings may be what parked it.
const OWN_WM_CLASS = /^com\.karthi\./;

function snapshotPath(projectId) {
    return GLib.build_filenamev([SNAPSHOT_DIR, `${projectId.replace(/[^\w.-]/g, '_')}.json`]);
}

function readJson(path) {
    try {
        const [ok, bytes] = GLib.file_get_contents(path);
        return ok ? JSON.parse(new TextDecoder().decode(bytes)) : null;
    } catch (e) {
        return null;
    }
}

// One call to the Project Context Service, as a promise.
function projectCall(method, params) {
    return new Promise((resolve, reject) => {
        Gio.DBus.session.call(
            'org.adaptive.ProjectContext', '/org/adaptive/ProjectContext',
            'org.adaptive.ProjectContext', method, params, null,
            Gio.DBusCallFlags.NONE, 3000, null,
            (conn, res) => {
                try {
                    resolve(conn.call_finish(res).deep_unpack());
                } catch (e) {
                    reject(e);
                }
            });
    });
}

var ProjectSnapshots = class ProjectSnapshots {
    constructor() {
        this._pending = [];
        this._createdId = 0;
        this._expireId = 0;
        this._timers = new Set();
    }

    attach() {
    }

    detach() {
        this._stopAdopting();
        for (const id of this._timers)
            GLib.source_remove(id);
        this._timers.clear();
    }

    hasSnapshot(projectId) {
        return !!projectId && GLib.file_test(snapshotPath(projectId), GLib.FileTest.EXISTS);
    }

    // '' means the active project. Resolves to the project, or throws.
    async _project(projectId) {
        let id = projectId;
        if (!id)
            [id] = await projectCall('GetActiveProject', null);
        if (!id)
            throw new Error('No project is active');
        const [raw] = await projectCall('GetProject', new GLib.Variant('(s)', [id]));
        const project = JSON.parse(raw || '{}');
        if (!project.id)
            throw new Error('That project no longer exists');
        return project;
    }

    _workspaceFor(project) {
        const manager = global.workspace_manager;
        const index = Number(project.workspace_index);
        if (Number.isInteger(index) && index >= 0 && index < manager.n_workspaces)
            return manager.get_workspace_by_index(index);
        return manager.get_active_workspace();
    }

    async park(projectId) {
        const project = await this._project(projectId);
        const workspace = this._workspaceFor(project);
        const tracker = Shell.WindowTracker.get_default();

        const entries = [];
        const toClose = [];
        let kept = 0;
        for (const window of workspace.list_windows()) {
            if (window.get_window_type() !== Meta.WindowType.NORMAL ||
                window.is_skip_taskbar() || window.is_on_all_workspaces() ||
                OWN_WM_CLASS.test(window.get_wm_class() || ''))
                continue;

            const app = tracker.get_window_app(window);
            const info = app ? app.get_app_info() : null;
            if (!info) {
                kept++;
                continue;
            }

            const rect = window.get_frame_rect();
            entries.push({
                appId: app.get_id(),
                categories: info.get_categories() || '',
                title: window.get_title() || '',
                rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
                maximized: window.get_maximized(),
                workspace: workspace.index(),
            });
            toClose.push(window);
        }

        if (!entries.length)
            return { ok: false, count: 0, kept, message: `Nothing to park on ${project.name}'s workspace` };

        // An earlier snapshot not yet resumed is kept and added to, so parking
        // twice does not forget the first lot.
        const path = snapshotPath(project.id);
        const earlier = readJson(path);
        const all = (earlier && Array.isArray(earlier.windows) ? earlier.windows : []).concat(entries);
        GLib.mkdir_with_parents(SNAPSHOT_DIR, 0o700);
        GLib.file_set_contents(path, `${JSON.stringify({
            project: project.id,
            name: project.name,
            path: project.path,
            parked_at: Math.floor(GLib.get_real_time() / 1e6),
            windows: all,
        }, null, 2)}\n`);

        const time = global.get_current_time();
        for (const window of toClose)
            window.delete(time);

        let message = `Parked ${entries.length} window${entries.length === 1 ? '' : 's'} of ${project.name}`;
        if (kept)
            message += `; ${kept} left open (no app to relaunch)`;
        Main.notify('Project parked', message);
        return { ok: true, count: entries.length, kept, message };
    }

    async resume(projectId) {
        const project = await this._project(projectId);
        const path = snapshotPath(project.id);
        const snapshot = readJson(path);
        if (!snapshot || !Array.isArray(snapshot.windows) || !snapshot.windows.length)
            return { ok: false, count: 0, message: `${project.name} has nothing parked` };

        const manager = global.workspace_manager;
        const folder = project.path || snapshot.path || GLib.get_home_dir();
        const first = snapshot.windows[0].workspace;
        const target = manager.get_workspace_by_index(
            Number.isInteger(first) && first < manager.n_workspaces ? first : manager.get_active_workspace_index());
        target.activate(global.get_current_time());

        this._startAdopting();
        let launched = 0;
        // Whatever cannot be launched now stays parked for the next resume.
        const leftover = [];
        for (const entry of snapshot.windows) {
            const app = Shell.AppSystem.get_default().lookup_app(entry.appId);
            if (!app) {
                leftover.push(entry);
                continue;
            }
            try {
                this._launch(app, entry, folder, target.index());
                this._pending.push(entry);
                launched++;
            } catch (e) {
                logError(e, `[Adaptive Snapshots] launching ${entry.appId}`);
                leftover.push(entry);
            }
        }

        try {
            if (leftover.length)
                GLib.file_set_contents(path, `${JSON.stringify({ ...snapshot, windows: leftover }, null, 2)}\n`);
            else
                Gio.File.new_for_path(path).delete(null);
        } catch (e) {
            logError(e, '[Adaptive Snapshots] updating snapshot');
        }

        let message = `Reopening ${launched} window${launched === 1 ? '' : 's'} of ${project.name}`;
        if (leftover.length)
            message += `; ${leftover.length} could not be reopened and stay parked`;
        Main.notify('Project resumed', message);
        return { ok: launched > 0, count: launched, message };
    }

    _launch(app, entry, folder, workspaceIndex) {
        const info = app.get_app_info();
        const kind = Util.classifyApp(entry.appId, entry.categories);
        const context = global.create_app_launch_context(0, workspaceIndex);

        if (kind === 'terminal') {
            const argv = entry.appId === 'org.gnome.Terminal.desktop'
                ? ['gnome-terminal', `--working-directory=${folder}`]
                : [info.get_executable()];
            GLib.spawn_async(folder, argv, null, GLib.SpawnFlags.SEARCH_PATH, null);
        } else if (kind === 'folder' && (info.supports_uris() || info.supports_files())) {
            info.launch([Gio.File.new_for_path(folder)], context);
        } else {
            info.launch([], context);
        }
    }

    // ------------------------------------------------- window placement

    _startAdopting() {
        if (!this._createdId) {
            this._createdId = global.display.connect('window-created', (_d, window) => {
                const id = GLib.timeout_add(GLib.PRIORITY_DEFAULT, ADOPT_DELAY_MS, () => {
                    this._timers.delete(id);
                    this._adopt(window);
                    return GLib.SOURCE_REMOVE;
                });
                this._timers.add(id);
            });
        }
        if (this._expireId)
            GLib.source_remove(this._expireId);
        this._expireId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, ADOPT_FOR_S, () => {
            this._expireId = 0;
            this._stopAdopting();
            return GLib.SOURCE_REMOVE;
        });
    }

    _stopAdopting() {
        if (this._createdId) {
            global.display.disconnect(this._createdId);
            this._createdId = 0;
        }
        if (this._expireId) {
            GLib.source_remove(this._expireId);
            this._expireId = 0;
        }
        this._pending = [];
    }

    _adopt(window) {
        if (!this._pending.length || window.get_window_type() !== Meta.WindowType.NORMAL)
            return;
        const app = Shell.WindowTracker.get_default().get_window_app(window);
        const index = app ? this._pending.findIndex(e => e.appId === app.get_id()) : -1;
        if (index < 0)
            return;
        const [entry] = this._pending.splice(index, 1);

        try {
            const workspace = global.workspace_manager.get_workspace_by_index(entry.workspace);
            if (workspace)
                window.change_workspace(workspace);
            if (window.get_maximized())
                window.unmaximize(Meta.MaximizeFlags.BOTH);
            const r = entry.rect;
            window.move_resize_frame(true, r.x, r.y, r.width, r.height);
            if (entry.maximized)
                window.maximize(entry.maximized);
        } catch (e) {
            logError(e, '[Adaptive Snapshots] placing a resumed window');
        }

        if (!this._pending.length)
            this._stopAdopting();
    }
};
