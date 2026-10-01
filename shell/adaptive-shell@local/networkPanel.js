// Adaptive Network panel
//
// A top-bar indicator next to Tasks: this computer's place on the network
// (addresses, router and its latency, DNS, Wi-Fi link, VPN tunnels, internet
// reachability) and every device answering on the local network, named where
// the network says who they are.
//
// The facts and the scan come from tools/network_info.py as JSON; the scan
// runs when the panel opens (at most once a minute) or on Scan, and takes a
// few seconds. The public IP is the one thing that asks an outside service,
// so it is only fetched when its button is pressed. Clicking any value or
// device copies its address.
//
// Paired phones (KDE Connect or GSConnect) are listed too, with their battery
// and Ring / Send file; tools/phone_info.py asks the session bus.

/* exported NetworkPanel */

const { Clutter, Gio, GLib, St } = imports.gi;
const Main = imports.ui.main;
const PanelMenu = imports.ui.panelMenu;

const Me = imports.misc.extensionUtils.getCurrentExtension();
const CC = Me.imports.ccUtil;

const HELPER = Me.dir.get_child('tools').get_child('network_info.py').get_path();
const SSH_HELPER = Me.dir.get_child('tools').get_child('ssh_connect.py').get_path();
const PHONE_HELPER = Me.dir.get_child('tools').get_child('phone_info.py').get_path();
const RESCAN_AFTER_S = 60;
const LIST_MAX_HEIGHT = 640;
const COPIED_MS = 1100;

const KIND_ICONS = {
    router: 'network-wireless-symbolic',
    computer: 'computer-symbolic',
    phone: 'phone-symbolic',
    tv: 'video-display-symbolic',
    printer: 'printer-symbolic',
    smart: 'preferences-system-symbolic',
    board: 'media-flash-symbolic',
    device: 'network-wired-symbolic',
};

function copy(text) {
    St.Clipboard.get_default().set_text(St.ClipboardType.CLIPBOARD, text);
}

function ago(seconds) {
    if (seconds < 10)
        return 'just now';
    if (seconds < 60)
        return `${Math.round(seconds)} s ago`;
    return `${Math.round(seconds / 60)} min ago`;
}

var NetworkPanel = class NetworkPanel {
    constructor() {
        this._button = null;
        this._openStateId = 0;
        this._sessionId = 0;
        this._info = null;
        this._scan = null;
        this._scannedAt = 0;
        this._scanning = false;
        this._publicIp = null;
        this._publicBusy = false;
        // The device being logged in to: { ip, user, password, busy, form, error }.
        this._ssh = null;
        // { backend, devices } from phone_info.py, and a per-phone status line.
        this._phones = null;
        this._phoneNote = {};
    }

    attach() {
        this._button = new PanelMenu.Button(0.5, 'Network', false);
        this._button.add_child(new St.Icon({
            icon_name: 'network-workgroup-symbolic',
            style_class: 'system-status-icon',
        }));

        this._button.menu.box.add_style_class_name('adaptive-cc-menu');
        const root = new St.BoxLayout({
            style_class: 'adaptive-cc adaptive-network',
            vertical: true,
            x_expand: true,
        });
        this._button.menu.box.add_child(root);

        const header = new St.BoxLayout({ style_class: 'adaptive-usb-header', x_expand: true });
        header.add_child(new St.Label({
            text: 'Network',
            style_class: 'adaptive-usb-title',
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        }));
        this._summary = new St.Label({
            style_class: 'adaptive-usb-summary',
            y_align: Clutter.ActorAlign.CENTER,
        });
        header.add_child(this._summary);
        root.add_child(header);

        this._scroll = new St.ScrollView({
            style_class: 'adaptive-cc-scroll vfade',
            overlay_scrollbars: true,
            x_expand: true,
        });
        this._scroll.set_policy(St.PolicyType.NEVER, St.PolicyType.AUTOMATIC);
        this._list = new St.BoxLayout({
            style_class: 'adaptive-cc-list',
            vertical: true,
            x_expand: true,
        });
        this._scroll.add_actor(this._list);
        root.add_child(this._scroll);

        // Just left of Tasks (or of whatever is leftmost of ours).
        const rightBox = Main.panel._rightBox;
        const neighbour = Main.panel.statusArea['adaptive-tasks'] ||
            Main.panel.statusArea['adaptive-usb'] || Main.panel.statusArea.aggregateMenu;
        const index = neighbour ? Math.max(0, rightBox.get_children().indexOf(neighbour.container)) : 0;
        Main.panel.addToStatusArea('adaptive-network', this._button, index, 'right');

        this._openStateId = this._button.menu.connect('open-state-changed', (_m, open) => {
            if (!open)
                return;
            this._loadInfo();
            this._loadPhones();
            if (GLib.get_monotonic_time() / 1e6 - this._scannedAt > RESCAN_AFTER_S)
                this._runScan();
            this._render();
        });
        this._sessionId = Main.sessionMode.connect('updated', () => this._syncSession());
        this._syncSession();
        log('[Adaptive Network] panel indicator installed');
    }

    detach() {
        if (this._sessionId) {
            Main.sessionMode.disconnect(this._sessionId);
            this._sessionId = 0;
        }
        if (this._button) {
            this._button.destroy();
            this._button = null;
        }
    }

    _syncSession() {
        if (this._button)
            this._button.container.visible = !Main.sessionMode.isLocked && !Main.sessionMode.isGreeter;
    }

    // --------------------------------------------------------------- data

    _helper(command, done, script = HELPER, extra = []) {
        try {
            const proc = Gio.Subprocess.new(['/usr/bin/python3', script, command, ...extra],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE);
            proc.communicate_utf8_async(null, null, (p, result) => {
                let data = null;
                try {
                    const [, stdout] = p.communicate_utf8_finish(result);
                    data = JSON.parse(stdout);
                } catch (e) {
                    logError(e, `[Adaptive Network] ${command}`);
                }
                if (this._button)
                    done(data);
            });
        } catch (e) {
            logError(e, '[Adaptive Network] helper');
            done(null);
        }
    }

    _loadInfo() {
        this._helper('info', data => {
            this._info = data;
            this._render();
        });
    }

    _loadPhones() {
        this._helper('list', data => {
            this._phones = data;
            this._render();
        }, PHONE_HELPER);
    }

    _phoneAction(command, phone) {
        this._phoneNote[phone.id] = {
            ring: 'Ringing…', send: 'Choosing a file…', clipboard: 'Sending the clipboard…',
        }[command];
        if (command === 'send')
            this._button.menu.close();
        this._render();
        this._helper(command, reply => {
            const ok = reply && reply.ok;
            this._phoneNote[phone.id] = ok
                ? (command === 'ring' ? 'Rang' : `Sent ${reply.sent || ''}`.trim())
                : (reply && reply.error === 'cancelled' ? '' : 'Did not work');
            this._render();
        }, PHONE_HELPER, [this._phones.backend, phone.id]);
    }

    _phoneRows() {
        const phones = this._phones;
        if (!phones || !phones.backend || !phones.devices.length)
            return [];
        const rows = [CC.makeHeading(
            `Phones · ${phones.backend === 'kdeconnect' ? 'KDE Connect' : 'GSConnect'}`)];
        for (const phone of phones.devices) {
            const details = [phone.reachable ? 'Connected' : 'Not in reach'];
            if (phone.battery !== null)
                details.push(`${phone.battery}%${phone.charging ? ' charging' : ''}`);
            if (this._phoneNote[phone.id])
                details.push(this._phoneNote[phone.id]);
            rows.push(CC.makeRow({
                icon: phone.type === 'tablet' ? 'computer-apple-ipad-symbolic' : 'phone-symbolic',
                title: phone.name,
                subtitle: details.join(' · '),
                active: phone.reachable,
                actions: phone.reachable ? [
                    { label: 'Ring', quiet: true, onClick: () => this._phoneAction('ring', phone) },
                    { label: 'Send file', quiet: true, onClick: () => this._phoneAction('send', phone) },
                    { label: 'Send clipboard', quiet: true, onClick: () => this._phoneAction('clipboard', phone) },
                ] : null,
            }));
        }
        return rows;
    }

    _runScan() {
        if (this._scanning)
            return;
        this._scanning = true;
        this._render();
        this._helper('scan', data => {
            this._scanning = false;
            if (data) {
                this._scan = data;
                this._scannedAt = GLib.get_monotonic_time() / 1e6;
            }
            this._render();
        });
    }

    // Logs in to a device and, when that works, opens a terminal on it. The
    // helper remembers the password once it has been proved right, so the
    // second time this is one click; errors are shown under the device.
    _sshConnect(device, typed = null) {
        const prior = this._ssh && this._ssh.ip === device.ip ? this._ssh : {};
        this._ssh = { ip: device.ip, user: prior.user || '', password: '', busy: true, form: false, error: '' };
        this._render();
        const input = JSON.stringify(typed || {});
        let proc;
        try {
            proc = Gio.Subprocess.new(['/usr/bin/python3', SSH_HELPER, 'connect', device.ip],
                Gio.SubprocessFlags.STDIN_PIPE | Gio.SubprocessFlags.STDOUT_PIPE |
                Gio.SubprocessFlags.STDERR_SILENCE);
        } catch (e) {
            logError(e, '[Adaptive Network] ssh');
            this._ssh = { ip: device.ip, user: '', password: '', busy: false, form: false, error: 'Could not start ssh helper' };
            this._render();
            return;
        }
        proc.communicate_utf8_async(input, null, (p, result) => {
            if (!this._button)
                return;
            let reply = { ok: false, error: 'SSH helper failed' };
            try {
                const [, stdout] = p.communicate_utf8_finish(result);
                reply = JSON.parse(stdout);
            } catch (e) {
                logError(e, '[Adaptive Network] ssh');
            }
            if (reply.ok) {
                this._ssh = null;
                this._button.menu.close();
                return;
            }
            this._ssh = {
                ip: device.ip,
                user: reply.user || '',
                password: '',
                busy: false,
                form: !!reply.need_password,
                error: reply.error || 'SSH failed',
            };
            this._render();
        });
    }

    _sshForm(device) {
        const ssh = this._ssh;
        const box = new St.BoxLayout({ style_class: 'adaptive-network-ssh', vertical: true, x_expand: true });
        if (ssh.error) {
            box.add_child(new St.Label({
                text: ssh.error,
                style_class: 'adaptive-network-ssh-error',
            }));
        }
        if (!ssh.form || ssh.busy)
            return box;

        const field = (hint, password, key) => {
            const entry = new St.Entry({
                style_class: 'adaptive-cc-entry',
                hint_text: hint,
                text: ssh[key],
                can_focus: true,
                x_expand: true,
            });
            if (password) {
                entry.clutter_text.set_password_char('●');
                entry.input_purpose = Clutter.InputContentPurpose.PASSWORD;
            }
            entry.clutter_text.connect('text-changed', () => {
                ssh[key] = entry.get_text();
            });
            box.add_child(entry);
            return entry;
        };
        const user = field('Username', false, 'user');
        const pass = field('Password (remembered after it works)', true, 'password');
        const go = () => {
            if (!ssh.user || !ssh.password)
                return;
            this._sshConnect(device, { user: ssh.user, password: ssh.password });
        };
        user.clutter_text.connect('activate', () => pass.grab_key_focus());
        pass.clutter_text.connect('activate', go);
        const connect = new St.Button({
            style_class: 'adaptive-cc-pill-button',
            label: 'Connect',
            can_focus: true,
            x_align: Clutter.ActorAlign.END,
        });
        connect.connect('clicked', go);
        box.add_child(connect);
        GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
            (ssh.user ? pass : user).grab_key_focus();
            return GLib.SOURCE_REMOVE;
        });
        return box;
    }

    _loadPublic() {
        if (this._publicBusy)
            return;
        this._publicBusy = true;
        this._render();
        this._helper('public', data => {
            this._publicBusy = false;
            this._publicIp = data && data.public ? data.public : 'Unavailable';
            this._render();
        });
    }

    // ------------------------------------------------------------- render

    _render() {
        if (!this._button || !this._button.menu.isOpen)
            return;
        const info = this._info;
        const devices = this._scan ? this._scan.devices : [];

        const network = info && info.wifi ? info.wifi.ssid
            : info && info.connected ? 'Wired' : 'Offline';
        this._summary.text = this._scan
            ? `${network} · ${devices.length} device${devices.length === 1 ? '' : 's'}`
            : network;

        this._list.destroy_all_children();
        this._list.add_child(CC.makeHeading('This Computer'));
        if (!info) {
            this._list.add_child(CC.makeRow({ icon: 'network-workgroup-symbolic', title: 'Reading…' }));
        } else if (!info.connected) {
            this._list.add_child(CC.makeRow({
                icon: 'network-offline-symbolic',
                title: 'Not connected',
                subtitle: 'No network route',
            }));
        } else {
            this._list.add_child(this._facts(info));
        }

        for (const row of this._phoneRows())
            this._list.add_child(row);

        this._list.add_child(this._devicesHeading(network, devices.length));
        if (!this._scan && this._scanning) {
            this._list.add_child(CC.makeRow({
                icon: 'network-workgroup-symbolic',
                title: 'Scanning the network…',
                subtitle: 'Asking every address on this network who is there',
            }));
        }
        for (const device of devices) {
            this._list.add_child(this._deviceRow(device));
            if (this._ssh && this._ssh.ip === device.ip)
                this._list.add_child(this._sshForm(device));
        }
        if (this._scan) {
            const age = GLib.get_monotonic_time() / 1e6 - this._scannedAt;
            this._list.add_child(new St.Label({
                text: `${this._scanning ? 'Scanning…' : `Scanned ${ago(age)}`} · ` +
                    `${this._scan.network || ''} · SSH to open a terminal, click a device to copy its address`,
                style_class: 'adaptive-network-note',
            }));
        }

        const [, natural] = this._list.get_preferred_height(-1);
        this._scroll.set_height(Math.min(natural, LIST_MAX_HEIGHT));
    }

    _facts(info) {
        const box = new St.BoxLayout({
            style_class: 'adaptive-cc-form adaptive-network-facts',
            vertical: true,
            x_expand: true,
        });
        const grid = new St.Widget({
            layout_manager: new Clutter.GridLayout({ column_spacing: 12, row_spacing: 2 }),
            x_expand: true,
        });
        box.add_child(grid);
        let row = 0;

        const line = (key, value, copyText = null, statusClass = null) => {
            if (!value)
                return;
            grid.layout_manager.attach(new St.Label({
                text: key,
                style_class: 'adaptive-usb-key',
                y_align: Clutter.ActorAlign.CENTER,
            }), 0, row, 1, 1);
            const text = new St.Label({ text: value, x_align: Clutter.ActorAlign.START });
            text.clutter_text.ellipsize = imports.gi.Pango.EllipsizeMode.END;
            const button = new St.Button({
                style_class: 'adaptive-network-value',
                child: text,
                x_expand: true,
                x_align: Clutter.ActorAlign.START,
                can_focus: !!copyText,
                reactive: !!copyText,
            });
            if (statusClass)
                button.add_style_class_name(statusClass);
            if (copyText) {
                button.connect('clicked', () => {
                    copy(copyText);
                    text.text = 'Copied';
                    GLib.timeout_add(GLib.PRIORITY_DEFAULT, COPIED_MS, () => {
                        if (text.get_stage())
                            text.text = value;
                        return GLib.SOURCE_REMOVE;
                    });
                });
            }
            grid.layout_manager.attach(button, 1, row, 1, 1);
            row++;
        };

        const ipv4 = info.ipv4[0] || '';
        const address = ipv4.split('/')[0];
        line('IP address', address, address);
        line('Subnet', ipv4 ? `/${ipv4.split('/')[1]}` : null);
        if (info.ipv6.length)
            line('IPv6', info.ipv6[0], info.ipv6[0]);
        line('Router', info.gateway
            ? `${info.gateway}${info.gateway_ms !== null ? `  ·  ${info.gateway_ms.toFixed(1)} ms` : ''}`
            : null, info.gateway);
        line('DNS', info.dns.slice(0, 2).join(', '), info.dns.join('\n'));

        const reach = {
            full: ['Connected', 'adaptive-network-good'],
            limited: ['Limited - no internet', 'adaptive-network-warn'],
            portal: ['Sign-in page', 'adaptive-network-warn'],
            none: ['No internet', 'adaptive-network-bad'],
        }[info.connectivity] || ['Unknown', null];
        line('Internet', reach[0], null, reach[1]);

        if (info.wifi) {
            const w = info.wifi;
            const band = parseInt(w.frequency) >= 5900 ? '6 GHz'
                : parseInt(w.frequency) >= 4900 ? '5 GHz' : '2.4 GHz';
            line('Wi-Fi', w.ssid, w.ssid);
            line('Signal', `${w.signal}%  ·  ${band}  ·  channel ${w.channel}`, null,
                w.signal < 35 ? 'adaptive-network-warn' : null);
            line('Link speed', w.rate);
            line('Security', w.security);
        } else if (info.speed) {
            line('Link speed', info.speed);
        }
        line('Interface', info.device);
        line('MAC address', info.mac, info.mac);
        line('Hostname', info.hostname, info.hostname);
        for (const tunnel of info.tunnels || [])
            line(tunnel.name.startsWith('tailscale') ? 'Tailscale' : `VPN (${tunnel.name})`,
                tunnel.address, tunnel.address);

        // Public IP: an outside service is asked only when the button is pressed.
        grid.layout_manager.attach(new St.Label({
            text: 'Public IP',
            style_class: 'adaptive-usb-key',
            y_align: Clutter.ActorAlign.CENTER,
        }), 0, row, 1, 1);
        if (this._publicIp) {
            const value = new St.Button({
                style_class: 'adaptive-network-value',
                label: this._publicIp,
                x_align: Clutter.ActorAlign.START,
                can_focus: true,
            });
            value.connect('clicked', () => copy(this._publicIp));
            grid.layout_manager.attach(value, 1, row, 1, 1);
        } else {
            const show = new St.Button({
                style_class: 'adaptive-cc-pill-button adaptive-cc-pill-quiet adaptive-network-show',
                label: this._publicBusy ? 'Asking…' : 'Show',
                x_align: Clutter.ActorAlign.START,
                can_focus: true,
            });
            show.connect('clicked', () => this._loadPublic());
            grid.layout_manager.attach(show, 1, row, 1, 1);
        }
        return box;
    }

    _devicesHeading(network, count) {
        const heading = new St.BoxLayout({ style_class: 'adaptive-tasks-heading', x_expand: true });
        heading.add_child(new St.Label({
            text: this._scan ? `Devices on ${network} · ${count}` : `Devices on ${network}`,
            style_class: 'adaptive-cc-list-heading',
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        }));
        const scan = new St.Button({
            style_class: 'adaptive-tasks-sort',
            label: this._scanning ? 'Scanning…' : 'Scan',
            can_focus: true,
            reactive: !this._scanning,
            y_align: Clutter.ActorAlign.CENTER,
        });
        scan.connect('clicked', () => this._runScan());
        heading.add_child(scan);
        return heading;
    }

    _deviceRow(device) {
        const title = device.name || device.vendor || 'Unknown device';
        const details = [device.ip];
        if (device.self)
            details.push('This computer');
        else if (device.gateway)
            details.push('Router');
        if (device.vendor && device.vendor !== title)
            details.push(device.vendor);
        else if (!device.vendor && !device.self)
            details.push('Unknown maker');
        details.push(device.mac);

        const row = CC.makeRow({
            icon: KIND_ICONS[device.kind] || KIND_ICONS.device,
            title,
            subtitle: details.join(' · '),
            active: device.self,
            action: device.self ? null : {
                label: this._ssh && this._ssh.ip === device.ip && this._ssh.busy ? 'Connecting…' : 'SSH',
                quiet: true,
                onClick: () => {
                    if (!(this._ssh && this._ssh.busy))
                        this._sshConnect(device);
                },
            },
            onActivate: () => {
                copy(device.ip);
                const label = row.get_child().get_children()[1].get_children()[0];
                const original = label.text;
                label.text = `Copied ${device.ip}`;
                GLib.timeout_add(GLib.PRIORITY_DEFAULT, COPIED_MS, () => {
                    if (label.get_stage())
                        label.text = original;
                    return GLib.SOURCE_REMOVE;
                });
            },
        });
        return row;
    }
};
