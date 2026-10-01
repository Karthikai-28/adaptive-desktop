// Adaptive Shell - the bottom dock: building it, its app buttons, menus and magnification.
//
// Part of the one AdaptiveShellV16 object in extension.js, kept in its own
// file by subject. The methods of the class below are copied onto that object
// when the extension loads, so `this` here is the shell itself and every
// field and method of the other parts is reachable through it.

/* exported ShellDock */

const { St, Gio, GLib, Clutter, Shell } = imports.gi;
const Main = imports.ui.main;
const PopupMenu = imports.ui.popupMenu;
const AppFavorites = imports.ui.appFavorites;
const DND = imports.ui.dnd;
const ExtensionUtils = imports.misc.extensionUtils;

const Me = ExtensionUtils.getCurrentExtension();
const DockExtras = Me.imports.dockExtras;

var ShellDock = class ShellDock {
    // Where a window minimises to: its app's icon on the dock of the screen it
    // is on, or that dock's middle if the app has no icon there.
    _dockIconRect(window) {
        const docks = this._docks || [];
        const dock = docks.find(d => d.index === window.get_monitor()) || docks[0];
        if (!dock || !dock.rail)
            return null;

        const app = Shell.WindowTracker.get_default().get_window_app(window);
        const button = app && dock.appsBox.get_children().find(
            c => c._adaptiveDockApp && c._adaptiveDockApp.get_id() === app.get_id());
        const target = button || dock.rail;

        const [x, y] = target.get_transformed_position();
        const [width, height] = target.get_transformed_size();
        if (button)
            return { x, y, width, height };
        return { x: x + width / 2 - 24, y, width: 48, height };
    }

    _installRail() {
        this._dockChrome = new St.Widget({
            reactive: false,
            style_class: 'adaptive-dock-reservation',
        });

        this._docks = [];
        this._buildDocks();

        Main.layoutManager.addChrome(
            this._dockChrome,
            {
                affectsStruts: true,
                trackFullscreen: true,
            }
        );

    }

    // Every monitor gets its own dock.
    //
    // With one dock, something has to decide which screen it belongs on, and
    // that was the focused window - so the monitor you were not working on had
    // no dock at all. Per-monitor docks remove the question entirely: each one
    // reveals on its own bottom edge and knows nothing about the others.
    _buildDocks() {
        this._destroyDocks();

        const monitors = Main.layoutManager.monitors || [];
        monitors.forEach((_monitor, index) => {
            this._docks.push(this._buildDockSurface(index));
        });

        log(`[Adaptive Shell] docks: ${this._docks.length} for `
            + `${monitors.length} monitor(s)`);
    }

    _buildDockSurface(index) {
        const rail = new St.BoxLayout({
            vertical: false,
            reactive: true,
            track_hover: true,
            style_class: 'adaptive-rail',
        });

        const appsBox = new St.BoxLayout({
            vertical: false,
            reactive: true,
            style_class: 'adaptive-window-list',
        });
        rail.add_child(appsBox);

        rail.add_child(new St.Widget({ style_class: 'adaptive-rail-rule' }));

        // Downloads and Trash sit after the divider, as on a Mac.
        const downloads = this._themedDockButton('folder-download', 'Downloads', button => {
            this._toggleDownloadsStack(button);
        });
        rail.add_child(downloads);

        const trash = this._themedDockButton('user-trash', 'Trash', () => {
            this._closeDockPopups();
            Gio.AppInfo.launch_default_for_uri('trash:///', null);
        });
        trash.connect('button-press-event', (_actor, event) => {
            if (event.get_button() !== 3)
                return Clutter.EVENT_PROPAGATE;
            this._openTrashMenu(trash);
            return Clutter.EVENT_STOP;
        });
        rail.add_child(trash);

        const showApps = this._utilityDockButton(
            'apps.svg',
            'Applications',
            () => this._showApplications()
        );
        showApps.add_style_class_name('adaptive-show-apps-button');
        rail.add_child(showApps);

        const dock = {
            index, rail, appsBox, showApps, downloads, trash,
            revealed: false, hideId: 0,
        };
        this._syncDockUtilities(dock);

        // Right-click on the dock itself (not an icon): its settings.
        rail.connect('button-press-event', (_actor, event) => {
            if (event.get_button() !== 3)
                return Clutter.EVENT_PROPAGATE;
            const source = event.get_source();
            if (source === rail || source === appsBox || (source && source.style_class === 'adaptive-rail-rule')) {
                this._openDockSettingsMenu(rail);
                return Clutter.EVENT_STOP;
            }
            return Clutter.EVENT_PROPAGATE;
        });

        // The whole dock is a drop target: DND walks up from the actor under
        // the pointer to the first delegate that handles drops.
        rail._delegate = {
            handleDragOver: (source, _actor, x) => this._dockDragOver(dock, source, x),
            acceptDrop: (source, _actor, x) => this._dockAcceptDrop(dock, source, x),
        };

        rail.connect('enter-event', () => {
            this._dockCancelHide(dock);
            return Clutter.EVENT_PROPAGATE;
        });

        rail.connect('leave-event', () => {
            this._dockScheduleHide(dock);
            return Clutter.EVENT_PROPAGATE;
        });

        Main.layoutManager.addChrome(rail, {
            affectsStruts: false,
            trackFullscreen: false,
        });

        // Existing code and the verification scripts expect a _rail.
        if (index === 0) {
            this._rail = rail;
            this._dockAppsBox = appsBox;
            this._showAppsButton = showApps;

            if (!this._dockMenuManager) {
                this._dockMenuManager =
                    new PopupMenu.PopupMenuManager({ actor: rail });
            }
        }

        return dock;
    }

    _destroyDocks() {
        for (const dock of this._docks || []) {
            this._dockCancelHide(dock);
            this._dock26StopWatchingPointer(dock);

            try {
                Main.layoutManager.removeChrome(dock.rail);
                dock.rail.destroy();
            } catch (e) {
            }
        }

        this._docks = [];
        this._rail = null;
        this._dockAppsBox = null;
        this._showAppsButton = null;

        // These all point at actors that have just been destroyed.
        this._destroyDockMenus();
        this._dockMenuManager = null;
        this._dockButtons = [];
    }

    _dockForMonitor(index) {
        return (this._docks || []).find(d => d.index === index) || null;
    }

    _dockCancelHide(dock) {
        if (dock && dock.hideId) {
            GLib.Source.remove(dock.hideId);
            dock.hideId = 0;
        }
    }

    _dockScheduleHide(dock) {
        if (!dock)
            return;

        this._dockCancelHide(dock);

        // A dock that is not hiding for any other reason stays put.
        if (!this._dock26MonitorNeedsHide(dock.index))
            return;

        dock.hideId = GLib.timeout_add(
            GLib.PRIORITY_DEFAULT,
            this._dock26HideDelayMs,
            () => {
                dock.hideId = 0;

                if (!this._dock26PointerHoldsDock(dock)) {
                    dock.revealed = false;
                    this._dock26Layout();
                }

                return GLib.SOURCE_REMOVE;
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

        // Clamp to the monitor the button is actually on. Clamping to the
        // primary one dragged tooltips for a secondary monitor's dock back
        // onto the primary screen.
        const monitor =
            Main.layoutManager.findMonitorForActor(actor) ||
            Main.layoutManager.primaryMonitor;

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
        if (!this._docks || !this._docks.length)
            return;

        // Rebuilding mid-drag would destroy the icon being dragged and the
        // gap it leaves; catch up when the drag ends.
        if (this._dockDrag) {
            this._dockRefreshPending = true;
            return;
        }

        // Reset once, not once per dock: doing this inside the loop tore down
        // the menus and signal connections the previous monitor's dock had
        // just made.
        this._disconnectWindowSignals();
        this._destroyDockMenus();
        this._dockButtons = [];

        const favorites = this._favorites || AppFavorites.getAppFavorites();
        const favoriteApps = favorites.getFavorites();
        const favoriteIds = new Set(favoriteApps.map(app => app.get_id()));

        const runningApps = Shell.AppSystem.get_default().get_running()
            .filter(app => !favoriteIds.has(app.get_id()))
            .sort((a, b) => this._appRecentTime(b) - this._appRecentTime(a));

        const entries = [];

        for (const app of favoriteApps.concat(runningApps)) {
            const windows = this._appWindows(app);
            const favorite = favorites.isFavorite(app.get_id());

            if (!favorite && windows.length === 0)
                continue;

            entries.push({ app, windows, favorite });

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

        // Recently used apps that are neither pinned nor open, after a divider.
        if (this._dockConfig.showRecent) {
            const shown = new Set(entries.map(e => e.app.get_id()));
            let recent = [];
            try {
                recent = Shell.AppUsage.get_default().get_most_used();
            } catch (e) {
            }
            for (const app of recent.filter(a => a && !shown.has(a.get_id())).slice(0, 3))
                entries.push({ app, windows: [], favorite: false, recent: true });
        }
        this._dockEntries = entries;

        for (const dock of this._docks)
            this._fillDock(dock, entries);

        this._syncDockActive();
        this._layoutRail();
    }

    // Every dock shows the same apps, but with its own button actors - an
    // actor has one parent, so a button cannot be on two monitors at once.
    _fillDock(dock, entries) {
        if (!dock || !dock.appsBox)
            return;

        dock.appsBox.destroy_all_children();

        // With more than one display, each dock shows the windows on its own
        // screen; pinned (and recent) apps appear on every dock.
        const perMonitor = this._dockConfig.perMonitor && (this._docks || []).length > 1;
        let dividerPlaced = false;

        for (const entry of entries) {
            let windows = entry.windows;
            if (perMonitor) {
                windows = windows.filter(w => {
                    try {
                        return w.get_monitor() === dock.index;
                    } catch (e) {
                        return false;
                    }
                });
                if (!entry.favorite && !entry.recent && windows.length === 0)
                    continue;
            }

            if (entry.recent && !dividerPlaced) {
                dock.appsBox.add_child(new St.Widget({ style_class: 'adaptive-rail-rule' }));
                dividerPlaced = true;
            }

            const button = this._appDockButton(
                entry.app,
                windows,
                entry.favorite,
                perMonitor ? dock.index : -1
            );
            button._adaptiveDockApp = entry.app;
            if (entry.recent)
                button.add_style_class_name('adaptive-dock-recent');
            dock.appsBox.add_child(button);
            this._dockButtons.push(button);
        }

        for (const utility of [dock.downloads, dock.trash, dock.showApps]) {
            if (utility && utility.visible)
                this._dockButtons.push(utility);
        }
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

    _appDockButton(app, windows, favorite, monitorIndex = -1) {
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
        this._sizeDockButton(button);
        if (this._dockAttention.has(app.get_id()))
            button.add_style_class_name('attention');

        const content = new St.BoxLayout({
            vertical: true,
            style_class: 'adaptive-app-dock-content',
            x_align: Clutter.ActorAlign.CENTER,
        });

        const size = this._dockIconSize;
        let icon;
        try {
            icon = app.create_icon_texture(size);
        } catch (e) {
            icon = new St.Icon({
                icon_name: 'application-x-executable-symbolic',
                icon_size: size,
            });
        }
        icon.add_style_class_name('adaptive-app-icon');

        // The icon sits in a holder so a badge (top right) and a progress bar
        // (bottom) can lie over it.
        const holder = new St.Widget({
            layout_manager: new Clutter.BinLayout(),
            style_class: 'adaptive-dock-icon-holder',
            x_align: Clutter.ActorAlign.CENTER,
        });
        holder.add_child(icon);
        // In a BinLayout, alignment only applies to a child that may expand.
        const badge = new St.Label({
            style_class: 'adaptive-dock-badge',
            x_expand: true,
            y_expand: true,
            x_align: Clutter.ActorAlign.END,
            y_align: Clutter.ActorAlign.START,
            visible: false,
        });
        holder.add_child(badge);
        const progress = new St.Widget({
            style_class: 'adaptive-dock-progress',
            layout_manager: new Clutter.BinLayout(),
            x_expand: true,
            y_expand: true,
            y_align: Clutter.ActorAlign.END,
            visible: false,
        });
        const progressFill = new St.Widget({
            style_class: 'adaptive-dock-progress-fill',
            x_align: Clutter.ActorAlign.START,
            y_expand: true,
        });
        progress.add_child(progressFill);
        progress.connect('notify::width', () => this._syncDockBadge(button));
        holder.add_child(progress);

        content.add_child(holder);
        content.add_child(this._windowIndicators(windows.length, isActive));
        button.set_child(content);

        button._adaptiveIcon = icon;
        button._adaptiveBadge = badge;
        button._adaptiveProgress = progress;
        button._adaptiveProgressFill = progressFill;
        button._adaptiveDockApp = app;
        this._syncDockBadge(button);

        this._addTooltip(button, appName);
        button.connect('clicked', () => {
            if (this._previews)
                this._previews.hide();
            this._activateDockApp(app, monitorIndex);
        });

        // Live window previews after a moment's hover.
        button.connect('notify::hover', () => {
            if (!this._previews)
                return;
            if (button.hover && !this._dockDrag && !this._dockMenus.some(m => m.isOpen))
                this._previews.hoverStart(button, app);
            else
                this._previews.hoverEnd();
        });

        // Scroll over an icon to step through that app's windows.
        button.connect('scroll-event', (_actor, event) =>
            this._scrollDockApp(app, event, monitorIndex));

        // Drag to reorder, or off the dock to remove - the macOS gestures.
        // `app` on the delegate is what GNOME's own drop targets (the app
        // grid, workspace thumbnails) look for too.
        const shell = this;
        button._delegate = {
            // Hidden while the icon is in the "Remove from Dock" zone: the
            // Overview's workspaces accept any app and open a new window of
            // it, which would swallow the drop meant to unpin it.
            get app() {
                const drag = shell._dockDrag;
                return drag && drag.removing && drag.app === app ? null : app;
            },
            _adaptiveDockItem: true,
            getDragActor: () => app.create_icon_texture(48),
            getDragActorSource: () => icon,
        };
        const draggable = DND.makeDraggable(button);
        draggable.connect('drag-begin', () => this._dockDragBegin(button, app));
        draggable.connect('drag-cancelled', () => this._dockDragCancelled());
        draggable.connect('drag-end', () => this._dockDragEnd());

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

    _activateDockApp(app, monitorIndex = -1) {
        let windows = this._appWindows(app);

        if (windows.length === 0) {
            app.activate();
            this._bounceWhileLaunching(app);
            return;
        }

        // A dock on one display switches to that display's windows first.
        if (monitorIndex >= 0) {
            const here = windows.filter(w => w.get_monitor() === monitorIndex);
            if (here.length)
                windows = here;
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

        // The actions the app itself declares: New Incognito Window, New
        // Tab, a terminal profile... New Window is already above.
        const info = app.get_app_info ? app.get_app_info() : null;
        const actions = info && typeof info.list_actions === 'function'
            ? info.list_actions().filter(a => !/^new[-_]?window$/i.test(a))
            : [];
        if (actions.length) {
            menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
            for (const action of actions) {
                const actionItem = new PopupMenu.PopupMenuItem(info.get_action_name(action) || action);
                actionItem.connect('activate', () => {
                    try {
                        app.launch_action(action, global.get_current_time(), -1);
                        this._bounceApp(app, 1);
                    } catch (e) {
                        logError(e, `[Adaptive Shell] app action ${action}`);
                    }
                });
                menu.addMenuItem(actionItem);
            }
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

        menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        const settingsItem = new PopupMenu.PopupMenuItem('Dock Settings…');
        settingsItem.connect('activate', () => {
            GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
                this._openDockSettingsMenu(button);
                return GLib.SOURCE_REMOVE;
            });
        });
        menu.addMenuItem(settingsItem);

        menu.connect('open-state-changed', (_menu, open) => {
            if (!open)
                this._scheduleDockDemagnify();
        });

        if (this._previews)
            this._previews.hide();
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
        const icon = this._dockContent(iconFile, name);
        button.set_child(icon);
        button._adaptiveIcon = icon;
        this._sizeDockButton(button);
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

                const [hoverScale, hoverLift, nearScale, nearLift] =
                    DockExtras.MAGNIFICATION[this._dockConfig.magnification] ||
                    DockExtras.MAGNIFICATION.medium;
                if (distance === 0) {
                    scale = hoverScale;
                    lift = hoverLift;
                } else if (distance === 1) {
                    scale = nearScale;
                    lift = nearLift;
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

        // Overview.show() returns early when the Overview is already up, so
        // showApps() does nothing from the window picker. GNOME's own dash
        // switches pages through its Show Applications toggle, which the
        // Overview listens to - do the same.
        const dash = Main.overview.dash;
        if (Main.overview.visible && dash && dash.showAppsButton)
            dash.showAppsButton.checked = true;
        else if (typeof Main.overview.showApps === 'function')
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

            if (this._isFocusedApp(button._adaptiveDockApp)) {
                this._dockAttention.delete(button._adaptiveDockApp.get_id());
                button.remove_style_class_name('attention');
            }

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
        for (const dock of this._docks || [])
            this._setActorActive(dock.showApps, appsUp);
    }
};
