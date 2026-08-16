const { St, Gio, GLib, Clutter } = imports.gi;
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
        this._projectLabel = null;
        this._activeProjectId = null;
        this._monitorChangedId = 0;
        this._hiddenActors = [];
        this._clockActor = null;
        this._clockDisplay = null;
        this._projectProxy = null;
        
        this._volumeSlider = null;
        this._volumeStream = null;
        this._statusLabels = {};
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

        if (this._systemCenterButton) {
            this._systemCenterButton.destroy();
            this._systemCenterButton = null;
        }

        if (this._workspacesButton) {
            this._workspacesButton.destroy();
            this._workspacesButton = null;
        }

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

        this._workspacesButton = new PanelMenu.Button(0.0, 'WorkspacesMenu', false);
        this._workspacesButton.add_style_class_name('adaptive-dock-button');
        
        const wsIconPath = GLib.build_filenamev([
            Me.path, 'assets', 'dock', 'workspaces.svg'
        ]);
        const wsIcon = new St.Icon({
            gicon: Gio.FileIcon.new(Gio.File.new_for_path(wsIconPath)),
            style_class: 'adaptive-dock-icon',
        });
        this._workspacesButton.add_child(wsIcon);
        
        this._workspacesButton.menu.connect('open-state-changed', (menu, open) => {
            if (open) {
                this._populateWorkspacesMenu();
            }
        });
        
        top.add_child(this._workspacesButton);

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

        this._systemCenterButton = new PanelMenu.Button(0.0, 'SystemCenterMenu', false);
        this._systemCenterButton.add_style_class_name('adaptive-dock-button');
        
        const iconPath = GLib.build_filenamev([
            Me.path, 'assets', 'dock', 'settings.svg'
        ]);
        const icon = new St.Icon({
            gicon: Gio.FileIcon.new(Gio.File.new_for_path(iconPath)),
            style_class: 'adaptive-dock-icon',
        });
        this._systemCenterButton.add_child(icon);
        
        let actions = SystemActions.getDefault();

        this._statusLabels = {
            network: this._statusRow('network-wireless-signal-excellent-symbolic', 'Network'),
            bluetooth: this._statusRow('bluetooth-active-symbolic', 'Bluetooth'),
            battery: this._statusRow('battery-good-symbolic', 'Power'),
            audio: this._statusRow('audio-speakers-symbolic', 'Audio'),
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
        
        this._systemCenterButton.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        
        let settingsItem = new PopupMenu.PopupMenuItem('System Settings');
        settingsItem.connect('activate', () => this._openSettings());
        this._systemCenterButton.menu.addMenuItem(settingsItem);
        
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
        
        let powerItem = new PopupMenu.PopupMenuItem('Power Off...');
        powerItem.connect('activate', () => actions.activatePowerOff());
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
