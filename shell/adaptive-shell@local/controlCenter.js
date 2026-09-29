// Adaptive Control Center v1
//
// GNOME 42's system menu - the "aggregate menu" at the right of the top bar -
// rebuilt as an Android/iOS-style control center: tiles for the things people
// switch, sliders for the things they set, and drill-down pages for Wi-Fi
// networks, Bluetooth devices, power mode, sound output and the session, so
// none of the everyday changes needs a trip into Settings.
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

// NetworkManager is optional at build time in GNOME; without it the Wi-Fi
// tile just reports itself unavailable.
let NM = null;
try {
    NM = imports.gi.NM;
} catch (e) {
    NM = null;
}

// Tallest a drill-down list grows before it scrolls.
const LIST_MAX_HEIGHT = 320;
const WIFI_SCAN_INTERVAL_S = 15;
const MAX_NETWORKS = 24;

// org.gnome.SessionManager.Inhibit flags: suspend | idle.
const INHIBIT_SUSPEND_AND_IDLE = 4 | 8;

const PROFILES = {
    'performance': {
        label: 'Performance',
        icon: 'power-profile-performance-symbolic',
    },
    'balanced': {
        label: 'Balanced',
        icon: 'power-profile-balanced-symbolic',
    },
    'power-saver': {
        label: 'Power Saver',
        icon: 'power-profile-power-saver-symbolic',
    },
};

// Yaru draws the power-profile icons in fixed red/green, which no stylesheet
// can recolour. Adwaita's are plain symbolic outlines, so those are used when
// installed, as file icons (a -symbolic.svg file still takes the text colour).
function profileIcon(name) {
    const path = `/usr/share/icons/Adwaita/scalable/status/${name}.svg`;
    if (GLib.file_test(path, GLib.FileTest.EXISTS))
        return new Gio.FileIcon({ file: Gio.File.new_for_path(path) });
    return name;
}

function iconProps(icon) {
    return typeof icon === 'string' ? { icon_name: icon } : { gicon: icon };
}

// UPower.DeviceState
const BATTERY_CHARGING = 1;
const BATTERY_FULL = 4;

function signalLevel(strength) {
    if (strength < 20)
        return 'none';
    if (strength < 40)
        return 'weak';
    if (strength < 50)
        return 'ok';
    if (strength < 80)
        return 'good';
    return 'excellent';
}

function ssidName(ssid) {
    if (!ssid || !NM)
        return null;
    return NM.utils_ssid_to_utf8(ssid.get_data()) || null;
}

function apSecured(ap) {
    const F = NM['80211ApSecurityFlags'];
    return ap.rsn_flags !== F.NONE ||
        ap.wpa_flags !== F.NONE ||
        !!(ap.flags & NM['80211ApFlags'].PRIVACY);
}

// 802.1x networks need a certificate/identity form that only Settings has.
function apEnterprise(ap) {
    const F = NM['80211ApSecurityFlags'];
    return !!((ap.rsn_flags | ap.wpa_flags) & F.KEY_MGMT_802_1X);
}

function volumeIcon(fraction, muted) {
    if (muted || fraction <= 0)
        return 'audio-volume-muted-symbolic';
    if (fraction < 0.34)
        return 'audio-volume-low-symbolic';
    if (fraction < 0.67)
        return 'audio-volume-medium-symbolic';
    return 'audio-volume-high-symbolic';
}

// PulseAudio names an output after its driver ("sof-hda-dsp HDMI / DisplayPort
// 1 Output"). The UI device behind it knows the port ("HDMI / DisplayPort 1
// Output") and where it lives, which is what a person picks between.
function describeSink(control, sink) {
    let port = null;
    let origin = null;
    try {
        const device = control.lookup_device_from_stream(sink);
        if (device) {
            port = device.get_description();
            origin = device.get_origin();
        }
    } catch (e) {
        // No UI device: fall back to the stream's own description.
    }

    const title = (port || sink.get_description() || sink.get_name() || 'Output')
        .replace(/ Output$/, '');

    // A bare driver id is not a place; say where it is instead.
    if (!origin || /^[a-z0-9_-]+$/.test(origin))
        origin = 'Built-in Audio';

    const text = `${title} ${sink.get_description() || ''}`;
    let icon = 'audio-speakers-symbolic';
    if (/HDMI|DisplayPort/i.test(text))
        icon = 'video-display-symbolic';
    else if (/head(phone|set)|bluez|buds|airpod/i.test(text) || /headset|headphone/.test(sink.get_icon_name() || ''))
        icon = 'audio-headphones-symbolic';

    return { title, subtitle: origin, icon };
}

// ------------------------------------------------------------------ widgets

// A GNOME toggle-switch drawn by the Adaptive SVGs, in a focusable button.
function makeSwitch() {
    const knob = new St.Bin({
        style_class: 'toggle-switch',
        y_align: Clutter.ActorAlign.CENTER,
    });
    const button = new St.Button({
        style_class: 'adaptive-cc-switch-button',
        child: knob,
        can_focus: true,
        y_align: Clutter.ActorAlign.CENTER,
    });
    button.setChecked = on => {
        if (on)
            knob.add_style_pseudo_class('checked');
        else
            knob.remove_style_pseudo_class('checked');
    };
    return button;
}

function makeRoundButton(iconName, accessibleName, onClick, extraClass = '') {
    const button = new St.Button({
        style_class: `adaptive-cc-round-button ${extraClass}`.trim(),
        can_focus: true,
        accessible_name: accessibleName,
        child: new St.Icon({ icon_name: iconName }),
        y_align: Clutter.ActorAlign.CENTER,
    });
    button.connect('clicked', onClick);
    return button;
}

// One line in a drill-down list: icon, title and subtitle, trailing icons,
// and optionally a trailing action button.
function makeRow({
    icon = null, title, subtitle = '', trailing = [], action = null,
    active = false, danger = false, onActivate = null,
}) {
    const button = new St.Button({
        style_class: danger ? 'adaptive-cc-row adaptive-cc-row-danger' : 'adaptive-cc-row',
        can_focus: !!onActivate,
        reactive: !!onActivate || !!action,
        x_expand: true,
    });
    if (active)
        button.add_style_pseudo_class('checked');

    const box = new St.BoxLayout({ style_class: 'adaptive-cc-row-box', x_expand: true });
    button.set_child(box);

    if (icon) {
        box.add_child(new St.Icon({
            ...iconProps(icon),
            style_class: 'adaptive-cc-row-icon',
            y_align: Clutter.ActorAlign.CENTER,
        }));
    }

    const text = new St.BoxLayout({
        vertical: true,
        x_expand: true,
        y_align: Clutter.ActorAlign.CENTER,
    });
    box.add_child(text);
    text.add_child(new St.Label({ text: title, style_class: 'adaptive-cc-row-title' }));
    if (subtitle) {
        text.add_child(new St.Label({
            text: subtitle,
            style_class: 'adaptive-cc-row-subtitle',
        }));
    }

    for (const name of trailing) {
        box.add_child(new St.Icon({
            icon_name: name,
            style_class: name === 'object-select-symbolic'
                ? 'adaptive-cc-row-check' : 'adaptive-cc-row-trailing',
            y_align: Clutter.ActorAlign.CENTER,
        }));
    }

    if (action) {
        const pill = new St.Button({
            style_class: 'adaptive-cc-pill-button',
            label: action.label,
            can_focus: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        pill.connect('clicked', action.onClick);
        box.add_child(pill);
    }

    if (onActivate)
        button.connect('clicked', onActivate);

    return button;
}

// A quick-settings tile. Tapping the body toggles when the tile has a toggle
// and opens its page otherwise; a tile with both gets a separate arrow for the
// page, the way Android splits the two.
var Tile = class Tile {
    constructor({ icon, title, onToggle = null, onOpen = null }) {
        this.actor = new St.BoxLayout({
            style_class: 'adaptive-cc-tile',
            x_expand: true,
        });

        this._main = new St.Button({
            style_class: 'adaptive-cc-tile-main',
            can_focus: true,
            x_expand: true,
            accessible_name: title,
        });
        this.actor.add_child(this._main);

        const box = new St.BoxLayout({ style_class: 'adaptive-cc-tile-box', x_expand: true });
        this._main.set_child(box);

        this._icon = new St.Icon({
            icon_name: icon,
            style_class: 'adaptive-cc-tile-icon',
            y_align: Clutter.ActorAlign.CENTER,
        });
        box.add_child(this._icon);

        const text = new St.BoxLayout({
            vertical: true,
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        box.add_child(text);

        text.add_child(new St.Label({ text: title, style_class: 'adaptive-cc-tile-title' }));
        this._subtitle = new St.Label({ text: '', style_class: 'adaptive-cc-tile-subtitle' });
        text.add_child(this._subtitle);

        this._main.connect('clicked', () => (onToggle || onOpen)?.());

        this._arrow = null;
        if (onOpen) {
            const chevron = new St.Icon({
                icon_name: 'go-next-symbolic',
                style_class: 'adaptive-cc-tile-chevron',
                y_align: Clutter.ActorAlign.CENTER,
            });

            if (onToggle) {
                this._arrow = new St.Button({
                    style_class: 'adaptive-cc-tile-arrow',
                    can_focus: true,
                    accessible_name: `${title} options`,
                    child: chevron,
                    y_expand: true,
                });
                this._arrow.connect('clicked', () => onOpen());
                this.actor.add_child(this._arrow);
            } else {
                box.add_child(chevron);
            }
        }
    }

    update({ active = false, subtitle = '', icon = null, sensitive = true }) {
        if (active)
            this.actor.add_style_pseudo_class('checked');
        else
            this.actor.remove_style_pseudo_class('checked');

        if (sensitive)
            this.actor.remove_style_pseudo_class('insensitive');
        else
            this.actor.add_style_pseudo_class('insensitive');

        this._main.reactive = sensitive;
        if (this._arrow)
            this._arrow.reactive = sensitive;

        this._subtitle.text = subtitle;
        if (icon)
            this._icon.set(iconProps(icon));
    }
};

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
        this._page = 'main';
        this._pages = {};
        this._syncingSliders = false;
        this._inhibitCookie = 0;
        this._inhibitPending = false;
        this._btPending = new Set();
        this._attached = false;
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

        this._stack = new St.Widget({
            layout_manager: new Clutter.BinLayout(),
            x_expand: true,
        });
        this._root.add_child(this._stack);

        this._buildMainPage();

        this._buildPage('wifi', 'Wi-Fi', {
            onToggle: () => this._toggleWifi(),
            settings: ['wifi', 'Network settings'],
        });
        this._buildPage('bluetooth', 'Bluetooth', {
            onToggle: () => this._toggleBluetooth(),
            settings: ['bluetooth', 'Bluetooth settings'],
        });
        this._buildPage('power', 'Power Mode', {
            settings: ['power', 'Power settings'],
        });
        this._buildPage('sound', 'Sound Output', {
            settings: ['sound', 'Sound settings'],
        });
        this._buildPage('session', 'Power', {});
    }

    _buildMainPage() {
        const page = new St.BoxLayout({
            style_class: 'adaptive-cc-main',
            vertical: true,
            x_expand: true,
        });
        this._stack.add_child(page);
        this._pages.main = { actor: page };

        // Header: battery on the left, session actions on the right.
        const header = new St.BoxLayout({ style_class: 'adaptive-cc-header', x_expand: true });
        page.add_child(header);

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
        this._settingsButton = makeRoundButton('emblem-system-symbolic', 'Settings',
            () => this._launchSettingsApp());
        header.add_child(this._settingsButton);
        this._lockButton = makeRoundButton('system-lock-screen-symbolic', 'Lock',
            () => {
                this._closeMenu();
                this._systemActions.activateLockScreen();
            });
        header.add_child(this._lockButton);
        header.add_child(makeRoundButton('system-shutdown-symbolic', 'Power Off / Log Out',
            () => this._showPage('session'), 'adaptive-cc-power-button'));

        // Tiles, two to a row.
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

        this._tiles = {
            wifi: new Tile({
                icon: 'network-wireless-symbolic',
                title: 'Wi-Fi',
                onToggle: () => this._toggleWifi(),
                onOpen: () => this._showPage('wifi'),
            }),
            bluetooth: new Tile({
                icon: 'bluetooth-active-symbolic',
                title: 'Bluetooth',
                onToggle: () => this._toggleBluetooth(),
                onOpen: () => this._showPage('bluetooth'),
            }),
            power: new Tile({
                icon: 'power-profile-balanced-symbolic',
                title: 'Power Mode',
                onOpen: () => this._showPage('power'),
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
        };

        Object.values(this._tiles).forEach((tile, i) => {
            grid.layout_manager.attach(tile.actor, i % 2, Math.floor(i / 2), 1, 1);
        });

        // Sliders.
        const sliders = new St.BoxLayout({
            style_class: 'adaptive-cc-sliders',
            vertical: true,
            x_expand: true,
        });
        page.add_child(sliders);

        this._volume = this._makeSliderRow('audio-volume-high-symbolic', {
            name: 'Volume',
            onIcon: () => {
                const sink = this._mixer.get_default_sink();
                if (sink)
                    sink.change_is_muted(!sink.is_muted);
            },
            onArrow: () => this._showPage('sound'),
            onChange: value => this._setVolume(value),
        });
        sliders.add_child(this._volume.row);

        this._brightness = this._makeSliderRow('display-brightness-symbolic', {
            name: 'Brightness',
            onChange: value => {
                const proxy = this._brightnessProxy();
                if (proxy)
                    proxy.Brightness = Math.round(value * 100);
            },
        });
        sliders.add_child(this._brightness.row);
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
                accessible_name: `${name} output`,
                child: new St.Icon({ icon_name: 'go-next-symbolic' }),
                y_align: Clutter.ActorAlign.CENTER,
            });
            arrow.connect('clicked', onArrow);
            row.add_child(arrow);
        }

        return { row, icon, slider };
    }

    _setSlider(slider, value) {
        this._syncingSliders = true;
        try {
            slider.value = value;
        } finally {
            this._syncingSliders = false;
        }
    }

    _buildPage(name, title, { onToggle = null, settings = null }) {
        const actor = new St.BoxLayout({
            style_class: 'adaptive-cc-page',
            vertical: true,
            x_expand: true,
            visible: false,
        });
        this._stack.add_child(actor);

        const header = new St.BoxLayout({ style_class: 'adaptive-cc-page-header', x_expand: true });
        actor.add_child(header);

        header.add_child(makeRoundButton('go-previous-symbolic', 'Back',
            () => this._showPage('main')));
        header.add_child(new St.Label({
            text: title,
            style_class: 'adaptive-cc-page-title',
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        }));

        let toggle = null;
        if (onToggle) {
            toggle = makeSwitch();
            toggle.accessible_name = title;
            toggle.connect('clicked', onToggle);
            header.add_child(toggle);
        }

        const status = new St.Label({
            style_class: 'adaptive-cc-page-status',
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
            const footer = new St.Button({
                style_class: 'adaptive-cc-footer',
                can_focus: true,
                x_expand: true,
                label,
            });
            footer.connect('clicked', () => this._openSettings(panel));
            actor.add_child(footer);
        }

        this._pages[name] = { actor, list, scroll, toggle, status };
    }

    // Replace a page's rows, then size its scroll view to them.
    _fillPage(page, rows, statusText = '') {
        page.list.destroy_all_children();
        for (const row of rows)
            page.list.add_child(row);

        page.status.text = statusText;
        page.status.visible = !!statusText;

        const [, natural] = page.list.get_preferred_height(-1);
        page.scroll.visible = rows.length > 0;
        page.scroll.set_height(Math.min(Math.max(natural, 0), LIST_MAX_HEIGHT));
    }

    _showPage(name) {
        if (!this._pages[name])
            return;

        this._page = name;
        for (const [key, page] of Object.entries(this._pages))
            page.actor.visible = key === name;

        this._wifiSignature = null;
        if (name === 'wifi')
            this._startScanning();
        else
            this._stopScanning();

        if (name === 'session')
            this._systemActions.forceUpdate();

        this._syncPage();

        // Keyboard users land on the page, not on the now-hidden tile.
        const target = this._pages[name].actor;
        if (this._menu && this._menu.isOpen)
            target.navigate_focus(null, St.DirectionType.TAB_FORWARD, false);
    }

    // ---------------------------------------------------------- lifecycle

    _onOpen() {
        if (!this._showingOurs)
            return;

        this._connectLive();
        this._showPage('main');
        this._syncAll();
    }

    _onClose() {
        this._dropLive();
        this._stopScanning();

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
        switch (this._page) {
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
        }
    }

    // --- Wi-Fi

    _toggleWifi() {
        const client = this._nmClient();
        if (!client)
            return;

        if (this._rfkill.airplaneMode) {
            this._rfkill.airplaneMode = false;
            client.wireless_enabled = true;
        } else {
            client.wireless_enabled = !client.wireless_enabled;
        }
    }

    _startScanning() {
        this._stopScanning();
        const scan = () => {
            const device = this._wifiDevice();
            if (device) {
                try {
                    device.request_scan_async(null, null);
                } catch (e) {
                    // NetworkManager refuses scans in quick succession.
                }
            }
            return GLib.SOURCE_CONTINUE;
        };
        scan();
        this._scanId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT,
            WIFI_SCAN_INTERVAL_S, scan);
    }

    _stopScanning() {
        if (this._scanId) {
            GLib.Source.remove(this._scanId);
            this._scanId = 0;
        }
    }

    // Access points grouped by name, strongest first within a name; the
    // connected one leads, then saved networks, then by signal.
    _wifiNetworks(client, device) {
        const saved = client.get_connections().filter(c => device.connection_valid(c));
        const byName = new Map();

        for (const ap of device.get_access_points() || []) {
            const name = ssidName(ap.get_ssid());
            if (!name)
                continue;

            let network = byName.get(name);
            if (!network) {
                network = { name, ap, connections: [] };
                byName.set(name, network);
            } else if (ap.strength > network.ap.strength) {
                network.ap = ap;
            }

            for (const connection of saved) {
                if (ap.connection_valid(connection) &&
                    !network.connections.includes(connection))
                    network.connections.push(connection);
            }
        }

        const activeName = device.active_access_point
            ? ssidName(device.active_access_point.get_ssid()) : null;

        // Sorted by signal *band*, then name: raw strength flickers by a few
        // points every scan, and sorting on it reshuffled the list under the
        // pointer.
        const band = n => ['none', 'weak', 'ok', 'good', 'excellent']
            .indexOf(signalLevel(n.ap.strength));

        return [...byName.values()]
            .map(n => Object.assign(n, { active: n.name === activeName }))
            .sort((a, b) =>
                (b.active - a.active) ||
                ((b.connections.length > 0) - (a.connections.length > 0)) ||
                (band(b) - band(a)) ||
                GLib.utf8_collate(a.name, b.name))
            .slice(0, MAX_NETWORKS);
    }

    _syncWifiPage() {
        const page = this._pages.wifi;
        const client = this._nmClient();
        const device = this._wifiDevice();

        if (!client || !device) {
            page.toggle.visible = false;
            this._fillPage(page, [], 'No Wi-Fi adapter was found.');
            return;
        }

        const enabled = client.wireless_enabled && !this._rfkill.airplaneMode;
        page.toggle.visible = true;
        page.toggle.setChecked(enabled);

        if (this._rfkill.airplaneMode) {
            this._fillPage(page, [], 'Airplane mode is on. Turn Wi-Fi on to leave it.');
            return;
        }
        if (!enabled) {
            this._fillPage(page, [], 'Wi-Fi is off.');
            return;
        }

        const state = device.get_state();
        const connecting = state > NM.DeviceState.DISCONNECTED &&
            state < NM.DeviceState.ACTIVATED;
        const networks = this._wifiNetworks(client, device);

        // A scan fires a burst of access-point signals that mostly change
        // nothing on screen. Rebuilding the rows anyway reset hover and
        // scrolling several times a second, so only rebuild on a visible
        // difference.
        const signature = networks.map(n => [
            n.name, n.active, n.connections.length > 0,
            signalLevel(n.ap.strength), apSecured(n.ap),
        ].join('|')).join('\n') + `|${connecting}`;
        if (signature === this._wifiSignature && page.list.get_n_children() > 0)
            return;
        this._wifiSignature = signature;

        const rows = networks.map(network => {
            const secured = apSecured(network.ap);
            let subtitle = '';
            if (network.active)
                subtitle = connecting ? 'Connecting…' : 'Connected';
            else if (network.connections.length > 0)
                subtitle = 'Saved';
            else if (apEnterprise(network.ap))
                subtitle = 'Enterprise · opens Settings';

            const trailing = [];
            if (secured)
                trailing.push('network-wireless-encrypted-symbolic');
            if (network.active && !connecting)
                trailing.push('object-select-symbolic');

            return makeRow({
                icon: `network-wireless-signal-${signalLevel(network.ap.strength)}-symbolic`,
                title: network.name,
                subtitle,
                trailing,
                active: network.active,
                action: network.active ? {
                    label: 'Disconnect',
                    onClick: () => this._disconnectWifi(device),
                } : null,
                onActivate: network.active ? null : () => this._connectWifi(network),
            });
        });

        this._fillPage(page, rows, rows.length ? '' : 'Searching for networks…');
    }

    _connectWifi(network) {
        const client = this._nmClient();
        const device = this._wifiDevice();
        if (!client || !device)
            return;

        try {
            if (network.connections.length > 0) {
                client.activate_connection_async(network.connections[0], device,
                    null, null, null);
                return;
            }

            if (apEnterprise(network.ap)) {
                const devicePath = NM.Object.prototype.get_path.call(device);
                this._closeMenu();
                Util.spawn(['gnome-control-center', 'wifi', 'connect-8021x-wifi',
                    devicePath, network.ap.get_path()]);
                return;
            }

            // A new secured network needs its password, which GNOME's network
            // agent asks for in a dialog of its own. The menu is closed first
            // so the dialog is not fighting it for the pointer.
            if (apSecured(network.ap))
                this._closeMenu();

            client.add_and_activate_connection_async(new NM.SimpleConnection(),
                device, network.ap.get_path(), null, null);
        } catch (e) {
            logError(e, `[Adaptive Control Center] connecting to ${network.name}`);
        }
    }

    _disconnectWifi(device) {
        try {
            device.disconnect_async(null, null);
        } catch (e) {
            logError(e, '[Adaptive Control Center] disconnecting Wi-Fi');
        }
    }

    // --- Bluetooth

    _toggleBluetooth() {
        const bt = this._agg && this._agg._bluetooth;
        const client = this._btClient();
        if (!client || !bt)
            return;

        // The same two steps GNOME's own Bluetooth menu takes.
        if (!client.default_adapter_powered) {
            if (bt._proxy)
                bt._proxy.BluetoothAirplaneMode = false;
            client.default_adapter_powered = true;
        } else if (bt._proxy) {
            bt._proxy.BluetoothAirplaneMode = true;
        } else {
            client.default_adapter_powered = false;
        }
    }

    _syncBluetoothPage() {
        const page = this._pages.bluetooth;
        const client = this._btClient();

        if (!client || !client.default_adapter) {
            page.toggle.visible = false;
            this._fillPage(page, [], 'No Bluetooth adapter was found.');
            return;
        }

        const powered = client.default_adapter_powered;
        page.toggle.visible = true;
        page.toggle.setChecked(powered);

        if (!powered) {
            this._fillPage(page, [], 'Bluetooth is off.');
            return;
        }

        const devices = this._btDevices()
            .sort((a, b) => (b.connected - a.connected) ||
                GLib.utf8_collate(a.alias || '', b.alias || ''));

        const rows = devices.map(device => {
            const path = device.get_object_path();
            const pending = this._btPending.has(path);
            let subtitle = device.connected ? 'Connected' : 'Not connected';
            if (pending)
                subtitle = device.connected ? 'Disconnecting…' : 'Connecting…';

            let battery = -1;
            try {
                battery = device.battery_percentage;
            } catch (e) {
                // Older gnome-bluetooth has no battery property.
            }
            if (device.connected && Number.isFinite(battery) && battery > 0)
                subtitle += ` · ${Math.round(battery)}%`;

            return makeRow({
                icon: device.icon ? `${device.icon}-symbolic` : 'bluetooth-active-symbolic',
                title: device.alias || device.name || 'Unknown device',
                subtitle,
                trailing: device.connected ? ['object-select-symbolic'] : [],
                active: device.connected,
                onActivate: pending ? null : () => this._toggleBtDevice(device),
            });
        });

        this._fillPage(page, rows,
            rows.length ? '' : 'No paired devices. Pair new ones in Bluetooth settings.');
    }

    _toggleBtDevice(device) {
        const client = this._btClient();
        const path = device.get_object_path();
        if (!client || this._btPending.has(path))
            return;

        this._btPending.add(path);
        this._queueSync();

        try {
            client.connect_service(path, !device.connected, null, (c, res) => {
                try {
                    c.connect_service_finish(res);
                } catch (e) {
                    log(`[Adaptive Control Center] Bluetooth ${device.alias}: ${e.message}`);
                }
                this._btPending.delete(path);
                this._queueSync();
            });
        } catch (e) {
            this._btPending.delete(path);
            logError(e, '[Adaptive Control Center] Bluetooth connect');
        }
    }

    // --- Power mode

    _syncPowerPage() {
        const page = this._pages.power;
        const proxy = this._profilesProxy();

        if (!proxy) {
            this._fillPage(page, [], 'Power profiles are not available on this machine.');
            return;
        }

        const available = (proxy.Profiles || [])
            .map(p => p.Profile.unpack())
            .filter(p => PROFILES[p]);
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

        this._fillPage(page, rows);
    }

    // --- Sound output

    _syncSoundPage() {
        const page = this._pages.sound;
        const current = this._mixer.get_default_sink();
        const sinks = this._mixer.get_sinks() || [];

        const rows = sinks.map(sink => {
            const active = !!current && sink.get_id() === current.get_id();
            const { title, subtitle, icon } = describeSink(this._mixer, sink);
            return makeRow({
                icon,
                title,
                subtitle,
                trailing: active ? ['object-select-symbolic'] : [],
                active,
                onActivate: active ? null : () => {
                    this._mixer.set_default_sink(sink);
                    this._queueSync();
                },
            });
        });

        this._fillPage(page, rows, rows.length ? '' : 'No sound outputs were found.');
    }

    // --- Session

    _syncSessionPage() {
        const page = this._pages.session;
        const actions = this._systemActions;
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
            null,
            null);
    }
};
