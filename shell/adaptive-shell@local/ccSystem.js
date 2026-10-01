// Adaptive Control Center - power mode, the tile layout editor, privacy, display, screen recording, the session and keep-awake.
//
// Part of the one ControlCenter object in controlCenter.js, kept in its own
// file by subject. The methods of the class below are copied onto that object
// when the extension loads, so `this` here is the Control Center itself.

/* exported CcSystem */

const { Clutter, Gio, GLib, Meta, St } = imports.gi;
const Main = imports.ui.main;

const Me = imports.misc.extensionUtils.getCurrentExtension();
const AdaptiveUtil = Me.imports.adaptiveUtil;
const CcUtil = Me.imports.ccUtil;
const {
    readBattery,
    CAMERA_POLL_S,
    UI_MODE_SCREENCAST,
    DEFAULT_TILES,
    TILE_DROPDOWNS,
    readConfig,
    writeConfig,
    run,
    appNameForPid,
    friendlyAppName,
    ignoreReply,
    INHIBIT_SUSPEND_AND_IDLE,
    PROFILES,
    profileIcon,
    iconProps,
    makeHeading,
    makeRow,
} = CcUtil;

var CcSystem = class CcSystem {
    // --- Power mode

    _syncPowerPage() {
        const page = this._pages.power;
        const proxy = this._profilesProxy();
        const health = AdaptiveUtil.batteryHealth(readBattery());

        if (!proxy && !health) {
            this._fillPage(page, [], 'Power profiles are not available on this machine.');
            return;
        }

        const available = proxy ? (proxy.Profiles || [])
            .map(p => p.Profile.unpack())
            .filter(p => PROFILES[p]) : [];
        const active = proxy ? proxy.ActiveProfile : '';
        if (this._unchanged(page, `${available.join(',')}|${active}|${JSON.stringify(health)}`, false))
            return;
        const order = ['performance', 'balanced', 'power-saver'];
        available.sort((a, b) => order.indexOf(a) - order.indexOf(b));

        const rows = available.map(profile => {
            const active = proxy.ActiveProfile === profile;
            return makeRow({
                icon: profileIcon(PROFILES[profile].icon),
                title: PROFILES[profile].label,
                trailing: active ? ['object-select-symbolic'] : [],
                active,
                onActivate: () => {
                    proxy.ActiveProfile = profile;
                },
            });
        });

        if (health) {
            rows.push(makeHeading('Battery'));
            let detail = `Holds ${health.full.toFixed(1)} of ${health.design.toFixed(1)} ${health.unit} when full`;
            if (health.cycles)
                detail += ` · ${health.cycles} cycles`;
            rows.push(makeRow({
                icon: health.healthPct < 80 ? 'battery-caution-symbolic' : 'battery-good-symbolic',
                title: `Battery health ${health.healthPct}%`,
                subtitle: detail,
                alert: health.healthPct < 80,
            }));
            if (health.limit) {
                rows.push(makeRow({
                    icon: 'battery-full-charging-symbolic',
                    title: 'Charge limit',
                    subtitle: `Stops charging at ${health.limit}% to slow wear`,
                }));
            }
        }

        this._fillPage(page, rows, proxy ? '' : 'Power profiles are not available on this machine.');
    }

    // --- Sound output

    // ------------------------------------------------------ tile layout

    // The tile order and visibility, from ~/.config/adaptive-desktop/
    // control-center.json, with any tile the file does not mention (a new one,
    // or a file from before it existed) appended and shown.
    _tileOrder() {
        const saved = Array.isArray(readConfig().tiles) ? readConfig().tiles : [];
        const order = saved.filter(t => t && DEFAULT_TILES.includes(t.id))
            .map(t => ({ id: t.id, visible: t.visible !== false }));
        for (const id of DEFAULT_TILES) {
            if (!order.some(t => t.id === id))
                order.push({ id, visible: true });
        }
        return order;
    }

    // Tiles two to a row; the grid row under each pair holds that pair's
    // dropdowns, so a dropdown always opens directly under its own tile
    // wherever the tile has been moved to.
    _layoutTiles() {
        const grid = this._grid;
        for (const child of grid.get_children())
            grid.remove_child(child);

        const visible = this._tileOrder().filter(t => t.visible && this._tiles[t.id]).map(t => t.id);
        visible.forEach((id, i) => {
            const row = 2 * Math.floor(i / 2);
            grid.layout_manager.attach(this._tiles[id].actor, i % 2, row, 1, 1);
            const dropdown = TILE_DROPDOWNS[id];
            if (dropdown && this._pages[dropdown])
                grid.layout_manager.attach(this._pages[dropdown].actor, 0, row + 1, 2, 1);
        });

        // A hidden tile's dropdown cannot stay open with nothing above it.
        const tileDropdowns = Object.values(TILE_DROPDOWNS);
        if (this._open && tileDropdowns.includes(this._open) &&
            !visible.some(id => TILE_DROPDOWNS[id] === this._open))
            this._openDropdown(null);

        if (this._media)
            this._syncMedia();
    }

    _saveTiles(order) {
        writeConfig({ tiles: order.map(({ id, visible }) => ({ id, visible })) });
        this._layoutTiles();
        this._syncEditPage(true);
    }

    _syncEditPage(force = false) {
        const page = this._pages.edit;
        const order = this._tileOrder();
        if (this._unchanged(page, JSON.stringify([order, readConfig().showMedia]), force))
            return;
        const rows = [makeHeading('Controls')];

        order.forEach((entry, i) => {
            const tile = this._tiles[entry.id];
            if (!tile)
                return;

            const row = new St.BoxLayout({
                style_class: 'adaptive-cc-row adaptive-cc-edit-row',
                x_expand: true,
            });

            const check = new St.Button({
                style_class: 'adaptive-cc-edit-check',
                can_focus: true,
                accessible_name: entry.visible ? `Hide ${tile.title}` : `Show ${tile.title}`,
                child: new St.Icon({ icon_name: entry.visible ? 'object-select-symbolic' : 'list-add-symbolic' }),
                y_align: Clutter.ActorAlign.CENTER,
            });
            if (entry.visible)
                check.add_style_pseudo_class('checked');
            check.connect('clicked', () => {
                order[i].visible = !order[i].visible;
                this._saveTiles(order);
            });
            row.add_child(check);

            row.add_child(new St.Icon({
                ...iconProps(tile.iconName),
                style_class: 'adaptive-cc-row-icon',
                y_align: Clutter.ActorAlign.CENTER,
            }));
            row.add_child(new St.Label({
                text: tile.title,
                style_class: entry.visible ? 'adaptive-cc-row-title' : 'adaptive-cc-row-title adaptive-cc-edit-hidden',
                x_expand: true,
                y_align: Clutter.ActorAlign.CENTER,
            }));

            const move = (icon, delta, label) => {
                const target = i + delta;
                const button = new St.Button({
                    style_class: 'adaptive-cc-edit-move',
                    can_focus: true,
                    accessible_name: `${label} ${tile.title}`,
                    child: new St.Icon({ icon_name: icon }),
                    reactive: target >= 0 && target < order.length,
                    y_align: Clutter.ActorAlign.CENTER,
                });
                if (!button.reactive)
                    button.add_style_pseudo_class('insensitive');
                button.connect('clicked', () => {
                    [order[i], order[target]] = [order[target], order[i]];
                    this._saveTiles(order);
                });
                row.add_child(button);
            };
            move('go-up-symbolic', -1, 'Move up');
            move('go-down-symbolic', 1, 'Move down');

            rows.push(row);
        });

        rows.push(makeHeading('Cards'));
        const showMedia = readConfig().showMedia !== false;
        rows.push(makeRow({
            icon: 'audio-x-generic-symbolic',
            title: 'Now Playing',
            subtitle: showMedia ? 'Shown while something plays' : 'Hidden',
            trailing: showMedia ? ['object-select-symbolic'] : [],
            onActivate: () => {
                writeConfig({ showMedia: !showMedia });
                this._syncMedia();
                this._syncEditPage(true);
            },
        }));
        rows.push(makeRow({
            icon: 'edit-undo-symbolic',
            title: 'Reset to Default',
            onActivate: () => {
                writeConfig({ tiles: null, showMedia: true });
                this._layoutTiles();
                this._syncEditPage(true);
            },
        }));

        this._fillPage(page, rows);
    }

    // ------------------------------------------------------------- privacy

    // Apps recording from a microphone, by the name a person knows them by.
    _micApps() {
        const names = new Set();
        let outputs = [];
        try {
            outputs = this._mixer.get_source_outputs() || [];
        } catch (e) {
            return [];
        }
        for (const stream of outputs) {
            if (stream.is_event_stream)
                continue;
            const id = stream.get_application_id() || '';
            const name = stream.get_name() || '';
            // Level meters and mixers read the mic without recording anyone.
            if (/peak detect|volumecontrol|pavucontrol|gnome-shell|speech-dispatcher/i.test(`${name} ${id}`))
                continue;
            names.add(friendlyAppName(id, name));
        }
        return [...names];
    }

    _buildPrivacy() {
        const box = new St.BoxLayout({
            style_class: 'adaptive-cc-privacy',
            vertical: true,
            x_expand: true,
            visible: false,
        });
        const line = dotClass => {
            const row = new St.BoxLayout({ style_class: 'adaptive-cc-privacy-row' });
            row.add_child(new St.Widget({
                style_class: `adaptive-cc-privacy-dot ${dotClass}`,
                y_align: Clutter.ActorAlign.CENTER,
            }));
            const label = new St.Label({
                style_class: 'adaptive-cc-privacy-label',
                x_expand: true,
                y_align: Clutter.ActorAlign.CENTER,
            });
            label.clutter_text.line_wrap = true;
            row.add_child(label);
            box.add_child(row);
            return { row, label };
        };
        this._privacyMic = line('adaptive-cc-privacy-mic');
        this._privacyCam = line('adaptive-cc-privacy-cam');
        this._privacy = box;
        this._cameraApps = [];
        return box;
    }

    _syncPrivacy() {
        if (!this._privacy)
            return;
        const mic = this._micApps();
        const cam = this._cameraApps || [];
        const list = names => {
            if (names.length <= 2)
                return names.join(' and ');
            return `${names.slice(0, 2).join(', ')} and ${names.length - 2} more`;
        };
        this._privacyMic.label.text = `Microphone in use by ${list(mic)}`;
        this._privacyMic.row.visible = mic.length > 0;
        this._privacyCam.label.text = `Camera in use by ${list(cam)}`;
        this._privacyCam.row.visible = cam.length > 0;
        this._privacy.visible = mic.length > 0 || cam.length > 0;
    }

    // Nothing reports camera use, so the panel asks the kernel who has a
    // /dev/video* open - only while the panel is open, and off the main loop.
    _pollCamera() {
        if (this._camBusy)
            return;
        const nodes = [];
        for (let i = 0; i < 16; i++) {
            if (GLib.file_test(`/dev/video${i}`, GLib.FileTest.EXISTS))
                nodes.push(`/dev/video${i}`);
        }
        if (!nodes.length || !GLib.find_program_in_path('fuser')) {
            this._cameraApps = [];
            return;
        }

        this._camBusy = true;
        run(['fuser', ...nodes], (_ok, out) => {
            this._camBusy = false;
            const pids = [...new Set(out.match(/\d+/g) || [])].map(p => parseInt(p, 10));
            const names = new Set();
            for (const pid of pids) {
                const found = appNameForPid(pid);
                if (!found || /^(pipewire|wireplumber)$/.test(found.name))
                    continue;
                names.add(found.isApp ? found.name : friendlyAppName(null, found.name));
            }
            this._cameraApps = [...names];
            this._syncPrivacy();
        });
    }

    _startCameraPolling() {
        this._stopCameraPolling();
        this._pollCamera();
        this._camTimer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, CAMERA_POLL_S, () => {
            this._pollCamera();
            return GLib.SOURCE_CONTINUE;
        });
    }

    _stopCameraPolling() {
        if (this._camTimer) {
            GLib.Source.remove(this._camTimer);
            this._camTimer = 0;
        }
    }

    // An orange dot beside the system icons whenever something records from
    // a microphone, like iOS. The mixer tells us when streams come and go, so
    // this listens all the time without polling anything.
    _installPanelDot() {
        const box = this._agg && this._agg._indicators;
        if (!box)
            return;
        this._panelDot = new St.Widget({
            style_class: 'adaptive-privacy-panel-dot',
            y_align: Clutter.ActorAlign.CENTER,
            visible: false,
        });
        box.insert_child_at_index(this._panelDot, 0);
        const sync = () => {
            if (this._panelDot)
                this._panelDot.visible = this._micApps().length > 0;
            if (this._menu && this._menu.isOpen)
                this._syncPrivacy();
        };
        this._dotIds = ['stream-added', 'stream-removed', 'state-changed']
            .map(signal => this._mixer.connect(signal, sync));
        sync();
    }

    _removePanelDot() {
        for (const id of this._dotIds || [])
            this._mixer.disconnect(id);
        this._dotIds = [];
        if (this._panelDot) {
            this._panelDot.destroy();
            this._panelDot = null;
        }
    }

    // ------------------------------------------------------------- display

    _syncDisplayPage() {
        const page = this._pages.display;
        const monitors = Main.layoutManager.monitors || [];
        const primary = Main.layoutManager.primaryIndex;
        let current = -1;
        try {
            current = Meta.MonitorManager.get().get_switch_config();
        } catch (e) {
        }
        if (this._unchanged(page, JSON.stringify([monitors.map(m => [m.x, m.y, m.width, m.height]),
            primary, current]), false))
            return;
        const rows = [makeHeading('Displays')];

        monitors.forEach((m, i) => {
            rows.push(makeRow({
                icon: 'video-display-symbolic',
                title: i === primary ? 'Main display' : `Display ${i + 1}`,
                subtitle: `${m.width} × ${m.height}${m.geometry_scale && m.geometry_scale !== 1 ? ` · ${m.geometry_scale}×` : ''}`,
            }));
        });

        let manager = null;
        try {
            manager = Meta.MonitorManager.get();
        } catch (e) {
        }

        // Mutter can report switching as possible with one screen (a ghost or
        // disconnected output); arranging needs two real ones.
        if (!manager || !manager.can_switch_config() || monitors.length < 2) {
            this._fillPage(page, rows, monitors.length < 2
                ? 'Connect another display to extend or mirror your screen.' : '');
            return;
        }

        const T = Meta.MonitorSwitchConfigType;
        rows.push(makeHeading('Arrangement'));
        for (const [type, title, icon] of [
            [T.ALL_LINEAR, 'Extend', 'video-joined-displays-symbolic'],
            [T.ALL_MIRROR, 'Mirror', 'view-mirror-symbolic'],
            [T.EXTERNAL, 'External Only', 'video-single-display-symbolic'],
            [T.BUILTIN, 'Built-in Only', 'computer-symbolic'],
        ]) {
            const active = current === type;
            rows.push(makeRow({
                icon,
                title,
                trailing: active ? ['object-select-symbolic'] : [],
                active,
                onActivate: active ? null : () => {
                    manager.switch_config(type);
                    this._queueSync();
                },
            }));
        }

        this._fillPage(page, rows);
    }

    // ------------------------------------------------------ screen record

    _record() {
        this._closeMenu();
        const ui = Main.screenshotUI;
        if (!ui)
            return;
        try {
            if (ui.screencast_in_progress) {
                ui.stopScreencast();
                return;
            }
            const promise = ui.open(UI_MODE_SCREENCAST);
            if (promise && promise.catch)
                promise.catch(e => logError(e, '[Adaptive Control Center] screen recording'));
        } catch (e) {
            logError(e, '[Adaptive Control Center] screen recording');
        }
    }

    // --- Session

    _syncSessionPage() {
        const page = this._pages.session;
        const actions = this._systemActions;
        if (this._unchanged(page, ['suspend', 'restart', 'power_off', 'logout', 'switch_user']
            .map(a => actions[`can_${a}`]).join(','), false))
            return;
        const run = fn => () => {
            this._closeMenu();
            fn();
        };

        const rows = [];
        if (actions.can_suspend) {
            rows.push(makeRow({
                icon: 'media-playback-pause-symbolic',
                title: 'Suspend',
                onActivate: run(() => actions.activateSuspend()),
            }));
        }
        if (actions.can_restart) {
            rows.push(makeRow({
                icon: 'system-reboot-symbolic',
                title: 'Restart…',
                onActivate: run(() => actions.activateRestart()),
            }));
        }
        if (actions.can_power_off) {
            rows.push(makeRow({
                icon: 'system-shutdown-symbolic',
                title: 'Power Off…',
                danger: true,
                onActivate: run(() => actions.activatePowerOff()),
            }));
        }
        if (actions.can_logout) {
            rows.push(makeRow({
                icon: 'system-log-out-symbolic',
                title: 'Log Out',
                onActivate: run(() => actions.activateLogout()),
            }));
        }
        if (actions.can_switch_user) {
            rows.push(makeRow({
                icon: 'system-users-symbolic',
                title: 'Switch User…',
                onActivate: run(() => actions.activateSwitchUser()),
            }));
        }

        this._fillPage(page, rows, rows.length ? '' : 'No session actions are available.');
    }

    // --------------------------------------------------------- keep awake

    _toggleInhibitor() {
        if (this._inhibitPending)
            return;

        if (this._inhibitCookie) {
            this._releaseInhibitor();
            this._queueSync();
            return;
        }

        this._inhibitPending = true;
        this._queueSync();

        Gio.DBus.session.call(
            'org.gnome.SessionManager',
            '/org/gnome/SessionManager',
            'org.gnome.SessionManager',
            'Inhibit',
            new GLib.Variant('(susu)', [
                'adaptive-shell', 0, 'Keep Awake from the Control Center',
                INHIBIT_SUSPEND_AND_IDLE,
            ]),
            new GLib.VariantType('(u)'),
            Gio.DBusCallFlags.NONE,
            -1,
            null,
            (connection, result) => {
                this._inhibitPending = false;
                try {
                    [this._inhibitCookie] = connection.call_finish(result).deep_unpack();
                } catch (e) {
                    this._inhibitCookie = 0;
                    logError(e, '[Adaptive Control Center] Keep Awake');
                }
                // Disabled while the call was in flight: let it go at once.
                if (!this._attached)
                    this._releaseInhibitor();
                else
                    this._queueSync();
            });
    }

    _releaseInhibitor() {
        if (!this._inhibitCookie)
            return;

        const cookie = this._inhibitCookie;
        this._inhibitCookie = 0;
        Gio.DBus.session.call(
            'org.gnome.SessionManager',
            '/org/gnome/SessionManager',
            'org.gnome.SessionManager',
            'Uninhibit',
            new GLib.Variant('(u)', [cookie]),
            null,
            Gio.DBusCallFlags.NONE,
            -1,
            null, ignoreReply);
    }
};
