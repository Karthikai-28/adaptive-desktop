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

const { Clutter, Gio, GLib, Meta, Shell, St } = imports.gi;
const Main = imports.ui.main;
const Mpris = imports.ui.mpris;
const Slider = imports.ui.slider;
const SystemActions = imports.misc.systemActions;
const Util = imports.misc.util;
const Volume = imports.ui.status.volume;
const Rfkill = imports.ui.status.rfkill;

const Me = imports.misc.extensionUtils.getCurrentExtension();
const QrCode = Me.imports.qrcode;

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

const CAMERA_POLL_S = 3;

// Bluetooth. A scan runs for a window rather than for as long as the dropdown
// is open; connecting retries what a device just out of its case typically
// answers with, then waits a moment in case it connects itself.
const BT_SCAN_S = 30;
const BT_CONNECT_ATTEMPTS = 3;
const BT_RETRY_MS = 1500;
const BT_SETTLE_MS = 5000;
// imports.ui.screenshot keeps its UIMode private; SCREENCAST is 1.
const UI_MODE_SCREENCAST = 1;

// Tiles in their default order. The saved order (Edit Controls) lives in
// ~/.config/adaptive-desktop/control-center.json.
const DEFAULT_TILES = [
    'wifi', 'bluetooth', 'power', 'nightLight', 'dnd',
    'airplane', 'awake', 'mic', 'tailscale',
];
// Tiles whose arrow opens a dropdown, and which one.
const TILE_DROPDOWNS = {
    wifi: 'wifi', bluetooth: 'bluetooth', power: 'power', tailscale: 'tailscale',
};

const CONFIG_PATH = GLib.build_filenamev(
    [GLib.get_user_config_dir(), 'adaptive-desktop', 'control-center.json']);

function readConfig() {
    try {
        const [ok, bytes] = GLib.file_get_contents(CONFIG_PATH);
        return ok ? JSON.parse(new TextDecoder().decode(bytes)) || {} : {};
    } catch (e) {
        return {};
    }
}

function writeConfig(patch) {
    try {
        GLib.mkdir_with_parents(GLib.path_get_dirname(CONFIG_PATH), 0o755);
        const merged = Object.assign(readConfig(), patch);
        for (const key of Object.keys(merged)) {
            if (merged[key] === null)
                delete merged[key];
        }
        GLib.file_set_contents(CONFIG_PATH, `${JSON.stringify(merged, null, 2)}\n`);
    } catch (e) {
        logError(e, '[Adaptive Control Center] saving control-center.json');
    }
}

// Run a command off the main loop and hand back (ok, stdout, stderr).
function run(argv, callback) {
    try {
        const proc = Gio.Subprocess.new(argv,
            Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE);
        proc.communicate_utf8_async(null, null, (p, res) => {
            let out = '';
            let err = '';
            let ok = false;
            try {
                [, out, err] = p.communicate_utf8_finish(res);
                ok = p.get_successful();
            } catch (e) {
                err = e.message;
            }
            callback(ok, out || '', err || '');
        });
    } catch (e) {
        callback(false, '', e.message);
    }
}

// The app behind a process: walk up the process tree to whichever ancestor
// owns a window (Chrome's camera runs in a helper), else the process name.
function appNameForPid(pid) {
    const tracker = Shell.WindowTracker.get_default();
    let current = pid;
    for (let depth = 0; depth < 6 && current > 1; depth++) {
        const app = tracker.get_app_from_pid(current);
        if (app)
            return app.get_name();
        try {
            const [, bytes] = GLib.file_get_contents(`/proc/${current}/stat`);
            const stat = new TextDecoder().decode(bytes);
            current = parseInt(stat.slice(stat.lastIndexOf(')') + 2).split(' ')[1], 10);
        } catch (e) {
            break;
        }
    }
    try {
        const [, bytes] = GLib.file_get_contents(`/proc/${pid}/comm`);
        return new TextDecoder().decode(bytes).trim();
    } catch (e) {
        return null;
    }
}

// The name a person knows an app by. Audio streams often carry an engine's
// name instead ("ZOOM VoiceEngine", "Chromium input"), so failing an exact
// .desktop match, the first word is searched among installed apps.
function friendlyAppName(appId, streamName) {
    const system = Shell.AppSystem.get_default();
    if (appId) {
        const app = system.lookup_app(`${appId}.desktop`) || system.lookup_desktop_wmclass(appId);
        if (app)
            return app.get_name();
    }

    const word = (streamName || '')
        .replace(/\b(voice ?engine|input|output|audio|playback|recording|stream)\b/ig, '')
        .trim().split(/\s+/)[0];
    if (!word)
        return streamName || 'An app';

    try {
        for (const group of Shell.AppSystem.search(word) || []) {
            for (const id of group) {
                const app = system.lookup_app(id);
                if (app)
                    return app.get_name();
            }
        }
    } catch (e) {
    }
    return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
}

// An icon shipped with the extension, drawn in the text colour like a theme
// symbolic icon.
function extensionIcon(name) {
    const file = Me.dir.get_child('assets').get_child('panel').get_child(`${name}.svg`);
    return new Gio.FileIcon({ file });
}

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

// What a failed connect means, in words a person can act on.
function btFailureText(message, connect) {
    if (!connect)
        return "Couldn't disconnect";
    if (/page-timeout|Host is down|timeout/i.test(message))
        return 'No answer. Take it out of the case or switch it on, then tap again.';
    if (/busy|InProgress/i.test(message))
        return 'Busy with another device. Try again in a moment.';
    if (/profile-unavailable|NotAvailable|NotSupported/i.test(message))
        return "It can't connect to this computer";
    return "Couldn't connect";
}

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
    icon = null, title, subtitle = '', trailing = [], action = null, actions = null,
    active = false, danger = false, alert = false, onActivate = null,
}) {
    const button = new St.Button({
        style_class: danger ? 'adaptive-cc-row adaptive-cc-row-danger' : 'adaptive-cc-row',
        can_focus: !!onActivate,
        reactive: !!onActivate || !!action || !!actions,
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

    for (const item of actions || (action ? [action] : [])) {
        const pill = new St.Button({
            style_class: item.quiet
                ? 'adaptive-cc-pill-button adaptive-cc-pill-quiet' : 'adaptive-cc-pill-button',
            label: item.label,
            can_focus: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        pill.connect('clicked', item.onClick);
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
        this.title = title;
        this.iconName = icon;
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
            ...iconProps(icon),
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
        this._wifiShare = null;
        this._players = new Map();
        this._mprisSub = 0;
        this._camTimer = 0;
        this._dotIds = [];
        this._ts = null;
        this._btScan = { timer: 0, active: false };
        this._btTimers = new Set();
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

        // Wired links sit at the top: they are the other half of "network".
        const ethernet = this._ethernetRows(client);

        if (this._rfkill.airplaneMode) {
            this._wifiJoin = null;
            this._fillPage(page, ethernet, 'Airplane mode is on. Tap Wi-Fi to turn it back on.');
            return;
        }
        if (!enabled) {
            this._wifiJoin = null;
            this._fillPage(page, ethernet, 'Wi-Fi is off.');
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
            `|${[...this._wifiErrors].join(',')}` +
            `|${client.get_devices().filter(d => d.get_device_type() === NM.DeviceType.ETHERNET)
                .map(d => d.get_state()).join(',')}` +
            `|${this._wifiShare ? JSON.stringify(this._wifiShare) : ''}`;
        if (!force && signature === this._wifiSignature && page.list.get_n_children() > 0)
            return;
        this._wifiSignature = signature;

        const rows = [...ethernet];
        if (ethernet.length)
            rows.push(makeHeading('Wi-Fi'));
        let form = null;
        const add = network => {
            rows.push(this._wifiRow(network, device, connecting));
            if (join && join.stage === 'form' && join.name === network.name) {
                form = this._wifiJoinForm(network);
                rows.push(form);
            }
            if (network.active && this._wifiShare && this._wifiShare.name === network.name)
                rows.push(this._shareForm(network, device));
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
            actions: network.active && !connecting ? [{
                label: 'Share',
                quiet: true,
                onClick: () => this._startShare(network, device),
            }, {
                label: 'Disconnect',
                onClick: () => this._disconnectWifi(device),
            }] : null,
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

    // Scanning and calling a device share the radio: on Intel controllers
    // (this machine's included) a connection attempt made during a scan
    // commonly fails with br-connection-page-timeout, and a long scan can make
    // Bluetooth audio stutter. So a scan is a 30-second window, it stops the
    // moment anything connects or pairs, and "Scan Again" starts another.
    _startBtScan() {
        this._stopBtScan();
        const client = this._btClient();
        if (!client || !client.default_adapter || !client.default_adapter_powered)
            return;
        this._setBtDiscovery(true);
        this._btScan.active = true;
        this._btScan.ran = true;
        this._btScan.timer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, BT_SCAN_S, () => {
            this._btScan.timer = 0;
            this._stopBtScan();
            this._btSignature = null;
            this._queueSync();
            return GLib.SOURCE_REMOVE;
        });
        this._btSignature = null;
    }

    _stopBtScan() {
        if (this._btScan.timer) {
            GLib.Source.remove(this._btScan.timer);
            this._btScan.timer = 0;
        }
        if (this._btScan.active) {
            this._btScan.active = false;
            this._setBtDiscovery(false);
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

        // Bluetooth turned on while the dropdown was open: scan now.
        if (this._open === 'bluetooth' && !this._btScan.active && !this._btScan.ran &&
            !this._btPair && this._btPending.size === 0)
            this._startBtScan();

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
            `|${[...this._btPending].join(',')}|${[...this._btErrors].join(',')}` +
            `|${this._btScan.active}`;
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
        others.forEach(add);
        if (this._btScan.active) {
            rows.push(makeRow({
                icon: 'bluetooth-active-symbolic',
                title: 'Looking for devices…',
                subtitle: 'Put the device in pairing mode',
            }));
        } else {
            rows.push(makeRow({
                icon: 'view-refresh-symbolic',
                title: others.length ? 'Scan Again' : 'Scan for Devices',
                subtitle: 'Put the device in pairing mode first',
                onActivate: this._btPair || this._btPending.size ? null : () => {
                    this._startBtScan();
                    this._syncBluetoothPage(true);
                },
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

        const connect = !device.connected;
        this._btErrors.delete(path);
        this._btPending.add(path);
        if (connect)
            this._stopBtScan();
        this._btSignature = null;
        this._queueSync();

        this._btConnect(device, connect, error => {
            this._btPending.delete(path);
            if (error)
                this._btErrors.set(path, error);
            this._btSignature = null;
            this._queueSync();
        });
    }

    // Connect (or disconnect) a known device, the way GNOME Settings does it
    // - gnome-bluetooth's connect_service - but patient: earbuds just out of
    // the case, or still holding a link to a phone, answer the first page with
    // a timeout or "busy" and connect a second later. done(null) on success,
    // done(message) on failure.
    _btConnect(device, connect, done, attempt = 1) {
        const client = this._btClient();
        const path = device.get_object_path();
        if (!client) {
            done(null);
            return;
        }

        try {
            client.connect_service(path, connect, null, (c, res) => {
                let error = null;
                try {
                    c.connect_service_finish(res);
                } catch (e) {
                    error = e;
                }

                if (!error || device.connected === connect) {
                    done(null);
                    return;
                }

                const message = error.message || '';
                log(`[Adaptive Control Center] Bluetooth ${device.alias} ` +
                    `(attempt ${attempt}): ${message}`);

                if (connect && /AlreadyConnected/.test(message)) {
                    done(null);
                    return;
                }

                const transient = /page-timeout|Host is down|busy|InProgress|NotReady|timeout|abort/i
                    .test(message);
                if (connect && transient && attempt < BT_CONNECT_ATTEMPTS) {
                    this._btLater(BT_RETRY_MS * attempt, () => {
                        if (device.connected)
                            done(null);
                        else
                            this._btConnect(device, connect, done, attempt + 1);
                    });
                    return;
                }

                // Often it connects anyway, on its own: wait for that before
                // calling it a failure.
                this._btAwaitState(device, connect, BT_SETTLE_MS, ok =>
                    done(ok ? null : btFailureText(message, connect)));
            });
        } catch (e) {
            logError(e, '[Adaptive Control Center] Bluetooth connect');
            done(connect ? "Couldn't connect" : "Couldn't disconnect");
        }
    }

    _btAwaitState(device, wanted, ms, callback) {
        if (device.connected === wanted) {
            callback(true);
            return;
        }
        let id = 0;
        let timer = 0;
        const finish = ok => {
            if (id)
                device.disconnect(id);
            id = 0;
            if (timer) {
                GLib.Source.remove(timer);
                this._btTimers.delete(timer);
            }
            timer = 0;
            callback(ok);
        };
        id = device.connect('notify::connected', () => {
            if (device.connected === wanted)
                finish(true);
        });
        timer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, ms, () => {
            this._btTimers.delete(timer);
            timer = 0;
            finish(device.connected === wanted);
            return GLib.SOURCE_REMOVE;
        });
        this._btTimers.add(timer);
    }

    _btLater(ms, fn) {
        const id = GLib.timeout_add(GLib.PRIORITY_DEFAULT, ms, () => {
            this._btTimers.delete(id);
            fn();
            return GLib.SOURCE_REMOVE;
        });
        this._btTimers.add(id);
    }

    _btDeviceByPath(path) {
        const client = this._btClient();
        if (!client)
            return null;
        const store = client.get_devices();
        for (let i = 0; i < store.get_n_items(); i++) {
            const device = store.get_item(i);
            if (device.get_object_path() === path)
                return device;
        }
        return null;
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
        // Pairing pages the device too; the scan has found it already.
        this._stopBtScan();
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

                    const paired = this._btDeviceByPath(path);
                    if (!paired) {
                        this._finishPairing(path, null);
                        return;
                    }
                    this._btConnect(paired, true, error =>
                        this._finishPairing(path, error ? `Paired. ${error}` : null));
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
        this._syncEditPage();
    }

    _syncEditPage() {
        const page = this._pages.edit;
        const order = this._tileOrder();
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
                this._syncEditPage();
            },
        }));
        rows.push(makeRow({
            icon: 'edit-undo-symbolic',
            title: 'Reset to Default',
            onActivate: () => {
                writeConfig({ tiles: null, showMedia: true });
                this._layoutTiles();
                this._syncEditPage();
            },
        }));

        this._fillPage(page, rows);
    }

    // -------------------------------------------------------- now playing

    _buildMediaCard() {
        const actor = new St.BoxLayout({
            style_class: 'adaptive-cc-media',
            x_expand: true,
            visible: false,
        });

        const art = new St.Icon({
            style_class: 'adaptive-cc-media-art',
            icon_size: 44,
            fallback_icon_name: 'audio-x-generic-symbolic',
        });
        actor.add_child(new St.Bin({
            style_class: 'adaptive-cc-media-art-bin',
            child: art,
            y_align: Clutter.ActorAlign.CENTER,
        }));

        // The text raises the player, the way tapping Now Playing does on a Mac.
        const body = new St.Button({
            style_class: 'adaptive-cc-media-body',
            can_focus: true,
            x_expand: true,
        });
        const text = new St.BoxLayout({ vertical: true, x_expand: true, y_align: Clutter.ActorAlign.CENTER });
        const title = new St.Label({ style_class: 'adaptive-cc-media-title' });
        const artist = new St.Label({ style_class: 'adaptive-cc-media-artist' });
        const app = new St.Label({ style_class: 'adaptive-cc-media-app' });
        text.add_child(title);
        text.add_child(artist);
        text.add_child(app);
        body.set_child(text);
        body.connect('clicked', () => {
            const player = this._currentPlayer();
            if (player) {
                this._closeMenu();
                player.raise();
            }
        });
        actor.add_child(body);

        const control = (icon, name, fn) => {
            const button = new St.Button({
                style_class: 'adaptive-cc-media-button',
                can_focus: true,
                accessible_name: name,
                child: new St.Icon({ icon_name: icon }),
                y_align: Clutter.ActorAlign.CENTER,
            });
            button.connect('clicked', () => {
                const player = this._currentPlayer();
                if (player)
                    fn(player);
            });
            actor.add_child(button);
            return button;
        };
        const prev = control('media-skip-backward-symbolic', 'Previous', p => p.previous());
        const play = control('media-playback-start-symbolic', 'Play', p => p.playPause());
        const next = control('media-skip-forward-symbolic', 'Next', p => p.next());
        play.add_style_class_name('adaptive-cc-media-play');

        this._media = { actor, art, title, artist, app, prev, play, next };
        this._players = new Map();
        return actor;
    }

    // MPRIS players come and go with their apps; the list of bus names is read
    // when the panel opens and followed while it stays open.
    _startMpris() {
        this._stopMpris();

        Gio.DBus.session.call('org.freedesktop.DBus', '/org/freedesktop/DBus',
            'org.freedesktop.DBus', 'ListNames', null, new GLib.VariantType('(as)'),
            Gio.DBusCallFlags.NONE, -1, null, (conn, res) => {
                try {
                    const [names] = conn.call_finish(res).deep_unpack();
                    for (const name of names) {
                        if (name.startsWith('org.mpris.MediaPlayer2.'))
                            this._addPlayer(name);
                    }
                } catch (e) {
                    logError(e, '[Adaptive Control Center] listing media players');
                }
                this._syncMedia();
            });

        this._mprisSub = Gio.DBus.session.signal_subscribe('org.freedesktop.DBus',
            'org.freedesktop.DBus', 'NameOwnerChanged', '/org/freedesktop/DBus',
            'org.mpris.MediaPlayer2', Gio.DBusSignalFlags.MATCH_ARG0_NAMESPACE,
            (_c, _s, _p, _i, _sig, params) => {
                const [name, , newOwner] = params.deep_unpack();
                if (newOwner)
                    this._addPlayer(name);
            });
    }

    _stopMpris() {
        if (this._mprisSub) {
            Gio.DBus.session.signal_unsubscribe(this._mprisSub);
            this._mprisSub = 0;
        }
    }

    _addPlayer(name) {
        if (this._players.has(name))
            return;
        try {
            const player = new Mpris.MprisPlayer(name);
            const ids = [
                player.connect('changed', () => this._syncMedia()),
                player.connect('closed', () => {
                    for (const id of ids)
                        player.disconnect(id);
                    this._players.delete(name);
                    this._syncMedia();
                }),
            ];
            this._players.set(name, player);
        } catch (e) {
            logError(e, `[Adaptive Control Center] media player ${name}`);
        }
    }

    // The one playing, else the most recently seen one with a track.
    _currentPlayer() {
        const players = [...this._players.values()].filter(p => {
            try {
                return p._playerProxy && p.trackTitle && p._visible !== false;
            } catch (e) {
                return false;
            }
        });
        return players.find(p => p.status === 'Playing') || players[players.length - 1] || null;
    }

    _syncMedia() {
        const media = this._media;
        if (!media)
            return;

        const player = this._currentPlayer();
        const show = !!player && readConfig().showMedia !== false;
        media.actor.visible = show;
        if (!show)
            return;

        media.title.text = player.trackTitle || 'Unknown title';
        const artists = Array.isArray(player.trackArtists) ? player.trackArtists.join(', ') : '';
        media.artist.text = artists;
        media.artist.visible = !!artists;

        let appName = '';
        try {
            appName = (player._mprisProxy && player._mprisProxy.Identity) || '';
        } catch (e) {
        }
        media.app.text = appName;
        media.app.visible = !!appName;

        const url = player.trackCoverUrl || '';
        if (url.startsWith('file://')) {
            media.art.gicon = new Gio.FileIcon({ file: Gio.File.new_for_uri(url) });
        } else if (url.startsWith('http')) {
            // Remote art is not fetched from inside the shell.
            media.art.gicon = null;
            media.art.icon_name = 'audio-x-generic-symbolic';
        } else {
            media.art.gicon = null;
            media.art.icon_name = 'audio-x-generic-symbolic';
        }

        const playing = player.status === 'Playing';
        media.play.child.icon_name = playing ? 'media-playback-pause-symbolic' : 'media-playback-start-symbolic';
        media.play.accessible_name = playing ? 'Pause' : 'Play';

        for (const [button, can] of [[media.prev, player.canGoPrevious], [media.next, player.canGoNext]]) {
            button.reactive = !!can;
            if (can)
                button.remove_style_pseudo_class('insensitive');
            else
                button.add_style_pseudo_class('insensitive');
        }
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
                const name = appNameForPid(pid);
                if (name && !/^(pipewire|wireplumber)$/.test(name))
                    names.add(friendlyAppName(null, name));
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

    // ----------------------------------------------------------- tailscale

    _tsRefresh() {
        if (this._tsBusy)
            return;
        if (!GLib.find_program_in_path('tailscale')) {
            this._ts = { installed: false };
            return;
        }
        this._tsBusy = true;
        run(['tailscale', 'status', '--json'], (_ok, out) => {
            this._tsBusy = false;
            let status = null;
            try {
                status = JSON.parse(out);
            } catch (e) {
            }
            this._ts = status ? {
                installed: true,
                state: status.BackendState,
                self: status.Self || {},
                ips: status.TailscaleIPs || (status.Self && status.Self.TailscaleIPs) || [],
                peers: Object.values(status.Peer || {}),
            } : { installed: true, state: 'Unknown', self: {}, ips: [], peers: [] };
            this._queueSync();
        });
    }

    _toggleTailscale() {
        const ts = this._ts;
        if (!ts || !ts.installed || this._tsPending)
            return;

        this._tsPending = true;
        this._tsError = null;
        this._queueSync();

        if (ts.state === 'Running') {
            run(['tailscale', 'down'], (ok, out, err) => this._tsDone(ok, `${out}${err}`));
            return;
        }

        // `tailscale up` waits for a browser login when one is needed and
        // prints the URL to visit; open it for the user as soon as it appears.
        let output = '';
        try {
            const proc = Gio.Subprocess.new(['tailscale', 'up'],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE);
            const stream = new Gio.DataInputStream({ base_stream: proc.get_stdout_pipe() });
            const readLine = () => {
                stream.read_line_async(GLib.PRIORITY_DEFAULT, null, (s, res) => {
                    let line = null;
                    try {
                        [line] = s.read_line_finish_utf8(res);
                    } catch (e) {
                    }
                    if (line === null)
                        return;
                    output += `${line}\n`;
                    const url = line.match(/https:\/\/login\.tailscale\.com\/\S+/);
                    if (url) {
                        this._closeMenu();
                        try {
                            Gio.AppInfo.launch_default_for_uri(url[0], null);
                        } catch (e) {
                            logError(e, '[Adaptive Control Center] opening the Tailscale login');
                        }
                    }
                    readLine();
                });
            };
            readLine();
            proc.wait_check_async(null, (p, res) => {
                let ok = false;
                try {
                    ok = p.wait_check_finish(res);
                } catch (e) {
                }
                this._tsDone(ok, output);
            });
        } catch (e) {
            this._tsDone(false, e.message);
        }
    }

    _tsDone(ok, output) {
        this._tsPending = false;
        if (!ok && /access denied|checkprefs|operator|permission/i.test(output || ''))
            this._tsError = 'permission';
        else if (!ok)
            this._tsError = 'failed';
        this._tsRefresh();
    }

    _syncTailscaleTile() {
        const tile = this._tiles.tailscale;
        const ts = this._ts;
        if (!ts) {
            tile.update({ subtitle: '…' });
            return;
        }
        if (!ts.installed) {
            tile.update({ subtitle: 'Not installed', sensitive: false });
            return;
        }

        const ipv4 = (ts.ips || []).find(ip => ip.includes('.'));
        let subtitle = {
            Running: ipv4 || 'Connected',
            Stopped: 'Off',
            NeedsLogin: 'Signed out',
            NeedsMachineAuth: 'Awaiting approval',
            Starting: 'Connecting…',
        }[ts.state] || ts.state || 'Unknown';
        if (this._tsPending)
            subtitle = ts.state === 'Running' ? 'Disconnecting…' : 'Connecting…';
        else if (this._tsError === 'permission')
            subtitle = 'Needs one-time setup';

        tile.update({ active: ts.state === 'Running', subtitle });
    }

    _syncTailscalePage() {
        const page = this._pages.tailscale;
        const ts = this._ts;

        if (!ts) {
            this._fillPage(page, [], 'Checking Tailscale…');
            return;
        }
        if (!ts.installed) {
            this._fillPage(page, [], 'Tailscale is not installed.');
            return;
        }

        const rows = [];

        if (this._tsError === 'permission') {
            const command = 'sudo tailscale set --operator=$USER';
            rows.push(this._makeConfirmForm({
                prompt: 'To switch Tailscale from here, allow your user to control it. ' +
                    'Run this once in a terminal:',
                code: command,
                cancelLabel: 'Copy Command',
                onCancel: () => {
                    St.Clipboard.get_default().set_text(St.ClipboardType.CLIPBOARD, command);
                    this._tsError = null;
                    this._syncTailscalePage();
                },
            }));
        }

        if (ts.state === 'NeedsLogin') {
            rows.push(makeRow({
                icon: 'avatar-default-symbolic',
                title: 'Sign in to Tailscale',
                subtitle: 'Opens the login page in your browser',
                onActivate: () => this._toggleTailscale(),
            }));
        } else if (ts.state === 'Running') {
            const self = ts.self || {};
            rows.push(this._copyRow({
                icon: 'computer-symbolic',
                title: `${self.HostName || 'This computer'} (this device)`,
                value: (ts.ips || []).find(ip => ip.includes('.')) || '',
            }));

            const peers = (ts.peers || []).slice().sort((a, b) =>
                (b.Online - a.Online) || (a.HostName || '').localeCompare(b.HostName || ''));
            if (peers.length) {
                rows.push(makeHeading('Devices'));
                for (const peer of peers) {
                    const ip = (peer.TailscaleIPs || []).find(x => x.includes('.')) || '';
                    rows.push(this._copyRow({
                        icon: /android|ios/i.test(peer.OS || '') ? 'phone-symbolic' : 'computer-symbolic',
                        title: peer.HostName || peer.DNSName || 'Device',
                        value: ip,
                        suffix: peer.Online ? 'Online' : 'Offline',
                        dim: !peer.Online,
                    }));
                }
            }
        }

        const status = {
            Stopped: 'Tailscale is off. Tap the tile to connect.',
            NeedsMachineAuth: 'This device is waiting for approval in the admin console.',
        }[ts.state] || (this._tsError === 'failed' ? "Couldn't change Tailscale." : '');

        this._fillPage(page, rows, status);
    }

    // A row whose value is copied when tapped, and which says so.
    _copyRow({ icon, title, value, suffix = '', dim = false }) {
        const copied = this._copiedValue === value && value;
        const subtitle = copied ? 'Copied to clipboard'
            : [value, suffix].filter(Boolean).join(' · ');
        const row = makeRow({
            icon,
            title,
            subtitle,
            trailing: value ? ['edit-copy-symbolic'] : [],
            onActivate: value ? () => {
                St.Clipboard.get_default().set_text(St.ClipboardType.CLIPBOARD, value);
                this._copiedValue = value;
                this._syncPage();
                GLib.timeout_add(GLib.PRIORITY_DEFAULT, 1200, () => {
                    if (this._copiedValue === value) {
                        this._copiedValue = null;
                        if (this._menu && this._menu.isOpen)
                            this._syncPage();
                    }
                    return GLib.SOURCE_REMOVE;
                });
            } : null,
        });
        if (dim)
            row.add_style_class_name('adaptive-cc-row-dim');
        return row;
    }

    // ------------------------------------------------------------- display

    _syncDisplayPage() {
        const page = this._pages.display;
        const monitors = Main.layoutManager.monitors || [];
        const primary = Main.layoutManager.primaryIndex;
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

        if (!manager || !manager.can_switch_config()) {
            this._fillPage(page, rows, monitors.length < 2
                ? 'Connect another display to extend or mirror your screen.' : '');
            return;
        }

        const current = manager.get_switch_config();
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

    // --------------------------------------------------------------- sound

    _syncSoundPage(force = false) {
        const page = this._pages.sound;
        if (!force && this._holdForPointer(page))
            return;

        const sink = this._mixer.get_default_sink();
        const source = this._mixer.get_default_source();
        const sinks = this._mixer.get_sinks() || [];
        const sources = (this._mixer.get_sources() || [])
            .filter(s => !/\.monitor$/.test(s.get_name() || ''));
        const apps = (this._mixer.get_sink_inputs() || []).filter(s => !s.is_event_stream);

        // Per-app sliders are dragged in place; rebuilding the list would drop
        // the drag, so only a change in what is listed rebuilds it.
        const signature = [
            sinks.map(s => s.get_id()).join(','), sink ? sink.get_id() : '',
            sources.map(s => s.get_id()).join(','), source ? source.get_id() : '',
            apps.map(s => `${s.get_id()}:${s.get_name()}`).join(','),
        ].join('|');
        if (!force && signature === this._soundSignature && page.list.get_n_children() > 0)
            return;
        this._soundSignature = signature;

        const rows = [makeHeading('Output')];
        for (const s of sinks) {
            const active = !!sink && s.get_id() === sink.get_id();
            const { title, subtitle, icon } = describeSink(this._mixer, s);
            rows.push(makeRow({
                icon, title, subtitle,
                trailing: active ? ['object-select-symbolic'] : [],
                active,
                onActivate: active ? null : () => {
                    this._mixer.set_default_sink(s);
                    this._queueSync();
                },
            }));
        }

        if (sources.length) {
            rows.push(makeHeading('Input'));
            for (const s of sources) {
                const active = !!source && s.get_id() === source.get_id();
                const { title, subtitle } = describeSink(this._mixer, s);
                rows.push(makeRow({
                    icon: /head(set|phone)/i.test(title) ? 'audio-headset-symbolic' : 'audio-input-microphone-symbolic',
                    title, subtitle,
                    trailing: active ? ['object-select-symbolic'] : [],
                    active,
                    onActivate: active ? null : () => {
                        this._mixer.set_default_source(s);
                        this._queueSync();
                    },
                }));
            }
        }

        if (apps.length) {
            rows.push(makeHeading('Apps'));
            for (const stream of apps)
                rows.push(this._appVolumeRow(stream));
        }

        this._fillPage(page, rows, sinks.length ? '' : 'No sound outputs were found.');
    }

    _appVolumeRow(stream) {
        const id = stream.get_application_id() || '';
        const app = id ? Shell.AppSystem.get_default().lookup_app(`${id}.desktop`) : null;
        const name = friendlyAppName(id, stream.get_name() || 'App');
        const max = this._mixer.get_vol_max_norm();

        const row = new St.BoxLayout({ style_class: 'adaptive-cc-app-volume', x_expand: true });

        const mute = new St.Button({
            style_class: 'adaptive-cc-slider-icon-button',
            can_focus: true,
            accessible_name: `Mute ${name}`,
            child: app ? app.create_icon_texture(20)
                : new St.Icon({ icon_name: stream.get_icon_name() || 'applications-multimedia-symbolic', icon_size: 20 }),
            y_align: Clutter.ActorAlign.CENTER,
        });
        if (stream.is_muted)
            mute.add_style_pseudo_class('checked');
        mute.connect('clicked', () => {
            stream.change_is_muted(!stream.is_muted);
            if (!stream.is_muted)
                mute.add_style_pseudo_class('checked');
            else
                mute.remove_style_pseudo_class('checked');
        });
        row.add_child(mute);

        const column = new St.BoxLayout({ vertical: true, x_expand: true, y_align: Clutter.ActorAlign.CENTER });
        column.add_child(new St.Label({ text: name, style_class: 'adaptive-cc-app-volume-name' }));
        const slider = new Slider.Slider(stream.is_muted ? 0 : Math.min(stream.volume / max, 1));
        slider.add_style_class_name('adaptive-cc-slider');
        slider.accessible_name = `${name} volume`;
        slider.connect('notify::value', () => {
            stream.volume = slider.value * max;
            if (stream.is_muted && slider.value > 0)
                stream.change_is_muted(false);
            stream.push_volume();
        });
        column.add_child(slider);
        row.add_child(column);
        return row;
    }

    // --------------------------------------------------- ethernet & share

    _ethernetRows(client) {
        const devices = client.get_devices().filter(d =>
            d.get_device_type() === NM.DeviceType.ETHERNET && d.get_managed());
        if (!devices.length)
            return [];

        const S = NM.DeviceState;
        const rows = [makeHeading('Ethernet')];
        for (const device of devices) {
            const state = device.get_state();
            const busy = state > S.DISCONNECTED && state < S.ACTIVATED;
            let subtitle;
            if (state === S.ACTIVATED) {
                const address = device.get_ip4_config() &&
                    device.get_ip4_config().get_addresses()[0];
                subtitle = address ? `Connected · ${address.get_address()}` : 'Connected';
            } else if (state === S.IP_CONFIG) {
                subtitle = 'Getting an IP address…';
            } else if (busy) {
                subtitle = 'Connecting…';
            } else if (state === S.UNAVAILABLE) {
                subtitle = 'Cable unplugged';
            } else if (state === S.FAILED) {
                subtitle = "Couldn't connect";
            } else {
                subtitle = 'Not connected';
            }

            const product = (device.get_product() || '').replace(/\s+/g, ' ').trim();
            rows.push(makeRow({
                icon: 'network-wired-symbolic',
                title: product ? `${product}` : 'Ethernet',
                subtitle: `${device.get_iface()} · ${subtitle}`,
                active: state === S.ACTIVATED,
                trailing: state === S.ACTIVATED ? ['object-select-symbolic'] : [],
                action: state === S.ACTIVATED || busy ? {
                    label: busy ? 'Stop' : 'Disconnect',
                    onClick: () => device.disconnect_async(null, null),
                } : null,
                onActivate: state === S.DISCONNECTED || state === S.FAILED
                    ? () => client.activate_connection_async(null, device, null, null, null)
                    : null,
            }));
        }
        return rows;
    }

    // "Share": a QR code a phone camera can join from, and the password.
    _shareForm(network, device) {
        const box = new St.BoxLayout({
            style_class: 'adaptive-cc-form adaptive-cc-share',
            vertical: true,
            x_expand: true,
        });

        const share = this._wifiShare;
        if (!share || share.name !== network.name)
            return box;

        if (share.error) {
            box.add_child(new St.Label({ text: share.error, style_class: 'adaptive-cc-form-prompt' }));
        } else if (share.password === undefined) {
            box.add_child(new St.Label({ text: 'Getting the password…', style_class: 'adaptive-cc-form-prompt' }));
        } else {
            const escape = s => s.replace(/([\;,:"])/g, '\\$1');
            const type = share.password ? 'WPA' : 'nopass';
            const payload = `WIFI:T:${type};S:${escape(network.name)};` +
                (share.password ? `P:${escape(share.password)};` : '') + ';';
            try {
                box.add_child(new QrCode.QrCodeActor(payload, 176));
            } catch (e) {
                logError(e, '[Adaptive Control Center] QR code');
            }
            box.add_child(new St.Label({
                text: `Point a phone camera at the code to join “${network.name}”.`,
                style_class: 'adaptive-cc-form-prompt adaptive-cc-share-caption',
                x_align: Clutter.ActorAlign.CENTER,
            }));

            if (share.password) {
                const passwordLabel = new St.Label({
                    text: share.reveal ? share.password : '•'.repeat(Math.min(share.password.length, 16)),
                    style_class: 'adaptive-cc-form-code adaptive-cc-share-password',
                    x_align: Clutter.ActorAlign.CENTER,
                });
                passwordLabel.clutter_text.line_wrap = true;
                box.add_child(passwordLabel);
            }
        }

        const buttons = new St.BoxLayout({
            style_class: 'adaptive-cc-form-buttons',
            x_align: Clutter.ActorAlign.END,
        });
        box.add_child(buttons);
        const button = (label, primary, fn) => {
            const b = new St.Button({
                style_class: primary ? 'adaptive-cc-form-button adaptive-cc-form-primary' : 'adaptive-cc-form-button',
                label,
                can_focus: true,
            });
            b.connect('clicked', fn);
            buttons.add_child(b);
            return b;
        };
        if (share.password) {
            button(share.reveal ? 'Hide' : 'Show', false, () => {
                share.reveal = !share.reveal;
                this._syncWifiPage(true);
            });
            const copyButton = button('Copy Password', false, () => {
                St.Clipboard.get_default().set_text(St.ClipboardType.CLIPBOARD, share.password);
                copyButton.label = 'Copied';
            });
        }
        box._entry = button('Done', true, () => {
            this._wifiShare = null;
            this._syncWifiPage(true);
        });
        return box;
    }

    _startShare(network, device) {
        if (this._wifiShare && this._wifiShare.name === network.name) {
            this._wifiShare = null;
            this._syncWifiPage(true);
            return;
        }

        const share = { name: network.name, password: undefined, reveal: false, error: null };
        this._wifiShare = share;
        this._syncWifiPage(true);

        const active = device.get_active_connection();
        const remote = active ? active.get_connection() : network.connections[0];
        if (!remote) {
            share.error = "This network's details aren't available.";
            this._syncWifiPage(true);
            return;
        }

        const security = remote.get_setting_wireless_security();
        if (!security) {
            share.password = '';
            this._syncWifiPage(true);
            return;
        }

        remote.get_secrets_async('802-11-wireless-security', null, (c, res) => {
            try {
                const secrets = c.get_secrets_finish(res).recursiveUnpack();
                const wsec = secrets['802-11-wireless-security'] || {};
                share.password = wsec.psk || wsec['wep-key0'] || '';
                if (!share.password)
                    share.error = "The password isn't stored on this computer.";
            } catch (e) {
                share.error = "Couldn't read the saved password.";
                log(`[Adaptive Control Center] Wi-Fi secrets: ${e.message}`);
            }
            if (this._wifiShare === share)
                this._syncWifiPage(true);
        });
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
