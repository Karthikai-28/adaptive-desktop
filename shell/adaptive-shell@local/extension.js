const { St, Gio, GLib, Clutter, Shell } = imports.gi;
const Main = imports.ui.main;
const PanelMenu = imports.ui.panelMenu;
const PopupMenu = imports.ui.popupMenu;
const SystemActions = imports.misc.systemActions;
const ExtensionUtils = imports.misc.extensionUtils;
const Gvc = imports.gi.Gvc;
const Slider = imports.ui.slider;

const Me = ExtensionUtils.getCurrentExtension();

let _shell = null;

class AdaptiveShellV16 {
    constructor() {
        this._rail = null;
        this._brandButton = null;
        this._projectButton = null;
        this._systemCenterButton = null;
        this._workspacesButton = null;
        this._commandButton = null;
        this._homeButton = null;
        this._filesButton = null;
        this._appsButton = null;
        this._windowList = null;
        this._menuManager = null;
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
        
        this._volumeSlider = null;
        this._volumeStream = null;
        this._statusLabels = {};
        this._audioOutputMenu = null;
        this._mixerControl = new Gvc.MixerControl({ name: 'Adaptive Shell Volume Control' });
        this._mixerControl.open();
        this._mixerControl.connect('state-changed', () => this._onMixerStateChanged());
        this._mixerControl.connect('default-sink-changed', () => this._onMixerStateChanged());
        this._mixerControl.connect('stream-added', (control, id) => {
            if (this._volumeStream && this._volumeStream.get_id() === id) {
                this._onMixerStateChanged();
            }
        });

        this._filesLauncher = GLib.build_filenamev([
            GLib.get_home_dir(),
            'adaptive-desktop',
            'scripts',
            'adaptive-files-launch-v1.6.sh',
        ]);
        this._settingsLauncher = GLib.build_filenamev([
            GLib.get_home_dir(),
            'adaptive-desktop',
            'scripts',
            'adaptive-settings-launch.sh',
        ]);
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
        this._commandHistoryFile = GLib.build_filenamev([
            GLib.get_home_dir(),
            '.config',
            'adaptive-desktop',
            'command-history.json',
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
        this._windowCreatedId = global.display.connect(
            'window-created',
            () => this._queueWindowListRefresh()
        );
        this._focusWindowId = global.display.connect(
            'notify::focus-window',
            () => this._queueWindowListRefresh()
        );
        this._overviewShowingId = Main.overview.connect(
            'showing',
            () => this._syncDockActive()
        );
        this._overviewHiddenId = Main.overview.connect(
            'hidden',
            () => this._syncDockActive()
        );

        this._layoutRail();
        this._syncDockActive();
        this._connectToProjectContext();
        this._queueWindowListRefresh();

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
        log('[Adaptive Shell v1.6] disable');

        if (this._monitorChangedId) {
            Main.layoutManager.disconnect(
                this._monitorChangedId
            );
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

        if (this._windowRefreshId) {
            GLib.Source.remove(this._windowRefreshId);
            this._windowRefreshId = 0;
        }

        this._disconnectWindowSignals();

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

        if (this._systemCenterButton) {
            this._systemCenterButton.destroy();
            this._systemCenterButton = null;
        }

        this._audioOutputMenu = null;

        if (this._workspacesButton) {
            this._workspacesButton.destroy();
            this._workspacesButton = null;
        }

        if (this._commandButton) {
            this._commandButton.destroy();
            this._commandButton = null;
        }

        this._menuManager = null;
        this._windowList = null;

        if (this._projectProxy) {
            this._projectProxy = null;
        }

        if (this._mixerControl) {
            this._mixerControl.close();
            this._mixerControl = null;
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
        this._rail = new St.BoxLayout({
            vertical: true,
            reactive: true,
            style_class: 'adaptive-rail',
        });

        const top = new St.BoxLayout({
            vertical: true,
            style_class: 'adaptive-rail-group',
        });

        this._homeButton = this._dockButton(
            'overview.svg',
            'Home',
            () => this._toggleOverview()
        );
        top.add_child(this._homeButton);

        this._filesButton = this._dockButton(
            'files.svg',
            'Adaptive Files',
            () => this._openFiles()
        );
        top.add_child(this._filesButton);

        this._appsButton = this._dockButton(
            'apps.svg',
            'Applications',
            () => this._showApplications()
        );
        top.add_child(this._appsButton);

        this._workspacesButton = this._railMenuButton(
            'workspaces.svg',
            'Workspaces'
        );

        this._workspacesButton.menu.connect('open-state-changed', (menu, open) => {
            this._setActorActive(this._workspacesButton, open);
            if (open) {
                this._populateWorkspacesMenu();
            }
        });
        
        top.add_child(this._workspacesButton);

        this._commandButton = this._railMenuButton('search.svg', 'Command');
        this._commandButton.menu.connect('open-state-changed', (menu, open) => {
            this._setActorActive(this._commandButton, open);
            if (open)
                this._populateCommandMenu();
        });
        top.add_child(this._commandButton);

        this._rail.add_child(top);

        const openGroup = new St.BoxLayout({
            vertical: true,
            style_class: 'adaptive-rail-group adaptive-window-group',
        });

        openGroup.add_child(
            new St.Label({
                text: 'OPEN',
                style_class: 'adaptive-rail-section-label',
                x_align: Clutter.ActorAlign.START,
            })
        );

        this._windowList = new St.BoxLayout({
            vertical: true,
            style_class: 'adaptive-window-list',
        });

        openGroup.add_child(this._windowList);
        this._rail.add_child(openGroup);

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

        this._systemCenterButton = this._railMenuButton('settings.svg', 'System');
        this._systemCenterButton.menu.connect('open-state-changed', (_menu, open) => {
            this._setActorActive(this._systemCenterButton, open);
        });
        
        let actions = SystemActions.getDefault();

        this._statusLabels = {
            network: this._statusRow('network-wireless-signal-excellent-symbolic', 'Network'),
            bluetooth: this._statusRow('bluetooth-active-symbolic', 'Bluetooth'),
            battery: this._statusRow('battery-good-symbolic', 'Power'),
            audio: this._statusRow('audio-speakers-symbolic', 'Audio'),
            performance: this._statusRow('utilities-system-monitor-symbolic', 'System'),
        };

        for (const key in this._statusLabels)
            this._systemCenterButton.menu.addMenuItem(this._statusLabels[key].item);

        this._systemCenterButton.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        
        let volumeItem = new PopupMenu.PopupBaseMenuItem({ activate: false });
        let volumeIcon = new St.Icon({
            icon_name: 'audio-volume-high-symbolic',
            style_class: 'popup-menu-icon'
        });
        this._volumeSlider = new Slider.Slider(0);
        this._volumeSlider.x_expand = true;
        this._volumeSlider.connect('notify::value', () => {
            if (this._volumeStream && this._mixerControl) {
                let volume = this._volumeSlider.value * this._mixerControl.get_vol_max_norm();
                this._volumeStream.volume = volume;
                this._volumeStream.push_volume();
            }
        });
        
        volumeItem.add_child(volumeIcon);
        volumeItem.add_child(this._volumeSlider);
        this._systemCenterButton.menu.addMenuItem(volumeItem);

        this._audioOutputMenu = new PopupMenu.PopupSubMenuMenuItem('Audio Output');
        this._audioOutputMenu.menu.connect('open-state-changed', (menu, open) => {
            if (open)
                this._populateAudioOutputMenu();
        });
        this._systemCenterButton.menu.addMenuItem(this._audioOutputMenu);
        
        this._systemCenterButton.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        
        let settingsItem = new PopupMenu.PopupMenuItem('System Settings');
        settingsItem.connect('activate', () => this._openSettings());
        this._systemCenterButton.menu.addMenuItem(settingsItem);
        
        this._systemCenterButton.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        let focusOnItem = new PopupMenu.PopupMenuItem('Focus On');
        focusOnItem.connect('activate', () => this._runFocus('on'));
        this._systemCenterButton.menu.addMenuItem(focusOnItem);

        let focusOffItem = new PopupMenu.PopupMenuItem('Focus Off');
        focusOffItem.connect('activate', () => this._runFocus('off'));
        this._systemCenterButton.menu.addMenuItem(focusOffItem);

        this._systemCenterButton.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        
        let lockItem = new PopupMenu.PopupMenuItem('Lock Screen');
        lockItem.connect('activate', () => actions.activateLockScreen());
        this._systemCenterButton.menu.addMenuItem(lockItem);
        
        let suspendItem = new PopupMenu.PopupMenuItem('Suspend');
        suspendItem.connect('activate', () => actions.activateSuspend());
        this._systemCenterButton.menu.addMenuItem(suspendItem);
        
        let logoutItem = new PopupMenu.PopupMenuItem('Return to Ubuntu...');
        logoutItem.connect('activate', () => actions.activateLogout());
        this._systemCenterButton.menu.addMenuItem(logoutItem);
        
        this._systemCenterButton.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        let restartItem = new PopupMenu.PopupMenuItem('Restart...');
        restartItem.connect('activate', () => {
            this._activateSystemAction(actions, 'activateRestart', 'Restart');
        });
        this._systemCenterButton.menu.addMenuItem(restartItem);

        let powerItem = new PopupMenu.PopupMenuItem('Shut Down...');
        powerItem.connect('activate', () => {
            this._activateSystemAction(actions, 'activatePowerOff', 'Shut Down');
        });
        this._systemCenterButton.menu.addMenuItem(powerItem);

        this._systemCenterButton.menu.connect('open-state-changed', (menu, open) => {
            if (open)
                this._refreshSystemCenterStatus();
        });
        
        bottom.add_child(this._systemCenterButton);

        this._rail.add_child(bottom);

        Main.layoutManager.addChrome(
            this._rail,
            {
                affectsStruts: true,
                trackFullscreen: true,
            }
        );
    }

    _statusRow(iconName, title) {
        const item = new PopupMenu.PopupBaseMenuItem({
            activate: false,
            reactive: false,
        });

        const icon = new St.Icon({
            icon_name: iconName,
            style_class: 'popup-menu-icon',
        });

        const titleLabel = new St.Label({
            text: title,
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });

        const valueLabel = new St.Label({
            text: 'Checking...',
            y_align: Clutter.ActorAlign.CENTER,
            style_class: 'adaptive-system-status-value',
        });

        item.add_child(icon);
        item.add_child(titleLabel);
        item.add_child(valueLabel);

        return { item, valueLabel };
    }

    _setStatus(key, value) {
        if (this._statusLabels[key])
            this._statusLabels[key].valueLabel.set_text(value);
    }

    _refreshSystemCenterStatus() {
        this._refreshNetworkStatus();
        this._refreshBluetoothStatus();
        this._refreshPowerStatus();
        this._refreshAudioStatus();
        this._refreshPerformanceStatus();
    }

    _refreshNetworkStatus() {
        this._readCommand(
            ['nmcli', '-t', '-f', 'STATE', 'general'],
            (text) => this._setStatus('network', this._humanStatus(text))
        );
    }

    _refreshBluetoothStatus() {
        this._readCommand(
            ['bluetoothctl', 'show'],
            (text) => {
                if (!text) {
                    this._setStatus('bluetooth', 'Unavailable');
                    return;
                }

                const powered = this._matchLine(text, /Powered:\s+(yes|no)/i);
                if (powered)
                    this._setStatus('bluetooth', powered.toLowerCase() === 'yes' ? 'On' : 'Off');
                else
                    this._setStatus('bluetooth', 'Unavailable');
            }
        );
    }

    _refreshPowerStatus() {
        this._readCommand(
            ['upower', '-i', '/org/freedesktop/UPower/devices/DisplayDevice'],
            (text) => {
                if (!text) {
                    this._setStatus('battery', 'Unavailable');
                    return;
                }

                const percentage = this._matchLine(text, /percentage:\s+([^\n]+)/i);
                const state = this._matchLine(text, /state:\s+([^\n]+)/i);

                if (percentage && state)
                    this._setStatus('battery', `${percentage.trim()} · ${this._humanStatus(state)}`);
                else if (percentage)
                    this._setStatus('battery', percentage.trim());
                else
                    this._setStatus('battery', 'Unavailable');
            }
        );
    }

    _refreshAudioStatus() {
        if (!this._volumeStream) {
            this._setStatus('audio', 'Unavailable');
            return;
        }

        const description =
            this._volumeStream.get_description() ||
            this._volumeStream.get_name() ||
            'Default output';

        this._setStatus('audio', description);
    }

    _refreshPerformanceStatus() {
        this._readCommand(['cat', '/proc/loadavg'], (loadText) => {
            this._readCommand(['cat', '/proc/meminfo'], (memText) => {
                const load = (loadText || '').split(/\s+/)[0] || '';
                const total = this._matchLine(memText, /^MemTotal:\s+(\d+)/m);
                const available = this._matchLine(memText, /^MemAvailable:\s+(\d+)/m);

                if (!load && (!total || !available)) {
                    this._setStatus('performance', 'Unavailable');
                    return;
                }

                if (total && available) {
                    const used = Math.max(0, Number(total) - Number(available));
                    const percent = Math.round((used / Number(total)) * 100);
                    this._setStatus('performance', `Load ${load || 'n/a'} · RAM ${percent}%`);
                    return;
                }

                this._setStatus('performance', `Load ${load}`);
            });
        });
    }

    _populateAudioOutputMenu() {
        if (!this._audioOutputMenu)
            return;

        this._audioOutputMenu.menu.removeAll();

        if (
            !this._mixerControl ||
            this._mixerControl.get_state() !== Gvc.MixerControlState.READY ||
            typeof this._mixerControl.get_sinks !== 'function'
        ) {
            const offline = new PopupMenu.PopupMenuItem('Audio service unavailable');
            offline.setSensitive(false);
            this._audioOutputMenu.menu.addMenuItem(offline);
            return;
        }

        const sinks = this._mixerControl.get_sinks() || [];

        if (!sinks.length) {
            const empty = new PopupMenu.PopupMenuItem('No output devices');
            empty.setSensitive(false);
            this._audioOutputMenu.menu.addMenuItem(empty);
            return;
        }

        for (const sink of sinks) {
            const label =
                sink.get_description() ||
                sink.get_name() ||
                'Audio output';
            const isActive =
                this._volumeStream &&
                sink.get_id &&
                this._volumeStream.get_id &&
                sink.get_id() === this._volumeStream.get_id();
            const item = new PopupMenu.PopupMenuItem(isActive ? `★ ${label}` : label);

            item.connect('activate', () => {
                try {
                    if (typeof this._mixerControl.set_default_sink === 'function') {
                        this._mixerControl.set_default_sink(sink);
                        this._volumeStream = sink;
                        this._refreshAudioStatus();
                    }
                } catch (e) {
                    logError(e, '[Adaptive Shell v1.6] set audio output');
                    Main.notifyError('Adaptive Desktop', 'Audio output could not be changed.');
                }
            });

            this._audioOutputMenu.menu.addMenuItem(item);
        }
    }

    _activateSystemAction(actions, methodName, label) {
        try {
            if (actions && typeof actions[methodName] === 'function') {
                actions[methodName]();
                return;
            }

            Main.notifyError(
                'Adaptive Desktop',
                `${label} is not available from this GNOME session.`
            );
        } catch (e) {
            logError(e, `[Adaptive Shell v1.6] ${label}`);
            Main.notifyError(
                'Adaptive Desktop',
                `${label} could not be started.`
            );
        }
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

    _railMenuButton(iconFile, labelText) {
        const button = new St.Button({
            reactive: true,
            can_focus: true,
            track_hover: true,
            style_class: 'adaptive-dock-button',
            accessible_name: labelText,
        });

        button.set_child(this._dockContent(iconFile, labelText));

        // Rail menus open to the right of the rail, not below the button,
        // so they never cover the rest of the rail.
        const menu = new PopupMenu.PopupMenu(button, 0.0, St.Side.LEFT);
        menu.actor.add_style_class_name('panel-menu');
        menu.actor.hide();
        Main.uiGroup.add_actor(menu.actor);

        if (!this._menuManager)
            this._menuManager = new PopupMenu.PopupMenuManager(this._rail);

        this._menuManager.addMenu(menu);

        button.menu = menu;
        button.connect('clicked', () => menu.toggle());
        button.connect('destroy', () => menu.destroy());

        return button;
    }

    _dockContent(iconFile, labelText) {
        const iconPath = GLib.build_filenamev([
            Me.path,
            'assets',
            'dock',
            iconFile,
        ]);

        const box = new St.BoxLayout({
            vertical: false,
            style_class: 'adaptive-dock-content',
            x_expand: true,
        });

        box.add_child(
            new St.Icon({
                gicon: Gio.FileIcon.new(
                    Gio.File.new_for_path(iconPath)
                ),
                style_class: 'adaptive-dock-icon',
            })
        );

        box.add_child(
            new St.Label({
                text: labelText,
                y_align: Clutter.ActorAlign.CENTER,
                style_class: 'adaptive-dock-label',
            })
        );

        return box;
    }

    _queueWindowListRefresh() {
        if (this._windowRefreshId)
            return;

        this._windowRefreshId = GLib.idle_add(
            GLib.PRIORITY_DEFAULT_IDLE,
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
                logError(e, '[Adaptive Shell v1.6] disconnect window signal');
            }
        }

        this._windowSignalIds = [];
    }

    _refreshWindowList() {
        if (!this._windowList)
            return;

        this._disconnectWindowSignals();
        this._windowList.destroy_all_children();

        const windows = global.get_window_actors()
            .map(actor => actor.meta_window)
            .filter(window => this._isDockWindow(window))
            .sort((a, b) => this._windowSortKey(a).localeCompare(this._windowSortKey(b)));

        if (!windows.length) {
            this._windowList.add_child(
                new St.Label({
                    text: 'No open windows',
                    style_class: 'adaptive-window-empty',
                    x_align: Clutter.ActorAlign.START,
                })
            );
            return;
        }

        for (const window of windows) {
            this._windowList.add_child(this._windowButton(window));

            try {
                this._windowSignalIds.push({
                    window,
                    id: window.connect('unmanaged', () => this._queueWindowListRefresh()),
                });
                this._windowSignalIds.push({
                    window,
                    id: window.connect('notify::title', () => this._queueWindowListRefresh()),
                });
            } catch (e) {
                logError(e, '[Adaptive Shell v1.6] connect window signal');
            }
        }
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

    _windowSortKey(window) {
        try {
            const app = Shell.WindowTracker.get_default().get_window_app(window);
            const appName = app ? app.get_name() : '';
            return `${appName} ${window.get_title() || ''}`;
        } catch (e) {
            return window.get_title() || '';
        }
    }

    _windowButton(window) {
        const app = Shell.WindowTracker.get_default().get_window_app(window);
        const appName = app ? app.get_name() : 'Window';
        const title = window.get_title() || appName;
        const isActive = global.display.focus_window === window;

        const button = new St.Button({
            reactive: true,
            can_focus: true,
            track_hover: true,
            style_class: isActive ? 'adaptive-window-button active' : 'adaptive-window-button',
            accessible_name: `Switch to ${title}`,
        });

        const row = new St.BoxLayout({
            vertical: false,
            style_class: 'adaptive-window-content',
            x_expand: true,
        });

        let icon;
        if (app)
            icon = app.create_icon_texture(18);
        else
            icon = new St.Icon({
                icon_name: 'application-x-executable-symbolic',
                style_class: 'adaptive-window-icon',
            });

        icon.add_style_class_name('adaptive-window-icon');
        row.add_child(icon);

        row.add_child(
            new St.Label({
                text: title,
                y_align: Clutter.ActorAlign.CENTER,
                style_class: 'adaptive-window-label',
            })
        );

        button.set_child(row);
        button.connect('clicked', () => {
            try {
                Main.activateWindow(window);
            } catch (e) {
                logError(e, '[Adaptive Shell v1.6] activate window');
            }
        });

        return button;
    }

    _dockButton(iconFile, name, callback) {
        const button = new St.Button({
            reactive: true,
            can_focus: true,
            track_hover: true,
            style_class: 'adaptive-dock-button',
            accessible_name: name,
        });

        button.set_child(this._dockContent(iconFile, name));

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

        const width = 172;
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

    _toggleOverview() {
        if (Main.overview.visible)
            Main.overview.hide();
        else
            Main.overview.show();

        this._syncDockActive();
    }

    _showApplications() {
        if (
            Main.overview &&
            typeof Main.overview.showApps ===
                'function'
        ) {
            Main.overview.showApps();
            this._syncDockActive();
            return;
        }

        Main.overview.show();
        this._syncDockActive();
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
        this._setActorActive(
            this._homeButton,
            Main.overview && Main.overview.visible
        );
    }
    
    _onMixerStateChanged() {
        if (this._mixerControl && this._mixerControl.get_state() === Gvc.MixerControlState.READY) {
            this._volumeStream = this._mixerControl.get_default_sink();
            if (this._volumeStream && this._volumeSlider) {
                let volume = this._volumeStream.volume / this._mixerControl.get_vol_max_norm();
                this._volumeSlider.value = volume;
            }
        }
    }

    _populateWorkspacesMenu() {
        this._workspacesButton.menu.removeAll();
        
        const wm = global.workspace_manager;
        const numWorkspaces = wm.get_n_workspaces();
        const activeIndex = wm.get_active_workspace_index();
        
        let header = new PopupMenu.PopupMenuItem('WORKSPACES');
        header.setSensitive(false);
        this._workspacesButton.menu.addMenuItem(header);

        if (this._activeProjectId && this._projectProxy) {
            const pinItem = new PopupMenu.PopupMenuItem(
                `Pin active project to Workspace ${activeIndex + 1}`
            );
            pinItem.connect('activate', () => {
                this._projectProxy.call(
                    'UpdateProject',
                    GLib.Variant.new('(ss)', [
                        this._activeProjectId,
                        JSON.stringify({ workspace_index: activeIndex }),
                    ]),
                    Gio.DBusCallFlags.NONE,
                    -1,
                    null,
                    null
                );
            });
            this._workspacesButton.menu.addMenuItem(pinItem);
            this._workspacesButton.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        }
        
        for (let i = 0; i < numWorkspaces; i++) {
            let isActive = (i === activeIndex);
            let label = isActive ? `★ Workspace ${i + 1}` : `Workspace ${i + 1}`;
            let item = new PopupMenu.PopupMenuItem(label);
            
            item.connect('activate', () => {
                let ws = wm.get_workspace_by_index(i);
                if (ws) {
                    ws.activate(global.get_current_time());
                }
            });
            
            this._workspacesButton.menu.addMenuItem(item);
        }
    }

    _populateCommandMenu() {
        this._commandButton.menu.removeAll();

        this._addCommandHeader('COMMANDS');

        if (GLib.file_test(this._commandLauncher, GLib.FileTest.IS_EXECUTABLE))
            this._addCommandItem('Open Command Palette', () => this._spawn([this._commandLauncher]));
        this._addCommandItem('Search apps and files...', () => this._showSearch());
        this._addCommandItem('Open Adaptive Files', () => this._openFiles());
        this._addCommandItem('Open System Settings', () => this._openSettings());
        if (GLib.file_test(this._focusCli, GLib.FileTest.IS_EXECUTABLE))
            this._addCommandItem('Apply Project Focus', () => this._spawn([this._focusCli, 'apply-project']));

        if (GLib.file_test(this._windowCli, GLib.FileTest.IS_EXECUTABLE)) {
            this._commandButton.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
            this._addCommandHeader('WINDOW');
            this._addCommandItem('Smart Tile Active Window', () => this._spawn([this._windowCli, 'tile', 'smart']));
            this._addCommandItem('Tile Active Window Left', () => this._spawn([this._windowCli, 'tile', 'left']));
            this._addCommandItem('Tile Active Window Right', () => this._spawn([this._windowCli, 'tile', 'right']));
            this._addCommandItem('Center Active Window', () => this._spawn([this._windowCli, 'tile', 'center']));
            this._addCommandItem('Maximize Active Window Around Dock', () => this._spawn([this._windowCli, 'tile', 'maximize']));
            this._addCommandItem('Toggle Active Window Fullscreen', () => this._spawn([this._windowCli, 'fullscreen']));
            this._addCommandItem('Save Active Window Placement', () => this._spawn([this._windowCli, 'save']));
            this._addCommandItem('Restore Active Window Placement', () => this._spawn([this._windowCli, 'restore']));
            this._addCommandItem('Save Project Window Placement', () => this._spawn([this._windowCli, 'save-project']));
            this._addCommandItem('Restore Project Window Placement', () => this._spawn([this._windowCli, 'restore-project']));
        }

        if (GLib.file_test(this._appearanceCli, GLib.FileTest.IS_EXECUTABLE)) {
            this._commandButton.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
            this._addCommandHeader('APPEARANCE');
            this._addCommandItem('Reduced Motion On', () => this._spawn([this._appearanceCli, 'reduced-motion', 'on']));
            this._addCommandItem('Reduced Motion Off', () => this._spawn([this._appearanceCli, 'reduced-motion', 'off']));
            this._addCommandItem('High Contrast On', () => this._spawn([this._appearanceCli, 'high-contrast', 'on']));
            this._addCommandItem('Dark Theme', () => this._spawn([this._appearanceCli, 'scheme', 'dark']));
            this._addCommandItem('Light Theme', () => this._spawn([this._appearanceCli, 'scheme', 'light']));
        }

        const recentActions = this._loadCommandHistory();
        if (recentActions.length) {
            this._commandButton.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
            this._addCommandHeader('RECENT');
            for (const action of recentActions.slice(0, 5))
                this._addCommandItem(action.label, () => this._runRememberedCommand(action.label), false);
        }

        this._commandButton.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this._addCommandHeader('SETTINGS');
        for (const section of this._settingsSections())
            this._addCommandItem(section.label, () => this._runSettingsSection(section));

        this._commandButton.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this._addCommandHeader('APPLICATIONS');

        try {
            const apps = Shell.AppSystem.get_default()
                .get_installed()
                .filter(app => app.should_show())
                .sort((a, b) => a.get_name().localeCompare(b.get_name()))
                .slice(0, 10);

            for (const app of apps)
                this._addCommandItem(app.get_name(), () => app.activate());
        } catch (e) {
            const item = new PopupMenu.PopupMenuItem('Applications unavailable');
            item.setSensitive(false);
            this._commandButton.menu.addMenuItem(item);
        }

        this._commandButton.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this._addCommandHeader('PROJECTS');

        if (!this._projectProxy) {
            const item = new PopupMenu.PopupMenuItem('Project service offline');
            item.setSensitive(false);
            this._commandButton.menu.addMenuItem(item);
            return;
        }

        const loading = new PopupMenu.PopupMenuItem('Loading projects...');
        loading.setSensitive(false);
        this._commandButton.menu.addMenuItem(loading);

        this._projectProxy.call(
            'ListProjects',
            null,
            Gio.DBusCallFlags.NONE,
            -1,
            null,
            (proxy, res) => {
                try {
                    loading.destroy();
                    const variant = proxy.call_finish(res);
                    const projects = JSON.parse(variant.deep_unpack()[0]);
                    let count = 0;

                    for (const pid in projects) {
                        count++;
                        const project = projects[pid];
                        this._addCommandItem(project.name, () => {
                            this._projectProxy.call(
                                'SetActiveProject',
                                GLib.Variant.new('(s)', [pid]),
                                Gio.DBusCallFlags.NONE,
                                -1,
                                null,
                                null
                            );
                        });
                    }

                    if (!count) {
                        const empty = new PopupMenu.PopupMenuItem('No projects registered');
                        empty.setSensitive(false);
                        this._commandButton.menu.addMenuItem(empty);
                    }
                } catch (e) {
                    logError(e, '[Adaptive Shell v1.6] command projects');
                }
            }
        );
    }

    _addCommandHeader(label) {
        const item = new PopupMenu.PopupMenuItem(label);
        item.setSensitive(false);
        this._commandButton.menu.addMenuItem(item);
    }

    _addCommandItem(label, callback, remember = true) {
        const item = new PopupMenu.PopupMenuItem(label);
        item.connect('activate', () => {
            try {
                if (remember)
                    this._rememberCommand(label);
                callback();
            } catch (e) {
                logError(e, `[Adaptive Shell v1.6] command ${label}`);
                Main.notifyError('Adaptive Desktop', `${label} could not run.`);
            }
        });
        this._commandButton.menu.addMenuItem(item);
    }

    _settingsSections() {
        return [
            { label: 'Appearance Settings', argv: ['gnome-control-center', 'appearance'] },
            { label: 'Display Settings', argv: ['gnome-control-center', 'display'] },
            { label: 'Sound Settings', argv: ['gnome-control-center', 'sound'] },
            { label: 'Keyboard Settings', argv: ['gnome-control-center', 'keyboard'] },
            { label: 'Network Settings', argv: ['gnome-control-center', 'network'] },
            { label: 'Power Settings', argv: ['gnome-control-center', 'power'] },
            { label: 'Privacy Settings', argv: ['gnome-control-center', 'privacy'] },
            { label: 'Accessibility Settings', argv: ['gnome-control-center', 'universal-access'] },
        ];
    }

    _runSettingsSection(section) {
        this._spawn(section.argv);
    }

    _runRememberedCommand(label) {
        const setting = this._settingsSections().find(section => section.label === label);
        if (setting) {
            this._runSettingsSection(setting);
            return;
        }

        if (label === 'Search apps and files...') {
            this._showSearch();
            return;
        }

        if (label === 'Open Adaptive Files') {
            this._openFiles();
            return;
        }

        if (label === 'Open System Settings') {
            this._openSettings();
            return;
        }

        if (GLib.file_test(this._windowCli, GLib.FileTest.IS_EXECUTABLE)) {
            const windowCommands = {
                'Smart Tile Active Window': ['tile', 'smart'],
                'Tile Active Window Left': ['tile', 'left'],
                'Tile Active Window Right': ['tile', 'right'],
                'Center Active Window': ['tile', 'center'],
                'Maximize Active Window Around Dock': ['tile', 'maximize'],
                'Toggle Active Window Fullscreen': ['fullscreen'],
                'Save Active Window Placement': ['save'],
                'Restore Active Window Placement': ['restore'],
                'Save Project Window Placement': ['save-project'],
                'Restore Project Window Placement': ['restore-project'],
            };

            if (windowCommands[label]) {
                this._spawn([this._windowCli, ...windowCommands[label]]);
                return;
            }
        }

        this._showSearch();
    }

    _loadCommandHistory() {
        try {
            const file = Gio.File.new_for_path(this._commandHistoryFile);
            const [, contents] = file.load_contents(null);
            return JSON.parse(imports.byteArray.toString(contents));
        } catch (e) {
            return [];
        }
    }

    _rememberCommand(label) {
        const history = this._loadCommandHistory().filter(item => item.label !== label);
        history.unshift({ label });

        try {
            const dir = GLib.path_get_dirname(this._commandHistoryFile);
            GLib.mkdir_with_parents(dir, 0o755);
            GLib.file_set_contents(
                this._commandHistoryFile,
                JSON.stringify(history.slice(0, 12))
            );
        } catch (e) {
            logError(e, '[Adaptive Shell v1.6] remember command');
        }
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
        if (GLib.file_test(this._settingsLauncher, GLib.FileTest.IS_EXECUTABLE)) {
            this._spawn([
                this._settingsLauncher,
            ]);
            return;
        }

        this._spawn([
            'gnome-control-center',
        ]);
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
