// Adaptive System Monitor panel
//
// A top-bar indicator next to ROS 2: live system vitals
// (CPU & per-core load, NVIDIA/Intel GPU load & VRAM, RAM & Swap buffers,
// disk usage & I/O, network rates, thermals, and top processes).

/* exported SystemPanel, Meter, MetricRow, MeterRow, ProcessRow */

const { Clutter, Gio, GLib, GObject, Shell, St } = imports.gi;
const Main = imports.ui.main;
const PanelMenu = imports.ui.panelMenu;

const Me = imports.misc.extensionUtils.getCurrentExtension();
const AdaptiveUtil = Me.imports.adaptiveUtil;
const CC = Me.imports.ccUtil;
const Sparkline = Me.imports.sparkline;
const Telemetry = Me.imports.telemetry;

const ACCENT_CPU = '#0A84FF';
const ACCENT_GPU = '#5E5CE6';
const ACCENT_NET = '#64D2FF';
const WARNING = '#FF9F0A';
const DANGER = '#FF453A';

const CONFIG_PATH = GLib.build_filenamev(
    [GLib.get_user_config_dir(), 'adaptive-desktop', 'system-panel.json']);

function readConfig() {
    try {
        const [ok, contents] = GLib.file_get_contents(CONFIG_PATH);
        if (!ok)
            return {};
        return JSON.parse(new TextDecoder().decode(contents)) || {};
    } catch (e) {
        return {};
    }
}

function writeConfig(patch) {
    try {
        const dir = GLib.path_get_dirname(CONFIG_PATH);
        GLib.mkdir_with_parents(dir, 0o755);
        const merged = Object.assign(readConfig(), patch);
        GLib.file_set_contents(CONFIG_PATH, JSON.stringify(merged, null, 2) + '\n');
    } catch (e) {
        logError(e, '[Adaptive System] saving system-panel.json');
    }
}

function pct(value) {
    return Number.isFinite(value) ? `${Math.round(value)}%` : '--';
}

function mhz(value) {
    if (!Number.isFinite(value))
        return '--';
    if (value >= 1000)
        return `${(value / 1000).toFixed(2)} GHz`;
    return `${Math.round(value)} MHz`;
}

function degrees(value) {
    return Number.isFinite(value) ? `${Math.round(value)}°C` : '--';
}

function fillStyle(hex) {
    return `background-color: ${hex};`;
}

// A percentage bar whose fill dynamically matches the widget width.
var Meter = GObject.registerClass(
class Meter extends St.Widget {
    _init() {
        super._init({
            style_class: 'adaptive-meter',
            layout_manager: new Clutter.BinLayout(),
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });

        this._fill = new St.Widget({
            style_class: 'adaptive-meter-fill',
            x_align: Clutter.ActorAlign.START,
        });
        this.add_child(this._fill);

        this._fraction = 0;
        this.connect('notify::width', () => this._apply());
    }

    setFraction(fraction) {
        this._fraction = Number.isFinite(fraction)
            ? Math.max(0, Math.min(1, fraction))
            : 0;
        this._apply();
    }

    setColor(hex) {
        if (this._color === hex)
            return;
        this._color = hex;
        this._fill.style = fillStyle(hex);
    }

    _apply() {
        const width = this.get_width();
        if (width <= 0)
            return;
        this._fill.set_width(Math.round(width * this._fraction));
    }
});

// A metric row: name, large figure, history sparkline, and clock/temperature meta.
var MetricRow = GObject.registerClass(
class MetricRow extends St.BoxLayout {
    _init(name, accent) {
        super._init({
            style_class: 'adaptive-metric',
            x_expand: true,
        });

        const left = new St.BoxLayout({
            vertical: true,
            style_class: 'adaptive-metric-left',
            y_align: Clutter.ActorAlign.CENTER,
        });
        this.add_child(left);

        left.add_child(new St.Label({
            text: name,
            style_class: 'adaptive-metric-name',
        }));

        this._value = new St.Label({
            text: '--',
            style_class: 'adaptive-metric-value',
        });
        left.add_child(this._value);

        this.sparkline = new Sparkline.Sparkline(accent, 100);
        this.add_child(this.sparkline.actor);

        this._meta = new St.Label({
            text: '',
            style_class: 'adaptive-metric-meta',
            y_align: Clutter.ActorAlign.CENTER,
        });
        this.add_child(this._meta);
    }

    setValue(text) {
        this._value.text = text;
    }

    setMeta(text) {
        this._meta.text = text;
    }

    setMetaColor(hex) {
        if (this._metaColor === hex)
            return;
        this._metaColor = hex;
        this._meta.style = `color: ${hex};`;
    }
});

// A labelled meter bar with a trailing figure.
var MeterRow = GObject.registerClass(
class MeterRow extends St.BoxLayout {
    _init(name) {
        super._init({
            style_class: 'adaptive-meter-row',
            x_expand: true,
        });

        this._name = new St.Label({
            text: name,
            style_class: 'adaptive-meter-name',
            y_align: Clutter.ActorAlign.CENTER,
        });
        this.add_child(this._name);

        this.meter = new Meter();
        this.add_child(this.meter);

        this._value = new St.Label({
            text: '--',
            style_class: 'adaptive-meter-value',
            y_align: Clutter.ActorAlign.CENTER,
        });
        this.add_child(this._value);
    }

    setName(text) {
        this._name.text = text;
    }

    setValue(text) {
        this._value.text = text;
    }
});

// One process: name (with instance count), CPU share, resident memory.
var ProcessRow = GObject.registerClass(
class ProcessRow extends St.BoxLayout {
    _init() {
        super._init({
            style_class: 'adaptive-proc-row',
            x_expand: true,
        });

        this._name = new St.Label({
            style_class: 'adaptive-proc-name',
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        this.add_child(this._name);

        this._cpu = new St.Label({
            style_class: 'adaptive-proc-cpu',
            y_align: Clutter.ActorAlign.CENTER,
        });
        this.add_child(this._cpu);

        this._mem = new St.Label({
            style_class: 'adaptive-proc-mem',
            y_align: Clutter.ActorAlign.CENTER,
        });
        this.add_child(this._mem);
    }

    update(proc) {
        this._name.text = proc.instances > 1
            ? `${proc.command} ×${proc.instances}`
            : proc.command;
        this._cpu.text = `${proc.percent.toFixed(0)}%`;
        this._mem.text = Telemetry.formatBytes(proc.rssBytes);

        const color = proc.percent >= 100 ? DANGER
            : proc.percent >= 40 ? WARNING
                : null;
        if (this._color !== color) {
            this._color = color;
            this._cpu.style = color ? `color: ${color};` : null;
        }
    }
});

var SystemPanel = class SystemPanel {
    constructor() {
        this._button = null;
        this._openStateId = 0;
        this._sessionId = 0;
        this._telemetry = null;
        this._expanded = readConfig().systemExpanded !== false;
        this._detail = [];
        this._coreBars = [];
        this._diskRows = [];
        this._netRows = [];
        this._thermalChips = [];
        this._procRows = [];
    }

    attach() {
        this._button = new PanelMenu.Button(0.5, 'System Monitor', false);

        let iconGIcon;
        try {
            iconGIcon = CC.extensionIcon('system-symbolic');
        } catch (e) {
            iconGIcon = new Gio.ThemedIcon({ name: 'utilities-system-monitor-symbolic' });
        }
        this._button.add_child(new St.Icon({
            gicon: iconGIcon,
            style_class: 'system-status-icon',
        }));

        this._button.menu.box.add_style_class_name('adaptive-cc-menu');
        const root = new St.BoxLayout({
            style_class: 'adaptive-cc adaptive-system-menu',
            vertical: true,
            x_expand: true,
        });
        this._button.menu.box.add_child(root);

        // Header
        const head = new St.BoxLayout({
            style_class: 'adaptive-shade-section-head',
            x_expand: true,
        });
        root.add_child(head);

        head.add_child(new St.Widget({
            style_class: 'adaptive-shade-live-dot',
            y_align: Clutter.ActorAlign.CENTER,
        }));

        head.add_child(new St.Label({
            text: 'System',
            style_class: 'adaptive-shade-section-title',
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        }));

        this._uptimeChip = new St.BoxLayout({
            style_class: 'adaptive-shade-uptime',
            y_align: Clutter.ActorAlign.CENTER,
            visible: false,
        });
        this._uptimeChip.add_child(new St.Widget({
            style_class: 'adaptive-shade-live-dot',
            y_align: Clutter.ActorAlign.CENTER,
        }));
        this._uptimeLabel = new St.Label({
            text: '',
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._uptimeChip.add_child(this._uptimeLabel);
        head.add_child(this._uptimeChip);

        this._expandButton = new St.Button({
            style_class: 'adaptive-shade-expander',
            can_focus: true,
        });
        this._expandButton.connect('clicked', () => this._toggleDetail());
        head.add_child(this._expandButton);

        const monitorBtn = new St.Button({
            style_class: 'adaptive-shade-expander',
            can_focus: true,
            label: 'Monitor',
        });
        monitorBtn.connect('clicked', () => {
            this._button.menu.close();
            const app = Shell.AppSystem.get_default().lookup_app('gnome-system-monitor.desktop');
            if (app)
                app.activate();
        });
        head.add_child(monitorBtn);

        // Scroll view for telemetry content
        this._scroll = new St.ScrollView({
            style_class: 'adaptive-cc-scroll',
            overlay_scrollbars: true,
            x_expand: true,
        });
        this._scroll.set_policy(St.PolicyType.NEVER, St.PolicyType.AUTOMATIC);
        root.add_child(this._scroll);

        const section = new St.BoxLayout({
            vertical: true,
            style_class: 'adaptive-shade-system',
            x_expand: true,
        });
        this._scroll.add_actor(section);
        this._systemSection = section;

        this._buildMetrics(section);

        // Add to panel: positioned right next to ROS 2 (or leftmost custom indicator)
        const rightBox = Main.panel._rightBox;
        const neighbour = Main.panel.statusArea['adaptive-ros'] ||
            Main.panel.statusArea['adaptive-network'] ||
            Main.panel.statusArea['adaptive-tasks'] ||
            Main.panel.statusArea['adaptive-usb'] ||
            Main.panel.statusArea.aggregateMenu;
        const index = neighbour ? Math.max(0, rightBox.get_children().indexOf(neighbour.container)) : 0;
        Main.panel.addToStatusArea('adaptive-system', this._button, index, 'right');

        this._telemetry = new Telemetry.Telemetry();
        this._telemetry.connect(snapshot => this._update(snapshot));

        this._openStateId = this._button.menu.connect('open-state-changed', (_m, open) => {
            this._onOpenStateChanged(open);
        });

        this._sessionId = Main.sessionMode.connect('updated', () => this._syncSession());
        this._syncSession();
        log('[Adaptive System] panel indicator installed');
    }

    _sectionTitle(parent, text) {
        const label = new St.Label({
            text,
            style_class: 'adaptive-shade-section-title',
        });
        parent.add_child(label);
        return label;
    }

    _buildMetrics(section) {
        this._detail = [];

        // CPU
        this._cpuRow = new MetricRow('CPU', ACCENT_CPU);
        section.add_child(this._cpuRow);

        this._coreBox = new St.BoxLayout({
            style_class: 'adaptive-shade-cores',
            x_expand: true,
        });
        section.add_child(this._coreBox);
        this._coreBars = [];
        this._detail.push(this._coreBox);

        this._loadLabel = new St.Label({
            text: '',
            style_class: 'adaptive-shade-load',
        });
        section.add_child(this._loadLabel);
        this._detail.push(this._loadLabel);

        // Memory & Swap
        this._memTitle = this._sectionTitle(section, 'Memory & Swap');
        this._memoryRow = new MeterRow('RAM');
        section.add_child(this._memoryRow);

        this._memoryDetailLabel = new St.Label({
            text: '',
            style_class: 'adaptive-shade-subline',
        });
        section.add_child(this._memoryDetailLabel);

        this._swapRow = new MeterRow('Swap');
        section.add_child(this._swapRow);

        this._swapDetailLabel = new St.Label({
            text: '',
            style_class: 'adaptive-shade-subline',
        });
        section.add_child(this._swapDetailLabel);

        // GPU & VRAM
        this._gpuTitle = this._sectionTitle(section, 'GPU');
        this._gpuRow = new MetricRow('GPU', ACCENT_GPU);
        section.add_child(this._gpuRow);

        this._vramRow = new MeterRow('VRAM');
        section.add_child(this._vramRow);

        this._vramDetailLabel = new St.Label({
            text: '',
            style_class: 'adaptive-shade-subline',
        });
        section.add_child(this._vramDetailLabel);

        this._igpuRow = new MetricRow('iGPU', ACCENT_CPU);
        section.add_child(this._igpuRow);
        this._igpuRow.visible = false;
        this._detail.push(this._igpuRow);

        // Storage / Disks
        this._diskTitle = this._sectionTitle(section, 'Storage');
        this._diskBox = new St.BoxLayout({ vertical: true, x_expand: true });
        section.add_child(this._diskBox);
        this._diskRows = [];

        this._diskIOLabel = new St.Label({
            text: '',
            style_class: 'adaptive-shade-subline',
        });
        section.add_child(this._diskIOLabel);
        this._detail.push(this._diskTitle, this._diskBox, this._diskIOLabel);

        // Network
        this._netTitle = this._sectionTitle(section, 'Network');
        this._netBox = new St.BoxLayout({ vertical: true, x_expand: true });
        section.add_child(this._netBox);
        this._netRows = [];
        this._detail.push(this._netTitle, this._netBox);

        // Thermals
        this._thermalTitle = this._sectionTitle(section, 'Temperatures');
        this._thermalGrid = new St.Widget({
            style_class: 'adaptive-shade-chips',
            layout_manager: new Clutter.GridLayout({
                orientation: Clutter.Orientation.HORIZONTAL,
                column_homogeneous: true,
                column_spacing: 6,
                row_spacing: 6,
            }),
            x_expand: true,
        });
        section.add_child(this._thermalGrid);
        this._thermalChips = [];
        this._detail.push(this._thermalTitle, this._thermalGrid);

        // Top Processes
        this._procTitle = this._sectionTitle(section, 'Top processes');
        this._procBox = new St.BoxLayout({ vertical: true, x_expand: true });
        section.add_child(this._procBox);
        this._procRows = [];

        this._memoryHogsLabel = new St.Label({
            text: '',
            style_class: 'adaptive-shade-subline',
        });
        section.add_child(this._memoryHogsLabel);
        this._detail.push(this._procTitle, this._procBox, this._memoryHogsLabel);

        // Battery
        this._batteryLabel = new St.Label({
            text: '',
            style_class: 'adaptive-shade-footer-item',
        });
        section.add_child(this._batteryLabel);

        this._applyDetail();
    }

    _toggleDetail() {
        this._expanded = !this._expanded;
        this._applyDetail();
        writeConfig({ systemExpanded: this._expanded });

        if (this._telemetry)
            this._telemetry.setDetailed(this._expanded);

        this._fitToMonitor();
    }

    _applyDetail() {
        for (const actor of this._detail)
            actor.visible = this._expanded;

        this._memoryDetailLabel.visible = this._expanded;
        this._swapDetailLabel.visible = this._expanded && this._swapRow.visible;

        this._expandButton.label = this._expanded ? 'Show less' : 'Show more';
    }

    _fitToMonitor() {
        if (!this._scroll || !this._systemSection)
            return;

        const monitor = Main.layoutManager.findMonitorForActor(this._button) ||
            Main.layoutManager.primaryMonitor;
        if (!monitor)
            return;

        const [, natural] = this._systemSection.get_preferred_height(-1);
        if (!(natural > 0))
            return;

        const cap = Math.max(240, monitor.height - 120);
        const height = Math.min(natural, cap);
        this._scroll.set_height(height);
    }

    _destroySparklines() {
        for (const row of [this._cpuRow, this._gpuRow, this._igpuRow]) {
            if (row && row.sparkline) {
                row.sparkline.destroy();
                row.sparkline = null;
            }
        }
    }

    _syncSession() {
        const allowed = Main.sessionMode.hasOverview;
        if (this._button)
            this._button.visible = allowed;
    }

    _onOpenStateChanged(isOpen) {
        if (!this._telemetry)
            return;

        if (isOpen) {
            this._fitToMonitor();
            for (const row of [this._cpuRow, this._gpuRow, this._igpuRow]) {
                if (row && row.sparkline)
                    row.sparkline.reset();
            }
            this._telemetry.setDetailed(this._expanded);
            this._telemetry.start();
        } else {
            this._telemetry.stop();
        }
    }

    _update(snapshot) {
        this._fitToMonitor();

        this._uptimeLabel.text = snapshot.uptimeSeconds
            ? `Up ${Telemetry.formatDuration(snapshot.uptimeSeconds)}`
            : '';
        this._uptimeChip.visible = !!snapshot.uptimeSeconds;

        this._updateCpu(snapshot);
        this._updateMemory(snapshot);
        this._updateGpu(snapshot);
        this._updateBattery(snapshot);

        if (!this._expanded)
            return;

        this._updateDisks(snapshot);
        this._updateNetwork(snapshot);
        this._updateThermal(snapshot);
        this._updateProcesses(snapshot);
    }

    _updateCpu(snapshot) {
        const cpu = snapshot.cpu;
        this._cpuRow.setValue(pct(cpu.percent));
        this._cpuRow.sparkline.push(cpu.percent);
        this._cpuRow.setMeta(`${mhz(cpu.freqMhz)}\n${degrees(cpu.tempC)}`);
        this._cpuRow.setMetaColor(Telemetry.tempColor(cpu.tempC));

        if (!this._expanded)
            return;

        this._updateCores(snapshot);

        const load = snapshot.load;
        if (Number.isFinite(load.avg1)) {
            const procs = Number.isFinite(snapshot.processes.count)
                ? `${snapshot.processes.count} processes, `
                : '';
            this._loadLabel.text =
                `load ${load.avg1.toFixed(2)}  ${load.avg5.toFixed(2)}  ` +
                `${load.avg15.toFixed(2)}   ·   ${procs}` +
                `${load.running} running of ${load.total} tasks`;
        }
    }

    _updateCores(snapshot) {
        const cores = snapshot.cpu.cores || [];

        if (this._coreBars.length !== cores.length) {
            this._coreBox.destroy_all_children();
            this._coreBars = cores.map(() => {
                const track = new St.Widget({
                    style_class: 'adaptive-core',
                    layout_manager: new Clutter.BinLayout(),
                    x_expand: true,
                });
                const fill = new St.Widget({
                    style_class: 'adaptive-core-fill',
                    y_align: Clutter.ActorAlign.END,
                    x_expand: true,
                });
                track.add_child(fill);
                this._coreBox.add_child(track);

                const bar = { track, fill, value: 0, color: null };
                track.connect('notify::height', () => this._applyCoreBar(bar));
                return bar;
            });
        }

        this._coreBars.forEach((bar, i) => {
            bar.value = Number.isFinite(cores[i]) ? cores[i] : 0;
            this._applyCoreBar(bar);
        });
    }

    _applyCoreBar(bar) {
        const height = bar.track.get_height();
        if (height > 0)
            bar.fill.set_height(Math.max(1, Math.round(height * bar.value / 100)));

        const color = bar.value >= 85 ? DANGER
            : bar.value >= 60 ? WARNING
                : ACCENT_CPU;
        if (bar.color !== color) {
            bar.color = color;
            bar.fill.style = fillStyle(color);
        }
    }

    _updateMemory(snapshot) {
        const mem = snapshot.memory;

        if (Number.isFinite(mem.totalBytes) && Number.isFinite(mem.usedBytes)) {
            const fraction = mem.percent / 100;
            this._memoryRow.meter.setFraction(fraction);
            this._memoryRow.meter.setColor(
                mem.percent >= 90 ? DANGER
                    : mem.percent >= 75 ? WARNING
                        : ACCENT_CPU);
            this._memoryRow.setValue(
                `${Telemetry.formatBytes(mem.usedBytes)} / ${Telemetry.formatBytes(mem.totalBytes)} (${Math.round(mem.percent)}%)`);

            const availText = Number.isFinite(mem.availableBytes)
                ? `Available ${Telemetry.formatBytes(mem.availableBytes)}`
                : '';
            const bufCache = (mem.buffersBytes || 0) + (mem.cachedBytes || 0);
            const bufCacheText = bufCache > 0
                ? ` · Buffers/Cache ${Telemetry.formatBytes(bufCache)}`
                : '';
            const freeText = Number.isFinite(mem.freeBytes)
                ? ` · Free ${Telemetry.formatBytes(mem.freeBytes)}`
                : '';
            this._memoryDetailLabel.text = `${availText}${bufCacheText}${freeText}`;
            this._memoryDetailLabel.visible = this._expanded;
        }

        const hasSwap = Number.isFinite(mem.swapTotalBytes) && mem.swapTotalBytes > 0;
        this._swapRow.visible = hasSwap;
        this._swapDetailLabel.visible = hasSwap && this._expanded;
        if (hasSwap) {
            const fraction = mem.swapUsedBytes / mem.swapTotalBytes;
            this._swapRow.meter.setFraction(fraction);
            this._swapRow.meter.setColor(fraction >= 0.5 ? WARNING : ACCENT_GPU);
            this._swapRow.setValue(
                `${Telemetry.formatBytes(mem.swapUsedBytes)} / ${Telemetry.formatBytes(mem.swapTotalBytes)} (${Math.round(mem.swapPercent || 0)}%)`);
            this._swapDetailLabel.text = `Free ${Telemetry.formatBytes(mem.swapFreeBytes)}`;
        }
    }

    _updateGpu(snapshot) {
        const gpu = snapshot.gpu;

        if (!gpu.available) {
            this._gpuTitle.visible = false;
            this._gpuRow.visible = false;
            this._vramRow.visible = false;
            this._vramDetailLabel.visible = false;
            return;
        }

        this._gpuTitle.visible = true;
        this._gpuTitle.text = gpu.name ? `GPU · ${gpu.name}` : 'GPU';

        this._gpuRow.visible = true;
        this._gpuRow.setValue(pct(gpu.percent));
        this._gpuRow.sparkline.push(gpu.percent);

        let clock = '';
        if (Number.isFinite(gpu.freqMhz))
            clock = gpu.freqMhz > 0 ? mhz(gpu.freqMhz) : 'Idle';
        const temp = Number.isFinite(gpu.tempC) ? `\n${degrees(gpu.tempC)}` : '';
        this._gpuRow.setMeta(`${clock}${temp}`);
        if (Number.isFinite(gpu.tempC))
            this._gpuRow.setMetaColor(Telemetry.tempColor(gpu.tempC));

        // GPU VRAM
        const hasVram = Number.isFinite(gpu.vramTotalBytes) && gpu.vramTotalBytes > 0;
        this._vramRow.visible = hasVram;
        this._vramDetailLabel.visible = hasVram;
        if (hasVram) {
            const vramFraction = gpu.vramPercent / 100;
            this._vramRow.meter.setFraction(vramFraction);
            this._vramRow.meter.setColor(
                vramFraction >= 0.9 ? DANGER : vramFraction >= 0.75 ? WARNING : ACCENT_GPU);
            this._vramRow.setValue(
                `${Telemetry.formatBytes(gpu.vramUsedBytes)} / ${Telemetry.formatBytes(gpu.vramTotalBytes)} (${Math.round(gpu.vramPercent)}%)`);
            const freeVram = Number.isFinite(gpu.vramFreeBytes)
                ? `Free ${Telemetry.formatBytes(gpu.vramFreeBytes)}`
                : '';
            const driverInfo = gpu.driver ? ` · Driver ${gpu.driver}` : '';
            this._vramDetailLabel.text = `${freeVram}${driverInfo}`;
        }

        // iGPU (Intel HD Graphics) if present alongside dedicated GPU
        const igpu = snapshot.igpu;
        if (igpu && igpu.available && igpu.name !== gpu.name) {
            this._igpuRow.visible = this._expanded;
            this._igpuRow.setValue(pct(igpu.percent));
            this._igpuRow.sparkline.push(igpu.percent);
            const iclock = Number.isFinite(igpu.freqMhz) ? (igpu.freqMhz > 0 ? mhz(igpu.freqMhz) : 'Idle') : '';
            this._igpuRow.setMeta(iclock);
        } else {
            this._igpuRow.visible = false;
        }
    }

    _updateDisks(snapshot) {
        const disks = snapshot.disks || [];

        if (this._diskRows.length !== disks.length) {
            this._diskBox.destroy_all_children();
            this._diskRows = disks.map(() => {
                const row = new MeterRow('');
                this._diskBox.add_child(row);
                return row;
            });
        }

        disks.forEach((disk, i) => {
            const row = this._diskRows[i];
            row.setName(disk.label);
            row.meter.setFraction(disk.percent / 100);
            row.meter.setColor(disk.percent >= 90 ? DANGER : ACCENT_NET);
            row.setValue(
                `${Telemetry.formatBytes(disk.usedBytes)} / ` +
                `${Telemetry.formatBytes(disk.totalBytes)}`);
        });

        const io = snapshot.diskIO;
        this._diskIOLabel.text =
            `read ${Telemetry.formatRate(io.readRate)}   ` +
            `write ${Telemetry.formatRate(io.writeRate)}`;
    }

    _updateNetwork(snapshot) {
        const interfaces = snapshot.network.interfaces || [];

        if (this._netRows.length !== interfaces.length) {
            this._netBox.destroy_all_children();
            this._netRows = interfaces.map(() => {
                const row = new St.BoxLayout({
                    style_class: 'adaptive-net-row',
                    x_expand: true,
                });
                const name = new St.Label({
                    style_class: 'adaptive-net-name',
                    x_expand: true,
                });
                const rate = new St.Label({ style_class: 'adaptive-net-rate' });
                row.add_child(name);
                row.add_child(rate);
                this._netBox.add_child(row);
                return { name, rate };
            });
        }

        interfaces.forEach((iface, i) => {
            const row = this._netRows[i];
            row.name.text = iface.name;
            row.rate.text =
                `↓ ${Telemetry.formatRate(iface.rxRate)}   ` +
                `↑ ${Telemetry.formatRate(iface.txRate)}`;
        });
    }

    _updateThermal(snapshot) {
        const zones = snapshot.thermal || [];

        if (this._thermalChips.length !== zones.length) {
            this._thermalGrid.destroy_all_children();
            this._thermalChips = zones.map((_zone, i) => {
                const chip = new St.BoxLayout({
                    vertical: true,
                    style_class: 'adaptive-chip',
                });
                const name = new St.Label({ style_class: 'adaptive-chip-name' });
                const value = new St.Label({ style_class: 'adaptive-chip-value' });
                chip.add_child(name);
                chip.add_child(value);
                this._thermalGrid.layout_manager.attach(
                    chip, i % 4, Math.floor(i / 4), 1, 1);
                return { name, value, color: null };
            });
        }

        zones.forEach((zone, i) => {
            const chip = this._thermalChips[i];
            chip.name.text = zone.label;
            chip.value.text = degrees(zone.celsius);

            const color = Telemetry.tempColor(zone.celsius);
            if (chip.color !== color) {
                chip.color = color;
                chip.value.style = `color: ${color};`;
            }
        });
    }

    _updateProcesses(snapshot) {
        const byCpu = snapshot.processes.byCpu || [];

        if (this._procRows.length !== byCpu.length) {
            this._procBox.destroy_all_children();
            this._procRows = byCpu.map(() => {
                const row = new ProcessRow();
                this._procBox.add_child(row);
                return row;
            });
        }

        byCpu.forEach((proc, i) => this._procRows[i].update(proc));

        const byMemory = snapshot.processes.byMemory || [];
        this._memoryHogsLabel.text = byMemory.length > 0
            ? `most memory: ${byMemory.slice(0, 3).map(
                p => `${p.command} ${Telemetry.formatBytes(p.rssBytes)}`).join('   ')}`
            : '';
    }

    _updateBattery(snapshot) {
        const battery = snapshot.battery;

        if (!battery.present) {
            this._batteryLabel.visible = false;
            return;
        }

        let text = `Battery ${Math.round(battery.percent)}% · ${battery.state}`;
        if (battery.timeRemaining > 0) {
            const minutes = Math.round(battery.timeRemaining / 60);
            const hours = Math.floor(minutes / 60);
            text += hours > 0
                ? ` · ${hours}h ${minutes % 60}m`
                : ` · ${minutes}m`;
        }
        this._batteryLabel.text = text;
        this._batteryLabel.visible = true;
    }

    detach() {
        if (this._sessionId) {
            Main.sessionMode.disconnect(this._sessionId);
            this._sessionId = 0;
        }
        if (this._openStateId && this._button) {
            this._button.menu.disconnect(this._openStateId);
            this._openStateId = 0;
        }
        if (this._telemetry) {
            this._telemetry.destroy();
            this._telemetry = null;
        }
        this._destroySparklines();
        if (this._button) {
            this._button.destroy();
            this._button = null;
        }
    }
};
