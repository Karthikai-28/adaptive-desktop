// Adaptive Control Center - Wi-Fi, its password and hotspot forms, Ethernet, sharing and Tailscale.
//
// Part of the one ControlCenter object in controlCenter.js, kept in its own
// file by subject. The methods of the class below are copied onto that object
// when the extension loads, so `this` here is the Control Center itself.

/* exported CcNetwork */

const { Clutter, Gio, GLib, St } = imports.gi;
const Util = imports.misc.util;

const Me = imports.misc.extensionUtils.getCurrentExtension();
const QrCode = Me.imports.qrcode;
const CcUtil = Me.imports.ccUtil;
const {
    NM,
    LIST_MAX_HEIGHT,
    SHARE_MAX_HEIGHT,
    WIFI_SCAN_INTERVAL_S,
    MAX_NETWORKS,
    run,
    signalLevel,
    ssidName,
    apSecured,
    apEnterprise,
    makeHeading,
    makeRow,
} = CcUtil;

var CcNetwork = class CcNetwork {
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
            if (network.active && this._wifiShare && this._wifiShare.name === network.name) {
                shareCard = this._shareForm(network, device);
                rows.push(shareCard);
            }
        };
        let shareCard = null;

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

        this._fillPage(page, rows, rows.length ? '' : 'Searching for networks…',
            shareCard ? SHARE_MAX_HEIGHT : LIST_MAX_HEIGHT);
        if (form)
            this._focusForm(page, form);
        else if (shareCard)
            this._focusForm(page, shareCard);
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
        if (this._unchanged(page, JSON.stringify([ts.state, ts.ips, ts.self.HostName,
            (ts.peers || []).map(p => [p.HostName, p.Online, p.TailscaleIPs]),
            this._tsError, this._copiedValue]), false))
            return;

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
};
