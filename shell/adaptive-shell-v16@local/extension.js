const { St, Gio, GLib, Clutter } = imports.gi;
const Main = imports.ui.main;
const PanelMenu = imports.ui.panelMenu;
const PopupMenu = imports.ui.popupMenu;
const ExtensionUtils = imports.misc.extensionUtils;

const Me = ExtensionUtils.getCurrentExtension();

let _shell = null;

class AdaptiveShellV16 {
    constructor() {
        this._rail = null;
        this._brandButton = null;
        this._projectButton = null;
        this._projectLabel = null;
        this._activeProjectId = null;
        this._monitorChangedId = 0;
        this._hiddenActors = [];
        this._clockActor = null;
        this._clockDisplay = null;
        this._projectProxy = null;

        this._filesLauncher = GLib.build_filenamev([
            GLib.get_home_dir(),
            'adaptive-desktop',
            'scripts',
            'adaptive-files-launch-v1.6.sh',
        ]);
    }

    enable() {
        log('[Adaptive Shell v1.6] enable');

        this._hideLegacyPanelItems();
        this._restoreGNOMEClock();
        this._installIdentity();
        this._installRail();

        this._monitorChangedId = Main.layoutManager.connect(
            'monitors-changed',
            () => this._layoutRail()
        );

        this._layoutRail();
        this._connectToProjectContext();

        log('[Adaptive Shell v1.6] functional rail installed');
        log('[Adaptive Shell v1.6] GNOME dateMenu restored');
    }

    _connectToProjectContext() {
        Gio.DBusProxy.new_for_bus(
            Gio.BusType.SESSION,
            Gio.DBusProxyFlags.NONE,
            null,
            'org.adaptive.ProjectContext',
            '/org/adaptive/ProjectContext',
            'org.adaptive.ProjectContext',
            null,
            (source, result) => {
                try {
                    this._projectProxy = Gio.DBusProxy.new_for_bus_finish(result);
                    if (this._projectProxy) {
                        this._projectProxy.connect('g-signal', (proxy, sender_name, signal_name, parameters) => {
                            if (signal_name === 'ActiveProjectChanged') {
                                let [id, name, path] = parameters.deep_unpack();
                                this._activeProjectId = id;
                                this._updateProjectLabel(name);
                            }
                        });
                        
                        this._projectProxy.call(
                            'GetActiveProject',
                            null,
                            Gio.DBusCallFlags.NONE,
                            -1,
                            null,
                            (proxy, res) => {
                                try {
                                    let variant = proxy.call_finish(res);
                                    let [id, name, path] = variant.deep_unpack();
                                    this._activeProjectId = id;
                                    this._updateProjectLabel(name);
                                } catch (e) {
                                    logError(e, '[Adaptive Shell v1.6] GetActiveProject failed');
                                }
                            }
                        );
                    }
                } catch (e) {
                    logError(e, '[Adaptive Shell v1.6] Error connecting to ProjectContext DBus');
                }
            }
        );
    }

    _updateProjectLabel(name) {
        if (this._projectLabel) {
            let display = name && name !== 'NONE' ? name.toUpperCase() : 'NONE';
            this._projectLabel.set_text('PROJECT · ' + display);
        }
    }

    disable() {
        log('[Adaptive Shell v1.6] disable');

        if (this._monitorChangedId) {
            Main.layoutManager.disconnect(
                this._monitorChangedId
            );
            this._monitorChangedId = 0;
        }

        if (this._rail) {
            Main.layoutManager.removeChrome(this._rail);
            this._rail.destroy();
            this._rail = null;
        }

        if (this._brandButton) {
            this._brandButton.destroy();
            this._brandButton = null;
        }

        if (this._projectButton) {
            this._projectButton.destroy();
            this._projectButton = null;
        }

        if (this._projectProxy) {
            this._projectProxy = null;
        }

        if (this._clockActor) {
            try {
                this._clockActor.remove_style_class_name(
                    'adaptive-stock-clock'
                );
            } catch (e) {
                logError(
                    e,
                    '[Adaptive Shell v1.6] clock cleanup'
                );
            }
            this._clockActor = null;
        }

        for (const item of this._hiddenActors) {
            try {
                if (item.wasVisible)
                    item.actor.show();
                else
                    item.actor.hide();
            } catch (e) {
                logError(
                    e,
                    '[Adaptive Shell v1.6] restore actor'
                );
            }
        }

        this._hiddenActors = [];
    }

    _actor(item) {
        if (!item)
            return null;

        if (item.container)
            return item.container;

        if (item.actor)
            return item.actor;

        return item;
    }

    _hideAndRemember(actor) {
        if (!actor)
            return;

        try {
            this._hiddenActors.push({
                actor,
                wasVisible: actor.visible,
            });
            actor.hide();
        } catch (e) {
            logError(
                e,
                '[Adaptive Shell v1.6] hide actor'
            );
        }
    }

    _hideLegacyPanelItems() {
        // Preserve right-side system indicators and the center dateMenu.
        // Remove only stock left-side Activities/current-app UI.
        this._hideAndRemember(
            this._actor(
                Main.panel.statusArea.activities
            )
        );

        this._hideAndRemember(
            this._actor(
                Main.panel.statusArea.appMenu
            )
        );
    }

    _restoreGNOMEClock() {
        const dateMenu =
            Main.panel.statusArea.dateMenu;

        if (!dateMenu) {
            log(
                '[Adaptive Shell v1.6] dateMenu not found'
            );
            return;
        }

        const actor = this._actor(dateMenu);

        if (!actor) {
            log(
                '[Adaptive Shell v1.6] dateMenu actor not found'
            );
            return;
        }

        try {
            // Undo prior Adaptive Shell builds that hid the stock time.
            actor.opacity = 255;
            actor.reactive = true;
            actor.show();

            if (Main.panel._centerBox)
                Main.panel._centerBox.show();

            // GNOME 42 dateMenu exposes _clockDisplay. Make it visible too
            // when available, but do not replace it: clicking remains the
            // native calendar/notifications menu.
            if (dateMenu._clockDisplay) {
                dateMenu._clockDisplay.show();
                this._clockDisplay =
                    dateMenu._clockDisplay;
            }

            actor.add_style_class_name(
                'adaptive-stock-clock'
            );

            this._clockActor = actor;
        } catch (e) {
            logError(
                e,
                '[Adaptive Shell v1.6] restoring GNOME clock'
            );
        }
    }

    _installIdentity() {
        this._brandButton = new St.Button({
            reactive: true,
            can_focus: true,
            track_hover: true,
            style_class: 'adaptive-brand-button',
            accessible_name: 'Adaptive Desktop overview',
        });

        const brand = new St.Label({
            text: 'ADAPTIVE',
            y_align: Clutter.ActorAlign.CENTER,
            style_class: 'adaptive-brand-label',
        });

        this._brandButton.set_child(brand);
        this._brandButton.connect(
            'clicked',
            () => this._showOverview()
        );

        this._projectButton = new PanelMenu.Button(0.0, 'ProjectMenu', false);
        this._projectButton.add_style_class_name('adaptive-project-button');
        
        this._projectLabel = new St.Label({
            text: 'PROJECT · NONE',
            y_align: Clutter.ActorAlign.CENTER,
            style_class: 'adaptive-project-label',
        });
        this._projectButton.add_child(this._projectLabel);
        
        this._projectButton.menu.connect('open-state-changed', (menu, open) => {
            if (open) {
                this._populateProjectMenu();
            }
        });

        Main.panel._leftBox.insert_child_at_index(
            this._brandButton,
            0
        );

        Main.panel._leftBox.insert_child_at_index(
            this._projectButton,
            1
        );
    }

    _populateProjectMenu() {
        this._projectButton.menu.removeAll();
        
        if (!this._projectProxy) {
            let item = new PopupMenu.PopupMenuItem('Project Service offline');
            item.setSensitive(false);
            this._projectButton.menu.addMenuItem(item);
            return;
        }

        this._projectProxy.call(
            'ListProjects',
            null,
            Gio.DBusCallFlags.NONE,
            -1,
            null,
            (proxy, res) => {
                try {
                    let variant = proxy.call_finish(res);
                    let projects = JSON.parse(variant.deep_unpack()[0]);
                    let hasItems = false;
                    
                    for (let pid in projects) {
                        hasItems = true;
                        let name = projects[pid].name;
                        let isActive = (pid === this._activeProjectId);
                        let item = new PopupMenu.PopupMenuItem(isActive ? `★ ${name}` : name);
                        item.connect('activate', () => {
                            this._projectProxy.call(
                                'SetActiveProject',
                                GLib.Variant.new('(s)', [pid]),
                                Gio.DBusCallFlags.NONE,
                                -1,
                                null,
                                null
                            );
                        });
                        this._projectButton.menu.addMenuItem(item);
                    }
                    
                    if (!hasItems) {
                        let empty = new PopupMenu.PopupMenuItem('No projects found');
                        empty.setSensitive(false);
                        this._projectButton.menu.addMenuItem(empty);
                    }
                } catch (e) {
                    logError(e, '[Adaptive Shell v1.6] ListProjects failed');
                }
            }
        );
    }

    _installRail() {
        this._rail = new St.BoxLayout({
            vertical: true,
            reactive: true,
            style_class: 'adaptive-rail',
        });

        const top = new St.BoxLayout({
            vertical: true,
            style_class: 'adaptive-rail-group',
        });

        top.add_child(
            this._dockButton(
                'overview.svg',
                'Overview',
                () => this._showOverview()
            )
        );

        top.add_child(
            this._dockButton(
                'files.svg',
                'Adaptive Files',
                () => this._openFiles()
            )
        );

        top.add_child(
            this._dockButton(
                'apps.svg',
                'Applications',
                () => this._showApplications()
            )
        );

        top.add_child(
            this._dockButton(
                'workspaces.svg',
                'Workspaces',
                () => this._showWorkspaces()
            )
        );

        top.add_child(
            this._dockButton(
                'search.svg',
                'Search',
                () => this._showSearch()
            )
        );

        this._rail.add_child(top);

        this._rail.add_child(
            new St.Widget({
                y_expand: true,
            })
        );

        const bottom = new St.BoxLayout({
            vertical: true,
            style_class:
                'adaptive-rail-group adaptive-rail-bottom',
        });

        bottom.add_child(
            this._dockButton(
                'settings.svg',
                'Settings',
                () => this._openSettings()
            )
        );

        this._rail.add_child(bottom);

        Main.layoutManager.addChrome(
            this._rail,
            {
                affectsStruts: true,
                trackFullscreen: true,
            }
        );
    }

    _dockButton(iconFile, name, callback) {
        const iconPath = GLib.build_filenamev([
            Me.path,
            'assets',
            'dock',
            iconFile,
        ]);

        const icon = new St.Icon({
            gicon: Gio.FileIcon.new(
                Gio.File.new_for_path(iconPath)
            ),
            style_class: 'adaptive-dock-icon',
        });

        const button = new St.Button({
            reactive: true,
            can_focus: true,
            track_hover: true,
            style_class: 'adaptive-dock-button',
            accessible_name: name,
        });

        button.set_child(icon);

        button.connect(
            'clicked',
            () => {
                log(
                    `[Adaptive Shell v1.6] click: ${name}`
                );

                try {
                    callback();
                } catch (e) {
                    logError(
                        e,
                        `[Adaptive Shell v1.6] ${name}`
                    );

                    Main.notifyError(
                        'Adaptive Desktop',
                        `${name} could not be opened.`
                    );
                }
            }
        );

        return button;
    }

    _layoutRail() {
        if (!this._rail)
            return;

        const monitor =
            Main.layoutManager.primaryMonitor;

        if (!monitor)
            return;

        const panelHeight = Math.max(
            Main.panel.height || 0,
            24
        );

        const width = 58;
        const height = Math.max(
            1,
            monitor.height - panelHeight
        );

        this._rail.set_position(
            monitor.x,
            monitor.y + panelHeight
        );

        this._rail.set_size(
            width,
            height
        );
    }

    _showOverview() {
        Main.overview.show();
    }

    _showApplications() {
        if (
            Main.overview &&
            typeof Main.overview.showApps ===
                'function'
        ) {
            Main.overview.showApps();
            return;
        }

        Main.overview.show();
    }

    _showWorkspaces() {
        Main.overview.show();
    }

    _showSearch() {
        Main.overview.show();

        // GNOME Shell 42 provides the overview search entry.
        // Focus it when available; otherwise typing after opening the
        // overview still starts normal GNOME search.
        GLib.idle_add(
            GLib.PRIORITY_DEFAULT_IDLE,
            () => {
                try {
                    if (
                        Main.overview.searchEntry &&
                        typeof Main.overview
                            .searchEntry
                            .grab_key_focus ===
                            'function'
                    ) {
                        Main.overview
                            .searchEntry
                            .grab_key_focus();
                    }
                } catch (e) {
                    logError(
                        e,
                        '[Adaptive Shell v1.6] search focus'
                    );
                }

                return GLib.SOURCE_REMOVE;
            }
        );
    }

    _openFiles() {
        if (!GLib.file_test(
            this._filesLauncher,
            GLib.FileTest.IS_EXECUTABLE
        )) {
            throw new Error(
                `Missing ${this._filesLauncher}`
            );
        }

        this._spawn([
            this._filesLauncher,
        ]);
    }

    _openSettings() {
        this._spawn([
            'gnome-control-center',
        ]);
    }

    _spawn(argv) {
        Gio.Subprocess.new(
            argv,
            Gio.SubprocessFlags.NONE
        );
    }
}

function init() {
}

function enable() {
    _shell = new AdaptiveShellV16();
    _shell.enable();
}

function disable() {
    if (_shell) {
        _shell.disable();
        _shell = null;
    }
}
