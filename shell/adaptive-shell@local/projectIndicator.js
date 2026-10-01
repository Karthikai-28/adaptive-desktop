// Adaptive project indicator - the active project in the top bar.
//
// Left of the top bar, where Activities used to be: the active project's name,
// its branch and how much is uncommitted ("adaptive-desktop · main ±3 ↑1").
// Hidden when no project is active. Its menu is the project's hub: open it in
// a terminal or Files, jot a quick note, park it or bring it back.
//
// Git runs here, not in the project scan, so the status is live: when the
// project changes, when the menu opens, and every GIT_REFRESH_S while shown.
// --no-optional-locks keeps it from ever contending with your own git.

/* exported ProjectIndicator */

const { Clutter, Gio, GLib, St } = imports.gi;
const Main = imports.ui.main;
const PanelMenu = imports.ui.panelMenu;
const PopupMenu = imports.ui.popupMenu;

const Me = imports.misc.extensionUtils.getCurrentExtension();
const Util = Me.imports.adaptiveUtil;

const BUS_NAME = 'org.adaptive.ProjectContext';
const OBJECT_PATH = '/org/adaptive/ProjectContext';
const GIT_REFRESH_S = 60;
const SCRIPTS = GLib.build_filenamev([GLib.get_home_dir(), 'adaptive-desktop', 'scripts']);

function script(name) {
    return GLib.build_filenamev([SCRIPTS, name]);
}

function spawn(argv, cwd = null) {
    try {
        GLib.spawn_async(cwd, argv, null, GLib.SpawnFlags.SEARCH_PATH, null);
    } catch (e) {
        logError(e, `[Adaptive Project] ${argv[0]}`);
    }
}

var ProjectIndicator = class ProjectIndicator {
    constructor(snapshots) {
        this._snapshots = snapshots;
        this._button = null;
        this._proxy = null;
        this._signalId = 0;
        this._ownerId = 0;
        this._timerId = 0;
        this._project = null;
        this._git = null;
        this._gitSerial = 0;
        this._cancellable = new Gio.Cancellable();
    }

    attach() {
        this._button = new PanelMenu.Button(0.0, 'Project', false);
        this._button.add_style_class_name('adaptive-project-indicator');
        const box = new St.BoxLayout({ style_class: 'adaptive-project-box' });
        this._name = new St.Label({ y_align: Clutter.ActorAlign.CENTER, style_class: 'adaptive-project-name' });
        this._status = new St.Label({ y_align: Clutter.ActorAlign.CENTER, style_class: 'adaptive-project-git' });
        box.add_child(this._name);
        box.add_child(this._status);
        this._button.add_child(box);
        this._button.container.hide();
        Main.panel.addToStatusArea('adaptive-project', this._button, 0, 'left');

        this._button.menu.connect('open-state-changed', (_m, open) => {
            if (open) {
                this._buildMenu();
                this._refreshGit();
            }
        });

        Gio.DBusProxy.new_for_bus(
            Gio.BusType.SESSION, Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES,
            null, BUS_NAME, OBJECT_PATH, BUS_NAME, this._cancellable,
            (_s, res) => {
                try {
                    this._proxy = Gio.DBusProxy.new_for_bus_finish(res);
                } catch (e) {
                    if (!(e.matches && e.matches(Gio.IOErrorEnum, Gio.IOErrorEnum.CANCELLED)))
                        logError(e, '[Adaptive Project] connecting to the project service');
                    return;
                }
                this._signalId = this._proxy.connect('g-signal', () => this._loadProject());
                this._ownerId = this._proxy.connect('notify::g-name-owner', () => this._loadProject());
                this._loadProject();
            });

        this._timerId = GLib.timeout_add_seconds(GLib.PRIORITY_LOW, GIT_REFRESH_S, () => {
            if (this._project)
                this._refreshGit();
            return GLib.SOURCE_CONTINUE;
        });
    }

    detach() {
        this._cancellable.cancel();
        if (this._timerId) {
            GLib.source_remove(this._timerId);
            this._timerId = 0;
        }
        if (this._proxy) {
            this._proxy.disconnect(this._signalId);
            this._proxy.disconnect(this._ownerId);
            this._proxy = null;
        }
        if (this._button) {
            this._button.destroy();
            this._button = null;
        }
    }

    // ------------------------------------------------------------ data

    _call(method, params, done) {
        if (!this._proxy || !this._proxy.get_name_owner()) {
            done(null);
            return;
        }
        this._proxy.call(method, params, Gio.DBusCallFlags.NONE, 3000, this._cancellable, (p, res) => {
            try {
                done(p.call_finish(res).deep_unpack());
            } catch (e) {
                if (!(e.matches && e.matches(Gio.IOErrorEnum, Gio.IOErrorEnum.CANCELLED)))
                    done(null);
            }
        });
    }

    _loadProject() {
        this._call('GetActiveProject', null, active => {
            const id = active ? active[0] : '';
            if (!id) {
                this._setProject(null);
                return;
            }
            this._call('GetProject', new GLib.Variant('(s)', [id]), result => {
                let project = null;
                try {
                    project = result ? JSON.parse(result[0]) : null;
                } catch (e) {
                    project = null;
                }
                this._setProject(project && project.id ? project : null);
            });
        });
    }

    _setProject(project) {
        if (!this._button)
            return;
        const changed = (project && project.path) !== (this._project && this._project.path);
        this._project = project;
        if (changed)
            this._git = null;
        this._button.container.visible = !!project;
        this._render();
        // PopupMenu.open() returns early on an empty menu, so a menu that is
        // only filled as it opens never opens at all. Keep it filled.
        this._buildMenu();
        if (project && changed)
            this._refreshGit();
    }

    _refreshGit() {
        const project = this._project;
        if (!project || !project.path)
            return;
        const serial = ++this._gitSerial;
        try {
            const proc = Gio.Subprocess.new(
                ['git', '--no-optional-locks', '-C', project.path, 'status', '--porcelain=v1', '--branch'],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE);
            proc.communicate_utf8_async(null, this._cancellable, (p, res) => {
                let out = '';
                try {
                    [, out] = p.communicate_utf8_finish(res);
                } catch (e) {
                    return;
                }
                if (serial !== this._gitSerial || !this._button)
                    return;
                this._git = Util.parseGitStatus(out);
                this._render();
            });
        } catch (e) {
            logError(e, '[Adaptive Project] git status');
        }
    }

    // ---------------------------------------------------------- render

    _render() {
        if (!this._button || !this._project)
            return;
        this._name.text = this._project.name;
        const status = Util.formatGitStatus(this._git);
        this._status.text = status ? `  ${status}` : '';
        this._status.visible = !!status;
        if (this._git && this._git.dirty)
            this._status.add_style_class_name('adaptive-project-git-dirty');
        else
            this._status.remove_style_class_name('adaptive-project-git-dirty');
    }

    _buildMenu() {
        const menu = this._button.menu;
        menu.removeAll();
        const project = this._project;
        if (!project)
            return;

        const where = project.path.replace(GLib.get_home_dir(), '~');
        const head = new PopupMenu.PopupMenuItem(where, { reactive: false });
        head.label.add_style_class_name('adaptive-project-path');
        menu.addMenuItem(head);
        if (this._git) {
            const g = this._git;
            const parts = [`On ${g.branch}`];
            parts.push(g.dirty ? `${g.dirty} uncommitted` : 'clean');
            if (g.ahead)
                parts.push(`${g.ahead} to push`);
            if (g.behind)
                parts.push(`${g.behind} to pull`);
            menu.addMenuItem(new PopupMenu.PopupMenuItem(parts.join(' · '), { reactive: false }));
        }
        menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        menu.addAction('Open in Terminal', () =>
            spawn(['gnome-terminal', `--working-directory=${project.path}`], project.path));
        menu.addAction('Open in Files', () => {
            try {
                Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(project.path).get_uri(), null);
            } catch (e) {
                logError(e, '[Adaptive Project] open in Files');
            }
        });
        menu.addAction('Quick Note…', () => spawn([script('adaptive-quick-note.py')]));
        // These open the Command palette already in the mode, where the list
        // lives; the menu stays a list of doors, not a second copy of it.
        menu.addAction('Tasks…', () => spawn([script('adaptive-command-launch.sh'), '--query', 'todo ']));
        menu.addAction('Search in Project…', () => spawn([script('adaptive-command-launch.sh'), '--query', '/']));
        menu.addAction('Switch Branch…', () => spawn([script('adaptive-command-launch.sh'), '--query', 'branch ']));
        const startup = project.metadata && project.metadata.startup;
        if (Array.isArray(startup) && startup.length) {
            menu.addAction(`Run Startup Command${startup.length === 1 ? '' : 's'}`, () =>
                spawn([script('project-cli.py'), 'startup', 'run', '--target', project.id]));
        }
        menu.addAction('All Projects…', () => spawn([script('adaptive-projects-launch.sh')]));
        menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        if (this._snapshots && this._snapshots.hasSnapshot(project.id)) {
            menu.addAction('Resume Project', () => this._snapshots.resume(project.id)
                .catch(e => Main.notify('Resume project', e.message)));
        }
        if (this._snapshots) {
            menu.addAction('Park Project', () => this._snapshots.park(project.id)
                .catch(e => Main.notify('Park project', e.message)));
        }
        menu.addAction('Project Settings…', () =>
            spawn([script('adaptive-settings-launch.sh'), '--section', 'projects']));
    }
};
