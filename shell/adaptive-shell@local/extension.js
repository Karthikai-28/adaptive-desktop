// Adaptive monitor-aware Dock v2.6
// Adaptive dock visual customization v2.3
// Width follows natural content width, so the dock grows/shrinks
// automatically as favorites/running applications change.

const { St, Gio, GLib, Clutter, Shell, Meta } = imports.gi;
const Main = imports.ui.main;
const Layout = imports.ui.layout;
const PanelMenu = imports.ui.panelMenu;
const PopupMenu = imports.ui.popupMenu;
const AppFavorites = imports.ui.appFavorites;
const ExtensionUtils = imports.misc.extensionUtils;
const Gvc = imports.gi.Gvc;

const Pango = imports.gi.Pango;

const Me = ExtensionUtils.getCurrentExtension();
const Shade = Me.imports.shade;

// Always-on-display tuning. The drift keeps a static clock from ghosting an
// OLED; the ambient level is what it settles to once nobody is looking.
const LOCK_AMBIENT_AFTER_S = 12;
const LOCK_AMBIENT_OPACITY = 145;
const LOCK_DRIFT_INTERVAL_S = 90;
const LOCK_DRIFT_RADIUS_PX = 14;
// Idle time on the lock screen before the screen-saver state takes over.
const AOD_IDLE_MS = 30 * 1000;

let _shell = null;

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
        this._projectProxy = null;
        this._tooltip = null;
        this._tooltipTimeoutId = 0;
        this._dockDemagnifyId = 0;
        this._lockedOnly = false;
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
        this._lockBackgroundGroup = null;

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
            return;
        }

        this._lockedOnly = false;

        this._hideLegacyPanelItems();
        this._restoreGNOMEClock();
        this._installShade();
        this._installRail();

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

    _lockHideDesktopChrome(hidden) {
        const actors = (this._docks || []).map(dock => dock.rail);
        actors.push(this._dockChrome);

        for (const actor of actors) {
            if (!actor)
                continue;

            try {
                actor.visible = !hidden;
            } catch (e) {
            }
        }

        if (hidden)
            this._hideTooltip();

        // Ask the dock to re-evaluate, so it hides through its own path too.
        try {
            this._dock26Layout();
        } catch (e) {
        }
    }

    _lockScreenStart() {
        this._lockAttempts = 0;

        // Installed up front and driven by its own timer. Tying either to the
        // unlock dialog meant both died with it: screenShield.js destroys the
        // dialog when it blanks, which is exactly when the always-on layer is
        // supposed to take over.
        this._aodInstall();

        if (!this._lockTickId) {
            this._lockTickId = GLib.timeout_add_seconds(
                GLib.PRIORITY_DEFAULT,
                1,
                () => {
                    try {
                        this._lockTick();
                    } catch (e) {
                        logError(e, '[Adaptive Shell] lock tick');
                        this._lockTickId = 0;
                        return GLib.SOURCE_REMOVE;
                    }

                    return GLib.SOURCE_CONTINUE;
                }
            );
        }

        // The dialog is built lazily, so it may not exist the moment the
        // extension is enabled into unlock-dialog mode.
        this._lockAttachId = GLib.timeout_add(
            GLib.PRIORITY_DEFAULT,
            300,
            () => {
                let done = false;

                try {
                    done = this._lockScreenAttach();
                } catch (e) {
                    logError(e, '[Adaptive Shell] lock screen attach');
                    done = true;
                }

                this._lockAttempts += 1;

                if (done || this._lockAttempts > 25) {
                    this._lockAttachId = 0;
                    return GLib.SOURCE_REMOVE;
                }

                return GLib.SOURCE_CONTINUE;
            }
        );
    }

    _lockScreenAttach() {
        const shield = Main.screenShield;
        const dialog = shield ? shield._dialog : null;

        if (!dialog || !dialog._clock || !dialog._clock._time)
            return false;

        const clock = dialog._clock;

        if (clock._adaptiveLock)
            return true;

        // GNOME 40+ paints the desktop wallpaper, blurred, behind the lock
        // screen - which is why org.gnome.desktop.screensaver's picture-uri
        // had no effect on it; that key is legacy. Hiding the background group
        // leaves the shield's own black showing, which is what the OLED
        // treatment needs. Restored when the session unlocks.
        try {
            if (dialog._backgroundGroup) {
                dialog._backgroundGroup.hide();
                this._lockBackgroundGroup = dialog._backgroundGroup;
            }
        } catch (e) {
        }

        clock._adaptiveLock = true;

        // GNOME leaves the prompt column at its natural alignment, which puts
        // the password box off to one side of the shield.
        try {
            dialog._promptBox.x_align = Clutter.ActorAlign.CENTER;
            dialog._promptBox.x_expand = true;
        } catch (e) {
        }

        const activity = new St.Label({
            style_class: 'adaptive-lock-activity',
            x_align: Clutter.ActorAlign.CENTER,
        });
        activity.clutter_text.line_wrap = true;
        activity.clutter_text.ellipsize = Pango.EllipsizeMode.NONE;
        activity.visible = false;

        try {
            clock.insert_child_below(activity, clock._hint);
        } catch (e) {
            clock.add_child(activity);
        }

        // St.Label ellipsizes by default. The label was sized for "01:20", so
        // appending seconds overflowed it and Pango replaced them with an
        // ellipsis - the seconds showed up as dots.
        try {
            clock._time.clutter_text.ellipsize = Pango.EllipsizeMode.NONE;
            clock._time.clutter_text.line_wrap = false;
            clock._time.x_expand = true;
        } catch (e) {
        }

        this._lockClock = clock;
        this._lockActivity = activity;

        // GNOME's own _updateClock() writes the wall clock's HH:MM into the
        // same label once a minute, which wiped the seconds every time the
        // minute rolled over. Wrapping it - rather than racing it from a
        // timer - means the date still updates GNOME's way and the seconds
        // are re-applied in the same frame, so the format never flickers.
        if (!clock._adaptiveUpdateClock) {
            clock._adaptiveUpdateClock = clock._updateClock.bind(clock);

            clock._updateClock = () => {
                clock._adaptiveUpdateClock();

                try {
                    this._lockApplyTime();
                } catch (e) {
                }
            };
        }

        this._lockTick();

        // Only the dialog's own bits are dropped here. The session is still
        // locked, so the always-on layer and the timer keep running.
        clock.connect('destroy', () => this._lockDetachDialog());

        log('[Adaptive Shell] lock screen clock extended');
        return true;
    }

    _lockTick() {
        // The dialog may be gone while the session stays locked; the always-on
        // layer below is what keeps the time on screen after that.
        this._lockApplyTime();

        if (this._lockAlive(this._lockActivity)) {
            this._lockActivity.text = this._lockActivitySummary();
            this._lockActivity.visible = !!this._lockActivity.text;
        }

        this._aodUpdate();

        this._lockTicks = (this._lockTicks || 0) + 1;
        this._lockAmbientStep();
    }

    // Always-on behaviour, borrowed from how phones do it.
    //
    // A static bright clock left on an OLED for hours is exactly how panels
    // acquire ghosting, so the clock drifts slowly around a small orbit and
    // settles to a dimmer level once nobody is interacting. Both are cheap:
    // one translation and one opacity, on the tick that already runs.
    _lockAmbientStep() {
        if (!this._lockAlive(this._lockClock))
            return;

        const ticks = this._lockTicks;

        // Fade to the ambient level a few seconds in, so the clock is bright
        // at the moment of locking and quiet afterwards.
        if (ticks === LOCK_AMBIENT_AFTER_S) {
            this._lockClock.ease({
                opacity: LOCK_AMBIENT_OPACITY,
                duration: 1200,
                mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            });
        }

        if (ticks % LOCK_DRIFT_INTERVAL_S !== 0)
            return;

        // Eight positions around a small circle: one full lap per
        // 8 * LOCK_DRIFT_INTERVAL_S, far slower than the eye tracks.
        const stop = (ticks / LOCK_DRIFT_INTERVAL_S) % 8;
        const angle = (stop / 8) * 2 * Math.PI;

        this._lockClock.ease({
            translation_x: Math.round(Math.cos(angle) * LOCK_DRIFT_RADIUS_PX),
            translation_y: Math.round(Math.sin(angle) * LOCK_DRIFT_RADIUS_PX),
            duration: 2500,
            mode: Clutter.AnimationMode.EASE_IN_OUT_QUAD,
        });
    }

    // Always-on layer.
    //
    // GNOME fades its unlock dialog out once the session is idle, leaving a
    // plain black shield - which is why the screen went "just black". This
    // clock lives on the shield group itself rather than inside that dialog,
    // so it survives the fade the way a phone's always-on display does.
    _aodInstall() {
        if (this._aodBox)
            return;

        const group = Main.layoutManager.screenShieldGroup;
        if (!group)
            return;

        const box = new St.BoxLayout({
            vertical: true,
            style_class: 'adaptive-aod',
            reactive: false,
        });

        this._aodTime = new St.Label({
            style_class: 'adaptive-aod-time',
            x_align: Clutter.ActorAlign.CENTER,
        });
        this._aodTime.clutter_text.ellipsize = Pango.EllipsizeMode.NONE;

        this._aodDate = new St.Label({
            style_class: 'adaptive-aod-date',
            x_align: Clutter.ActorAlign.CENTER,
        });
        this._aodDate.clutter_text.ellipsize = Pango.EllipsizeMode.NONE;

        box.add_child(this._aodTime);
        box.add_child(this._aodDate);

        group.add_child(box);

        try {
            group.set_child_above_sibling(box, null);
        } catch (e) {
        }

        this._aodBox = box;

        this._aodLayout();
        this._aodUpdate();
    }

    _aodLayout() {
        if (!this._aodBox)
            return;

        const monitor = Main.layoutManager.primaryMonitor;
        if (!monitor)
            return;

        const [, width] = this._aodBox.get_preferred_width(-1);
        const [, height] = this._aodBox.get_preferred_height(width);

        this._aodBox.set_position(
            monitor.x + Math.round((monitor.width - width) / 2),
            monitor.y + Math.round((monitor.height - height) / 2)
        );
    }

    _aodUpdate() {
        if (!this._aodBox)
            return;

        const now = GLib.DateTime.new_now_local();

        this._aodTime.text = now.format(this._lockTimeFormat || '%H:%M:%S').trim();
        this._aodDate.text = now.format('%A %e %B').replace(/\s+/g, ' ').trim();

        // Drive the screen-saver state directly instead of waiting for GNOME
        // to fade its dialog. With the always-on switch on, the session never
        // goes idle by GNOME's reckoning, so that fade never happens and the
        // lock UI would simply sit there for ever. Phones do this by idle
        // time, so this does too: after AOD_IDLE_MS with no input the dialog
        // steps aside and the bare clock takes the screen; any input brings it
        // straight back.
        let idle = 0;

        try {
            idle = global.backend.get_core_idle_monitor().get_idletime();
        } catch (e) {
        }

        const show = idle >= AOD_IDLE_MS;
        const dialog = Main.screenShield ? Main.screenShield._dialog : null;

        // Hide what the dialog *shows*, not the dialog itself. The dialog is
        // the opaque cover over the session: hiding it outright let the
        // desktop - dock and panel included - show through underneath.
        if (dialog) {
            for (const part of [dialog._clock, dialog._notifications]) {
                if (!part)
                    continue;

                try {
                    part.visible = !show;
                } catch (e) {
                }
            }
        }

        if (show !== this._aodShown) {
            this._aodShown = show;
            log(`[Adaptive Shell] always-on layer ${show ? 'shown' : 'hidden'}`);
        }

        this._aodBox.visible = show;
        this._aodLayout();
    }

    _aodRemove() {
        this._lockRestoreDialogParts();
        this._lockRestoreBackground();

        try {
            const dialog = Main.screenShield ? Main.screenShield._dialog : null;
            if (dialog)
                dialog.visible = true;
        } catch (e) {
        }

        this._aodShown = false;

        if (!this._aodBox)
            return;

        try {
            this._aodBox.destroy();
        } catch (e) {
        }

        this._aodBox = null;
        this._aodTime = null;
        this._aodDate = null;
    }

    _lockAlive(actor) {
        // A destroyed actor keeps its JS wrapper, so the usual truthiness test
        // passes and the next property access asserts inside Clutter.
        try {
            return !!actor && actor.get_stage() !== null;
        } catch (e) {
            return false;
        }
    }

    _lockApplyTime() {

        // The 12/24-hour preference is read once and cached: this runs every
        // second, and building a Gio.Settings each time would be wasteful.
        if (this._lockTimeFormat === undefined) {
            this._lockTimeFormat = '%H:%M:%S';

            try {
                const iface = new Gio.Settings({
                    schema_id: 'org.gnome.desktop.interface',
                });

                if (iface.get_string('clock-format') === '12h')
                    this._lockTimeFormat = '%l:%M:%S %p';
            } catch (e) {
            }
        }

        if (!this._lockClock || !this._lockAlive(this._lockClock._time)) {
            this._lockDetachDialog();
            return;
        }

        const now = GLib.DateTime.new_now_local();
        this._lockClock._time.text = now.format(this._lockTimeFormat).trim();
    }

    _lockActivitySummary() {
        try {
            const running = Shell.AppSystem.get_default().get_running();

            if (!running.length)
                return '';

            const names = running
                .map(app => app.get_name())
                .filter(name => !!name)
                .sort();

            const shown = names.slice(0, 4).join(' · ');
            const extra = names.length - Math.min(names.length, 4);

            const label = running.length === 1
                ? '1 APP RUNNING'
                : `${running.length} APPS RUNNING`;

            return extra > 0
                ? `${label}\n${shown} +${extra}`
                : `${label}\n${shown}`;
        } catch (e) {
            return '';
        }
    }

    _lockRestoreDialogParts() {
        const dialog = Main.screenShield ? Main.screenShield._dialog : null;
        if (!dialog)
            return;

        for (const part of [dialog._clock, dialog._notifications]) {
            if (!part)
                continue;

            try {
                part.visible = true;
            } catch (e) {
            }
        }
    }

    _lockRestoreBackground() {
        if (!this._lockBackgroundGroup)
            return;

        try {
            this._lockBackgroundGroup.show();
        } catch (e) {
        }

        this._lockBackgroundGroup = null;
    }

    _lockDetachDialog() {
        this._lockRestoreBackground();

        if (this._lockClock && this._lockClock._adaptiveUpdateClock) {
            try {
                this._lockClock._updateClock =
                    this._lockClock._adaptiveUpdateClock;
                this._lockClock._adaptiveUpdateClock = null;
            } catch (e) {
            }
        }

        this._lockClock = null;
        this._lockActivity = null;
    }

    _lockScreenStop() {
        if (this._lockAttachId) {
            GLib.Source.remove(this._lockAttachId);
            this._lockAttachId = 0;
        }

        if (this._lockTickId) {
            GLib.Source.remove(this._lockTickId);
            this._lockTickId = 0;
        }

        if (this._lockActivity) {
            try {
                this._lockActivity.destroy();
            } catch (e) {
            }
            this._lockActivity = null;
        }

        if (this._lockClock) {
            try {
                this._lockClock.remove_all_transitions();
                this._lockClock.opacity = 255;
                this._lockClock.translation_x = 0;
                this._lockClock.translation_y = 0;
            } catch (e) {
            }

            if (this._lockClock._adaptiveUpdateClock) {
                this._lockClock._updateClock =
                    this._lockClock._adaptiveUpdateClock;
                this._lockClock._adaptiveUpdateClock = null;
            }

            this._lockClock._adaptiveLock = false;
            this._lockClock = null;
        }

        this._aodRemove();
        this._lockTicks = 0;
        this._lockTimeFormat = undefined;
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
            this._lockScreenStop();
            return;
        }

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

        const showApps = this._utilityDockButton(
            'apps.svg',
            'Applications',
            () => this._showApplications()
        );
        showApps.add_style_class_name('adaptive-show-apps-button');
        rail.add_child(showApps);

        const dock = { index, rail, appsBox, showApps, revealed: false, hideId: 0 };

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

        for (const entry of entries) {
            const button = this._appDockButton(
                entry.app,
                entry.windows,
                entry.favorite
            );
            button._adaptiveDockApp = entry.app;
            dock.appsBox.add_child(button);
            this._dockButtons.push(button);
        }

        if (dock.showApps)
            this._dockButtons.push(dock.showApps);
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
        for (const dock of this._docks || [])
            this._setActorActive(dock.showApps, appsUp);
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

        if (this._dock26Pressure) {
            this._dock26Pressure.destroy();
            this._dock26Pressure = null;
        }

        for (const barrier of this._dock26Barriers) {
            try {
                barrier.destroy();
            } catch (e) {
            }
        }

        this._dock26Barriers = [];
    }

    _dock26SupportsBarriers() {
        try {
            return global.display.supports_extended_barriers();
        } catch (e) {
            return false;
        }
    }

    // A mouse button held down means a drag - selecting cells or text,
    // resizing a row - that happens to run into the bottom of the screen.
    // macOS does not bring the Dock up for that, and neither does this.
    _dock26PointerButtonHeld() {
        try {
            const [, , mods] = global.get_pointer();
            return !!(mods & (
                Clutter.ModifierType.BUTTON1_MASK |
                Clutter.ModifierType.BUTTON2_MASK |
                Clutter.ModifierType.BUTTON3_MASK
            ));
        } catch (e) {
            return false;
        }
    }

    _dock26RebuildHotEdges() {
        this._dock26DestroyHotEdges();

        // Indexes are renumbered when a display is plugged or unplugged, so a
        // remembered target can now point at a different screen - or at none.
        // Re-resolve from the pointer's own monitor instead of trusting it.
        this._dock26ClearReveals();
        this._dock26TargetMonitor = -1;

        if (this._dock26SupportsBarriers())
            this._dock26BuildBarriers();
        else
            this._dock26BuildFallbackEdges();

        this._dock26EnsureTargetMonitor();
        this._dock26SyncTargetFromFocus(false);
        this._dock26Layout();
    }

    _dock26BuildBarriers() {
        const monitors = Main.layoutManager.monitors || [];

        this._dock26Pressure = new Layout.PressureBarrier(
            this._dock26PressureThreshold,
            this._dock26PressureTimeoutMs,
            Shell.ActionMode.NORMAL
        );

        // Barriers never fire their hit while a button is down, so a drag
        // selection running into the bottom edge builds up no pressure.
        this._dock26Pressure.setEventFilter(
            () => this._dock26PointerButtonHeld()
        );

        // The trigger signal says nothing about which barrier was pushed, and
        // the barrier needs the event back to let the pointer through to a
        // monitor stacked underneath. Each barrier's own hit handler runs
        // before the pressure barrier's (it is connected first) and records it.
        let lastHit = null;

        this._dock26Pressure.connect('trigger', () => {
            const hit = lastHit;
            lastHit = null;
            if (!hit)
                return;

            this._dock26RequestReveal(hit.barrier._adaptiveMonitor);

            try {
                hit.barrier.release(hit.event);
            } catch (e) {
            }
        });

        monitors.forEach((monitor, index) => {
            const y = monitor.y + monitor.height;

            try {
                const barrier = new Meta.Barrier({
                    display: global.display,
                    x1: monitor.x,
                    x2: monitor.x + monitor.width,
                    y1: y,
                    y2: y,
                    directions: Meta.BarrierDirection.NEGATIVE_Y,
                });

                barrier._adaptiveMonitor = index;
                barrier.connect('hit', (b, event) => {
                    lastHit = { barrier: b, event };
                });

                this._dock26Pressure.addBarrier(barrier);
                this._dock26Barriers.push(barrier);
            } catch (e) {
                logError(e, `[Adaptive Shell] dock barrier monitor ${index}`);
            }
        });

        log(`[Adaptive Shell] dock reveal: pressure barriers on `
            + `${this._dock26Barriers.length} monitor(s)`);
    }

    _dock26BuildFallbackEdges() {
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

        log(`[Adaptive Shell] dock reveal: no extended barriers, `
            + `${this._dock26HotEdges.length} dwell edge(s)`);
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
        // Mutter asserts rather than returning false for an index it does not
        // have, and this one is -1 before the first resolve and stale for a
        // moment after a display is unplugged.
        const monitors = this._dock26MonitorCount();
        const valid = Number.isInteger(index) && index >= 0 && index < monitors;

        try {
            if (
                valid &&
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

    // Deliberately not "the focused window is maximized". A quick-settings
    // menu, a Ctrl+Alt+T terminal or an upload dialog takes focus away from
    // the maximized window without moving it, and a focus-only test then said
    // "nothing is maximized" and revealed the dock over content the user was
    // still reading. What matters is whether a maximized window occupies this
    // monitor at all.
    _dock26MonitorHasFocusedMaximized(index) {
        if (!this._dock26HideOnMaximized)
            return false;

        const focused = global.display.get_focus_window();

        try {
            if (
                focused &&
                focused.get_monitor() === index &&
                this._dock26WindowFullyMaximized(focused)
            )
                return true;
        } catch (e) {
        }

        try {
            const workspace =
                global.workspace_manager.get_active_workspace();

            if (!workspace)
                return false;

            for (const window of workspace.list_windows()) {
                try {
                    if (
                        window.get_monitor() === index &&
                        !window.minimized &&
                        this._dock26WindowFullyMaximized(window)
                    )
                        return true;
                } catch (e) {
                }
            }
        } catch (e) {
        }

        return false;
    }

    _dock26RaiseAboveWindows(dock) {
        const rail = dock && dock.rail;
        if (!rail)
            return;

        try {
            const parent = rail.get_parent();
            if (parent)
                parent.set_child_above_sibling(rail, null);
        } catch (e) {
        }
    }

    _dock26Locked() {
        return (
            Main.sessionMode.isLocked ||
            Main.sessionMode.currentMode === 'unlock-dialog'
        );
    }

    _dock26MonitorNeedsHide(index) {
        // Setting visible=false from outside does not survive: the dock's own
        // layout pass runs afterwards and shows it again. Locked has to be one
        // of the dock's own reasons to stay down.
        if (this._dock26Locked())
            return true;

        return (
            this._dock26MonitorInFullscreen(index) ||
            this._dock26MonitorHasFocusedMaximized(index)
        );
    }

    // Focus used to move the dock to the focused window's monitor, which is
    // exactly why the other screen had none. Every monitor has its own dock
    // now, so focus only affects whether a dock should hide behind a
    // fullscreen or maximized window on its own monitor.
    _dock26SyncTargetFromFocus(_forceMove = true) {
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

        const changed = () => this._dock26SyncVisibility();

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
        for (const dock of this._docks || [])
            this._dockCancelHide(dock);
    }

    // Nothing is being deliberately reached for any more, on any screen.
    _dock26ClearReveals() {
        for (const dock of this._docks || [])
            dock.revealed = false;
    }

    // Fallback only (no extended barriers): the pointer has to rest on the
    // 1px edge, so passing over it on the way to something does nothing.
    _dock26OnEdgeEnter(index) {
        this._dock26CancelReveal();

        this._dock26RevealTimerId =
            GLib.timeout_add(
                GLib.PRIORITY_DEFAULT,
                this._dock26RevealDelayMs,
                () => {
                    this._dock26RevealTimerId = 0;

                    const edge =
                        this._dock26EdgeForMonitor(index);

                    if (
                        edge &&
                        edge.hover &&
                        !this._dock26PointerButtonHeld()
                    )
                        this._dock26RequestReveal(index);

                    return GLib.SOURCE_REMOVE;
                }
            );
    }

    // A deliberate reach for the dock on this monitor.
    _dock26RequestReveal(index) {
        const dock = this._dockForMonitor(index);

        log(`[Adaptive Shell] dock reveal request monitor ${index}, `
            + `dock ${dock ? 'found' : 'MISSING'}`);

        if (!dock)
            return;

        this._dockCancelHide(dock);
        this._dock26TargetMonitor = index;

        // Never over a locked screen; everywhere else the reveal is
        // honoured, fullscreen included.
        dock.revealed = !this._dock26Locked();
        this._dock26Layout();

        if (dock.revealed)
            this._dock26WatchPointer(dock);
    }

    // Is the pointer still using the dock? Over it, in the gap between it and
    // the screen edge (where the push that revealed it left the pointer), or
    // in one of its menus.
    _dock26PointerHoldsDock(dock) {
        if (!dock)
            return false;

        if (dock.rail && dock.rail.hover)
            return true;

        if (this._dockMenus.some(menu => menu.isOpen))
            return true;

        const monitor = (Main.layoutManager.monitors || [])[dock.index];
        const zone = dock.zone;
        if (!monitor || !zone)
            return false;

        try {
            const [px, py] = global.get_pointer();
            const slack = 8;

            return (
                px >= zone.x - slack &&
                px < zone.x + zone.width + slack &&
                py >= zone.y - slack &&
                py < monitor.y + monitor.height
            );
        } catch (e) {
            return false;
        }
    }

    // A revealed dock never sees a leave-event if the pointer never entered
    // it - the push leaves the pointer on the edge, below the dock. So while
    // it is revealed, watch where the pointer is and put it away once the
    // pointer has moved off, the way the macOS Dock does.
    _dock26WatchPointer(dock) {
        if (!dock || dock.pointerWatchId)
            return;

        dock.pointerWatchId = GLib.timeout_add(
            GLib.PRIORITY_DEFAULT,
            this._dock26PointerPollMs,
            () => {
                if (!dock.revealed) {
                    dock.pointerWatchId = 0;
                    return GLib.SOURCE_REMOVE;
                }

                if (this._dock26PointerHoldsDock(dock))
                    this._dockCancelHide(dock);
                else if (!dock.hideId)
                    this._dockScheduleHide(dock);

                return GLib.SOURCE_CONTINUE;
            }
        );
    }

    _dock26StopWatchingPointer(dock) {
        if (dock && dock.pointerWatchId) {
            GLib.Source.remove(dock.pointerWatchId);
            dock.pointerWatchId = 0;
        }
    }

    _dock26ShowDock(dock, animated) {
        const rail = dock && dock.rail;
        if (!rail)
            return;

        rail.reactive = true;
        rail.show();
        rail.remove_all_transitions();

        if (!animated) {
            rail.opacity = 255;
            rail.translation_y = 0;
            return;
        }

        rail.ease({
            opacity: 255,
            translation_y: 0,
            duration: this._dock26RevealDurationMs,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
        });
    }

    _dock26HideDock(dock, animated) {
        const rail = dock && dock.rail;
        if (!rail)
            return;

        // The pointer can still be over an icon when the dock slides away, and
        // the tooltip would then be left floating on the wallpaper with no dock
        // under it.
        this._hideTooltip();

        rail.reactive = false;
        rail.remove_all_transitions();

        const offset =
            this._dock26SurfaceHeight +
            this._dock26BottomGap + 8;

        if (!animated) {
            rail.opacity = 0;
            rail.translation_y = offset;
            return;
        }

        rail.ease({
            opacity: 0,
            translation_y: offset,
            duration: this._dock26HideDurationMs,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
        });
    }

    // The dock should be exactly as wide as what it shows.
    _dock26ContentWidth(rail = this._rail) {
        if (!rail)
            return 0;

        const children = rail
            .get_children()
            .filter(child => child.visible);

        let content = 0;

        for (const child of children) {
            const [, natural] = child.get_preferred_width(
                this._dock26SurfaceHeight
            );
            content += Math.ceil(natural);

            // Margins sit outside the preferred width, so leaving them out
            // makes the dock narrower than its own contents.
            try {
                const childNode = child.get_theme_node();
                content +=
                    childNode.get_margin(St.Side.LEFT) +
                    childNode.get_margin(St.Side.RIGHT);
            } catch (e) {
            }
        }

        let spacing = 0;
        let padding = 0;

        try {
            const node = rail.get_theme_node();
            spacing = node.get_length('spacing');
            padding =
                node.get_horizontal_padding() +
                node.get_border_width(St.Side.LEFT) +
                node.get_border_width(St.Side.RIGHT);
        } catch (e) {
        }

        if (children.length > 1)
            content += spacing * (children.length - 1);

        const width = Math.ceil(content + padding);

        // One NaN from a theme lookup would land in set_size() and assert.
        return Number.isFinite(width) ? width : 0;
    }

    _dock26Layout() {
        for (const dock of this._docks || [])
            this._dock26LayoutOne(dock);

        this._dock26LayoutReservation();
        this._dock26QueueRelayout();
        this._dock26UpdateRegions();
    }

    // The 1px strut sits on the primary monitor. It never grows: an
    // auto-hiding dock is an overlay, and a strut that toggled between 70px
    // and 1px re-ran the work-area calculation and visibly resized every
    // maximized window on the screen.
    _dock26LayoutReservation() {
        if (!this._dockChrome)
            return;

        const monitor = this._dock26Monitor(
            this._dock26PrimaryMonitorIndex()
        );
        if (!monitor)
            return;

        this._dockChrome.set_position(
            monitor.x,
            monitor.y + monitor.height - 1
        );
        this._dockChrome.set_size(monitor.width, 1);
    }

    _dock26LayoutOne(dock) {
        if (!dock || !dock.rail)
            return;

        const index = dock.index;

        // Deliberately not _dock26Monitor(), which falls back to the primary
        // monitor for an unknown index. Between a display being unplugged and
        // the docks being rebuilt that would stack two docks on one screen.
        const monitor = (Main.layoutManager.monitors || [])[index];
        if (!monitor) {
            dock.rail.hide();
            return;
        }

        // Width is summed from the children rather than taken from
        // get_preferred_width(). Some child over-claimed, so the rail was
        // allocated ~540px wider than its icons; the box was centred correctly
        // but the icons packed against its right edge, which reads as a dock
        // sitting well right of centre.
        const naturalWidth = this._dock26ContentWidth(dock.rail);
        dock.contentWidth = naturalWidth;

        const width = Math.max(
            100,
            Math.min(
                Math.ceil(naturalWidth),
                monitor.width - 24
            )
        );

        // Centre on this monitor, then clamp inside it. With an external
        // display attached the X screen is the union of both monitors, so a
        // stale or screen-sized geometry here pushed the dock off-centre
        // towards the second monitor instead of sitting in the middle of the
        // one it belongs to.
        const centred =
            monitor.x +
            Math.round((monitor.width - width) / 2);

        const x = Math.max(
            monitor.x,
            Math.min(centred, monitor.x + monitor.width - width)
        );

        const y =
            monitor.y +
            monitor.height -
            this._dock26SurfaceHeight -
            this._dock26BottomGap;

        // A 1024px-wide monitor cannot fit the whole dock. Clip only in that
        // case, so the overflow stops at the screen edge instead of painting
        // across onto the neighbouring monitor - and so the dock's shadow is
        // left intact everywhere it does fit.
        dock.rail.clip_to_allocation = naturalWidth > width;

        dock.rail.set_position(x, y);
        dock.rail.set_size(
            width,
            this._dock26SurfaceHeight
        );
        dock.zone = { x, y, width };

        // Logged on change only, so a misplaced dock can be diagnosed from the
        // journal without a running Looking Glass.
        const placement = `${width}x${this._dock26SurfaceHeight}+${x}+${y}`;
        if (dock.placement !== placement) {
            dock.placement = placement;
            log(`[Adaptive Shell] dock monitor ${index}: ${placement} `
                + `(monitor ${monitor.width}x${monitor.height}`
                + `+${monitor.x}+${monitor.y})`);
        }

        const hidden =
            this._dock26MonitorNeedsHide(index);

        if (hidden && this._dock26Locked()) {
            // Locked is the only absolute: nothing of the desktop goes on top
            // of the lock screen, hot edge included.
            dock.revealed = false;
            this._dock26HideDock(dock, true);
        } else if (hidden) {
            // Fullscreen suppresses the dock appearing *by itself*, which was
            // the original complaint, but reaching for the bottom edge is a
            // deliberate request and still works.
            if (dock.revealed) {
                this._dock26ShowDock(dock, true);
                this._dock26RaiseAboveWindows(dock);
            } else {
                this._dock26HideDock(dock, true);
            }
        } else {
            dock.revealed = false;
            this._dock26ShowDock(dock, false);
        }
    }

    // Icons can finish allocating after the layout ran, leaving a dock centred
    // on a stale width. Re-check once on idle and correct if it moved.
    _dock26QueueRelayout() {
        if (!this._dock26RelayoutId) {
            this._dock26RelayoutId = GLib.idle_add(
                GLib.PRIORITY_DEFAULT_IDLE,
                () => {
                    this._dock26RelayoutId = 0;

                    // Compare against the width the layout was computed
                    // from, not against the dock's allocated width. The
                    // allocated width is clamped to the monitor and to a
                    // minimum, so on a narrow screen it legitimately differs
                    // from the content width forever - and comparing those two
                    // made this idle re-run the layout, re-arm itself, and spin
                    // the shell's main loop until GC was starved out.
                    const stale = (this._docks || []).some(dock => {
                        if (!dock.rail)
                            return false;

                        const settled =
                            this._dock26ContentWidth(dock.rail);

                        return settled > 0 &&
                            Math.abs(settled - (dock.contentWidth || 0)) > 1;
                    });

                    if (stale && this._dock26SettlePasses < 4) {
                        this._dock26SettlePasses += 1;
                        this._dock26Layout();
                    } else {
                        this._dock26SettlePasses = 0;
                    }

                    return GLib.SOURCE_REMOVE;
                }
            );
        }
    }

    _dock26UpdateRegions() {
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
                            this._dock26ClearReveals();
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
                    () => {
                        // A new display needs its own dock, and a removed one
                        // leaves a dock pointing at a monitor index that no
                        // longer exists.
                        this._buildDocks();
                        this._refreshWindowList();
                        this._dock26RebuildHotEdges();
                    }
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

    // A display appearing or disappearing can leave windows somewhere the
    // user cannot reach them.
    _onDisplaysChanged() {
        this._runDisplayGuard();

        // Mutter relocates windows itself when a monitor goes away, so give it
        // a moment and only clean up what it left behind. Running immediately
        // would fight it and move windows twice.
        if (this._rescueTimerId)
            GLib.Source.remove(this._rescueTimerId);

        this._rescueTimerId = GLib.timeout_add(
            GLib.PRIORITY_DEFAULT,
            1500,
            () => {
                this._rescueTimerId = 0;
                this._rescueStrandedWindows();
                return GLib.SOURCE_REMOVE;
            }
        );
    }

    // An HDMI port can report "connected" with nothing plugged into it, and
    // then windows get placed on a screen that does not physically exist.
    _runDisplayGuard() {
        if (!GLib.file_test(this._displayGuard, GLib.FileTest.IS_EXECUTABLE))
            return;

        // A single unplug arrives as several monitors-changed events, and each
        // one would otherwise spawn its own xrandr.
        const now = GLib.get_monotonic_time();
        if (this._displayGuardRunAt && now - this._displayGuardRunAt < 3000000)
            return;

        this._displayGuardRunAt = now;
        this._spawn([this._displayGuard]);
    }

    _windowVisibleFraction(rect, monitors) {
        const area = rect.width * rect.height;
        if (!area)
            return 1;

        let best = 0;

        for (const monitor of monitors) {
            const ox = Math.max(
                0,
                Math.min(rect.x + rect.width, monitor.x + monitor.width) -
                    Math.max(rect.x, monitor.x)
            );
            const oy = Math.max(
                0,
                Math.min(rect.y + rect.height, monitor.y + monitor.height) -
                    Math.max(rect.y, monitor.y)
            );

            best = Math.max(best, ox * oy);
        }

        return best / area;
    }

    // Windows left on a monitor that no longer exists are still open and still
    // running - they are just nowhere you can click. Bring them back.
    _rescueStrandedWindows() {
        const monitors = Main.layoutManager.monitors || [];
        if (!monitors.length)
            return;

        const primary = Main.layoutManager.primaryIndex;
        const work = Main.layoutManager.getWorkAreaForMonitor(primary);
        let rescued = 0;

        for (const actor of global.get_window_actors()) {
            const window = actor.meta_window;
            if (!window)
                continue;

            try {
                if (window.is_override_redirect())
                    continue;

                const type = window.get_window_type();
                if (
                    type !== Meta.WindowType.NORMAL &&
                    type !== Meta.WindowType.DIALOG &&
                    type !== Meta.WindowType.MODAL_DIALOG
                )
                    continue;

                const rect = window.get_frame_rect();

                // Half on screen is still reachable - a title bar is enough to
                // drag it back. Only rescue what is genuinely gone.
                if (this._windowVisibleFraction(rect, monitors) >= 0.5)
                    continue;

                log(`[Adaptive Shell] rescuing "${window.get_title()}" from `
                    + `${rect.width}x${rect.height}+${rect.x}+${rect.y}`);

                window.move_to_monitor(primary);

                // move_to_monitor keeps the window's relative position, which
                // for a window that was off the right of a wider screen can
                // still land it outside. Clamp it into the work area.
                const moved = window.get_frame_rect();
                const x = Math.max(
                    work.x,
                    Math.min(moved.x, work.x + work.width - moved.width)
                );
                const y = Math.max(
                    work.y,
                    Math.min(moved.y, work.y + work.height - moved.height)
                );

                if (x !== moved.x || y !== moved.y)
                    window.move_frame(true, x, y);

                rescued += 1;
            } catch (e) {
                logError(e, '[Adaptive Shell] rescue window');
            }
        }

        if (rescued)
            Main.notify(
                'Adaptive Desktop',
                rescued === 1
                    ? 'Moved 1 window back from a disconnected display.'
                    : `Moved ${rescued} windows back from a disconnected display.`
            );
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
