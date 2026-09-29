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

/* exported NetworkPanel */

const { Clutter, Gio, GLib, St } = imports.gi;
const Main = imports.ui.main;
const PanelMenu = imports.ui.panelMenu;

const Me = imports.misc.extensionUtils.getCurrentExtension();
const CC = Me.imports.controlCenter;

const HELPER = Me.dir.get_child('tools').get_child('network_info.py').get_path();
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

    _helper(command, done) {
        try {
            const proc = Gio.Subprocess.new(['/usr/bin/python3', HELPER, command],
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

        this._list.add_child(this._devicesHeading(network, devices.length));
        if (!this._scan && this._scanning) {
            this._list.add_child(CC.makeRow({
                icon: 'network-workgroup-symbolic',
                title: 'Scanning the network…',
                subtitle: 'Asking every address on this network who is there',
            }));
        }
        for (const device of devices)
            this._list.add_child(this._deviceRow(device));
        if (this._scan) {
            const age = GLib.get_monotonic_time() / 1e6 - this._scannedAt;
            this._list.add_child(new St.Label({
                text: `${this._scanning ? 'Scanning…' : `Scanned ${ago(age)}`} · ` +
                    `${this._scan.network || ''} · click a device to copy its address`,
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
