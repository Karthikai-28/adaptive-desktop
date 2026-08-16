// Adaptive monitor-aware Dock v2.6
// Adaptive dock visual customization v2.3
// Width follows natural content width, so the dock grows/shrinks
// automatically as favorites/running applications change.

const { St, Gio, GLib, Clutter, Shell, Meta } = imports.gi;
const Main = imports.ui.main;
const PanelMenu = imports.ui.panelMenu;
const PopupMenu = imports.ui.popupMenu;
const AppFavorites = imports.ui.appFavorites;
const ExtensionUtils = imports.misc.extensionUtils;
const Gvc = imports.gi.Gvc;

const Me = ExtensionUtils.getCurrentExtension();

let _shell = null;

class AdaptiveShellV16 {
    constructor() {
        // Bottom application dock. The historic member name `_rail` is kept so
        // existing verification/recovery scripts remain compatible while the
        // actor itself is now a centered horizontal dock.
        this._rail = null;
        // Adaptive bottom dock stability v2.1.
        // The transparent dock chrome owns the bottom work-area strut.
        this._dockChrome = null;
        this._dockAppsBox = null;
        this._dockButtons = [];
        this._dockMenus = [];
        this._dockMenuManager = null;
        this._showAppsButton = null;
        this._favorites = null;
        this._favoritesChangedId = 0;
        this._appStateChangedId = 0;
        this._brandButton = null;
        this._projectButton = null;
        this._projectLabel = null;
        this._activeProjectId = null;
        this._monitorChangedId = 0;
        this._overviewShowingId = 0;
        this._overviewHiddenId = 0;
        this._windowCreatedId = 0;
        this._focusWindowId = 0;
        this._windowRefreshId = 0;
        this._windowSignalIds = [];
        this._hiddenActors = [];
        this._clockActor = null;
        this._clockDisplay = null;
        this._projectProxy = null;
        this._tooltip = null;
        this._tooltipTimeoutId = 0;
        this._dockDemagnifyId = 0;

        this._commandLauncher = GLib.build_filenamev([
            GLib.get_home_dir(),
            'adaptive-desktop',
            'scripts',
            'adaptive-command-launch.sh',
        ]);
        this._focusCli = GLib.build_filenamev([
            GLib.get_home_dir(),
            'adaptive-desktop',
            'scripts',
            'focus-cli.py',
        ]);
        this._windowCli = GLib.build_filenamev([
            GLib.get_home_dir(),
            'adaptive-desktop',
            'scripts',
            'window-cli.py',
        ]);
        this._appearanceCli = GLib.build_filenamev([
            GLib.get_home_dir(),
            'adaptive-desktop',
            'scripts',
            'appearance-cli.py',
        ]);
        // Dock v2.6: one visible Dock, hot edge on every monitor.
        this._dock26HotEdges = [];
        this._dock26TargetMonitor = -1;
        this._dock26FocusWindow = null;
        this._dock26FocusSignalIds = [];
        this._dock26FullscreenSignalId = 0;
        this._dock26FocusChangedId = 0;
        this._dock26MonitorsChangedId = 0;
        this._dock26WindowEnteredMonitorId = 0;
        this._dock26RevealTimerId = 0;
        this._dock26HideTimerId = 0;
        this._dock26EdgeRevealed = false;
        this._dock26HideOnMaximized = true;
        this._dock26ReservedHeight = 70;
        this._dock26SurfaceHeight = 54;
        this._dock26BottomGap = 6;
        this._dock26HotEdgeHeight = 5;
        this._dock26RevealDelayMs = 110;
        this._dock26HideDelayMs = 320;
        this._dock26RevealDurationMs = 145;
        this._dock26HideDurationMs = 145;

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
        this._windowCreatedId = global.display.connect(
            'window-created',
            () => this._queueWindowListRefresh()
        );
        this._focusWindowId = global.display.connect(
            'notify::focus-window',
            () => this._syncDockActive()
        );
        this._overviewShowingId = Main.overview.connect(
            'showing',
            () => this._syncDockActive()
        );
        this._overviewHiddenId = Main.overview.connect(
            'hidden',
            () => this._syncDockActive()
        );

        this._favorites = AppFavorites.getAppFavorites();
        this._favoritesChangedId = this._favorites.connect(
            'changed',
            () => this._queueWindowListRefresh()
        );

        const appSystem = Shell.AppSystem.get_default();
        this._appStateChangedId = appSystem.connect(
            'app-state-changed',
            () => this._queueWindowListRefresh()
        );

        this._connectToProjectContext();
        this._queueWindowListRefresh();
        this._syncDockActive();

        log('[Adaptive Shell] interactive bottom dock installed');
        log('[Adaptive Shell] GNOME dateMenu restored');
        this._dock26ConnectRuntime();

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
                                this._restoreProjectWorkspace(id);
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
                                    this._restoreProjectWorkspace(id);
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

    _restoreProjectWorkspace(projectId) {
        if (!projectId || !this._projectProxy)
            return;

        this._projectProxy.call(
            'GetProject',
            GLib.Variant.new('(s)', [projectId]),
            Gio.DBusCallFlags.NONE,
            -1,
            null,
            (proxy, res) => {
                try {
                    const variant = proxy.call_finish(res);
                    const [rawProject] = variant.deep_unpack();
                    const project = JSON.parse(rawProject || '{}');
                    const workspaceIndex = Number(project.workspace_index);

                    if (!Number.isInteger(workspaceIndex) || workspaceIndex < 0)
                        return;

                    const workspace = global.workspace_manager.get_workspace_by_index(workspaceIndex);
                    if (workspace)
                        workspace.activate(global.get_current_time());
                } catch (e) {
                    logError(e, '[Adaptive Shell v1.6] restore project workspace');
                }
            }
        );
    }

    disable() {
        log('[Adaptive Shell] disable');

        if (this._monitorChangedId) {
            Main.layoutManager.disconnect(this._monitorChangedId);
            this._monitorChangedId = 0;
        }

        if (this._overviewShowingId) {
            Main.overview.disconnect(this._overviewShowingId);
            this._overviewShowingId = 0;
        }

        if (this._overviewHiddenId) {
            Main.overview.disconnect(this._overviewHiddenId);
            this._overviewHiddenId = 0;
        }

        if (this._windowCreatedId) {
            global.display.disconnect(this._windowCreatedId);
            this._windowCreatedId = 0;
        }

        if (this._focusWindowId) {
            global.display.disconnect(this._focusWindowId);
            this._focusWindowId = 0;
        }

        if (this._favorites && this._favoritesChangedId) {
            try {
                this._favorites.disconnect(this._favoritesChangedId);
            } catch (e) {
                logError(e, '[Adaptive Shell] disconnect favorites');
            }
            this._favoritesChangedId = 0;
        }

        if (this._appStateChangedId) {
            try {
                Shell.AppSystem.get_default().disconnect(this._appStateChangedId);
            } catch (e) {
                logError(e, '[Adaptive Shell] disconnect app-state');
            }
            this._appStateChangedId = 0;
        }

        if (this._windowRefreshId) {
            GLib.Source.remove(this._windowRefreshId);
            this._windowRefreshId = 0;
        }

        if (this._tooltipTimeoutId) {
            GLib.Source.remove(this._tooltipTimeoutId);
            this._tooltipTimeoutId = 0;
        }

        if (this._dockDemagnifyId) {
            GLib.Source.remove(this._dockDemagnifyId);
            this._dockDemagnifyId = 0;
        }

        this._dock26Cleanup();
        this._disconnectWindowSignals();
        this._destroyDockMenus();
        this._hideTooltip();

        if (this._rail) {
            Main.layoutManager.removeChrome(this._rail);
            this._rail.destroy();
            this._rail = null;
        }

        if (this._dockChrome) {
            Main.layoutManager.removeChrome(this._dockChrome);
            this._dockChrome.destroy();
            this._dockChrome = null;
        }

        this._dockAppsBox = null;
        this._dockButtons = [];
        this._showAppsButton = null;
        this._favorites = null;
        this._dockMenuManager = null;

        if (this._brandButton) {
            this._brandButton.destroy();
            this._brandButton = null;
        }

        if (this._projectButton) {
            this._projectButton.destroy();
            this._projectButton = null;
        }

        if (this._projectProxy)
            this._projectProxy = null;

        if (this._clockActor) {
            try {
                this._clockActor.remove_style_class_name('adaptive-stock-clock');
            } catch (e) {
                logError(e, '[Adaptive Shell] clock cleanup');
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
                logError(e, '[Adaptive Shell] restore actor');
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
            () => this._toggleOverview()
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

        // A PanelMenu.Button already lives inside its own container, so it has
        // to go through addToStatusArea instead of being reparented directly.
        Main.panel.addToStatusArea(
            'adaptive-project',
            this._projectButton,
            1,
            'left'
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
        this._dockChrome = new St.Widget({
            reactive: false,
            style_class: 'adaptive-dock-reservation',
        });

        this._rail = new St.BoxLayout({
            vertical: false,
            reactive: true,
            track_hover: true,
            style_class: 'adaptive-rail',
        });

        this._dockMenuManager = new PopupMenu.PopupMenuManager({
            actor: this._rail,
        });

        this._dockAppsBox = new St.BoxLayout({
            vertical: false,
            reactive: true,
            style_class: 'adaptive-window-list',
        });
        this._rail.add_child(this._dockAppsBox);

        const separator = new St.Widget({
            style_class: 'adaptive-rail-rule',
        });
        this._rail.add_child(separator);

        this._showAppsButton = this._utilityDockButton(
            'apps.svg',
            'Applications',
            () => this._showApplications()
        );
        this._showAppsButton.add_style_class_name(
            'adaptive-show-apps-button'
        );
        this._rail.add_child(this._showAppsButton);

        this._rail.connect(
            'enter-event',
            () => {
                this._dock26CancelHide();
                return Clutter.EVENT_PROPAGATE;
            }
        );

        this._rail.connect(
            'leave-event',
            () => {
                this._dock26ScheduleHide();
                return Clutter.EVENT_PROPAGATE;
            }
        );

        Main.layoutManager.addChrome(
            this._dockChrome,
            {
                affectsStruts: true,
                trackFullscreen: true,
            }
        );

        Main.layoutManager.addChrome(
            this._rail,
            {
                affectsStruts: false,
                trackFullscreen: false,
            }
        );
    }

    _readCommand(argv, callback) {
        let proc;

        try {
            proc = Gio.Subprocess.new(
                argv,
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE
            );
        } catch (e) {
            callback('');
            return;
        }

        proc.communicate_utf8_async(null, null, (source, result) => {
            try {
                const [, stdout] = source.communicate_utf8_finish(result);
                callback((stdout || '').trim());
            } catch (e) {
                callback('');
            }
        });
    }

    _matchLine(text, regex) {
        const match = text.match(regex);
        return match ? match[1] : '';
    }

    _humanStatus(value) {
        const clean = (value || '').trim().replace(/-/g, ' ');

        if (!clean)
            return 'Unavailable';

        return clean.charAt(0).toUpperCase() + clean.slice(1);
    }

    // Icon-only, as in the design: the rail is a column of marks, not a list of
    // rows. Names live in the tooltip so nothing is lost.
    _dockContent(iconFile, labelText) {
        const iconPath = GLib.build_filenamev([
            Me.path,
            'assets',
            'dock',
            iconFile,
        ]);

        return new St.Icon({
            gicon: Gio.FileIcon.new(Gio.File.new_for_path(iconPath)),
            style_class: 'adaptive-dock-icon',
            x_align: Clutter.ActorAlign.CENTER,
            y_align: Clutter.ActorAlign.CENTER,
        });
    }

    _addTooltip(actor, text) {
        actor.connect('notify::hover', () => {
            if (actor.hover) {
                if (this._dockDemagnifyId) {
                    GLib.Source.remove(this._dockDemagnifyId);
                    this._dockDemagnifyId = 0;
                }

                if (this._tooltipTimeoutId) {
                    GLib.Source.remove(this._tooltipTimeoutId);
                    this._tooltipTimeoutId = 0;
                }

                this._magnifyDock(actor);

                this._tooltipTimeoutId = GLib.timeout_add(
                    GLib.PRIORITY_DEFAULT,
                    280,
                    () => {
                        this._tooltipTimeoutId = 0;
                        if (actor.hover)
                            this._showTooltip(actor, text);
                        return GLib.SOURCE_REMOVE;
                    }
                );
            } else {
                if (this._tooltipTimeoutId) {
                    GLib.Source.remove(this._tooltipTimeoutId);
                    this._tooltipTimeoutId = 0;
                }

                this._hideTooltip();
                this._scheduleDockDemagnify();
            }
        });

        actor.connect('destroy', () => {
            if (this._tooltipTimeoutId) {
                GLib.Source.remove(this._tooltipTimeoutId);
                this._tooltipTimeoutId = 0;
            }
            this._hideTooltip();
        });
    }

    _scheduleDockDemagnify() {
        if (this._dockDemagnifyId)
            GLib.Source.remove(this._dockDemagnifyId);

        this._dockDemagnifyId = GLib.timeout_add(
            GLib.PRIORITY_DEFAULT,
            85,
            () => {
                this._dockDemagnifyId = 0;
                const hovered = this._dockButtons.find(
                    button => button && button.hover
                );
                this._magnifyDock(hovered || null);
                return GLib.SOURCE_REMOVE;
            }
        );
    }

    _showTooltip(actor, text) {
        this._hideTooltip();

        this._tooltip = new St.Label({
            text,
            style_class: 'adaptive-tooltip',
        });
        Main.layoutManager.addChrome(this._tooltip);

        const [x, y] = actor.get_transformed_position();
        const [, naturalWidth] = this._tooltip.get_preferred_width(-1);
        const [, naturalHeight] = this._tooltip.get_preferred_height(naturalWidth);

        const monitor = Main.layoutManager.primaryMonitor;
        let targetX = Math.round(x + actor.get_width() / 2 - naturalWidth / 2);
        const targetY = Math.round(y - naturalHeight - 12);

        if (monitor) {
            targetX = Math.max(
                monitor.x + 8,
                Math.min(targetX, monitor.x + monitor.width - naturalWidth - 8)
            );
        }

        this._tooltip.set_position(targetX, targetY);
    }

    _hideTooltip() {
        if (!this._tooltip)
            return;

        Main.layoutManager.removeChrome(this._tooltip);
        this._tooltip.destroy();
        this._tooltip = null;
    }

    _queueWindowListRefresh() {
        if (this._windowRefreshId)
            return;

        this._windowRefreshId = GLib.timeout_add(
            GLib.PRIORITY_DEFAULT,
            110,
            () => {
                this._windowRefreshId = 0;
                this._refreshWindowList();
                return GLib.SOURCE_REMOVE;
            }
        );
    }

    _disconnectWindowSignals() {
        for (const item of this._windowSignalIds) {
            try {
                item.window.disconnect(item.id);
            } catch (e) {
                logError(e, '[Adaptive Shell] disconnect window signal');
            }
        }
        this._windowSignalIds = [];
    }

    _destroyDockMenus() {
        for (const menu of this._dockMenus) {
            try {
                menu.destroy();
            } catch (e) {
                logError(e, '[Adaptive Shell] destroy dock menu');
            }
        }
        this._dockMenus = [];
    }

    _refreshWindowList() {
        if (!this._dockAppsBox)
            return;

        this._disconnectWindowSignals();
        this._destroyDockMenus();
        this._dockAppsBox.destroy_all_children();
        this._dockButtons = [];

        const favorites = this._favorites || AppFavorites.getAppFavorites();
        const favoriteApps = favorites.getFavorites();
        const favoriteIds = new Set(favoriteApps.map(app => app.get_id()));

        const runningApps = Shell.AppSystem.get_default().get_running()
            .filter(app => !favoriteIds.has(app.get_id()))
            .sort((a, b) => this._appRecentTime(b) - this._appRecentTime(a));

        const apps = favoriteApps.concat(runningApps);

        for (const app of apps) {
            const windows = this._appWindows(app);
            const favorite = favorites.isFavorite(app.get_id());

            if (!favorite && windows.length === 0)
                continue;

            const button = this._appDockButton(app, windows, favorite);
            button._adaptiveDockApp = app;
            this._dockAppsBox.add_child(button);
            this._dockButtons.push(button);

            for (const window of windows) {
                try {
                    this._windowSignalIds.push({
                        window,
                        id: window.connect(
                            'unmanaged',
                            () => this._queueWindowListRefresh()
                        ),
                    });
                } catch (e) {
                    logError(e, '[Adaptive Shell] connect window signal');
                }
            }
        }

        if (this._showAppsButton && !this._dockButtons.includes(this._showAppsButton))
            this._dockButtons.push(this._showAppsButton);

        this._syncDockActive();
        this._layoutRail();
    }

    _appWindows(app) {
        try {
            return app.get_windows()
                .filter(window => this._isDockWindow(window))
                .sort((a, b) => this._windowRecentTime(b) - this._windowRecentTime(a));
        } catch (e) {
            return [];
        }
    }

    _windowRecentTime(window) {
        try {
            return window.get_user_time ? window.get_user_time() : 0;
        } catch (e) {
            return 0;
        }
    }

    _appRecentTime(app) {
        const windows = this._appWindows(app);
        return windows.length ? this._windowRecentTime(windows[0]) : 0;
    }

    _isDockWindow(window) {
        if (!window)
            return false;

        try {
            if (window.skip_taskbar)
                return false;
            if (window.is_override_redirect && window.is_override_redirect())
                return false;
            return true;
        } catch (e) {
            return false;
        }
    }

    _appDockButton(app, windows, favorite) {
        const appName = app.get_name() || app.get_id() || 'Application';
        const isActive = this._isFocusedApp(app);

        const button = new St.Button({
            reactive: true,
            can_focus: true,
            track_hover: true,
            style_class: isActive ? 'adaptive-dock-button active' : 'adaptive-dock-button',
            accessible_name: appName,
        });
        button.set_pivot_point(0.5, 1.0);

        const content = new St.BoxLayout({
            vertical: true,
            style_class: 'adaptive-app-dock-content',
            x_align: Clutter.ActorAlign.CENTER,
        });

        let icon;
        try {
            icon = app.create_icon_texture(36);
        } catch (e) {
            icon = new St.Icon({
                icon_name: 'application-x-executable-symbolic',
                icon_size: 36,
            });
        }
        icon.add_style_class_name('adaptive-app-icon');
        content.add_child(icon);
        content.add_child(this._windowIndicators(windows.length, isActive));
        button.set_child(content);

        this._addTooltip(button, appName);
        button.connect('clicked', () => this._activateDockApp(app));

        button.connect('button-press-event', (_actor, event) => {
            const mouseButton = event.get_button();

            if (mouseButton === 2) {
                this._openNewWindow(app);
                return Clutter.EVENT_STOP;
            }

            if (mouseButton === 3) {
                this._hideTooltip();
                this._openDockMenu(button, app, windows, favorite);
                return Clutter.EVENT_STOP;
            }

            return Clutter.EVENT_PROPAGATE;
        });

        return button;
    }

    _windowIndicators(windowCount, active) {
        const row = new St.BoxLayout({
            vertical: false,
            style_class: active
                ? 'adaptive-running-indicators active'
                : 'adaptive-running-indicators',
            x_align: Clutter.ActorAlign.CENTER,
        });

        if (windowCount <= 0)
            return row;

        const visibleDots = Math.min(windowCount, 5);
        for (let i = 0; i < visibleDots; i++) {
            row.add_child(new St.Widget({
                style_class: active ? 'adaptive-running-dot active' : 'adaptive-running-dot',
            }));
        }

        if (windowCount > 5) {
            row.add_child(new St.Label({
                text: `${windowCount}`,
                style_class: 'adaptive-running-count',
            }));
        }

        return row;
    }

    _isFocusedApp(app) {
        const focus = global.display.focus_window;
        if (!focus)
            return false;

        try {
            return Shell.WindowTracker.get_default().get_window_app(focus) === app;
        } catch (e) {
            return false;
        }
    }

    _activateDockApp(app) {
        const windows = this._appWindows(app);

        if (windows.length === 0) {
            app.activate();
            return;
        }

        const focus = global.display.focus_window;
        const tracker = Shell.WindowTracker.get_default();
        const focusedApp = focus ? tracker.get_window_app(focus) : null;

        let target = windows[0];
        if (focusedApp === app && windows.length > 1) {
            const index = windows.indexOf(focus);
            target = windows[(index + 1 + windows.length) % windows.length];
        }

        Main.activateWindow(target);
    }

    _openNewWindow(app) {
        try {
            if (
                typeof app.can_open_new_window === 'function' &&
                !app.can_open_new_window()
            ) {
                app.activate();
                return;
            }

            if (typeof app.open_new_window === 'function') {
                app.open_new_window(-1);
                return;
            }

            app.activate();
        } catch (e) {
            logError(e, '[Adaptive Shell] open new window');
        }
    }

    _openDockMenu(button, app, windows, favorite) {
        this._destroyDockMenus();
        this._hideTooltip();

        const menu = new PopupMenu.PopupMenu(button, 0.5, St.Side.BOTTOM);
        menu.actor.add_style_class_name('adaptive-dock-popup');
        Main.uiGroup.add_actor(menu.actor);
        menu.actor.hide();
        this._dockMenuManager.addMenu(menu);
        this._dockMenus.push(menu);

        const openItem = new PopupMenu.PopupMenuItem(
            windows.length ? 'Activate' : 'Open'
        );
        openItem.connect('activate', () => this._activateDockApp(app));
        menu.addMenuItem(openItem);

        const canOpenNew =
            typeof app.can_open_new_window !== 'function' ||
            app.can_open_new_window();

        if (canOpenNew) {
            const newWindowItem = new PopupMenu.PopupMenuItem('New Window');
            newWindowItem.connect('activate', () => this._openNewWindow(app));
            menu.addMenuItem(newWindowItem);
        }

        if (windows.length > 1) {
            menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
            for (const window of windows) {
                const title = window.get_title() || app.get_name() || 'Window';
                const windowItem = new PopupMenu.PopupMenuItem(title);
                windowItem.connect('activate', () => Main.activateWindow(window));
                menu.addMenuItem(windowItem);
            }
        }

        const appId = app.get_id();
        const canFavorite =
            !!appId &&
            !(typeof app.is_window_backed === 'function' && app.is_window_backed());

        if (canFavorite) {
            menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

            const favoriteNow = this._favorites
                ? this._favorites.isFavorite(appId)
                : favorite;

            const favoriteItem = new PopupMenu.PopupMenuItem(
                favoriteNow ? 'Remove from Favorites' : 'Add to Favorites'
            );

            favoriteItem.connect('activate', () => {
                const currentlyFavorite = this._favorites.isFavorite(appId);
                if (currentlyFavorite)
                    this._favorites.removeFavorite(appId);
                else
                    this._favorites.addFavorite(appId);

                menu.close();
                this._queueWindowListRefresh();
            });
            menu.addMenuItem(favoriteItem);
        }

        if (windows.length > 0) {
            menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
            const closeItem = new PopupMenu.PopupMenuItem(
                windows.length === 1 ? 'Close Window' : `Close ${windows.length} Windows`
            );
            closeItem.connect('activate', () => {
                const timestamp = global.get_current_time();
                for (const window of this._appWindows(app)) {
                    try {
                        window.delete(timestamp);
                    } catch (e) {
                        logError(e, '[Adaptive Shell] close window');
                    }
                }
            });
            menu.addMenuItem(closeItem);
        }

        menu.connect('open-state-changed', (_menu, open) => {
            if (!open)
                this._scheduleDockDemagnify();
        });

        menu.open();
    }

    _utilityDockButton(iconFile, name, callback) {
        const button = new St.Button({
            reactive: true,
            can_focus: true,
            track_hover: true,
            style_class: 'adaptive-dock-button adaptive-utility-dock-button',
            accessible_name: name,
        });
        button.set_pivot_point(0.5, 1.0);
        button.set_child(this._dockContent(iconFile, name));
        button.connect('clicked', callback);
        this._addTooltip(button, name);
        return button;
    }

    _magnifyDock(activeButton) {
        const activeIndex =
            activeButton
                ? this._dockButtons.indexOf(activeButton)
                : -1;

        for (
            let i = 0;
            i < this._dockButtons.length;
            i++
        ) {
            const button = this._dockButtons[i];

            if (!button)
                continue;

            let scale = 1.0;
            let lift = 0;

            if (activeIndex >= 0) {
                const distance =
                    Math.abs(i - activeIndex);

                if (distance === 0) {
                    scale = 1.18;
                    lift = -5;
                } else if (distance === 1) {
                    scale = 1.08;
                    lift = -1;
                }
            }

            button.remove_all_transitions();

            button.ease({
                scale_x: scale,
                scale_y: scale,
                translation_y: lift,
                duration: 120,
                mode:
                    Clutter.AnimationMode
                        .EASE_OUT_QUAD,
            });
        }
    }

    _layoutRail() {
        this._dock26EnsureTargetMonitor();
        this._dock26Layout();
    }

    _showOverview() {
        Main.overview.show();
    }

    _toggleOverview() {
        if (Main.overview.visible)
            Main.overview.hide();
        else
            Main.overview.show();

        this._syncDockActive();
    }

    // Pressing the button a second time should put the desktop back, rather
    // than re-showing a grid that is already on screen.
    _showApplications() {
        if (this._appsShowing()) {
            Main.overview.hide();
            this._syncDockActive();
            return;
        }

        if (Main.overview && typeof Main.overview.showApps === 'function')
            Main.overview.showApps();
        else
            Main.overview.show();

        this._syncDockActive();
    }

    _appsShowing() {
        if (!Main.overview.visible)
            return false;

        // GNOME 42's own ControlsManager._toggleAppsPage() reads this same
        // flag, so it stays true to whatever the shell thinks is showing.
        // (viewSelector, the pre-40 way to ask, no longer exists.)
        const dash = Main.overview.dash;
        return !!(dash && dash.showAppsButton && dash.showAppsButton.checked);
    }

    _toggleWorkspaces() {
        // The overview is GNOME's real workspace switcher; a rail menu could
        // only ever list what dynamic workspaces happened to exist.
        this._toggleOverview();
    }

    _showWorkspaces() {
        Main.overview.show();
        this._syncDockActive();
    }

    _setActorActive(actor, active) {
        if (!actor)
            return;

        if (active)
            actor.add_style_class_name('active');
        else
            actor.remove_style_class_name('active');
    }

    _syncDockActive() {
        for (const button of this._dockButtons) {
            if (!button || !button._adaptiveDockApp)
                continue;

            this._setActorActive(
                button,
                this._isFocusedApp(button._adaptiveDockApp)
            );
        }

        const appsUp = !!(
            Main.overview &&
            Main.overview.visible &&
            this._appsShowing()
        );
        this._setActorActive(this._showAppsButton, appsUp);
    }

    _dock26MonitorCount() {
        try {
            return Main.layoutManager.monitors.length;
        } catch (e) {
            return 0;
        }
    }

    _dock26PrimaryMonitorIndex() {
        try {
            const index = global.display.get_primary_monitor();
            if (
                Number.isInteger(index) &&
                index >= 0 &&
                index < this._dock26MonitorCount()
            )
                return index;
        } catch (e) {
        }
        return 0;
    }

    _dock26Monitor(index) {
        const monitors = Main.layoutManager.monitors || [];
        if (
            Number.isInteger(index) &&
            index >= 0 &&
            index < monitors.length
        )
            return monitors[index];

        const fallback = this._dock26PrimaryMonitorIndex();
        return monitors[fallback] ||
            Main.layoutManager.primaryMonitor ||
            null;
    }

    _dock26WindowMonitor(window) {
        if (window) {
            try {
                const index = window.get_monitor();
                if (
                    Number.isInteger(index) &&
                    index >= 0 &&
                    index < this._dock26MonitorCount()
                )
                    return index;
            } catch (e) {
            }
        }

        try {
            const current = global.display.get_current_monitor();
            if (
                Number.isInteger(current) &&
                current >= 0 &&
                current < this._dock26MonitorCount()
            )
                return current;
        } catch (e) {
        }

        return this._dock26PrimaryMonitorIndex();
    }

    _dock26EnsureTargetMonitor() {
        const count = this._dock26MonitorCount();

        if (!count) {
            this._dock26TargetMonitor = -1;
            return;
        }

        if (
            !Number.isInteger(this._dock26TargetMonitor) ||
            this._dock26TargetMonitor < 0 ||
            this._dock26TargetMonitor >= count
        ) {
            this._dock26TargetMonitor =
                this._dock26WindowMonitor(
                    global.display.get_focus_window()
                );
        }
    }

    _dock26DestroyHotEdges() {
        for (const entry of this._dock26HotEdges) {
            if (!entry || !entry.actor)
                continue;

            try {
                Main.layoutManager.removeChrome(entry.actor);
            } catch (e) {
            }

            try {
                entry.actor.destroy();
            } catch (e) {
            }
        }

        this._dock26HotEdges = [];
    }

    _dock26RebuildHotEdges() {
        this._dock26DestroyHotEdges();

        const monitors = Main.layoutManager.monitors || [];

        monitors.forEach((monitor, index) => {
            const edge = new St.Widget({
                reactive: true,
                track_hover: true,
                style_class: 'adaptive-dock-hot-edge',
            });

            edge.set_position(
                monitor.x,
                monitor.y + monitor.height -
                    this._dock26HotEdgeHeight
            );
            edge.set_size(
                monitor.width,
                this._dock26HotEdgeHeight
            );

            edge.connect(
                'enter-event',
                () => {
                    this._dock26OnEdgeEnter(index);
                    return Clutter.EVENT_PROPAGATE;
                }
            );

            edge.connect(
                'leave-event',
                () => {
                    this._dock26CancelReveal();
                    this._dock26ScheduleHide(index);
                    return Clutter.EVENT_PROPAGATE;
                }
            );

            Main.layoutManager.addChrome(
                edge,
                {
                    affectsStruts: false,
                    trackFullscreen: false,
                }
            );

            this._dock26HotEdges.push({
                actor: edge,
                index,
            });
        });

        this._dock26EnsureTargetMonitor();
        this._dock26SyncTargetFromFocus(false);
        this._dock26Layout();
    }

    _dock26EdgeForMonitor(index) {
        const entry = this._dock26HotEdges.find(
            item => item.index === index
        );
        return entry ? entry.actor : null;
    }

    _dock26WindowFullyMaximized(window) {
        if (!window)
            return false;

        try {
            if (
                typeof window.is_maximized === 'function'
            )
                return !!window.is_maximized();
        } catch (e) {
        }

        try {
            const flags = window.get_maximize_flags();
            return !!(
                (flags & Meta.MaximizeFlags.HORIZONTAL) &&
                (flags & Meta.MaximizeFlags.VERTICAL)
            );
        } catch (e) {
        }

        try {
            return !!(
                window.maximized_horizontally &&
                window.maximized_vertically
            );
        } catch (e) {
            return false;
        }
    }

    // Mutter's get_monitor_in_fullscreen() tracks the *topmost* window, so it
    // flips false the moment anything stacks above the fullscreen window - a
    // quick-settings menu, a Ctrl+Alt+T terminal, a file-picker for an upload.
    // The dock would then reveal itself over content that is still fullscreen.
    // So it is only one of two signals: the workspace scan below reports a
    // fullscreen window on this monitor no matter what sits on top of it.
    _dock26MonitorInFullscreen(index) {
        try {
            if (
                typeof global.display
                    .get_monitor_in_fullscreen === 'function'
            ) {
                if (!!global.display.get_monitor_in_fullscreen(index))
                    return true;
            }
        } catch (e) {
        }

        try {
            const workspace =
                global.workspace_manager.get_active_workspace();

            if (!workspace)
                return false;

            for (const window of workspace.list_windows()) {
                try {
                    // A minimized fullscreen window is not on screen, so it
                    // must not keep the dock suppressed.
                    if (
                        window.get_monitor() === index &&
                        window.is_fullscreen() &&
                        !window.minimized
                    )
                        return true;
                } catch (e) {
                }
            }
        } catch (e) {
        }

        return false;
    }

    _dock26MonitorHasFocusedMaximized(index) {
        if (!this._dock26HideOnMaximized)
            return false;

        const window = global.display.get_focus_window();
        if (!window)
            return false;

        try {
            if (window.get_monitor() !== index)
                return false;
        } catch (e) {
            return false;
        }

        return this._dock26WindowFullyMaximized(window);
    }

    _dock26MonitorNeedsHide(index) {
        return (
            this._dock26MonitorInFullscreen(index) ||
            this._dock26MonitorHasFocusedMaximized(index)
        );
    }

    _dock26SyncTargetFromFocus(forceMove = true) {
        const window = global.display.get_focus_window();
        const index = this._dock26WindowMonitor(window);

        if (
            !forceMove &&
            this._dock26TargetMonitor >= 0
        ) {
            this._dock26WatchFocusWindow();
            return;
        }

        if (
            Number.isInteger(index) &&
            index >= 0
        )
            this._dock26TargetMonitor = index;

        this._dock26EdgeRevealed = false;
        this._dock26WatchFocusWindow();
        this._dock26SyncVisibility();
    }

    _dock26DisconnectFocusWindow() {
        if (!this._dock26FocusWindow) {
            this._dock26FocusSignalIds = [];
            return;
        }

        for (const id of this._dock26FocusSignalIds) {
            try {
                this._dock26FocusWindow.disconnect(id);
            } catch (e) {
            }
        }

        this._dock26FocusSignalIds = [];
        this._dock26FocusWindow = null;
    }

    _dock26WatchFocusWindow() {
        this._dock26DisconnectFocusWindow();

        const window = global.display.get_focus_window();
        if (!window)
            return;

        this._dock26FocusWindow = window;

        const changed = () => {
            this._dock26TargetMonitor =
                this._dock26WindowMonitor(window);
            this._dock26EdgeRevealed = false;
            this._dock26SyncVisibility();
        };

        for (const signal of [
            'notify::maximized-horizontally',
            'notify::maximized-vertically',
            'notify::fullscreen',
            'size-changed',
            'position-changed',
        ]) {
            try {
                const id = window.connect(signal, changed);
                this._dock26FocusSignalIds.push(id);
            } catch (e) {
            }
        }
    }

    _dock26CancelReveal() {
        if (!this._dock26RevealTimerId)
            return;

        GLib.Source.remove(this._dock26RevealTimerId);
        this._dock26RevealTimerId = 0;
    }

    _dock26CancelHide() {
        if (!this._dock26HideTimerId)
            return;

        GLib.Source.remove(this._dock26HideTimerId);
        this._dock26HideTimerId = 0;
    }

    _dock26OnEdgeEnter(index) {
        this._dock26CancelHide();
        this._dock26CancelReveal();

        this._dock26TargetMonitor = index;

        if (!this._dock26MonitorNeedsHide(index)) {
            this._dock26EdgeRevealed = true;
            this._dock26Layout();
            return;
        }

        this._dock26EdgeRevealed = false;
        this._dock26Layout();

        this._dock26RevealTimerId =
            GLib.timeout_add(
                GLib.PRIORITY_DEFAULT,
                this._dock26RevealDelayMs,
                () => {
                    this._dock26RevealTimerId = 0;

                    const edge =
                        this._dock26EdgeForMonitor(index);

                    if (!edge || !edge.hover)
                        return GLib.SOURCE_REMOVE;

                    this._dock26TargetMonitor = index;
                    this._dock26EdgeRevealed = true;
                    this._dock26Layout();

                    return GLib.SOURCE_REMOVE;
                }
            );
    }

    _dock26ScheduleHide(
        index = this._dock26TargetMonitor
    ) {
        this._dock26CancelHide();

        if (!this._dock26MonitorNeedsHide(index))
            return;

        this._dock26HideTimerId =
            GLib.timeout_add(
                GLib.PRIORITY_DEFAULT,
                this._dock26HideDelayMs,
                () => {
                    this._dock26HideTimerId = 0;

                    const edge =
                        this._dock26EdgeForMonitor(index);

                    if (
                        (this._rail && this._rail.hover) ||
                        (edge && edge.hover)
                    )
                        return GLib.SOURCE_REMOVE;

                    this._dock26EdgeRevealed = false;
                    this._dock26Layout();

                    return GLib.SOURCE_REMOVE;
                }
            );
    }

    _dock26ShowDock(animated) {
        if (!this._rail)
            return;

        this._rail.reactive = true;
        this._rail.show();
        this._rail.remove_all_transitions();

        if (!animated) {
            this._rail.opacity = 255;
            this._rail.translation_y = 0;
            return;
        }

        this._rail.ease({
            opacity: 255,
            translation_y: 0,
            duration: this._dock26RevealDurationMs,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
        });
    }

    _dock26HideDock(animated) {
        if (!this._rail)
            return;

        this._rail.reactive = false;
        this._rail.remove_all_transitions();

        const offset =
            this._dock26SurfaceHeight +
            this._dock26BottomGap + 8;

        if (!animated) {
            this._rail.opacity = 0;
            this._rail.translation_y = offset;
            return;
        }

        this._rail.ease({
            opacity: 0,
            translation_y: offset,
            duration: this._dock26HideDurationMs,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
        });
    }

    _dock26Layout() {
        if (!this._rail || !this._dockChrome)
            return;

        this._dock26EnsureTargetMonitor();

        const index = this._dock26TargetMonitor;
        const monitor = this._dock26Monitor(index);
        if (!monitor)
            return;

        const [, naturalWidth] =
            this._rail.get_preferred_width(-1);

        const width = Math.max(
            100,
            Math.min(
                Math.ceil(naturalWidth),
                monitor.width - 24
            )
        );

        const x =
            monitor.x +
            Math.round((monitor.width - width) / 2);

        const y =
            monitor.y +
            monitor.height -
            this._dock26SurfaceHeight -
            this._dock26BottomGap;

        this._rail.set_position(x, y);
        this._rail.set_size(
            width,
            this._dock26SurfaceHeight
        );

        const hidden =
            this._dock26MonitorNeedsHide(index);

        if (hidden) {
            this._dockChrome.set_position(
                monitor.x,
                monitor.y + monitor.height - 1
            );
            this._dockChrome.set_size(
                monitor.width,
                1
            );

            if (this._dock26EdgeRevealed)
                this._dock26ShowDock(true);
            else
                this._dock26HideDock(true);
        } else {
            this._dockChrome.set_position(
                monitor.x,
                monitor.y +
                    monitor.height -
                    this._dock26ReservedHeight
            );
            this._dockChrome.set_size(
                monitor.width,
                this._dock26ReservedHeight
            );

            this._dock26EdgeRevealed = false;
            this._dock26ShowDock(false);
        }

        try {
            if (
                typeof Main.layoutManager
                    ._queueUpdateRegions === 'function'
            )
                Main.layoutManager._queueUpdateRegions();
        } catch (e) {
            logError(
                e,
                '[Adaptive Shell] v2.6 work-area update'
            );
        }
    }

    _dock26SyncVisibility() {
        this._dock26EnsureTargetMonitor();
        this._dock26Layout();
    }

    _dock26ConnectRuntime() {
        this._dock26RebuildHotEdges();

        if (!this._dock26FullscreenSignalId) {
            try {
                this._dock26FullscreenSignalId =
                    global.display.connect(
                        'in-fullscreen-changed',
                        () => {
                            this._dock26EdgeRevealed = false;
                            this._dock26SyncVisibility();
                        }
                    );
            } catch (e) {
                logError(
                    e,
                    '[Adaptive Shell] v2.6 fullscreen signal'
                );
            }
        }

        if (!this._dock26FocusChangedId) {
            this._dock26FocusChangedId =
                global.display.connect(
                    'notify::focus-window',
                    () =>
                        this._dock26SyncTargetFromFocus(true)
                );
        }

        if (!this._dock26WindowEnteredMonitorId) {
            try {
                this._dock26WindowEnteredMonitorId =
                    global.display.connect(
                        'window-entered-monitor',
                        (_display, monitorIndex, window) => {
                            if (
                                window ===
                                global.display.get_focus_window()
                            ) {
                                this._dock26TargetMonitor =
                                    monitorIndex;
                                this._dock26EdgeRevealed = false;
                                this._dock26SyncVisibility();
                            }
                        }
                    );
            } catch (e) {
            }
        }

        if (!this._dock26MonitorsChangedId) {
            this._dock26MonitorsChangedId =
                Main.layoutManager.connect(
                    'monitors-changed',
                    () => this._dock26RebuildHotEdges()
                );
        }

        this._dock26SyncTargetFromFocus(true);
    }

    _dock26Cleanup() {
        this._dock26CancelReveal();
        this._dock26CancelHide();
        this._dock26DisconnectFocusWindow();
        this._dock26DestroyHotEdges();

        if (this._dock26FullscreenSignalId) {
            try {
                global.display.disconnect(
                    this._dock26FullscreenSignalId
                );
            } catch (e) {
            }
            this._dock26FullscreenSignalId = 0;
        }

        if (this._dock26FocusChangedId) {
            try {
                global.display.disconnect(
                    this._dock26FocusChangedId
                );
            } catch (e) {
            }
            this._dock26FocusChangedId = 0;
        }

        if (this._dock26WindowEnteredMonitorId) {
            try {
                global.display.disconnect(
                    this._dock26WindowEnteredMonitorId
                );
            } catch (e) {
            }
            this._dock26WindowEnteredMonitorId = 0;
        }

        if (this._dock26MonitorsChangedId) {
            try {
                Main.layoutManager.disconnect(
                    this._dock26MonitorsChangedId
                );
            } catch (e) {
            }
            this._dock26MonitorsChangedId = 0;
        }
    }

    _syncDockVisibility() {
        this._dock26SyncVisibility();
    }

    _runSettingsSection(section) {
        this._spawn(section.argv);
    }

    _activateApp(desktopId, fallbackArgv) {
        const app = Shell.AppSystem.get_default().lookup_app(desktopId);

        if (app) {
            app.activate();
            return;
        }

        if (fallbackArgv)
            this._spawn(fallbackArgv);
    }

    _openFiles() {
        this._activateApp('org.gnome.Nautilus.desktop', ['nautilus']);
    }

    _openCommand() {
        if (!GLib.file_test(this._commandLauncher, GLib.FileTest.IS_EXECUTABLE)) {
            Main.notifyError('Adaptive Desktop', 'Command palette is not installed.');
            return;
        }

        this._spawn([this._commandLauncher]);
    }

    _openSettings() {
        this._activateApp('gnome-control-center.desktop', ['gnome-control-center']);
    }

    _runFocus(mode) {
        if (!GLib.file_test(this._focusCli, GLib.FileTest.IS_EXECUTABLE)) {
            Main.notifyError('Adaptive Desktop', 'Focus controls are not installed.');
            return;
        }

        this._spawn([
            this._focusCli,
            mode,
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
