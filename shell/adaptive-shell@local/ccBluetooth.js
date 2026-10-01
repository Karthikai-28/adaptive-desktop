// Adaptive Control Center - Bluetooth devices and pairing.
//
// Part of the one ControlCenter object in controlCenter.js, kept in its own
// file by subject. The methods of the class below are copied onto that object
// when the extension loads, so `this` here is the Control Center itself.

/* exported CcBluetooth */

const { Gio, GLib } = imports.gi;

const Me = imports.misc.extensionUtils.getCurrentExtension();
const CcUtil = Me.imports.ccUtil;
const {
    BT_SCAN_S,
    BT_CONNECT_ATTEMPTS,
    BT_RETRY_MS,
    BT_SETTLE_MS,
    ignoreReply,
    AGENT_PATH,
    AGENT_XML,
    btFailureText,
    pairingError,
    makeHeading,
    makeRow,
} = CcUtil;

var CcBluetooth = class CcBluetooth {
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
        // Forced: the pointer is on the row that was just tapped, and the
        // hold-still rule must not hide that row's own "Connecting…".
        this._btRefresh();

        this._btConnect(device, connect, error => {
            this._btPending.delete(path);
            if (error)
                this._btErrors.set(path, error);
            this._btRefresh();
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

    // Show the outcome of something the user did right away - list and tile.
    _btRefresh() {
        this._btSignature = null;
        if (this._menu && this._menu.isOpen && this._open === 'bluetooth')
            this._syncBluetoothPage(true);
        this._queueSync();
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
                        null, Gio.DBusCallFlags.NONE, -1, null, ignoreReply);

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
            null, Gio.DBusCallFlags.NONE, -1, null, ignoreReply);
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
                'CancelPairing', null, null, Gio.DBusCallFlags.NONE, -1, null, ignoreReply);
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
};
