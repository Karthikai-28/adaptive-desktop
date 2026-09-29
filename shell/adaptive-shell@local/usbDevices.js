// Adaptive USB panel
//
// A top-bar indicator, next to the system menu, that lists what is plugged
// into the machine - serial ports first, because that is what hardware work
// needs to find - with vendor and product ids, device paths, the stable
// /dev/serial/by-id path, driver, speed and port, and one-tap copies of the
// things that end up pasted into a terminal or a udev rule.
//
// Everything comes from udev (GUdev), which is also what makes it live: plug
// or unplug something and the list follows, and a serial port that appears
// says so in a notification. Every device shows its /dev nodes - serial
// ports, video, disks and partitions, input and hidraw - and drives can be
// ejected (unmounted and powered off) through GIO, the way Files does it.

/* exported UsbPanel */

const { Clutter, Gio, GLib, GUdev, St } = imports.gi;
const Main = imports.ui.main;
const MessageTray = imports.ui.messageTray;
const PanelMenu = imports.ui.panelMenu;
const Util = imports.misc.util;
const ShellMountOperation = imports.ui.shellMountOperation;

const Me = imports.misc.extensionUtils.getCurrentExtension();
const CC = Me.imports.controlCenter;

const REFRESH_DEBOUNCE_MS = 300;

// Kernel subsystems whose device files are worth showing against a USB device.
const NODE_SUBSYSTEMS = ['tty', 'video4linux', 'block', 'hidraw', 'input'];
const COPIED_FEEDBACK_MS = 1200;
const LIST_MAX_HEIGHT = 600;

// USB class codes (bDeviceClass / bInterfaceClass).
const CLASS = {
    AUDIO: '01', CDC: '02', HID: '03', STORAGE: '08', HUB: '09',
    CDC_DATA: '0a', VIDEO: '0e', WIRELESS: 'e0', VENDOR: 'ff',
};

function formatSpeed(mbps) {
    const value = parseFloat(mbps);
    if (!Number.isFinite(value))
        return 'Unknown';
    if (value <= 1.5)
        return '1.5 Mbps (USB 1.x Low Speed)';
    if (value <= 12)
        return '12 Mbps (USB 1.x Full Speed)';
    if (value <= 480)
        return '480 Mbps (USB 2.0 High Speed)';
    if (value <= 5000)
        return '5 Gbps (USB 3.x SuperSpeed)';
    if (value <= 10000)
        return '10 Gbps (USB 3.x SuperSpeed+)';
    return `${value / 1000} Gbps (USB 3.2 / USB4)`;
}

// One /dev node, with what it is.
function describeNode(subsystem, dev, file) {
    const node = { file, subsystem, devtype: dev.get_devtype(), primary: true, label: '' };
    switch (subsystem) {
    case 'tty':
        node.label = 'serial port';
        break;
    case 'video4linux': {
        // UVC cameras expose a capture node and a metadata node each.
        const caps = dev.get_property('ID_V4L_CAPABILITIES') || '';
        node.primary = caps.includes(':capture:');
        node.label = node.primary ? 'video capture' : 'video metadata';
        break;
    }
    case 'block': {
        if (node.devtype === 'partition') {
            node.primary = false;
            const label = dev.get_property('ID_FS_LABEL');
            const type = dev.get_property('ID_FS_TYPE');
            node.label = [label ? `“${label}”` : 'partition', type].filter(Boolean).join(', ');
        } else {
            node.label = 'disk';
        }
        break;
    }
    case 'hidraw':
        node.primary = false;
        node.label = 'raw HID';
        break;
    case 'input':
        node.label = dev.get_property('ID_INPUT_KEYBOARD') === '1' ? 'keyboard input'
            : dev.get_property('ID_INPUT_MOUSE') === '1' ? 'mouse input' : 'input events';
        break;
    }
    return node;
}

// The GIO drive for a USB device's disk, if it has one.
function driveFor(device) {
    const disks = device.nodes.filter(n => n.subsystem === 'block' && n.devtype === 'disk')
        .map(n => n.file);
    if (!disks.length)
        return null;
    return Gio.VolumeMonitor.get().get_connected_drives()
        .find(d => disks.includes(d.get_identifier('unix-device'))) || null;
}

function mountsOf(drive) {
    return drive.get_volumes().map(v => v.get_mount()).filter(Boolean);
}

function slug(text) {
    return (text || 'device').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'device';
}

function copy(text) {
    St.Clipboard.get_default().set_text(St.ClipboardType.CLIPBOARD, text);
}

// What a person calls a device, from what its interfaces say it is.
function kindOf(classes, hasSerial) {
    if (hasSerial)
        return { label: 'Serial', icon: 'utilities-terminal-symbolic' };
    if (classes.has(CLASS.STORAGE))
        return { label: 'Storage', icon: 'drive-removable-media-symbolic' };
    if (classes.has(CLASS.VIDEO))
        return { label: 'Camera', icon: 'camera-web-symbolic' };
    if (classes.has(CLASS.AUDIO))
        return { label: 'Audio', icon: 'audio-headphones-symbolic' };
    if (classes.has(CLASS.HID))
        return { label: 'Input', icon: 'input-keyboard-symbolic' };
    if (classes.has(CLASS.WIRELESS))
        return { label: 'Wireless', icon: 'bluetooth-active-symbolic' };
    if (classes.has(CLASS.CDC) || classes.has(CLASS.CDC_DATA))
        return { label: 'Communications', icon: 'network-wired-symbolic' };
    return { label: 'USB device', icon: 'media-removable-symbolic' };
}

var UsbPanel = class UsbPanel {
    constructor() {
        this._button = null;
        this._client = null;
        this._ueventId = 0;
        this._refreshId = 0;
        this._sessionId = 0;
        this._openStateId = 0;
        this._expanded = null;
        this._devices = [];
        this._knownPorts = null;
        this._source = null;
        this._ejecting = new Set();
        this._ejectErrors = new Map();
        this._volumeIds = [];
    }

    attach() {
        try {
            this._client = new GUdev.Client({ subsystems: ['usb', 'tty'] });
        } catch (e) {
            logError(e, '[Adaptive USB] udev is unavailable');
            return;
        }

        this._button = new PanelMenu.Button(0.5, 'USB Devices', false);

        const box = new St.BoxLayout({ style_class: 'panel-status-indicators-box' });
        const iconFile = Me.dir.get_child('assets').get_child('panel').get_child('usb-symbolic.svg');
        box.add_child(new St.Icon({
            gicon: new Gio.FileIcon({ file: iconFile }),
            style_class: 'system-status-icon',
        }));
        this._badge = new St.Label({
            style_class: 'adaptive-usb-badge',
            y_align: Clutter.ActorAlign.CENTER,
            visible: false,
        });
        box.add_child(this._badge);
        this._button.add_child(box);

        // Same look as the Control Center popup.
        this._button.menu.box.add_style_class_name('adaptive-cc-menu');
        this._root = new St.BoxLayout({
            style_class: 'adaptive-cc adaptive-usb',
            vertical: true,
            x_expand: true,
        });
        this._button.menu.box.add_child(this._root);

        const header = new St.BoxLayout({ style_class: 'adaptive-usb-header', x_expand: true });
        header.add_child(new St.Label({
            text: 'USB Devices',
            style_class: 'adaptive-usb-title',
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        }));
        this._summary = new St.Label({
            style_class: 'adaptive-usb-summary',
            y_align: Clutter.ActorAlign.CENTER,
        });
        header.add_child(this._summary);
        this._root.add_child(header);

        this._scroll = new St.ScrollView({
            style_class: 'adaptive-cc-scroll vfade',
            overlay_scrollbars: true,
            x_expand: true,
            reactive: true,
            track_hover: true,
        });
        this._scroll.set_policy(St.PolicyType.NEVER, St.PolicyType.AUTOMATIC);
        this._list = new St.BoxLayout({
            style_class: 'adaptive-cc-list',
            vertical: true,
            x_expand: true,
        });
        this._scroll.add_actor(this._list);
        this._root.add_child(this._scroll);

        // Just left of the system menu.
        const rightBox = Main.panel._rightBox;
        const agg = Main.panel.statusArea.aggregateMenu;
        const index = agg ? Math.max(0, rightBox.get_children().indexOf(agg.container)) : 0;
        Main.panel.addToStatusArea('adaptive-usb', this._button, index, 'right');

        this._ueventId = this._client.connect('uevent', (_c, action, device) =>
            this._onUevent(action, device));
        this._openStateId = this._button.menu.connect('open-state-changed', (_m, open) => {
            if (open) {
                this._expanded = null;
                this._refresh(true);
            }
        });
        this._scroll.connect('notify::hover', () => {
            if (!this._scroll.hover && this._stale)
                this._refresh(true);
        });
        this._sessionId = Main.sessionMode.connect('updated', () => this._syncSession());

        // Mounts come and go without a USB event (mounting, ejecting).
        this._volumeMonitor = Gio.VolumeMonitor.get();
        this._volumeIds = ['mount-added', 'mount-removed', 'drive-connected', 'drive-disconnected']
            .map(signal => this._volumeMonitor.connect(signal, () => this._onUevent('change', null)));

        this._refresh(true);
        this._syncSession();
        log('[Adaptive USB] panel indicator installed');
    }

    detach() {
        if (this._refreshId) {
            GLib.Source.remove(this._refreshId);
            this._refreshId = 0;
        }
        if (this._ueventId && this._client) {
            this._client.disconnect(this._ueventId);
            this._ueventId = 0;
        }
        if (this._sessionId) {
            Main.sessionMode.disconnect(this._sessionId);
            this._sessionId = 0;
        }
        for (const id of this._volumeIds)
            this._volumeMonitor.disconnect(id);
        this._volumeIds = [];
        if (this._source) {
            this._source.destroy();
            this._source = null;
        }
        if (this._button) {
            this._button.destroy();
            this._button = null;
        }
        this._client = null;
    }

    // Not on the lock screen: the panel there is GNOME's, and a list of what
    // is plugged into a locked machine is nobody's business.
    _syncSession() {
        if (this._button)
            this._button.container.visible = !Main.sessionMode.isLocked && !Main.sessionMode.isGreeter;
    }

    // --------------------------------------------------------------- data

    _collect() {
        const all = this._client.query_by_subsystem('usb');
        const interfaces = new Map();
        for (const dev of all) {
            if (dev.get_devtype() !== 'usb_interface')
                continue;
            const parent = dev.get_parent();
            if (!parent)
                continue;
            const key = parent.get_sysfs_path();
            if (!interfaces.has(key))
                interfaces.set(key, []);
            interfaces.get(key).push({
                cls: (dev.get_sysfs_attr('bInterfaceClass') || '').trim().toLowerCase(),
                driver: dev.get_driver(),
            });
        }

        const ports = new Map();
        for (const tty of this._client.query_by_subsystem('tty')) {
            const usb = tty.get_parent_with_subsystem('usb', 'usb_device');
            const node = tty.get_device_file();
            if (!usb || !node)
                continue;
            const iface = tty.get_parent_with_subsystem('usb', 'usb_interface');
            const byId = (tty.get_device_file_symlinks() || [])
                .find(p => p.startsWith('/dev/serial/by-id/')) || null;
            const key = usb.get_sysfs_path();
            if (!ports.has(key))
                ports.set(key, []);
            ports.get(key).push({
                node,
                byId,
                driver: iface ? iface.get_driver() : null,
            });
        }

        // Device files, by the USB device they belong to.
        const nodes = new Map();
        for (const subsystem of NODE_SUBSYSTEMS) {
            for (const dev of this._client.query_by_subsystem(subsystem)) {
                const file = dev.get_device_file();
                const usb = file && dev.get_parent_with_subsystem('usb', 'usb_device');
                if (!usb)
                    continue;
                // Input: the event node is the one programs open; mouseN and
                // the legacy nodes are noise.
                if (subsystem === 'input' && !/^event\d+$/.test(dev.get_name()))
                    continue;
                const key = usb.get_sysfs_path();
                if (!nodes.has(key))
                    nodes.set(key, []);
                nodes.get(key).push(describeNode(subsystem, dev, file));
            }
        }
        for (const list of nodes.values())
            list.sort((a, b) => a.file.localeCompare(b.file, undefined, { numeric: true }));

        const devices = [];
        for (const dev of all) {
            if (dev.get_devtype() !== 'usb_device')
                continue;
            const a = key => (dev.get_sysfs_attr(key) || '').trim();
            const vid = a('idVendor');
            const pid = a('idProduct');
            const cls = a('bDeviceClass').toLowerCase();

            // Root hubs and hubs are plumbing, not devices.
            if (vid === '1d6b' || cls === CLASS.HUB)
                continue;

            const key = dev.get_sysfs_path();
            const ifaces = interfaces.get(key) || [];
            const devPorts = ports.get(key) || [];
            const classes = new Set(ifaces.map(i => i.cls));
            if (cls && cls !== '00' && cls !== 'ef')
                classes.add(cls);

            const vendorDb = dev.get_property('ID_VENDOR_FROM_DATABASE');
            const vendor = a('manufacturer') || vendorDb || 'Unknown vendor';
            const kind = kindOf(classes, devPorts.length > 0);
            // Some chips (Intel's Bluetooth, for one) report no product name and
            // the hardware database has none either; say what it is instead.
            const product = a('product') || dev.get_property('ID_MODEL_FROM_DATABASE') ||
                (kind.label === 'Wireless' ? 'Bluetooth adapter' : `${kind.label} (${vid}:${pid})`);

            devices.push({
                key,
                vid,
                pid,
                vendor,
                vendorDb: vendorDb && vendorDb !== vendor ? vendorDb : null,
                product,
                serial: a('serial'),
                speed: a('speed'),
                version: a('version'),
                removable: a('removable'),
                bus: a('busnum'),
                devnum: a('devnum'),
                port: dev.get_name(),
                drivers: [...new Set(ifaces.map(i => i.driver).filter(Boolean))],
                ports: devPorts,
                nodes: nodes.get(key) || [],
                kind,
            });
        }

        return devices;
    }

    // ------------------------------------------------------------- events

    _onUevent(action, device) {
        if (device) {
            const subsystem = device.get_subsystem();
            const relevant = subsystem === 'tty' ||
                (subsystem === 'usb' && device.get_devtype() === 'usb_device');
            if (!relevant || (action !== 'add' && action !== 'remove'))
                return;
        }

        // A plug is a burst of events (device, interfaces, tty); settle first.
        if (this._refreshId)
            GLib.Source.remove(this._refreshId);
        this._refreshId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, REFRESH_DEBOUNCE_MS, () => {
            this._refreshId = 0;
            this._refresh(false);
            return GLib.SOURCE_REMOVE;
        });
    }

    _refresh(force) {
        let devices;
        try {
            devices = this._collect();
        } catch (e) {
            logError(e, '[Adaptive USB] reading udev');
            return;
        }
        this._devices = devices;

        this._announcePorts(devices);

        const serialCount = devices.reduce((n, d) => n + d.ports.length, 0);
        this._badge.text = `${serialCount}`;
        this._badge.visible = serialCount > 0;

        if (!this._button.menu.isOpen)
            return;

        // Like the Wi-Fi list: never reshuffle rows under the pointer.
        if (!force && this._scroll.hover && this._list.get_n_children() > 0) {
            this._stale = true;
            return;
        }
        this._stale = false;
        this._render();
    }

    // A serial port appearing or going is the moment someone reaches for its
    // path, so it gets a notification. Other devices do not - a hub or a
    // mouse arriving is noise.
    _announcePorts(devices) {
        const current = new Map();
        for (const d of devices) {
            for (const p of d.ports)
                current.set(p.node, { device: d, port: p });
        }

        if (this._knownPorts) {
            for (const [node, { device }] of current) {
                if (!this._knownPorts.has(node))
                    this._notify(`${device.product} connected`, `${node} · ${device.vid}:${device.pid}`);
            }
            for (const [node, device] of this._knownPorts) {
                if (!current.has(node))
                    this._notify(`${device.product} disconnected`, `${node} is gone`);
            }
        }

        this._knownPorts = new Map([...current].map(([node, { device }]) => [node, device]));
    }

    _notify(title, body) {
        try {
            if (!this._source) {
                this._source = new MessageTray.Source('USB Devices', 'media-removable-symbolic');
                this._source.connect('destroy', () => {
                    this._source = null;
                });
                Main.messageTray.add(this._source);
            }
            const notification = new MessageTray.Notification(this._source, title, body);
            notification.setTransient(true);
            this._source.showNotification(notification);
        } catch (e) {
            logError(e, '[Adaptive USB] notification');
        }
    }

    // ------------------------------------------------------------- render

    _render() {
        const devices = this._devices;
        this._list.destroy_all_children();
        this._detailsActor = null;

        const serial = [];
        for (const d of devices) {
            for (const p of d.ports)
                serial.push({ device: d, port: p });
        }
        serial.sort((a, b) => a.port.node.localeCompare(b.port.node, undefined, { numeric: true }));

        const others = devices.filter(d => d.ports.length === 0 && d.removable !== 'fixed')
            .sort((a, b) => a.product.localeCompare(b.product));
        const builtin = devices.filter(d => d.ports.length === 0 && d.removable === 'fixed')
            .sort((a, b) => a.product.localeCompare(b.product));

        const parts = [];
        parts.push(`${serial.length} serial`);
        parts.push(`${others.length} USB`);
        this._summary.text = parts.join(' · ');

        this._list.add_child(CC.makeHeading('Serial Ports'));
        if (serial.length) {
            for (const { device, port } of serial)
                this._addDevice(device, port);
        } else {
            this._list.add_child(CC.makeRow({
                icon: 'utilities-terminal-symbolic',
                title: 'No serial ports',
                subtitle: 'Plug in a board or adapter - it will appear here',
            }));
        }

        if (others.length) {
            this._list.add_child(CC.makeHeading('USB Devices'));
            for (const d of others)
                this._addDevice(d, null);
        }

        if (builtin.length) {
            this._list.add_child(CC.makeHeading('Built-in'));
            for (const d of builtin)
                this._addDevice(d, null);
        }

        const [, natural] = this._list.get_preferred_height(-1);
        this._scroll.set_height(Math.min(natural, LIST_MAX_HEIGHT));

        // An expanded card can end below the fold; bring all of it into view.
        if (this._detailsActor) {
            const card = this._detailsActor;
            GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
                if (card.get_stage())
                    Util.ensureActorVisibleInScrollView(this._scroll, card);
                return GLib.SOURCE_REMOVE;
            });
        }
    }

    _addDevice(device, port) {
        const id = port ? port.node : device.key;
        const open = this._expanded === id;
        const vidpid = `${device.vid}:${device.pid}`;

        const primary = device.nodes.filter(n => n.primary).map(n => n.file).slice(0, 2);
        const drive = port ? null : driveFor(device);
        const ejecting = this._ejecting.has(device.key);
        const ejectError = this._ejectErrors.get(device.key);

        let subtitle = port
            ? `${port.node} · ${vidpid}${port.driver ? ` · ${port.driver}` : ''}`
            : [primary.join(', '), vidpid, device.vendor].filter(Boolean).join(' · ');
        if (ejecting)
            subtitle = 'Ejecting…';
        else if (ejectError)
            subtitle = ejectError;
        else if (!port && device.kind.label === 'Storage' && !drive)
            subtitle = `Safe to unplug · ${vidpid}`;

        this._list.add_child(CC.makeRow({
            icon: device.kind.icon,
            title: device.product,
            subtitle,
            alert: !!ejectError && !ejecting,
            active: open,
            trailing: [open ? 'pan-up-symbolic' : 'pan-down-symbolic'],
            actions: drive && !ejecting ? [{
                label: 'Eject',
                quiet: true,
                onClick: () => this._eject(device, drive),
            }] : null,
            onActivate: () => {
                this._expanded = open ? null : id;
                this._render();
            },
        }));

        if (open) {
            this._detailsActor = this._details(device, port);
            this._list.add_child(this._detailsActor);
        }
    }

    _details(device, port) {
        const box = new St.BoxLayout({
            style_class: 'adaptive-cc-form adaptive-usb-details',
            vertical: true,
            x_expand: true,
        });

        const grid = new St.Widget({
            layout_manager: new Clutter.GridLayout({ column_spacing: 12, row_spacing: 4 }),
            x_expand: true,
        });
        box.add_child(grid);

        const lines = [];
        const line = (label, value) => {
            if (!value)
                return;
            lines.push(`${label}: ${value}`);
            const row = lines.length - 1;
            grid.layout_manager.attach(new St.Label({
                text: label,
                style_class: 'adaptive-usb-key',
            }), 0, row, 1, 1);
            const v = new St.Label({
                text: value,
                style_class: 'adaptive-usb-value',
                x_expand: true,
            });
            // Several values span lines (device files, mount points); an
            // ellipsizing label would show only the first.
            v.clutter_text.line_wrap = true;
            v.clutter_text.line_wrap_mode = imports.gi.Pango.WrapMode.WORD_CHAR;
            v.clutter_text.ellipsize = imports.gi.Pango.EllipsizeMode.NONE;
            grid.layout_manager.attach(v, 1, row, 1, 1);
        };

        line('Product', device.product);
        line('Vendor', device.vendorDb ? `${device.vendor} (${device.vendorDb})` : device.vendor);
        // lsusb's form. Inter also draws the x of "0x04e8" as a multiplication
        // sign, which is one more reason not to write it.
        line('VID', device.vid);
        line('PID', device.pid);
        line('Serial', device.serial);
        line('Type', device.kind.label);
        line('USB port', `Bus ${device.bus} · port ${device.port} · device ${device.devnum}`);
        line('Speed', formatSpeed(device.speed));
        line('USB version', device.version ? `USB ${device.version}` : null);
        line('Driver', (port && port.driver) || device.drivers.join(', ') || 'None bound');

        let access = null;
        if (port) {
            line('Path', port.node);
            line('Stable path', port.byId);
            access = this._access(port.node);
            line('Access', access.text);
        }

        if (device.nodes.length)
            line('Device files', device.nodes.map(n => `${n.file}  (${n.label})`).join('\n'));

        const drive = port ? null : driveFor(device);
        const mounts = drive ? mountsOf(drive) : [];
        if (mounts.length)
            line('Mounted at', mounts.map(m => m.get_root().get_path()).join('\n'));

        const buttons = new St.BoxLayout({
            style_class: 'adaptive-cc-form-buttons adaptive-usb-actions',
            x_align: Clutter.ActorAlign.START,
        });
        box.add_child(buttons);

        const action = (label, text) => {
            const button = new St.Button({
                style_class: 'adaptive-cc-form-button',
                label,
                can_focus: true,
            });
            button.connect('clicked', () => {
                copy(text);
                button.label = 'Copied';
                GLib.timeout_add(GLib.PRIORITY_DEFAULT, COPIED_FEEDBACK_MS, () => {
                    if (button.get_stage())
                        button.label = label;
                    return GLib.SOURCE_REMOVE;
                });
            });
            buttons.add_child(button);
        };

        if (port) {
            action('Copy path', port.byId || port.node);
            action('Copy VID:PID', `${device.vid}:${device.pid}`);
            // A rule that gives the board a fixed name, whatever ttyACMn it
            // lands on - the thing most often looked up when a second board
            // shuffles the numbering.
            const serialMatch = device.serial ? `, ATTRS{serial}=="${device.serial}"` : '';
            action('Copy udev rule',
                `SUBSYSTEM=="tty", ATTRS{idVendor}=="${device.vid}", ATTRS{idProduct}=="${device.pid}"` +
                `${serialMatch}, SYMLINK+="${slug(device.product)}", MODE="0660", GROUP="dialout"`);
        } else {
            const primaryNode = device.nodes.find(n => n.primary);
            if (primaryNode)
                action('Copy path', primaryNode.file);
            action('Copy VID:PID', `${device.vid}:${device.pid}`);
            action('Copy details', lines.join('\n'));
        }

        if (drive) {
            // Drive actions get their own row, ending in the primary button.
            const driveButtons = new St.BoxLayout({
                style_class: 'adaptive-cc-form-buttons adaptive-usb-actions',
                x_align: Clutter.ActorAlign.END,
            });
            box.add_child(driveButtons);
            if (mounts.length) {
                const openButton = new St.Button({
                    style_class: 'adaptive-cc-form-button',
                    label: 'Open',
                    can_focus: true,
                });
                openButton.connect('clicked', () => {
                    this._button.menu.close();
                    try {
                        Gio.AppInfo.launch_default_for_uri(mounts[0].get_root().get_uri(), null);
                    } catch (e) {
                        logError(e, '[Adaptive USB] opening a drive');
                    }
                });
                driveButtons.add_child(openButton);
            }
            const eject = new St.Button({
                style_class: 'adaptive-cc-form-button adaptive-cc-form-primary',
                label: this._ejecting.has(device.key) ? 'Ejecting…' : 'Eject',
                can_focus: true,
                reactive: !this._ejecting.has(device.key),
            });
            eject.connect('clicked', () => this._eject(device, drive));
            driveButtons.add_child(eject);
        }

        if (access && !access.ok) {
            const hint = new St.Label({
                text: 'You cannot open this port. Add yourself to the port\'s group ' +
                    '(usually "dialout") and log in again.',
                style_class: 'adaptive-usb-warning',
            });
            hint.clutter_text.line_wrap = true;
            box.add_child(hint);
        }

        return box;
    }

    // "Safely remove": unmount everything on the drive and power it down
    // (stop) when the drive supports that - an SSD like the T7 does - else
    // eject it, else just unmount. GNOME's mount operation handles the
    // "device is busy" case, listing what holds files open on it.
    _eject(device, drive) {
        if (this._ejecting.has(device.key))
            return;
        this._ejecting.add(device.key);
        this._ejectErrors.delete(device.key);
        this._render();

        const name = device.product;
        const mountOperation = new ShellMountOperation.ShellMountOperation(drive);
        const operation = mountOperation.mountOp;
        const done = error => {
            try {
                mountOperation.close();
            } catch (e) {
            }
            this._ejecting.delete(device.key);
            if (error) {
                const busy = /busy|in use|target is busy/i.test(error.message);
                this._ejectErrors.set(device.key, busy
                    ? 'In use. Close files and apps using it, then eject.'
                    : "Couldn't eject");
                log(`[Adaptive USB] eject ${name}: ${error.message}`);
            } else {
                this._notify(`${name} can be unplugged`, 'It has been safely ejected.');
            }
            this._refresh(true);
        };

        try {
            if (drive.can_stop()) {
                drive.stop(Gio.MountUnmountFlags.NONE, operation, null, (d, res) => {
                    try {
                        d.stop_finish(res);
                        done(null);
                    } catch (e) {
                        done(e);
                    }
                });
            } else if (drive.can_eject()) {
                drive.eject_with_operation(Gio.MountUnmountFlags.NONE, operation, null, (d, res) => {
                    try {
                        d.eject_with_operation_finish(res);
                        done(null);
                    } catch (e) {
                        done(e);
                    }
                });
            } else {
                const mounts = mountsOf(drive);
                let pending = mounts.length;
                let failure = null;
                if (!pending) {
                    done(null);
                    return;
                }
                for (const mount of mounts) {
                    mount.unmount_with_operation(Gio.MountUnmountFlags.NONE, operation, null, (m, res) => {
                        try {
                            m.unmount_with_operation_finish(res);
                        } catch (e) {
                            failure = failure || e;
                        }
                        if (--pending === 0)
                            done(failure);
                    });
                }
            }
        } catch (e) {
            done(e);
        }
    }

    _access(node) {
        try {
            const info = Gio.File.new_for_path(node).query_info(
                'access::can-read,access::can-write,owner::group',
                Gio.FileQueryInfoFlags.NONE, null);
            const read = info.get_attribute_boolean('access::can-read');
            const write = info.get_attribute_boolean('access::can-write');
            const group = info.get_attribute_string('owner::group');
            if (read && write)
                return { ok: true, text: `Read and write${group ? ` (group ${group})` : ''}` };
            return { ok: false, text: `No access${group ? ` - owned by group ${group}` : ''}` };
        } catch (e) {
            return { ok: false, text: 'Unknown' };
        }
    }
};
