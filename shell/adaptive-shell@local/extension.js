// Adaptive Shell - the extension's one object and its lifecycle.
//
// AdaptiveShellV16 is the whole desktop: the bottom dock, the lock screen, the
// panels and the services behind the Command palette. This file holds what
// ties it together - its state, enable() and disable(), and installing each
// panel and service. The rest of its methods live by subject in:
//
//   shellLock.js           lock screen and always-on display
//   shellDock.js           building the dock, app buttons, menus, magnification
//   shellDockFeatures.js   badges, bounce, scroll, stacks, hotkeys, spring-load
//   shellDockDnd.js        drag and drop on the dock
//   shellDockAutohide.js   dock placement per monitor, hiding and revealing
//   shellDisplays.js       display changes and stranded-window rescue
//
// They are copied onto the class at the bottom of this file, so it is still
// one object and `this` is the same everywhere. A method called across files
// is checked by scripts/verify-shell-methods.py --class, and the whole thing
// is loaded in a real shell by scripts/verify-shell-nested.sh.

const { Gio, GLib, Shell } = imports.gi;
const Main = imports.ui.main;
const AppFavorites = imports.ui.appFavorites;
const ExtensionUtils = imports.misc.extensionUtils;

const Me = ExtensionUtils.getCurrentExtension();
const Shade = Me.imports.shade;
const DockExtras = Me.imports.dockExtras;
const ControlCenter = Me.imports.controlCenter;
const UsbDevices = Me.imports.usbDevices;
const ShellActions = Me.imports.shellActions;
const TaskManager = Me.imports.taskManager;
const NetworkPanel = Me.imports.networkPanel;
const MinimizeEffect = Me.imports.minimizeEffect;
const ClipboardHistory = Me.imports.clipboardHistory;
const ProjectSnapshots = Me.imports.projectSnapshots;
const ProjectIndicator = Me.imports.projectIndicator;
const ScreenText = Me.imports.screenText;
const DropdownTerminal = Me.imports.dropdownTerminal;
const Watchdog = Me.imports.watchdog;
const ShellLock = Me.imports.shellLock;
const ShellDock = Me.imports.shellDock;
const ShellDockFeatures = Me.imports.shellDockFeatures;
const ShellDockDnd = Me.imports.shellDockDnd;
const ShellDockAutohide = Me.imports.shellDockAutohide;
const ShellDisplays = Me.imports.shellDisplays;

// `var`, so the nested-shell check's probe can reach the running shell object
// (a GJS module exports `var`, not `let`). Nothing else reads it.
var _shell = null;

class AdaptiveShellV16 {
    constructor() {
        // Bottom application dock. The historic member name `_rail` is kept so
        // existing verification/recovery scripts remain compatible while the
        // actor itself is now a centered horizontal dock.
        this._rail = null;
        // One dock per monitor, so which screen has a dock never depends on
        // where the focused window happens to be.
        this._docks = [];
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
        // Adaptive Shade: the notification center built inside GNOME's date menu.
        this._shade = null;
        // Adaptive Control Center: the system menu rebuilt as quick settings.
        this._controlCenter = null;
        // Adaptive USB panel: plugged-in devices and serial ports, top right.
        this._usbPanel = null;
        this._shellActions = null;
        // Palette bridge services and the top-bar project hub.
        this._clipboardHistory = null;
        this._snapshots = null;
        this._screenText = null;
        this._dropdown = null;
        this._projectIndicator = null;
        // Crash watchdog: set when this start stood down instead of building.
        this._watchdogTripped = false;
        this._healthyId = 0;
        this._taskPanel = null;
        this._networkPanel = null;
        this._projectProxy = null;
        this._tooltip = null;
        this._tooltipTimeoutId = 0;
        this._dockDemagnifyId = 0;
        // Dock drag and drop: reorder, pin from the app grid, drag off to unpin.
        this._dockDrag = null;
        this._dockPlaceholder = null;
        this._dockRemoveLabel = null;
        this._dockDragMonitor = null;
        this._dockRefreshPending = false;
        this._overviewDragIds = [];
        // Dock extras: settings, badges, previews, stacks, attention, hotkeys.
        this._dockConfig = DockExtras.readDockConfig();
        this._dockIconSize = 36;
        this._launcherEntries = null;
        this._previews = null;
        this._trash = null;
        this._dockAttention = new Set();
        this._dockLaunching = new Set();
        this._dockTimers = new Set();
        this._dockExtraIds = [];
        this._hotkeysInstalled = false;
        this._springId = 0;
        this._springApp = null;
        this._dockScrollTime = 0;
        this._dockEntries = [];
        this._lockedOnly = false;
        this._lockedOnlyModeId = 0;
        this._lockedOnlyPollId = 0;
        this._lockClock = null;
        this._lockActivity = null;
        this._lockAttachId = 0;
        this._lockTickId = 0;
        this._lockAttempts = 0;
        this._lockActive = false;
        this._sessionModeId = 0;
        this._aodBox = null;
        this._aodTime = null;
        this._aodDate = null;

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
        this._displayGuard = GLib.build_filenamev([
            GLib.get_home_dir(),
            'adaptive-desktop',
            'scripts',
            'adaptive-display-guard.py',
        ]);
        this._rescueTimerId = 0;
        this._displayGuardRunAt = 0;
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
        this._dock26RelayoutId = 0;
        // Belt and braces. A settle check that never settles must not be able
        // to re-arm this idle forever: that spins the shell's main loop until
        // GC is starved and the session stops responding.
        this._dock26SettlePasses = 0;
        this._dock26HideOnMaximized = true;
        this._dock26ReservedHeight = 70;
        this._dock26SurfaceHeight = 54;
        this._dock26BottomGap = 6;
        // Reveal works like the macOS auto-hidden Dock: brushing the bottom
        // edge on the way to a sheet tab, a scrollbar or a chat box does
        // nothing; pushing on past the edge does. The push is a pressure
        // barrier (the same mechanism as the Activities hot corner), so there
        // is no reactive strip over the bottom of the window eating clicks.
        this._dock26Pressure = null;
        this._dock26Barriers = [];
        this._dock26PressureThreshold = 100;
        this._dock26PressureTimeoutMs = 1000;
        // Without extended barriers, a 1px edge the pointer has to rest on.
        this._dock26HotEdgeHeight = 1;
        this._dock26RevealDelayMs = 450;
        this._dock26PointerPollMs = 100;
        this._dock26HideDelayMs = 320;
        this._dock26RevealDurationMs = 145;
        this._dock26HideDurationMs = 145;

    }

    enable() {
        log('[Adaptive Shell v1.6] enable');

        // The extension stays enabled in unlock-dialog mode so the lock screen
        // keeps the Adaptive stylesheet. None of the desktop furniture belongs
        // there: building a dock, a panel identity or D-Bus watchers over the
        // lock screen would put interactive shell chrome in front of a locked
        // session. The stylesheet is loaded by the extension system itself, so
        // returning here still styles the lock screen.
        if (Main.sessionMode.currentMode === 'unlock-dialog' ||
            Main.sessionMode.isLocked) {
            this._lockedOnly = true;
            log('[Adaptive Shell] locked session: lock screen only');
            this._lockScreenStart();

            // GNOME can re-run enable() while the session is locked, and it
            // does not run it again on unlock. Without this the desktop
            // (dock, panels, shade) is never built after unlocking.
            this._lockedOnlyModeId = Main.sessionMode.connect(
                'updated',
                () => this._onLockedOnlyModeChanged()
            );

            // The 'updated' signal has not been seen on unlock in every path
            // (logind unlock, for one), so a slow poll backs it up.
            this._lockedOnlyPollId = GLib.timeout_add_seconds(
                GLib.PRIORITY_DEFAULT,
                1,
                () => {
                    this._onLockedOnlyModeChanged();
                    return this._lockedOnly ? GLib.SOURCE_CONTINUE : GLib.SOURCE_REMOVE;
                }
            );
            return;
        }

        this._enableDesktop();
    }

    _onLockedOnlyModeChanged() {
        if (!this._lockedOnly)
            return;

        if (Main.sessionMode.currentMode === 'unlock-dialog' ||
            Main.sessionMode.isLocked)
            return;

        this._lockedOnly = false;
        this._lockedOnlyCleanup();
        this._lockScreenStop();
        log('[Adaptive Shell] session unlocked: building desktop');
        this._enableDesktop();
    }

    _lockedOnlyCleanup() {
        if (this._lockedOnlyModeId) {
            Main.sessionMode.disconnect(this._lockedOnlyModeId);
            this._lockedOnlyModeId = 0;
        }

        // Returning SOURCE_REMOVE from the callback also removes it; removing
        // here covers the disable() path.
        if (this._lockedOnlyPollId) {
            GLib.Source.remove(this._lockedOnlyPollId);
            this._lockedOnlyPollId = 0;
        }
    }

    _enableDesktop() {
        this._lockedOnly = false;

        // A desktop that keeps taking the shell down is not built again.
        // See watchdog.js; Adaptive Settings re-arms it.
        if (Watchdog.recordStart()) {
            this._standDown();
            return;
        }
        this._healthyId = GLib.timeout_add_seconds(
            GLib.PRIORITY_LOW, Watchdog.healthyAfterSeconds(), () => {
                this._healthyId = 0;
                Watchdog.markHealthy();
                return GLib.SOURCE_REMOVE;
            });

        this._hideLegacyPanelItems();
        this._restoreGNOMEClock();
        this._dockConfig = DockExtras.readDockConfig();
        this._applyDockSizing();
        this._installShade();
        this._installControlCenter();
        this._installUsbPanel();
        this._installTaskPanel();
        this._installNetworkPanel();
        this._installPaletteServices();
        this._installShellActions();
        this._installProjectIndicator();
        this._installRail();
        this._minimizeFx = new MinimizeEffect.GenieMinimize(w => this._dockIconRect(w));
        this._minimizeFx.attach();

        this._monitorChangedId = Main.layoutManager.connect(
            'monitors-changed',
            () => {
                this._layoutRail();
                this._onDisplaysChanged();
            }
        );
        this._windowCreatedId = global.display.connect(
            'window-created',
            () => this._queueWindowListRefresh()
        );
        this._focusWindowId = global.display.connect(
            'notify::focus-window',
            () => this._syncDockActive()
        );
        // The dock stays up in the Overview whatever is maximized behind it,
        // so apps can be dragged from the app grid onto it.
        this._overviewShowingId = Main.overview.connect(
            'showing',
            () => {
                this._syncDockActive();
                this._dock26Layout();
            }
        );
        this._overviewHiddenId = Main.overview.connect(
            'hidden',
            () => {
                this._syncDockActive();
                this._dock26Layout();
            }
        );
        this._installDockDnd();
        this._installDockExtras();

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

        // Locking does not re-run enable(). An extension that supports both
        // "user" and "unlock-dialog" is left running across the transition
        // rather than being disabled and re-enabled, so the lock screen work
        // has to hang off the session mode changing, not off enable().
        this._sessionModeId = Main.sessionMode.connect(
            'updated',
            () => this._onSessionModeChanged()
        );

        this._connectToProjectContext();
        this._queueWindowListRefresh();
        this._syncDockActive();
        this._onSessionModeChanged();

        log('[Adaptive Shell] interactive bottom dock installed');
        log('[Adaptive Shell] GNOME dateMenu restored');
        this._dock26ConnectRuntime();

        // A ghost output that is already up at login never fires
        // monitors-changed, so nothing would ever look at it.
        this._onDisplaysChanged();

    }

    // ---------------------------------------------------------------- lock
    //
    // Everything below runs only while the session is locked. It adds to
    // GNOME's unlock dialog and never touches authentication: the prompt, the
    // password entry and the unlock path stay exactly as GNOME built them.

    _onSessionModeChanged() {
        const locked =
            Main.sessionMode.currentMode === 'unlock-dialog' ||
            Main.sessionMode.isLocked;

        if (locked === this._lockActive)
            return;

        this._lockActive = locked;

        if (locked) {
            // The extension keeps running while locked, so the desktop's own
            // chrome has to be put away by hand - a dock floating over the
            // lock screen would be both wrong and clickable.
            this._lockHideDesktopChrome(true);
            this._lockScreenStart();
        } else {
            this._lockScreenStop();
            this._lockHideDesktopChrome(false);
        }
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
                                    this._restoreProjectWorkspace(id);
                                } catch (e) {
                                    // At login the shell can be up before the
                                    // project service has claimed its name.
                                    // That is expected, not a fault, so it is
                                    // retried quietly instead of logged as an
                                    // error.
                                    if (`${e}`.includes('ServiceUnknown') ||
                                        `${e}`.includes('NameHasNoOwner')) {
                                        if (!this._projectRetries) {
                                            this._projectRetries = 0;
                                        }

                                        if (this._projectRetries < 5) {
                                            this._projectRetries += 1;
                                            GLib.timeout_add_seconds(
                                                GLib.PRIORITY_DEFAULT, 4,
                                                () => {
                                                    this._connectToProjectContext();
                                                    return GLib.SOURCE_REMOVE;
                                                });
                                        }
                                    } else {
                                        logError(e, '[Adaptive Shell] GetActiveProject failed');
                                    }
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

        // Nothing was built when enabling into a locked session, so there is
        // nothing to tear down. Running the full teardown would touch actors
        // that were never created.
        if (this._lockedOnly) {
            this._lockedOnly = false;
            this._lockedOnlyCleanup();
            this._lockScreenStop();
            return;
        }

        // Stood down by the watchdog: nothing was built either.
        if (this._watchdogTripped) {
            this._watchdogTripped = false;
            return;
        }

        // A clean disable (logout, extension turned off) is not a crash.
        if (this._healthyId) {
            GLib.source_remove(this._healthyId);
            this._healthyId = 0;
        }
        Watchdog.markHealthy();

        if (this._sessionModeId) {
            Main.sessionMode.disconnect(this._sessionModeId);
            this._sessionModeId = 0;
        }

        this._lockScreenStop();
        this._lockActive = false;

        // Before anything else: the shade holds GNOME's own message list and
        // has to hand it back intact whatever else happens during teardown.
        if (this._shade) {
            this._shade.detach();
            this._shade = null;
        }

        // Same reason: GNOME's system-menu sections are hidden, not removed,
        // and have to be shown again before anything else is torn down.
        if (this._controlCenter) {
            this._controlCenter.detach();
            this._controlCenter = null;
        }

        if (this._usbPanel) {
            this._usbPanel.detach();
            this._usbPanel = null;
        }

        if (this._projectIndicator) {
            this._projectIndicator.detach();
            this._projectIndicator = null;
        }

        if (this._shellActions) {
            this._shellActions.detach();
            this._shellActions = null;
        }

        for (const name of ['_clipboardHistory', '_snapshots', '_screenText', '_dropdown']) {
            if (this[name]) {
                this[name].detach();
                this[name] = null;
            }
        }

        if (this._taskPanel) {
            this._taskPanel.detach();
            this._taskPanel = null;
        }

        if (this._networkPanel) {
            this._networkPanel.detach();
            this._networkPanel = null;
        }

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

        if (this._minimizeFx) {
            this._minimizeFx.detach();
            this._minimizeFx = null;
        }

        this._removeDockDnd();

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

        if (this._dock26RelayoutId) {
            GLib.Source.remove(this._dock26RelayoutId);
            this._dock26RelayoutId = 0;
        }

        if (this._rescueTimerId) {
            GLib.Source.remove(this._rescueTimerId);
            this._rescueTimerId = 0;
        }

        if (this._dockDemagnifyId) {
            GLib.Source.remove(this._dockDemagnifyId);
            this._dockDemagnifyId = 0;
        }

        this._removeDockExtras();
        this._dock26Cleanup();
        this._disconnectWindowSignals();
        this._destroyDockMenus();
        this._hideTooltip();

        this._destroyDocks();

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

    // The Adaptive Shade rebuilds the interior of the date menu popup as an
    // information center: clock, notifications grouped per application, full
    // system telemetry. It holds no controls - GNOME's aggregate menu owns
    // those - and leaves the calendar column stock. The message list is
    // reparented,
    // never replaced, so notification delivery, storage, urgency and history
    // stay GNOME's.
    _installShade() {
        try {
            this._shade = new Shade.Shade();
            this._shade.attach();
        } catch (e) {
            logError(e, '[Adaptive Shell] installing the Adaptive Shade');
            this._shade = null;
        }
    }

    // The Adaptive Control Center turns GNOME's system menu into Android/iOS
    // quick settings: tiles, sliders, and in-place Wi-Fi, Bluetooth, power and
    // sound pages. GNOME's indicators keep running underneath and are what it
    // drives; their sections stay in the popup, hidden.
    _installControlCenter() {
        try {
            this._controlCenter = new ControlCenter.ControlCenter();
            this._controlCenter.attach();
        } catch (e) {
            logError(e, '[Adaptive Shell] installing the Control Center');
            this._controlCenter = null;
        }
    }

    // Running apps and busy processes, each with an End button; next to the
    // USB panel. See taskManager.js.
    _installTaskPanel() {
        try {
            this._taskPanel = new TaskManager.TaskPanel();
            this._taskPanel.attach();
        } catch (e) {
            logError(e, '[Adaptive Shell] installing the Tasks panel');
            this._taskPanel = null;
        }
    }

    // This computer's addresses and every device on the local network; next
    // to Tasks. See networkPanel.js and tools/network_info.py.
    _installNetworkPanel() {
        try {
            this._networkPanel = new NetworkPanel.NetworkPanel();
            this._networkPanel.attach();
        } catch (e) {
            logError(e, '[Adaptive Shell] installing the Network panel');
            this._networkPanel = null;
        }
    }

    // Shell-only actions (app grid, search, Shade, Control Center, workspaces)
    // for the touchpad gesture daemon; see shellActions.js.
    // What the Command palette reaches through org.adaptive.Shell: clipboard
    // history, project park/resume, text from the screen. Each is optional;
    // one failing to start leaves the others working.
    _installPaletteServices() {
        const make = (name, build) => {
            try {
                const service = build();
                if (service.attach)
                    service.attach();
                return service;
            } catch (e) {
                logError(e, `[Adaptive Shell] starting ${name}`);
                return null;
            }
        };
        this._clipboardHistory = make('clipboard history', () => new ClipboardHistory.ClipboardHistory());
        this._snapshots = make('project snapshots', () => new ProjectSnapshots.ProjectSnapshots());
        this._screenText = make('screen text', () => new ScreenText.ScreenText());
        this._dropdown = make('drop-down terminal', () => new DropdownTerminal.DropdownTerminal());
        if (this._controlCenter)
            this._controlCenter.screenText = this._screenText;
    }

    // The active project, its git status and its menu, left of the top bar.
    _installProjectIndicator() {
        try {
            this._projectIndicator = new ProjectIndicator.ProjectIndicator(this._snapshots);
            this._projectIndicator.attach();
        } catch (e) {
            logError(e, '[Adaptive Shell] installing the project indicator');
            this._projectIndicator = null;
        }
    }

    // The watchdog tripped: leave stock GNOME in place and say why, once the
    // message tray is up to show it.
    _standDown() {
        this._watchdogTripped = true;
        log('[Adaptive Shell] watchdog: desktop not built after repeated crashes');
        GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 5, () => {
            Main.notify('Adaptive Desktop stood down',
                'The Adaptive shell crashed several times in a row, so it is off for now. ' +
                'Re-enable it in Adaptive Settings → Updates & Recovery.');
            return GLib.SOURCE_REMOVE;
        });
    }

    _installShellActions() {
        try {
            this._shellActions = new ShellActions.ShellActions({
                clipboard: this._clipboardHistory,
                snapshots: this._snapshots,
                screenText: this._screenText,
                dropdown: this._dropdown,
            });
            this._shellActions.attach();
        } catch (e) {
            logError(e, '[Adaptive Shell] exporting gesture actions');
            this._shellActions = null;
        }
    }

    // A top-bar indicator listing USB devices and serial ports with their
    // VID:PID, paths and drivers; live from udev.
    _installUsbPanel() {
        try {
            this._usbPanel = new UsbDevices.UsbPanel();
            this._usbPanel.attach();
        } catch (e) {
            logError(e, '[Adaptive Shell] installing the USB panel');
            this._usbPanel = null;
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

// The shell is one object, but its code is kept by subject. Each part is a
// class whose methods are copied onto AdaptiveShellV16 here, so `this` is the
// same shell in all of them.
for (const part of [
    ShellLock.ShellLock,
    ShellDock.ShellDock,
    ShellDockFeatures.ShellDockFeatures,
    ShellDockDnd.ShellDockDnd,
    ShellDockAutohide.ShellDockAutohide,
    ShellDisplays.ShellDisplays,
]) {
    for (const name of Object.getOwnPropertyNames(part.prototype)) {
        if (name !== 'constructor') {
            Object.defineProperty(AdaptiveShellV16.prototype, name,
                Object.getOwnPropertyDescriptor(part.prototype, name));
        }
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
