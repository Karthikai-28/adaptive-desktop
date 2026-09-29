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

// NetworkManager is optional at build time in GNOME; without it the Wi-Fi
// tile just reports itself unavailable.
let NM = null;
try {
    NM = imports.gi.NM;
} catch (e) {
    NM = null;
}

// Tallest a dropdown list grows before it scrolls.
const LIST_MAX_HEIGHT = 264;
const DROPDOWN_FADE_MS = 140;
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

// The Bluetooth pairing agent this panel registers while it pairs a device.
const AGENT_PATH = '/org/adaptive/shell/BluetoothAgent';
const AGENT_XML = `<node>
  <interface name="org.bluez.Agent1">
    <method name="Release"/>
    <method name="RequestPinCode">
      <arg type="o" direction="in"/><arg type="s" direction="out"/>
    </method>
    <method name="DisplayPinCode">
      <arg type="o" direction="in"/><arg type="s" direction="in"/>
    </method>
    <method name="RequestPasskey">
      <arg type="o" direction="in"/><arg type="u" direction="out"/>
    </method>
    <method name="DisplayPasskey">
      <arg type="o" direction="in"/><arg type="u" direction="in"/><arg type="q" direction="in"/>
    </method>
    <method name="RequestConfirmation">
      <arg type="o" direction="in"/><arg type="u" direction="in"/>
    </method>
    <method name="RequestAuthorization">
      <arg type="o" direction="in"/>
    </method>
    <method name="AuthorizeService">
      <arg type="o" direction="in"/><arg type="s" direction="in"/>
    </method>
    <method name="Cancel"/>
  </interface>
</node>`;

// What a failed BlueZ Pair() means, in words a person can act on.
function pairingError(error) {
    const message = error && error.message ? error.message : '';
    if (/AuthenticationFailed/.test(message))
        return 'Pairing failed. Check the code and try again.';
    if (/AuthenticationCanceled|AuthenticationRejected|Canceled|Rejected/.test(message))
        return 'Pairing was cancelled';
    if (/ConnectionAttemptFailed|AuthenticationTimeout|Timeout|timed out|NoReply/i.test(message))
        return "No response. Is it in pairing mode?";
    if (/InProgress/.test(message))
        return 'Already pairing';
    return "Couldn't pair";
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

// A section label inside a dropdown list ("Known Networks", "My Devices").
function makeHeading(text) {
    return new St.Label({ text, style_class: 'adaptive-cc-list-heading', x_expand: true });
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

// One line in a dropdown list: icon, title and subtitle, trailing icons,
// and optionally a trailing action button.
function makeRow({
    icon = null, title, subtitle = '', trailing = [], action = null,
    active = false, danger = false, alert = false, onActivate = null,
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
            style_class: alert
                ? 'adaptive-cc-row-subtitle adaptive-cc-row-alert'
                : 'adaptive-cc-row-subtitle',
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
// and opens its dropdown otherwise; a tile with both gets a separate arrow for
// the dropdown, the way Android splits the two.
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
        this._chevron = null;
        if (onOpen) {
            const chevron = new St.Icon({
                icon_name: 'pan-down-symbolic',
                style_class: 'adaptive-cc-tile-chevron',
                y_align: Clutter.ActorAlign.CENTER,
            });
            this._chevron = chevron;

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

    // The chevron points up while this tile's dropdown is open.
    setExpanded(open) {
        if (!this._chevron)
            return;
        this._chevron.icon_name = open ? 'pan-up-symbolic' : 'pan-down-symbolic';
        const holder = this._arrow || this._main;
        if (open)
            holder.add_style_pseudo_class('expanded');
        else
            holder.remove_style_pseudo_class('expanded');
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
            this._buildAgent();

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

        const grid = this._grid.layout_manager;
        grid.attach(this._buildDropdown('wifi', {
            settings: ['wifi', 'Network Settings'],
        }), 0, 1, 2, 1);
        grid.attach(this._buildDropdown('bluetooth', {
            settings: ['bluetooth', 'Bluetooth Settings'],
        }), 0, 1, 2, 1);
        grid.attach(this._buildDropdown('power', {
            settings: ['power', 'Power Settings'],
        }), 0, 3, 2, 1);

        this._slidersBox.insert_child_above(this._buildDropdown('sound', {
            settings: ['sound', 'Sound Settings'],
        }), this._volume.row);
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
        };

        Object.values(this._tiles).forEach((tile, i) => {
            grid.layout_manager.attach(tile.actor, i % 2, 2 * Math.floor(i / 2), 1, 1);
        });

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

    _buildDropdown(name, { settings = null }) {
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

    // Replace a dropdown's rows, then size its scroll view to them.
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
        if (this._open === 'wifi')
            this._startScanning();
        else
            this._stopScanning();

        // Forms belong to the dropdown they were opened in.
        if (this._wifiJoin && this._wifiJoin.stage === 'form')
            this._wifiJoin = null;
        if (this._open !== 'bluetooth')
            this._cancelPairing();
        this._setBtDiscovery(this._open === 'bluetooth');

        if (this._open === 'session')
            this._systemActions.forceUpdate();

        this._syncPage();
    }

    // Whatever opened a dropdown shows that it is open.
    _setExpander(name, open) {
        if (this._tiles[name]) {
            this._tiles[name].setExpanded(open);
            return;
        }

        const button = name === 'session' ? this._powerButton
            : name === 'sound' ? this._volume.arrow : null;
        if (!button)
            return;

        if (open)
            button.add_style_pseudo_class('expanded');
        else
            button.remove_style_pseudo_class('expanded');

        if (name === 'sound')
            button.child.icon_name = open ? 'pan-up-symbolic' : 'pan-down-symbolic';
    }

    // ---------------------------------------------------------- lifecycle

    _onOpen() {
        if (!this._showingOurs)
            return;

        this._connectLive();
        this._openDropdown(null);
        this._syncAll();
    }

    _onClose() {
        this._dropLive();
        this._stopScanning();
        this._setBtDiscovery(false);

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

    _syncWifiPage(force = false) {
        const page = this._pages.wifi;
        const client = this._nmClient();
        const device = this._wifiDevice();

        if (!client || !device) {
            this._fillPage(page, [], 'No Wi-Fi adapter was found.');
            return;
        }

        const enabled = client.wireless_enabled && !this._rfkill.airplaneMode;

        if (this._rfkill.airplaneMode) {
            this._wifiJoin = null;
            this._fillPage(page, [], 'Airplane mode is on. Tap Wi-Fi to turn it back on.');
            return;
        }
        if (!enabled) {
            this._wifiJoin = null;
            this._fillPage(page, [], 'Wi-Fi is off.');
            return;
        }

        const state = device.get_state();
        const connecting = state > NM.DeviceState.DISCONNECTED &&
            state < NM.DeviceState.ACTIVATED;
        const networks = this._wifiNetworks(client, device);
        const join = this._wifiJoin;

        // A password being typed must survive the scan that lands halfway
        // through it, so an open form freezes the list until it closes.
        if (!force && join && join.stage === 'form' && page.list.get_n_children() > 0)
            return;
        if (!force && this._holdForPointer(page))
            return;

        // A scan fires a burst of access-point signals that mostly change
        // nothing on screen. Rebuilding the rows anyway reset hover and
        // scrolling several times a second, so only rebuild on a visible
        // difference.
        const signature = networks.map(n => [
            n.name, n.active, n.connections.length > 0,
            signalLevel(n.ap.strength), apSecured(n.ap),
        ].join('|')).join('\n') +
            `|${connecting}|${join ? `${join.name}:${join.stage}` : ''}` +
            `|${[...this._wifiErrors].join(',')}`;
        if (!force && signature === this._wifiSignature && page.list.get_n_children() > 0)
            return;
        this._wifiSignature = signature;

        const rows = [];
        let form = null;
        const add = network => {
            rows.push(this._wifiRow(network, device, connecting));
            if (join && join.stage === 'form' && join.name === network.name) {
                form = this._wifiJoinForm(network);
                rows.push(form);
            }
        };

        networks.filter(n => n.active).forEach(add);

        const known = networks.filter(n => !n.active && n.connections.length > 0);
        if (known.length) {
            rows.push(makeHeading('Known Networks'));
            known.forEach(add);
        }

        const other = networks.filter(n => !n.active && n.connections.length === 0);
        if (other.length) {
            rows.push(makeHeading('Other Networks'));
            other.forEach(add);
        }

        this._fillPage(page, rows, rows.length ? '' : 'Searching for networks…');
        if (form)
            this._focusForm(page, form);
    }

    _wifiRow(network, device, connecting) {
        const join = this._wifiJoin;
        const joining = join && join.stage === 'connecting' && join.name === network.name;
        const error = this._wifiErrors.get(network.name);
        const secured = apSecured(network.ap);

        let subtitle = '';
        if (network.active)
            subtitle = connecting ? 'Connecting…' : 'Connected';
        else if (joining)
            subtitle = 'Connecting…';
        else if (error)
            subtitle = error;
        else if (apEnterprise(network.ap))
            subtitle = 'Enterprise · opens Settings';
        else if (!secured)
            subtitle = 'Open network';

        const trailing = [];
        if (secured)
            trailing.push('network-wireless-encrypted-symbolic');
        if (network.active && !connecting)
            trailing.push('object-select-symbolic');

        return makeRow({
            icon: `network-wireless-signal-${signalLevel(network.ap.strength)}-symbolic`,
            title: network.name,
            subtitle,
            alert: !!error && !network.active && !joining,
            trailing,
            active: network.active,
            action: network.active ? {
                label: 'Disconnect',
                onClick: () => this._disconnectWifi(device),
            } : null,
            onActivate: network.active || joining ? null : () => this._connectWifi(network),
        });
    }

    // WPA/WPA2 personal and WPA3 personal are the passwords a form can carry.
    // Anything else (WEP) goes to GNOME's own secrets dialog.
    _wifiKeyMgmt(ap) {
        const F = NM['80211ApSecurityFlags'];
        const flags = ap.rsn_flags | ap.wpa_flags;
        if (flags & F.KEY_MGMT_PSK)
            return 'wpa-psk';
        if (F.KEY_MGMT_SAE && (flags & F.KEY_MGMT_SAE))
            return 'sae';
        return null;
    }

    _connectWifi(network) {
        const client = this._nmClient();
        const device = this._wifiDevice();
        if (!client || !device)
            return;

        this._wifiErrors.delete(network.name);

        try {
            // Known: NetworkManager already has the password.
            if (network.connections.length > 0) {
                this._wifiJoin = { name: network.name, stage: 'connecting' };
                client.activate_connection_async(network.connections[0], device,
                    null, null, (c, res) => {
                        try {
                            this._watchJoin(network.name, c.activate_connection_finish(res), false);
                        } catch (e) {
                            this._joinFailed(network.name, null, "Couldn't connect");
                        }
                    });
                this._syncWifiPage(true);
                return;
            }

            if (apEnterprise(network.ap)) {
                const devicePath = NM.Object.prototype.get_path.call(device);
                this._closeMenu();
                Util.spawn(['gnome-control-center', 'wifi', 'connect-8021x-wifi',
                    devicePath, network.ap.get_path()]);
                return;
            }

            if (!apSecured(network.ap)) {
                this._addAndActivate(network, new NM.SimpleConnection());
                return;
            }

            const keyMgmt = this._wifiKeyMgmt(network.ap);
            if (!keyMgmt) {
                // WEP: GNOME's network agent asks for the key in its own
                // dialog, which needs the pointer the menu is holding.
                this._closeMenu();
                client.add_and_activate_connection_async(new NM.SimpleConnection(),
                    device, network.ap.get_path(), null, null);
                return;
            }

            // A new secured network: open (or close) the password form under it.
            const open = this._wifiJoin && this._wifiJoin.stage === 'form' &&
                this._wifiJoin.name === network.name;
            this._wifiJoin = open ? null : { name: network.name, stage: 'form', keyMgmt };
            this._syncWifiPage(true);
        } catch (e) {
            logError(e, `[Adaptive Control Center] connecting to ${network.name}`);
        }
    }

    _wifiJoinForm(network) {
        return this._makeSecretForm({
            prompt: `Enter the password for “${network.name}”`,
            hint: 'Password',
            submitLabel: 'Join',
            // WPA passphrases are 8 to 63 characters.
            minLength: 8,
            onSubmit: password => {
                const connection = new NM.SimpleConnection();
                connection.add_setting(new NM.SettingWirelessSecurity({
                    key_mgmt: this._wifiJoin ? this._wifiJoin.keyMgmt : 'wpa-psk',
                    psk: password,
                }));
                this._addAndActivate(network, connection);
            },
            onCancel: () => {
                this._wifiJoin = null;
                this._syncWifiPage(true);
            },
        });
    }

    _addAndActivate(network, connection) {
        const client = this._nmClient();
        const device = this._wifiDevice();
        if (!client || !device)
            return;

        this._wifiJoin = { name: network.name, stage: 'connecting' };
        this._syncWifiPage(true);

        client.add_and_activate_connection_async(connection, device,
            network.ap.get_path(), null, (c, res) => {
                try {
                    this._watchJoin(network.name, c.add_and_activate_connection_finish(res), true);
                } catch (e) {
                    this._joinFailed(network.name, null, "Couldn't connect");
                }
            });
    }

    // Follow one activation to the end. A new profile that never came up -
    // wrong password, out of range - is deleted again, so a bad password is
    // never left saved to fail the next time.
    _watchJoin(name, active, isNew) {
        this._stopWatchingJoin();

        const remote = isNew ? active.get_connection() : null;
        const id = active.connect('state-changed', (_active, state, reason) => {
            if (state === NM.ActiveConnectionState.ACTIVATED) {
                this._stopWatchingJoin();
                this._wifiJoin = null;
                this._wifiErrors.delete(name);
                this._queueSync();
            } else if (state === NM.ActiveConnectionState.DEACTIVATED) {
                const R = NM.ActiveConnectionStateReason;
                const badSecret = reason === R.NO_SECRETS || reason === R.LOGIN_FAILED;
                this._joinFailed(name, remote, badSecret ? 'Wrong password' : "Couldn't connect");
            }
        });
        this._joinWatch = [active, id];
    }

    _stopWatchingJoin() {
        if (this._joinWatch) {
            const [active, id] = this._joinWatch;
            try {
                active.disconnect(id);
            } catch (e) {
            }
            this._joinWatch = null;
        }
    }

    _joinFailed(name, remote, message) {
        this._stopWatchingJoin();
        if (remote) {
            try {
                remote.delete_async(null, null);
            } catch (e) {
                logError(e, '[Adaptive Control Center] removing a failed Wi-Fi profile');
            }
        }
        this._wifiErrors.set(name, message);
        this._wifiJoin = null;
        this._queueSync();
    }

    _disconnectWifi(device) {
        try {
            device.disconnect_async(null, null);
        } catch (e) {
            logError(e, '[Adaptive Control Center] disconnecting Wi-Fi');
        }
    }

    // --- Forms

    // An inline form for a secret: a Wi-Fi password, a Bluetooth PIN or
    // passkey. It lives in the dropdown, under the row it belongs to.
    _makeSecretForm({
        prompt, hint, submitLabel, minLength = 1, secret = true,
        numeric = false, onSubmit, onCancel,
    }) {
        const box = new St.BoxLayout({
            style_class: 'adaptive-cc-form',
            vertical: true,
            x_expand: true,
        });

        const label = new St.Label({ text: prompt, style_class: 'adaptive-cc-form-prompt' });
        label.clutter_text.line_wrap = true;
        box.add_child(label);

        const field = new St.BoxLayout({ style_class: 'adaptive-cc-form-field', x_expand: true });
        box.add_child(field);

        const entry = new St.Entry({
            style_class: 'adaptive-cc-entry',
            hint_text: hint,
            can_focus: true,
            x_expand: true,
        });
        if (secret) {
            entry.clutter_text.set_password_char('●');
            entry.input_purpose = Clutter.InputContentPurpose.PASSWORD;
        } else if (numeric) {
            entry.input_purpose = Clutter.InputContentPurpose.DIGITS;
        }
        field.add_child(entry);

        if (secret) {
            const eye = new St.Button({
                style_class: 'adaptive-cc-form-eye',
                can_focus: true,
                accessible_name: 'Show password',
                child: new St.Icon({ icon_name: 'view-reveal-symbolic' }),
                y_align: Clutter.ActorAlign.CENTER,
            });
            eye.connect('clicked', () => {
                const hidden = entry.clutter_text.get_password_char() !== 0;
                entry.clutter_text.set_password_char(hidden ? '' : '●');
                eye.child.icon_name = hidden ? 'view-conceal-symbolic' : 'view-reveal-symbolic';
            });
            field.add_child(eye);
        }

        const buttons = new St.BoxLayout({
            style_class: 'adaptive-cc-form-buttons',
            x_align: Clutter.ActorAlign.END,
        });
        box.add_child(buttons);

        const cancel = new St.Button({
            style_class: 'adaptive-cc-form-button',
            label: 'Cancel',
            can_focus: true,
        });
        cancel.connect('clicked', () => onCancel());
        buttons.add_child(cancel);

        const submit = new St.Button({
            style_class: 'adaptive-cc-form-button adaptive-cc-form-primary',
            label: submitLabel,
            can_focus: true,
        });
        buttons.add_child(submit);

        const valid = () => {
            const text = entry.get_text();
            return text.length >= minLength && (!numeric || /^\d+$/.test(text));
        };
        const syncSubmit = () => {
            const ok = valid();
            submit.reactive = ok;
            if (ok)
                submit.remove_style_pseudo_class('insensitive');
            else
                submit.add_style_pseudo_class('insensitive');
        };
        entry.clutter_text.connect('text-changed', syncSubmit);
        syncSubmit();

        const go = () => {
            if (valid())
                onSubmit(entry.get_text());
        };
        entry.clutter_text.connect('activate', go);
        submit.connect('clicked', go);

        box._entry = entry;
        return box;
    }

    // A question with no typing: a code to compare, or a yes/no.
    _makeConfirmForm({ prompt, code = null, confirmLabel, cancelLabel = 'Cancel', onConfirm = null, onCancel }) {
        const box = new St.BoxLayout({
            style_class: 'adaptive-cc-form',
            vertical: true,
            x_expand: true,
        });

        const label = new St.Label({ text: prompt, style_class: 'adaptive-cc-form-prompt' });
        label.clutter_text.line_wrap = true;
        box.add_child(label);

        if (code) {
            box.add_child(new St.Label({
                text: code,
                style_class: 'adaptive-cc-form-code',
                x_align: Clutter.ActorAlign.CENTER,
            }));
        }

        const buttons = new St.BoxLayout({
            style_class: 'adaptive-cc-form-buttons',
            x_align: Clutter.ActorAlign.END,
        });
        box.add_child(buttons);

        const cancel = new St.Button({
            style_class: 'adaptive-cc-form-button',
            label: cancelLabel,
            can_focus: true,
        });
        cancel.connect('clicked', () => onCancel());
        buttons.add_child(cancel);

        if (onConfirm) {
            const confirm = new St.Button({
                style_class: 'adaptive-cc-form-button adaptive-cc-form-primary',
                label: confirmLabel,
                can_focus: true,
            });
            confirm.connect('clicked', () => onConfirm());
            buttons.add_child(confirm);
            box._entry = confirm;
        } else {
            box._entry = cancel;
        }

        return box;
    }

    // Put the keyboard in the form and scroll it into view, once it is laid out.
    _focusForm(page, form) {
        GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
            if (form.get_stage() && form._entry) {
                form._entry.grab_key_focus();
                try {
                    Util.ensureActorVisibleInScrollView(page.scroll, form);
                } catch (e) {
                }
            }
            return GLib.SOURCE_REMOVE;
        });
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

    // Scanning makes the adapter discoverable and costs power, so it runs only
    // while the Bluetooth dropdown is open.
    _setBtDiscovery(on) {
        const client = this._btClient();
        if (!client || !client.default_adapter)
            return;
        on = on && client.default_adapter_powered;
        try {
            if (client.default_adapter_setup_mode !== on)
                client.default_adapter_setup_mode = on;
        } catch (e) {
            logError(e, '[Adaptive Control Center] Bluetooth discovery');
        }
    }

    // Everything the adapter knows about that has a real name - paired ones
    // and ones found by scanning. Unnamed devices are only an address and
    // nobody can tell them apart, so they are left out.
    _btAllDevices() {
        const client = this._btClient();
        if (!client)
            return [];
        const store = client.get_devices();
        const devices = [];
        for (let i = 0; i < store.get_n_items(); i++) {
            const device = store.get_item(i);
            const known = device.paired || device.trusted;
            const name = device.name || '';
            if (!known && (!name || /^([0-9A-F]{2}[:-]){5}[0-9A-F]{2}$/i.test(name)))
                continue;
            devices.push(device);
        }
        return devices;
    }

    _syncBluetoothPage(force = false) {
        const page = this._pages.bluetooth;
        const client = this._btClient();

        if (!client || !client.default_adapter) {
            this._fillPage(page, [], 'No Bluetooth adapter was found.');
            return;
        }

        const powered = client.default_adapter_powered;
        if (!powered) {
            this._fillPage(page, [], 'Bluetooth is off.');
            return;
        }

        // Scanning follows the dropdown; start it if Bluetooth was only just
        // turned on while the dropdown was open.
        if (this._open === 'bluetooth')
            this._setBtDiscovery(true);

        // Don't rebuild under someone typing a PIN.
        const pair = this._btPair;
        if (!force && pair && pair.stage !== 'pairing' && pair.stage !== 'connecting' &&
            page.list.get_n_children() > 0)
            return;
        if (!force && this._holdForPointer(page))
            return;

        const byName = (a, b) => GLib.utf8_collate(a.alias || a.name || '', b.alias || b.name || '');
        const devices = this._btAllDevices();
        const mine = devices.filter(d => d.paired || d.trusted)
            .sort((a, b) => (b.connected - a.connected) || byName(a, b));
        const others = devices.filter(d => !d.paired && !d.trusted).sort(byName).slice(0, 20);

        // Scanning reports devices one at a time; rebuilding the list on each
        // could swallow a tap that lands mid-rebuild. Rebuild on real change.
        const signature = [...mine, ...others].map(d => [
            d.get_object_path(), d.alias || d.name, d.connected, d.paired || d.trusted, d.icon,
        ].join('|')).join('\n') +
            `|${pair ? `${pair.path}:${pair.stage}` : ''}` +
            `|${[...this._btPending].join(',')}|${[...this._btErrors].join(',')}`;
        if (!force && signature === this._btSignature && page.list.get_n_children() > 0)
            return;
        this._btSignature = signature;

        const rows = [];
        let form = null;
        const add = device => {
            rows.push(this._btRow(device));
            if (pair && pair.path === device.get_object_path()) {
                const f = this._btPairForm(pair);
                if (f) {
                    form = f;
                    rows.push(f);
                }
            }
        };

        if (mine.length) {
            rows.push(makeHeading('My Devices'));
            mine.forEach(add);
        }

        rows.push(makeHeading('Other Devices'));
        if (others.length) {
            others.forEach(add);
        } else {
            rows.push(makeRow({
                icon: 'bluetooth-active-symbolic',
                title: 'Looking for devices…',
                subtitle: 'Put the device in pairing mode',
            }));
        }

        this._fillPage(page, rows);
        if (form)
            this._focusForm(page, form);
    }

    _btRow(device) {
        const path = device.get_object_path();
        const known = device.paired || device.trusted;
        const pair = this._btPair && this._btPair.path === path ? this._btPair : null;
        const pending = this._btPending.has(path);
        const error = this._btErrors.get(path);

        let subtitle;
        if (pair)
            subtitle = pair.stage === 'connecting' ? 'Connecting…' : 'Pairing…';
        else if (pending)
            subtitle = device.connected ? 'Disconnecting…' : 'Connecting…';
        else if (error)
            subtitle = error;
        else if (!known)
            subtitle = 'Tap to pair';
        else
            subtitle = device.connected ? 'Connected' : 'Not connected';

        if (!pair && !pending && !error && device.connected) {
            let battery = -1;
            try {
                battery = device.battery_percentage;
            } catch (e) {
                // Older gnome-bluetooth has no battery property.
            }
            if (Number.isFinite(battery) && battery > 0)
                subtitle += ` · ${Math.round(battery)}%`;
        }

        return makeRow({
            icon: device.icon ? `${device.icon}-symbolic` : 'bluetooth-active-symbolic',
            title: device.alias || device.name || 'Unknown device',
            subtitle,
            alert: !!error && !pair && !pending,
            trailing: device.connected ? ['object-select-symbolic'] : [],
            active: device.connected,
            onActivate: pair || pending || (this._btPair && !pair) ? null
                : known ? () => this._toggleBtDevice(device)
                    : () => this._pairBtDevice(device),
        });
    }

    _toggleBtDevice(device) {
        const client = this._btClient();
        const path = device.get_object_path();
        if (!client || this._btPending.has(path))
            return;

        this._btErrors.delete(path);
        this._btPending.add(path);
        this._queueSync();

        try {
            client.connect_service(path, !device.connected, null, (c, res) => {
                try {
                    c.connect_service_finish(res);
                } catch (e) {
                    this._btErrors.set(path, device.connected
                        ? "Couldn't disconnect" : "Couldn't connect. Is it on and nearby?");
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

    // --- Bluetooth pairing
    //
    // GNOME 42's Bluetooth library has no pairing call, so this talks to BlueZ
    // directly: Device1.Pair, then Trusted, then connect. BlueZ asks the agent
    // registered on the *calling* connection for any PIN or code, so the shell
    // registers its agent just for the length of a pairing and never becomes
    // the system's default agent - Settings keeps that role when it is open.

    _pairBtDevice(device) {
        if (this._btPair)
            return;

        const path = device.get_object_path();
        this._btErrors.delete(path);
        this._btPair = {
            path,
            name: device.alias || device.name || 'the device',
            stage: 'pairing',
            invocation: null,
            code: null,
        };
        this._syncBluetoothPage(true);

        this._registerAgent(() => {
            if (!this._btPair || this._btPair.path !== path)
                return;

            Gio.DBus.system.call('org.bluez', path, 'org.bluez.Device1', 'Pair',
                null, null, Gio.DBusCallFlags.NONE, 90000, null, (conn, res) => {
                    let error = null;
                    try {
                        conn.call_finish(res);
                    } catch (e) {
                        error = e;
                    }

                    if (!this._btPair || this._btPair.path !== path)
                        return;

                    if (error && !/AlreadyExists/.test(error.message)) {
                        this._finishPairing(path, pairingError(error));
                        return;
                    }

                    // Trusted is what lets it reconnect on its own later.
                    Gio.DBus.system.call('org.bluez', path,
                        'org.freedesktop.DBus.Properties', 'Set',
                        new GLib.Variant('(ssv)', ['org.bluez.Device1', 'Trusted',
                            new GLib.Variant('b', true)]),
                        null, Gio.DBusCallFlags.NONE, -1, null, null);

                    this._btPair.stage = 'connecting';
                    this._btPair.invocation = null;
                    this._unregisterAgent();
                    this._syncBluetoothPage(true);

                    const client = this._btClient();
                    if (!client) {
                        this._finishPairing(path, null);
                        return;
                    }
                    client.connect_service(path, true, null, (c, r) => {
                        let message = null;
                        try {
                            c.connect_service_finish(r);
                        } catch (e) {
                            message = "Paired, but couldn't connect";
                        }
                        this._finishPairing(path, message);
                    });
                });
        });
    }

    // The prompt for whatever BlueZ asked the agent, if it asked anything.
    _btPairForm(pair) {
        const reply = fn => {
            const invocation = pair.invocation;
            pair.invocation = null;
            pair.stage = 'pairing';
            if (invocation)
                fn(invocation);
            this._syncBluetoothPage(true);
        };
        const reject = () => reply(inv =>
            inv.return_dbus_error('org.bluez.Error.Rejected', 'Cancelled by the user'));

        switch (pair.stage) {
        case 'pin':
            return this._makeSecretForm({
                prompt: `Enter the PIN for “${pair.name}”. Try 0000 or 1234 if the device has no screen.`,
                hint: 'PIN',
                submitLabel: 'Pair',
                secret: false,
                onSubmit: pin => reply(inv => inv.return_value(new GLib.Variant('(s)', [pin]))),
                onCancel: () => this._cancelPairing(),
            });
        case 'passkey':
            return this._makeSecretForm({
                prompt: `Enter the passkey shown on “${pair.name}”.`,
                hint: 'Passkey',
                submitLabel: 'Pair',
                secret: false,
                numeric: true,
                onSubmit: key => reply(inv =>
                    inv.return_value(new GLib.Variant('(u)', [parseInt(key, 10)]))),
                onCancel: () => this._cancelPairing(),
            });
        case 'confirm':
            return this._makeConfirmForm({
                prompt: `Confirm that “${pair.name}” shows this code:`,
                code: pair.code,
                confirmLabel: 'Pair',
                onConfirm: () => reply(inv => inv.return_value(null)),
                onCancel: () => {
                    reject();
                    this._cancelPairing();
                },
            });
        case 'authorize':
            return this._makeConfirmForm({
                prompt: `Allow “${pair.name}” to pair with this computer?`,
                confirmLabel: 'Allow',
                onConfirm: () => reply(inv => inv.return_value(null)),
                onCancel: () => {
                    reject();
                    this._cancelPairing();
                },
            });
        case 'display':
            return this._makeConfirmForm({
                prompt: `Type this code on “${pair.name}”, then press Enter on it:`,
                code: pair.code,
                onCancel: () => this._cancelPairing(),
            });
        }
        return null;
    }

    _registerAgent(then) {
        if (this._agentRegistered || !this._agentExport) {
            then();
            return;
        }
        Gio.DBus.system.call('org.bluez', '/org/bluez', 'org.bluez.AgentManager1',
            'RegisterAgent', new GLib.Variant('(os)', [AGENT_PATH, 'KeyboardDisplay']),
            null, Gio.DBusCallFlags.NONE, -1, null, (conn, res) => {
                try {
                    conn.call_finish(res);
                    this._agentRegistered = true;
                } catch (e) {
                    if (!/AlreadyExists/.test(e.message))
                        log(`[Adaptive Control Center] Bluetooth agent: ${e.message}`);
                    else
                        this._agentRegistered = true;
                }
                then();
            });
    }

    _unregisterAgent() {
        if (!this._agentRegistered)
            return;
        this._agentRegistered = false;
        Gio.DBus.system.call('org.bluez', '/org/bluez', 'org.bluez.AgentManager1',
            'UnregisterAgent', new GLib.Variant('(o)', [AGENT_PATH]),
            null, Gio.DBusCallFlags.NONE, -1, null, null);
    }

    _finishPairing(path, errorText) {
        const pair = this._btPair;
        if (pair && pair.invocation) {
            pair.invocation.return_dbus_error('org.bluez.Error.Canceled', 'Pairing ended');
            pair.invocation = null;
        }
        this._btPair = null;
        if (errorText)
            this._btErrors.set(path, errorText);
        this._unregisterAgent();
        if (this._pages.bluetooth)
            this._syncBluetoothPage(true);
    }

    _cancelPairing() {
        const pair = this._btPair;
        if (!pair)
            return;

        if (pair.stage !== 'connecting') {
            Gio.DBus.system.call('org.bluez', pair.path, 'org.bluez.Device1',
                'CancelPairing', null, null, Gio.DBusCallFlags.NONE, -1, null, null);
        }
        this._finishPairing(pair.path, null);
    }

    // BlueZ calling the agent. Each ask parks the D-Bus invocation on the
    // pairing and shows the matching form; the form's buttons answer it.
    _buildAgent() {
        const ask = stage => (params, invocation) => {
            const [device, passkey] = params;
            const pair = this._btPair;
            if (!pair || pair.path !== device || !this._attached) {
                invocation.return_dbus_error('org.bluez.Error.Rejected', 'Not pairing this device');
                return;
            }
            pair.stage = stage;
            pair.invocation = invocation;
            pair.code = passkey === undefined ? null : String(passkey).padStart(6, '0');
            this._syncBluetoothPage(true);
        };
        const show = (device, code) => {
            const pair = this._btPair;
            if (!pair || pair.path !== device)
                return;
            pair.stage = 'display';
            pair.code = String(code);
            this._syncBluetoothPage(true);
        };

        const impl = {
            Release: () => {
                this._agentRegistered = false;
            },
            RequestPinCodeAsync: ask('pin'),
            DisplayPinCode: (device, pin) => show(device, pin),
            RequestPasskeyAsync: ask('passkey'),
            DisplayPasskey: (device, passkey) => show(device, String(passkey).padStart(6, '0')),
            RequestConfirmationAsync: ask('confirm'),
            RequestAuthorizationAsync: ask('authorize'),
            AuthorizeServiceAsync: ([device], invocation) => {
                if (this._btPair && this._btPair.path === device)
                    invocation.return_value(null);
                else
                    invocation.return_dbus_error('org.bluez.Error.Rejected', 'Not pairing this device');
            },
            Cancel: () => {
                if (this._btPair) {
                    this._btPair.invocation = null;
                    this._btPair.stage = 'pairing';
                    this._syncBluetoothPage(true);
                }
            },
        };

        try {
            this._agentExport = Gio.DBusExportedObject.wrapJSObject(AGENT_XML, impl);
            this._agentExport.export(Gio.DBus.system, AGENT_PATH);
        } catch (e) {
            this._agentExport = null;
            logError(e, '[Adaptive Control Center] exporting the Bluetooth agent');
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
