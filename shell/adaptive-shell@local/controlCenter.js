// Adaptive Control Center v1
//
// GNOME 42's system menu - the "aggregate menu" at the right of the top bar -
// rebuilt as an Android/iOS-style control center: tiles for the things people
// switch, sliders for the things they set, and dropdowns that open in place
// under their control - Wi-Fi networks, Bluetooth devices, power mode, sound
// output and the session - so none of the everyday changes needs a trip into
// Settings, or even away from the panel.
//
// Like the Shade, this rearranges rather than reimplements. Every indicator
// GNOME builds for this menu keeps running: its NetworkManager client, its
// Bluetooth client and its D-Bus proxies are what these tiles read and write,
// and its menu sections stay in the popup, only hidden. detach() shows them
// again, and so does the lock screen, where GNOME's restricted menu is the
// right one to offer.
//
// Nothing listens while the popup is shut. Signals are connected when it
// opens and dropped when it closes, and every open starts from a full sync.

/* exported ControlCenter */
const { Clutter, Gio, GLib, Shell, St } = imports.gi;
const Main = imports.ui.main;
const Slider = imports.ui.slider;
const SystemActions = imports.misc.systemActions;
const Util = imports.misc.util;
const Volume = imports.ui.status.volume;
const Rfkill = imports.ui.status.rfkill;

const Me = imports.misc.extensionUtils.getCurrentExtension();
const CcUtil = Me.imports.ccUtil;
const {
    NM,
    LIST_MAX_HEIGHT,
    DROPDOWN_FADE_MS,
    extensionIcon,
    PROFILES,
    profileIcon,
    BATTERY_CHARGING,
    BATTERY_FULL,
    signalLevel,
    ssidName,
    volumeIcon,
    makeRoundButton,
    Tile,
} = CcUtil;
const CcNetwork = Me.imports.ccNetwork;
const CcBluetooth = Me.imports.ccBluetooth;
const CcMedia = Me.imports.ccMedia;
const CcSystem = Me.imports.ccSystem;

// ------------------------------------------------------------ control center

var ControlCenter = class ControlCenter {
    constructor() {
        this._agg = null;
        this._menu = null;
        this._root = null;
        this._stock = [];
        this._showingOurs = false;
        this._ownChange = false;
        this._openStateId = 0;
        this._sessionId = 0;
        this._live = [];
        this._streamLive = [];
        this._syncId = 0;
        this._scanId = 0;
        this._open = null;
        this._pages = {};
        this._syncingSliders = false;
        this._inhibitCookie = 0;
        this._inhibitPending = false;
        this._btPending = new Set();
        this._btErrors = new Map();
        this._btPair = null;
        this._wifiJoin = null;
        this._wifiErrors = new Map();
        this._joinWatch = null;
        this._agentExport = null;
        this._agentRegistered = false;
        this._wifiShare = null;
        this._players = new Map();
        this._mprisSub = 0;
        this._camTimer = 0;
        this._dotIds = [];
        this._ts = null;
        this._btScan = { timer: 0, active: false };
        this._btTimers = new Set();
        this._attached = false;
        // screenText.js, handed over by the extension after it starts.
        this.screenText = null;
    }

    // ------------------------------------------------------------- attach

    attach() {
        if (this._attached)
            return;

        const agg = Main.panel.statusArea.aggregateMenu;
        if (!agg || !agg.menu || !agg.menu.box) {
            log('[Adaptive Control Center] no aggregate menu; staying stock');
            return;
        }

        this._agg = agg;
        this._menu = agg.menu;

        try {
            this._systemActions = SystemActions.getDefault();
            this._mixer = Volume.getMixerControl();
            this._rfkill = Rfkill.getRfkillManager();
            this._colorSettings = new Gio.Settings({
                schema_id: 'org.gnome.settings-daemon.plugins.color',
            });
            this._notifSettings = new Gio.Settings({
                schema_id: 'org.gnome.desktop.notifications',
            });

            this._build();
            this._buildAgent();
            this._installPanelDot();

            // GNOME's sections stay in the popup, hidden. Their own code
            // toggles their visibility for its own reasons, so the wanted
            // state is tracked and re-applied rather than set once.
            for (const actor of this._menu.box.get_children()) {
                const record = { actor, visible: actor.visible, id: 0 };
                record.id = actor.connect('notify::visible', () => {
                    if (this._ownChange)
                        return;

                    if (!this._showingOurs) {
                        record.visible = actor.visible;
                        return;
                    }

                    // While this panel is up, only GNOME ever shows a
                    // section, so "shown" is GNOME's word and is recorded.
                    // "Hidden" is the echo of our own hide: GObject queues a
                    // notification raised inside a notify handler and delivers
                    // it after the handler - and the _ownChange guard - has
                    // returned. Recording that echo lost the network section
                    // for good whenever NetworkManager came up after attach.
                    if (actor.visible) {
                        record.visible = true;
                        this._setVisible(actor, false);
                    }
                });
                this._stock.push(record);
            }

            this._menu.box.add_child(this._root);

            this._openStateId = this._menu.connect('open-state-changed',
                (_menu, open) => (open ? this._onOpen() : this._onClose()));
            this._sessionId = Main.sessionMode.connect('updated',
                () => this._syncSession());

            this._attached = true;
            this._syncSession();
            log('[Adaptive Control Center] attached to the system menu');
        } catch (e) {
            logError(e, '[Adaptive Control Center] attach failed; reverting to stock');
            this.detach();
        }
    }

    detach() {
        this._onClose();

        if (this._openStateId && this._menu) {
            this._menu.disconnect(this._openStateId);
            this._openStateId = 0;
        }

        if (this._sessionId) {
            Main.sessionMode.disconnect(this._sessionId);
            this._sessionId = 0;
        }

        // Keep Awake belongs to this panel; it must not outlive it.
        this._releaseInhibitor();

        this._cancelPairing();
        this._unregisterAgent();
        this._stopWatchingJoin();
        this._removePanelDot();
        this._stopMpris();
        this._stopCameraPolling();
        this._stopBtScan();
        for (const id of this._btTimers)
            GLib.Source.remove(id);
        this._btTimers.clear();
        if (this._agentExport) {
            try {
                this._agentExport.unexport();
            } catch (e) {
            }
            this._agentExport = null;
        }

        this._showingOurs = false;
        for (const record of this._stock) {
            try {
                record.actor.disconnect(record.id);
                this._setVisible(record.actor, record.visible);
            } catch (e) {
                logError(e, '[Adaptive Control Center] restoring a stock section');
            }
        }
        this._stock = [];

        if (this._menu && this._menu.box)
            this._menu.box.remove_style_class_name('adaptive-cc-menu');

        if (this._root) {
            this._root.destroy();
            this._root = null;
        }

        this._pages = {};
        this._agg = null;
        this._menu = null;
        this._attached = false;
    }

    _setVisible(actor, visible) {
        this._ownChange = true;
        try {
            actor.visible = visible;
        } finally {
            this._ownChange = false;
        }
    }

    // The lock screen keeps GNOME's restricted menu; everywhere else this one.
    _syncSession() {
        const restricted = Main.sessionMode.isLocked || Main.sessionMode.isGreeter;
        const ours = !restricted;

        this._showingOurs = ours;
        for (const record of this._stock)
            this._setVisible(record.actor, ours ? false : record.visible);

        this._root.visible = ours;
        if (ours)
            this._menu.box.add_style_class_name('adaptive-cc-menu');
        else
            this._menu.box.remove_style_class_name('adaptive-cc-menu');
    }

    _closeMenu() {
        if (this._menu)
            this._menu.close();
    }

    _openSettings(panel) {
        this._closeMenu();
        Main.overview.hide();
        try {
            Util.spawn(['gnome-control-center', panel]);
        } catch (e) {
            logError(e, `[Adaptive Control Center] opening Settings (${panel})`);
        }
    }

    // --------------------------------------------------------------- build

    _build() {
        this._root = new St.BoxLayout({
            style_class: 'adaptive-cc',
            vertical: true,
            x_expand: true,
        });

        this._buildMainPage();

        // Each dropdown opens directly under the control that opens it.
        this._mainPage.insert_child_above(
            this._buildDropdown('session', {}), this._header);

        this._buildDropdown('wifi', { settings: ['wifi', 'Network Settings'] });
        this._buildDropdown('bluetooth', { settings: ['bluetooth', 'Bluetooth Settings'] });
        this._buildDropdown('power', { settings: ['power', 'Power Settings'] });
        this._buildDropdown('tailscale', {
            link: ['Admin Console', () => {
                this._closeMenu();
                Gio.AppInfo.launch_default_for_uri('https://login.tailscale.com/admin/machines', null);
            }],
        });
        this._layoutTiles();

        this._slidersBox.insert_child_above(this._buildDropdown('sound', {
            settings: ['sound', 'Sound Settings'],
        }), this._volume.row);
        this._slidersBox.insert_child_above(this._buildDropdown('display', {
            settings: ['display', 'Display Settings'],
        }), this._brightness.row);

        this._mainPage.add_child(this._buildDropdown('edit', {}));
    }

    _buildMainPage() {
        const page = new St.BoxLayout({
            style_class: 'adaptive-cc-main',
            vertical: true,
            x_expand: true,
        });
        this._root.add_child(page);
        this._mainPage = page;

        // Header: battery on the left, session actions on the right.
        const header = new St.BoxLayout({ style_class: 'adaptive-cc-header', x_expand: true });
        page.add_child(header);
        this._header = header;

        this._battery = new St.BoxLayout({
            style_class: 'adaptive-cc-battery',
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._batteryIcon = new St.Icon({ y_align: Clutter.ActorAlign.CENTER });
        this._batteryLabel = new St.Label({ y_align: Clutter.ActorAlign.CENTER });
        this._battery.add_child(this._batteryIcon);
        this._battery.add_child(this._batteryLabel);
        header.add_child(this._battery);

        header.add_child(new St.Widget({ x_expand: true }));

        header.add_child(makeRoundButton('camera-photo-symbolic', 'Screenshot',
            () => this._screenshot()));
        header.add_child(makeRoundButton('insert-text-symbolic', 'Copy Text from Screen',
            () => this._copyScreenText()));
        this._recordButton = makeRoundButton('media-record-symbolic', 'Record Screen',
            () => this._record(), 'adaptive-cc-record-button');
        header.add_child(this._recordButton);
        this._settingsButton = makeRoundButton('emblem-system-symbolic', 'Settings',
            () => this._launchSettingsApp());
        header.add_child(this._settingsButton);
        this._lockButton = makeRoundButton('system-lock-screen-symbolic', 'Lock',
            () => {
                this._closeMenu();
                this._systemActions.activateLockScreen();
            });
        header.add_child(this._lockButton);
        this._powerButton = makeRoundButton('system-shutdown-symbolic', 'Power Off / Log Out',
            () => this._toggleDropdown('session'), 'adaptive-cc-power-button');
        header.add_child(this._powerButton);

        // Microphone and camera in use, when they are.
        page.add_child(this._buildPrivacy());

        // Tiles, two to a row. Grid rows alternate: tiles on even rows, and the
        // odd row under each pair is where that pair's dropdown opens.
        const grid = new St.Widget({
            style_class: 'adaptive-cc-tiles',
            layout_manager: new Clutter.GridLayout({
                column_homogeneous: true,
                column_spacing: 10,
                row_spacing: 10,
            }),
            x_expand: true,
        });
        page.add_child(grid);
        this._grid = grid;

        this._tiles = {
            wifi: new Tile({
                icon: 'network-wireless-symbolic',
                title: 'Wi-Fi',
                onToggle: () => this._toggleWifi(),
                onOpen: () => this._toggleDropdown('wifi'),
            }),
            bluetooth: new Tile({
                icon: 'bluetooth-active-symbolic',
                title: 'Bluetooth',
                onToggle: () => this._toggleBluetooth(),
                onOpen: () => this._toggleDropdown('bluetooth'),
            }),
            power: new Tile({
                icon: 'power-profile-balanced-symbolic',
                title: 'Power Mode',
                onOpen: () => this._toggleDropdown('power'),
            }),
            nightLight: new Tile({
                icon: 'night-light-symbolic',
                title: 'Night Light',
                onToggle: () => this._colorSettings.set_boolean('night-light-enabled',
                    !this._colorSettings.get_boolean('night-light-enabled')),
            }),
            dnd: new Tile({
                icon: 'notifications-disabled-symbolic',
                title: 'Do Not Disturb',
                onToggle: () => this._notifSettings.set_boolean('show-banners',
                    !this._notifSettings.get_boolean('show-banners')),
            }),
            airplane: new Tile({
                icon: 'airplane-mode-symbolic',
                title: 'Airplane Mode',
                onToggle: () => {
                    this._rfkill.airplaneMode = !this._rfkill.airplaneMode;
                },
            }),
            awake: new Tile({
                icon: 'view-reveal-symbolic',
                title: 'Keep Awake',
                onToggle: () => this._toggleInhibitor(),
            }),
            mic: new Tile({
                icon: 'microphone-sensitivity-high-symbolic',
                title: 'Microphone',
                onToggle: () => {
                    const source = this._mixer.get_default_source();
                    if (source)
                        source.change_is_muted(!source.is_muted);
                },
            }),
            tailscale: new Tile({
                icon: extensionIcon('tailscale-symbolic'),
                title: 'Tailscale',
                onToggle: () => this._toggleTailscale(),
                onOpen: () => this._toggleDropdown('tailscale'),
            }),
        };
        // Placed by _layoutTiles(), once their dropdowns exist.

        page.add_child(this._buildMediaCard());

        // Sliders.
        const sliders = new St.BoxLayout({
            style_class: 'adaptive-cc-sliders',
            vertical: true,
            x_expand: true,
        });
        page.add_child(sliders);
        this._slidersBox = sliders;

        this._volume = this._makeSliderRow('audio-volume-high-symbolic', {
            name: 'Volume',
            onIcon: () => {
                const sink = this._mixer.get_default_sink();
                if (sink)
                    sink.change_is_muted(!sink.is_muted);
            },
            onArrow: () => this._toggleDropdown('sound'),
            onChange: value => this._setVolume(value),
        });
        sliders.add_child(this._volume.row);

        this._brightness = this._makeSliderRow('display-brightness-symbolic', {
            name: 'Brightness',
            onArrow: () => this._toggleDropdown('display'),
            onChange: value => {
                const proxy = this._brightnessProxy();
                if (proxy)
                    proxy.Brightness = Math.round(value * 100);
            },
        });
        sliders.add_child(this._brightness.row);

        this._editButton = new St.Button({
            style_class: 'adaptive-cc-dropdown-link adaptive-cc-edit-link',
            label: 'Edit Controls…',
            can_focus: true,
            x_align: Clutter.ActorAlign.CENTER,
        });
        this._editButton.connect('clicked', () => this._toggleDropdown('edit'));
        page.add_child(this._editButton);
    }

    _makeSliderRow(iconName, { name, onIcon = null, onArrow = null, onChange }) {
        const row = new St.BoxLayout({ style_class: 'adaptive-cc-slider-row', x_expand: true });

        const icon = new St.Icon({
            icon_name: iconName,
            style_class: 'adaptive-cc-slider-icon',
            y_align: Clutter.ActorAlign.CENTER,
        });

        if (onIcon) {
            const button = new St.Button({
                style_class: 'adaptive-cc-slider-icon-button',
                child: icon,
                can_focus: true,
                accessible_name: `Mute ${name}`,
                y_align: Clutter.ActorAlign.CENTER,
            });
            button.connect('clicked', onIcon);
            row.add_child(button);
        } else {
            const holder = new St.Bin({
                style_class: 'adaptive-cc-slider-icon-button',
                child: icon,
                y_align: Clutter.ActorAlign.CENTER,
            });
            row.add_child(holder);
        }

        const slider = new Slider.Slider(0);
        slider.add_style_class_name('adaptive-cc-slider');
        slider.accessible_name = name;
        slider.y_align = Clutter.ActorAlign.CENTER;
        slider.connect('notify::value', () => {
            if (!this._syncingSliders)
                onChange(slider.value);
        });
        row.add_child(slider);

        if (onArrow) {
            const arrow = new St.Button({
                style_class: 'adaptive-cc-slider-arrow',
                can_focus: true,
                accessible_name: `${name} options`,
                child: new St.Icon({ icon_name: 'pan-down-symbolic' }),
                y_align: Clutter.ActorAlign.CENTER,
            });
            arrow.connect('clicked', onArrow);
            row.add_child(arrow);
            return { row, icon, slider, arrow };
        }

        return { row, icon, slider, arrow: null };
    }

    _setSlider(slider, value) {
        this._syncingSliders = true;
        try {
            slider.value = value;
        } finally {
            this._syncingSliders = false;
        }
    }

    _buildDropdown(name, { settings = null, link = null }) {
        const actor = new St.BoxLayout({
            style_class: 'adaptive-cc-dropdown',
            vertical: true,
            x_expand: true,
            visible: false,
            reactive: true,
            track_hover: true,
        });

        // Lists never reorder under the pointer (see _holdForPointer); what
        // arrived while it was over the list is applied once it leaves.
        actor.connect('notify::hover', () => {
            const page = this._pages[name];
            if (!actor.hover && page && page.stale) {
                page.stale = false;
                this._queueSync();
            }
        });

        const status = new St.Label({
            style_class: 'adaptive-cc-dropdown-status',
            x_expand: true,
            visible: false,
        });
        status.clutter_text.line_wrap = true;
        actor.add_child(status);

        const scroll = new St.ScrollView({
            style_class: 'adaptive-cc-scroll vfade',
            overlay_scrollbars: true,
            x_expand: true,
        });
        scroll.set_policy(St.PolicyType.NEVER, St.PolicyType.AUTOMATIC);
        actor.add_child(scroll);

        const list = new St.BoxLayout({
            style_class: 'adaptive-cc-list',
            vertical: true,
            x_expand: true,
        });
        scroll.add_actor(list);

        if (settings) {
            const [panel, label] = settings;
            const link = new St.Button({
                style_class: 'adaptive-cc-dropdown-link',
                can_focus: true,
                x_align: Clutter.ActorAlign.START,
                label: `${label}…`,
            });
            link.connect('clicked', () => this._openSettings(panel));
            actor.add_child(link);
        } else if (link) {
            const [label, onClick] = link;
            const button = new St.Button({
                style_class: 'adaptive-cc-dropdown-link',
                can_focus: true,
                x_align: Clutter.ActorAlign.START,
                label: `${label}…`,
            });
            button.connect('clicked', onClick);
            actor.add_child(button);
        }

        this._pages[name] = { actor, list, scroll, status };
        return actor;
    }

    // Scan results arrive every few seconds and re-sort the list. Applying
    // them while the pointer is over it moves rows under the cursor - a tap
    // meant for one network lands on another, and a saved one connects on
    // the spot. So, as on macOS, a list holds still while it is being
    // pointed at, and catches up when the pointer leaves.
    _holdForPointer(page) {
        if (page.actor.hover && page.list.get_n_children() > 0) {
            page.stale = true;
            return true;
        }
        return false;
    }

    // Background events (a volume tick, a network change) re-run every sync.
    // Rebuilding a list that shows the same thing destroys the button under a
    // click in progress and the tap is lost, so a list is rebuilt only when
    // what it shows has changed - or when forced, after the user's own action.
    _unchanged(page, signature, force) {
        if (!force && page.signature === signature && page.list.get_n_children() > 0)
            return true;
        page.signature = signature;
        return false;
    }

    // Replace a dropdown's rows, then size its scroll view to them.
    _fillPage(page, rows, statusText = '', maxHeight = LIST_MAX_HEIGHT) {
        page.list.destroy_all_children();
        for (const row of rows)
            page.list.add_child(row);

        page.status.text = statusText;
        page.status.visible = !!statusText;

        const [, natural] = page.list.get_preferred_height(-1);
        page.scroll.visible = rows.length > 0;
        page.scroll.set_height(Math.min(Math.max(natural, 0), maxHeight));
    }

    _toggleDropdown(name) {
        this._openDropdown(this._open === name ? null : name);
    }

    // One dropdown at a time, the way an accordion works: opening one closes
    // whichever was open. null closes them all.
    _openDropdown(name) {
        this._open = name && this._pages[name] ? name : null;

        for (const [key, page] of Object.entries(this._pages)) {
            const open = key === this._open;
            if (page.actor.visible !== open) {
                page.actor.remove_all_transitions();
                page.actor.visible = open;
                if (open) {
                    page.actor.opacity = 0;
                    page.actor.ease({
                        opacity: 255,
                        duration: DROPDOWN_FADE_MS,
                        mode: Clutter.AnimationMode.EASE_OUT_QUAD,
                    });
                }
            }
            this._setExpander(key, open);
        }

        this._wifiSignature = null;
        this._btSignature = null;
        for (const page of Object.values(this._pages))
            page.signature = null;
        if (this._open === 'wifi')
            this._startScanning();
        else
            this._stopScanning();

        // Forms belong to the dropdown they were opened in.
        if (this._wifiJoin && this._wifiJoin.stage === 'form')
            this._wifiJoin = null;
        if (this._open !== 'bluetooth')
            this._cancelPairing();
        if (this._open === 'bluetooth') {
            this._btScan.ran = false;
            this._startBtScan();
        } else {
            this._stopBtScan();
        }

        if (this._open === 'session')
            this._systemActions.forceUpdate();
        if (this._open === 'tailscale')
            this._tsRefresh();
        if (this._open !== 'wifi')
            this._wifiShare = null;
        this._soundSignature = null;

        this._syncPage();
    }

    // Whatever opened a dropdown shows that it is open.
    _setExpander(name, open) {
        if (this._tiles[name]) {
            this._tiles[name].setExpanded(open);
            return;
        }

        const button = {
            session: this._powerButton,
            sound: this._volume.arrow,
            display: this._brightness.arrow,
            edit: this._editButton,
        }[name];
        if (!button)
            return;

        if (open)
            button.add_style_pseudo_class('expanded');
        else
            button.remove_style_pseudo_class('expanded');

        if (name === 'sound' || name === 'display')
            button.child.icon_name = open ? 'pan-up-symbolic' : 'pan-down-symbolic';
    }

    // ---------------------------------------------------------- lifecycle

    _onOpen() {
        if (!this._showingOurs)
            return;

        this._connectLive();
        this._openDropdown(null);
        this._startMpris();
        this._startCameraPolling();
        this._tsRefresh();
        this._syncAll();
    }

    _onClose() {
        this._dropLive();
        this._stopScanning();
        this._stopBtScan();
        this._stopMpris();
        this._stopCameraPolling();
        this._wifiShare = null;

        // Nobody can answer a pairing prompt in a closed panel.
        this._cancelPairing();
        if (this._wifiJoin && this._wifiJoin.stage === 'form')
            this._wifiJoin = null;
        this._wifiErrors.clear();
        this._btErrors.clear();

        if (this._syncId) {
            GLib.Source.remove(this._syncId);
            this._syncId = 0;
        }
    }

    _listen(obj, signal, callback) {
        if (!obj)
            return;
        try {
            const id = obj.connect(signal, callback);
            this._live.push([obj, id]);
        } catch (e) {
            // A signal a given GNOME build does not have is not fatal.
        }
    }

    _connectLive() {
        this._dropLive();
        const queue = () => this._queueSync();

        this._listen(this._mixer, 'default-sink-changed', () => this._watchStreams());
        this._listen(this._mixer, 'default-source-changed', () => this._watchStreams());
        this._listen(this._mixer, 'stream-added', queue);
        this._listen(this._mixer, 'stream-removed', queue);
        this._watchStreams();

        this._listen(this._brightnessProxy(), 'g-properties-changed', queue);
        this._listen(this._batteryProxy(), 'g-properties-changed', queue);
        this._listen(this._profilesProxy(), 'g-properties-changed', queue);
        this._listen(this._colorSettings, 'changed::night-light-enabled', queue);
        this._listen(this._notifSettings, 'changed::show-banners', queue);
        this._listen(this._rfkill, 'airplane-mode-changed', queue);

        const client = this._nmClient();
        if (client) {
            for (const signal of [
                'notify::wireless-enabled', 'notify::primary-connection',
                'notify::active-connections', 'device-added', 'device-removed',
            ])
                this._listen(client, signal, queue);
        }

        this._listen(Main.layoutManager, 'monitors-changed', queue);
        if (client) {
            for (const device of client.get_devices()) {
                if (device.get_device_type() === NM.DeviceType.ETHERNET)
                    this._listen(device, 'state-changed', queue);
            }
        }

        const wifi = this._wifiDevice();
        if (wifi) {
            for (const signal of [
                'notify::active-access-point', 'state-changed',
                'access-point-added', 'access-point-removed',
            ])
                this._listen(wifi, signal, queue);
        }

        const bt = this._btClient();
        if (bt) {
            for (const signal of [
                'notify::default-adapter-powered', 'notify::default-adapter',
                'device-added', 'device-removed',
            ])
                this._listen(bt, signal, queue);

            for (const device of this._btDevices())
                this._listen(device, 'notify::connected', queue);
        }
    }

    _dropLive() {
        for (const [obj, id] of [...this._live, ...this._streamLive]) {
            try {
                obj.disconnect(id);
            } catch (e) {
                // Already gone with its object.
            }
        }
        this._live = [];
        this._streamLive = [];
    }

    // The default sink and source change identity when the output device
    // does, so their signals are re-wired rather than connected once.
    _watchStreams() {
        for (const [obj, id] of this._streamLive) {
            try {
                obj.disconnect(id);
            } catch (e) {
            }
        }
        this._streamLive = [];

        const queue = () => this._queueSync();
        for (const stream of [this._mixer.get_default_sink(), this._mixer.get_default_source()]) {
            if (!stream)
                continue;
            for (const signal of ['notify::volume', 'notify::is-muted']) {
                try {
                    this._streamLive.push([stream, stream.connect(signal, queue)]);
                } catch (e) {
                }
            }
        }
        this._queueSync();
    }

    _queueSync() {
        if (this._syncId)
            return;
        this._syncId = GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
            this._syncId = 0;
            this._syncAll();
            return GLib.SOURCE_REMOVE;
        });
    }

    _syncAll() {
        for (const part of [
            () => this._syncHeader(),
            () => this._syncTiles(),
            () => this._syncSliders(),
            () => this._syncMedia(),
            () => this._syncPrivacy(),
            () => this._syncPage(),
        ]) {
            try {
                part();
            } catch (e) {
                logError(e, '[Adaptive Control Center] sync');
            }
        }
    }

    // ------------------------------------------------------------ sources

    _nmClient() {
        return (NM && this._agg && this._agg._network && this._agg._network._client) || null;
    }

    _wifiDevice() {
        const client = this._nmClient();
        if (!client)
            return null;
        return client.get_devices().find(d =>
            d.get_device_type() === NM.DeviceType.WIFI && d.get_managed()) || null;
    }

    _btClient() {
        const bt = this._agg && this._agg._bluetooth;
        return (bt && bt._client) || null;
    }

    _btDevices() {
        const client = this._btClient();
        if (!client)
            return [];
        const store = client.get_devices();
        const devices = [];
        for (let i = 0; i < store.get_n_items(); i++) {
            const device = store.get_item(i);
            if (device.paired || device.trusted)
                devices.push(device);
        }
        return devices;
    }

    _brightnessProxy() {
        const b = this._agg && this._agg._brightness;
        return (b && b._proxy) || null;
    }

    _batteryProxy() {
        const p = this._agg && this._agg._power;
        return (p && p._proxy) || null;
    }

    _profilesProxy() {
        const p = this._agg && this._agg._powerProfiles;
        const proxy = p && p._proxy;
        return proxy && proxy.g_name_owner ? proxy : null;
    }

    // ------------------------------------------------------------- header

    _syncHeader() {
        const proxy = this._batteryProxy();
        const present = proxy && proxy.IsPresent;
        this._battery.visible = !!present;
        if (present) {
            let text = `${Math.round(proxy.Percentage)}%`;
            if (proxy.State === BATTERY_CHARGING)
                text += ' · Charging';
            else if (proxy.State === BATTERY_FULL)
                text += ' · Full';
            this._batteryLabel.text = text;
            this._batteryIcon.icon_name = proxy.IconName || 'battery-symbolic';
        }

        this._lockButton.visible = this._systemActions.can_lock_screen;

        const recording = !!(Main.screenshotUI && Main.screenshotUI.screencast_in_progress);
        if (recording)
            this._recordButton.add_style_pseudo_class('checked');
        else
            this._recordButton.remove_style_pseudo_class('checked');
        this._recordButton.accessible_name = recording ? 'Stop Recording' : 'Record Screen';
        this._settingsButton.visible = Main.sessionMode.allowSettings;
    }

    _screenshot() {
        this._closeMenu();
        try {
            if (Main.screenshotUI)
                Main.screenshotUI.open();
            else
                Util.spawn(['gnome-screenshot', '-i']);
        } catch (e) {
            logError(e, '[Adaptive Control Center] screenshot');
        }
    }

    // Set by the extension once the screen text service is up (screenText.js).
    _copyScreenText() {
        this._closeMenu();
        if (this.screenText)
            this.screenText.start();
        else
            Main.notify('Copy text from screen', 'Text recognition is not available');
    }

    _launchSettingsApp() {
        this._closeMenu();
        Main.overview.hide();
        const app = Shell.AppSystem.get_default().lookup_app('gnome-control-center.desktop');
        if (app)
            app.activate();
    }

    // -------------------------------------------------------------- tiles

    _syncTiles() {
        this._syncWifiTile();
        this._syncBluetoothTile();
        this._syncPowerTile();
        this._syncTailscaleTile();

        const night = this._colorSettings.get_boolean('night-light-enabled');
        this._tiles.nightLight.update({ active: night, subtitle: night ? 'On' : 'Off' });

        const quiet = !this._notifSettings.get_boolean('show-banners');
        this._tiles.dnd.update({
            active: quiet,
            subtitle: quiet ? 'Silenced' : 'Off',
            icon: quiet ? 'notifications-disabled-symbolic'
                : 'preferences-system-notifications-symbolic',
        });

        const airplane = this._rfkill.airplaneMode;
        this._tiles.airplane.update({
            active: airplane,
            subtitle: this._rfkill.hwAirplaneMode ? 'Hardware switch'
                : airplane ? 'On' : 'Off',
            sensitive: !this._rfkill.hwAirplaneMode,
        });

        const awake = this._inhibitCookie > 0;
        this._tiles.awake.update({
            active: awake,
            subtitle: this._inhibitPending ? '…' : awake ? 'Screen stays on' : 'Off',
            icon: awake ? 'view-reveal-symbolic' : 'view-conceal-symbolic',
        });

        const source = this._mixer.get_default_source();
        this._tiles.mic.update({
            active: !!source && !source.is_muted,
            subtitle: !source ? 'No microphone' : source.is_muted ? 'Muted' : 'Live',
            icon: source && !source.is_muted ? 'microphone-sensitivity-high-symbolic'
                : 'microphone-sensitivity-muted-symbolic',
            sensitive: !!source,
        });
    }

    _syncWifiTile() {
        const client = this._nmClient();
        const device = this._wifiDevice();

        if (!client || !device) {
            this._tiles.wifi.update({
                subtitle: 'Unavailable',
                icon: 'network-wireless-disabled-symbolic',
                sensitive: false,
            });
            return;
        }

        const enabled = client.wireless_enabled && !this._rfkill.airplaneMode;
        const ap = device.active_access_point;
        const state = device.get_state();
        let subtitle, icon;

        if (!enabled) {
            subtitle = 'Off';
            icon = 'network-wireless-disabled-symbolic';
        } else if (state > NM.DeviceState.DISCONNECTED && state < NM.DeviceState.ACTIVATED) {
            subtitle = 'Connecting…';
            icon = 'network-wireless-acquiring-symbolic';
        } else if (ap && state === NM.DeviceState.ACTIVATED) {
            subtitle = ssidName(ap.get_ssid()) || 'Connected';
            icon = `network-wireless-signal-${signalLevel(ap.strength)}-symbolic`;
        } else {
            subtitle = 'Not connected';
            icon = 'network-wireless-offline-symbolic';
        }

        this._tiles.wifi.update({ active: enabled, subtitle, icon });
    }

    _syncBluetoothTile() {
        const client = this._btClient();
        if (!client || !client.default_adapter) {
            this._tiles.bluetooth.update({
                subtitle: 'Unavailable',
                icon: 'bluetooth-disabled-symbolic',
                sensitive: false,
            });
            return;
        }

        const powered = client.default_adapter_powered;
        const connected = this._btDevices().filter(d => d.connected);
        let subtitle = powered ? 'On' : 'Off';
        if (powered && connected.length === 1)
            subtitle = connected[0].alias;
        else if (powered && connected.length > 1)
            subtitle = `${connected.length} connected`;

        this._tiles.bluetooth.update({
            active: powered,
            subtitle,
            icon: powered ? 'bluetooth-active-symbolic' : 'bluetooth-disabled-symbolic',
        });
    }

    _syncPowerTile() {
        const proxy = this._profilesProxy();
        if (!proxy) {
            this._tiles.power.update({ subtitle: 'Unavailable', sensitive: false });
            return;
        }

        const profile = PROFILES[proxy.ActiveProfile] || PROFILES.balanced;
        this._tiles.power.update({
            active: proxy.ActiveProfile !== 'balanced',
            subtitle: profile.label,
            icon: profileIcon(profile.icon),
        });
    }

    // ------------------------------------------------------------ sliders

    _syncSliders() {
        const sink = this._mixer.get_default_sink();
        this._volume.row.visible = !!sink;
        if (sink) {
            const fraction = sink.is_muted
                ? 0 : sink.volume / this._mixer.get_vol_max_norm();
            this._setSlider(this._volume.slider, Math.min(fraction, 1));
            this._volume.icon.icon_name = volumeIcon(fraction, sink.is_muted);
        }

        const proxy = this._brightnessProxy();
        const level = proxy ? proxy.Brightness : -1;
        const hasBrightness = Number.isFinite(level) && level >= 0;
        this._brightness.row.visible = hasBrightness;
        if (hasBrightness)
            this._setSlider(this._brightness.slider, level / 100);
    }

    _setVolume(value) {
        const sink = this._mixer.get_default_sink();
        if (!sink)
            return;

        const volume = value * this._mixer.get_vol_max_norm();
        if (volume < 1) {
            sink.volume = 0;
            if (!sink.is_muted)
                sink.change_is_muted(true);
        } else {
            sink.volume = volume;
            if (sink.is_muted)
                sink.change_is_muted(false);
        }
        sink.push_volume();
        this._volume.icon.icon_name = volumeIcon(value, sink.is_muted);
    }

    // -------------------------------------------------------------- pages

    _syncPage() {
        switch (this._open) {
        case 'wifi':
            this._syncWifiPage();
            break;
        case 'bluetooth':
            this._syncBluetoothPage();
            break;
        case 'power':
            this._syncPowerPage();
            break;
        case 'sound':
            this._syncSoundPage();
            break;
        case 'session':
            this._syncSessionPage();
            break;
        case 'tailscale':
            this._syncTailscalePage();
            break;
        case 'display':
            this._syncDisplayPage();
            break;
        case 'edit':
            this._syncEditPage();
            break;
        }
    }
};

// The Control Center is one object, but its code is kept by subject. Each part
// is a class whose methods are copied onto ControlCenter here, so `this` is
// the same object in all of them.
for (const part of [
    CcNetwork.CcNetwork,
    CcBluetooth.CcBluetooth,
    CcMedia.CcMedia,
    CcSystem.CcSystem,
]) {
    for (const name of Object.getOwnPropertyNames(part.prototype)) {
        if (name !== 'constructor') {
            Object.defineProperty(ControlCenter.prototype, name,
                Object.getOwnPropertyDescriptor(part.prototype, name));
        }
    }
}
