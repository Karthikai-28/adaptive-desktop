// Adaptive Control Center - what its parts share.
//
// The constants, small readers and widget builders used across the Control
// Center's files (controlCenter.js and the cc*.js parts beside it). Everything
// here is declared with `var` or `function`, which is what a GJS module
// exports; the parts take what they need by name at the top of each file.

/* exported BATTERY_ATTRS, readBattery, NM, LIST_MAX_HEIGHT, DROPDOWN_FADE_MS, SHARE_MAX_HEIGHT, WIFI_SCAN_INTERVAL_S, MAX_NETWORKS, CAMERA_POLL_S, BT_SCAN_S, BT_CONNECT_ATTEMPTS, BT_RETRY_MS, BT_SETTLE_MS, UI_MODE_SCREENCAST, DEFAULT_TILES, TILE_DROPDOWNS, CONFIG_PATH, readConfig, writeConfig, run, appNameForPid, friendlyAppName, extensionIcon, ignoreReply, INHIBIT_SUSPEND_AND_IDLE, PROFILES, profileIcon, iconProps, AGENT_PATH, AGENT_XML, btFailureText, pairingError, BATTERY_CHARGING, BATTERY_FULL, signalLevel, ssidName, apSecured, apEnterprise, volumeIcon, describeSink, makeHeading, makeRoundButton, makeRow, Tile */

const { Clutter, Gio, GLib, Shell, St } = imports.gi;

const Me = imports.misc.extensionUtils.getCurrentExtension();

var BATTERY_ATTRS = [
    'energy_full', 'energy_full_design', 'charge_full', 'charge_full_design',
    'cycle_count', 'charge_control_end_threshold',
];

// The first battery's health attributes as strings; {} without a battery.
// Small sysfs reads, made only when the power dropdown syncs.
function readBattery() {
    const values = {};
    try {
        const dir = Gio.File.new_for_path('/sys/class/power_supply');
        const children = dir.enumerate_children('standard::name', Gio.FileQueryInfoFlags.NONE, null);
        let info;
        let battery = null;
        while (!battery && (info = children.next_file(null))) {
            if (/^BAT/.test(info.get_name()))
                battery = dir.get_child(info.get_name());
        }
        children.close(null);
        if (!battery)
            return values;
        for (const attr of BATTERY_ATTRS) {
            try {
                const [ok, bytes] = GLib.file_get_contents(battery.get_child(attr).get_path());
                if (ok)
                    values[attr] = new TextDecoder().decode(bytes).trim();
            } catch (e) {
                // Not every battery reports every attribute.
            }
        }
    } catch (e) {
        logError(e, '[Adaptive Control Center] reading battery health');
    }
    return values;
}

// NetworkManager is optional at build time in GNOME; without it the Wi-Fi
// tile just reports itself unavailable.
var NM = null;
try {
    NM = imports.gi.NM;
} catch (e) {
    NM = null;
}

// Tallest a dropdown list grows before it scrolls.
var LIST_MAX_HEIGHT = 264;
var DROPDOWN_FADE_MS = 140;
// The Wi-Fi share card (QR code, password, buttons) needs more room than a list.
var SHARE_MAX_HEIGHT = 500;
var WIFI_SCAN_INTERVAL_S = 15;
var MAX_NETWORKS = 24;

var CAMERA_POLL_S = 3;

// Bluetooth. A scan runs for a window rather than for as long as the dropdown
// is open; connecting retries what a device just out of its case typically
// answers with, then waits a moment in case it connects itself.
var BT_SCAN_S = 30;
var BT_CONNECT_ATTEMPTS = 3;
var BT_RETRY_MS = 1500;
var BT_SETTLE_MS = 5000;
// imports.ui.screenshot keeps its UIMode private; SCREENCAST is 1.
var UI_MODE_SCREENCAST = 1;

// Tiles in their default order. The saved order (Edit Controls) lives in
// ~/.config/adaptive-desktop/control-center.json.
var DEFAULT_TILES = [
    'wifi', 'bluetooth', 'power', 'nightLight', 'dnd',
    'airplane', 'awake', 'mic', 'tailscale',
];
// Tiles whose arrow opens a dropdown, and which one.
var TILE_DROPDOWNS = {
    wifi: 'wifi', bluetooth: 'bluetooth', power: 'power', tailscale: 'tailscale',
};

var CONFIG_PATH = GLib.build_filenamev(
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
            return { name: app.get_name(), isApp: true };
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
        return { name: new TextDecoder().decode(bytes).trim(), isApp: false };
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

    // Only accept a search hit that is plainly the same app: its name or id
    // contains the word. A looser match turned "bash" into an unrelated app.
    const needle = word.toLowerCase();
    try {
        const heuristic = typeof system.lookup_heuristic_basename === 'function'
            ? system.lookup_heuristic_basename(needle) : null;
        if (heuristic)
            return heuristic.get_name();
        for (const group of Shell.AppSystem.search(word) || []) {
            for (const id of group) {
                const app = system.lookup_app(id);
                if (app && (app.get_name().toLowerCase().includes(needle) ||
                    id.toLowerCase().includes(needle)))
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

// Callback for D-Bus calls whose reply nobody needs. It has to be a real
// function: GNOME promisifies DBusConnection.call, and a null callback makes
// the wrapper add its own (an 11th argument, logged as a warning each time).
function ignoreReply(connection, result) {
    try {
        connection.call_finish(result);
    } catch (e) {
        // Fire-and-forget; failure here changes nothing.
    }
}

// org.gnome.SessionManager.Inhibit flags: suspend | idle.
var INHIBIT_SUSPEND_AND_IDLE = 4 | 8;

var PROFILES = {
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
var AGENT_PATH = '/org/adaptive/shell/BluetoothAgent';
var AGENT_XML = `<node>
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
        return 'No answer. Is it on and out of its case?';
    if (/busy|InProgress/i.test(message))
        return 'Busy with another device. Try again.';
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
var BATTERY_CHARGING = 1;
var BATTERY_FULL = 4;

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

    for (const name of trailing) {
        box.add_child(new St.Icon({
            icon_name: name,
            style_class: name === 'object-select-symbolic'
                ? 'adaptive-cc-row-check' : 'adaptive-cc-row-trailing',
            y_align: Clutter.ActorAlign.CENTER,
        }));
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
