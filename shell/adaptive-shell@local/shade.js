// Adaptive Shade v2 - an information center
//
// The date menu, rebuilt as somewhere to LOOK at things rather than change them.
// It carries a clock, notifications grouped per application, and the machine's
// full state; GNOME's own aggregate menu in the top-right keeps every control,
// so nothing here toggles anything.
//
// The calendar column is GNOME's, untouched. An Adaptive month/agenda/week view
// was built and removed: the stock calendar is what was wanted.
//
// The popup stays GNOME's. This takes the native CalendarMessageList out of
// #calendarArea, wraps it in a column carrying a header and live system
// telemetry, and puts that column back where the list stood. The list itself is
// never rebuilt, so notification delivery, storage, urgency, history and Clear
// all remain the code GNOME ships. Only the arrangement of cards inside it
// changes, and only when the grouped section builds successfully.
//
// Because this rearranges actors the shell owns, detach() has to be exact: the
// recorded parent, index and y_expand are what make disabling the extension give
// back a working stock date menu.

/* exported Shade */

const { St, Clutter, GLib, GObject } = imports.gi;
const Main = imports.ui.main;

const Me = imports.misc.extensionUtils.getCurrentExtension();
const Telemetry = Me.imports.telemetry;
const Sparkline = Me.imports.sparkline;
const Notifications = Me.imports.notifications;

// Layout bounds for _fitToMonitor().
const NOTIFICATION_MIN_HEIGHT = 220;
const MIN_SYSTEM_HEIGHT = 260;

const ACCENT_CPU = '#78A9FF';
const ACCENT_GPU = '#9A8BFF';
const ACCENT_NET = '#66E0FF';
const WARNING = '#F3C96B';
const DANGER = '#FF7A90';

// Matches the ~/.config/adaptive-desktop/projects.json convention already used
// by the Projects app.
const CONFIG_PATH = GLib.build_filenamev(
    [GLib.get_user_config_dir(), 'adaptive-desktop', 'shade.json']);

function readConfig() {
    try {
        const [ok, contents] = GLib.file_get_contents(CONFIG_PATH);
        if (!ok)
            return {};
        return JSON.parse(new TextDecoder().decode(contents)) || {};
    } catch (e) {
        // No config, or unparseable: defaults are the answer either way.
        return {};
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

// A percentage bar. St has no progress widget, so the fill is a plain actor
// whose width is recomputed whenever the track's own width changes - which
// covers both value updates and the popup being resized.
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
        // Assigning .style forces St to reparse the rule, so skip the write
        // when the colour has not actually changed - which is most ticks.
        if (this._color === hex)
            return;
        this._color = hex;
        this._fill.style = `background-color: ${hex};`;
    }

    _apply() {
        const width = this.get_width();
        if (width <= 0)
            return;
        this._fill.set_width(Math.round(width * this._fraction));
    }
});

// "CPU  34%  <sparkline>  2.58 GHz / 71 degrees" on one line.
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

    // The temperature reading drives the colour, not the load: a busy cold chip
    // is fine and an idle hot one is not.
    setMetaColor(hex) {
        if (this._metaColor === hex)
            return;
        this._metaColor = hex;
        this._meta.style = `color: ${hex};`;
    }
});

// A labelled bar with a trailing figure, for anything that is a share of a
// fixed total rather than a rate over time.
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

// One process: name, CPU share, resident memory.
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
        // Multi-process applications are aggregated by name upstream, so say
        // how many when it is more than one.
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

var Shade = class Shade {
    constructor(callbacks) {
        this._callbacks = callbacks || {};

        this._dateMenu = null;
        this._messageList = null;
        this._origParent = null;
        this._origIndex = -1;
        this._origYExpand = true;

        this._container = null;
        this._telemetry = null;
        this._grouped = null;
        this._placeholder = null;
        this._placeholderParent = null;
        this._stockSection = null;
        this._stockIndex = -1;
        this._openStateId = 0;
        this._attached = false;
    }

    // --------------------------------------------------------------- attach

    attach() {
        if (this._attached)
            return;

        const dateMenu = Main.panel.statusArea.dateMenu;
        if (!dateMenu || !dateMenu._messageList) {
            log('[Adaptive Shade] date menu has no message list; staying stock');
            return;
        }

        const messageList = dateMenu._messageList;
        const parent = messageList.get_parent();
        if (!parent) {
            log('[Adaptive Shade] message list is unparented; staying stock');
            return;
        }

        // Remember exactly where the list came from. detach() puts it back here
        // and nowhere else. GNOME builds it with y_expand already set, so record
        // what it actually was rather than assuming.
        this._origParent = parent;
        this._origIndex = parent.get_children().indexOf(messageList);
        this._origYExpand = messageList.y_expand;
        this._dateMenu = dateMenu;
        this._messageList = messageList;

        try {
            this._telemetry = new Telemetry.Telemetry();

            this._container = new St.BoxLayout({
                vertical: true,
                style_class: 'adaptive-shade',
                x_expand: true,
                y_expand: true,
            });

            this._buildHeader();
            this._buildSystem();

            parent.remove_child(messageList);
            messageList.y_expand = true;
            this._container.add_child(messageList);
            parent.insert_child_at_index(this._container, this._origIndex);

            this._installGroupedNotifications();
            this._unstackPlaceholder();

            this._telemetry.connect(snapshot => this._update(snapshot));

            // Nothing polls while the shade is shut. This is the whole reason
            // a per-second sysfs sweep is affordable inside gnome-shell.
            this._openStateId = dateMenu.menu.connect(
                'open-state-changed',
                (menu, isOpen) => this._onOpenStateChanged(isOpen));

            this._attached = true;
            log('[Adaptive Shade] attached to the GNOME date menu');
        } catch (e) {
            logError(e, '[Adaptive Shade] attach failed; reverting to stock');
            this.detach();
        }
    }

    // Swap GNOME's flat notification list for the per-app grouped one.
    //
    // Two fallbacks, because an unreadable notification list is worse than an
    // ugly one: a config switch for a permanent opt-out, and a catch that puts
    // GNOME's own section straight back if the grouped one cannot be built.
    _installGroupedNotifications() {
        if (readConfig().notificationGrouping === false) {
            log('[Adaptive Shade] notification grouping disabled by config');
            return;
        }

        const list = this._messageList;
        const sectionList = list._sectionList;
        const stock = list._notificationSection;

        if (!sectionList || !stock) {
            log('[Adaptive Shade] no notification section to group; staying stock');
            return;
        }

        try {
            this._stockIndex = sectionList.get_children().indexOf(stock);
            // Removed, not destroyed: the object stays alive and wired so
            // detach can put the original back rather than rebuild it.
            sectionList.remove_child(stock);
            this._stockSection = stock;

            this._grouped = new Notifications.GroupedNotificationSection();
            list._addSection(this._grouped);

            log('[Adaptive Shade] notifications grouped by application');
        } catch (e) {
            logError(e, '[Adaptive Shade] grouping failed; restoring GNOME list');
            this._restoreStockNotifications();
        }
    }

    _restoreStockNotifications() {
        if (this._grouped) {
            try {
                this._grouped.destroy();
            } catch (e) {
                logError(e, '[Adaptive Shade] destroying grouped section');
            }
            this._grouped = null;
        }

        if (this._stockSection && this._messageList) {
            try {
                const sectionList = this._messageList._sectionList;
                if (sectionList && !this._stockSection.get_parent()) {
                    const index = Math.max(0, Math.min(
                        this._stockIndex, sectionList.get_children().length));
                    sectionList.insert_child_at_index(this._stockSection, index);
                }
            } catch (e) {
                logError(e, '[Adaptive Shade] restoring GNOME notification list');
            }
        }

        this._stockSection = null;
        this._stockIndex = -1;
    }

    // GNOME stacks the "No Notifications" placeholder over the message list with
    // a Clutter.BinLayout, so it shares that space with the box holding the
    // scroll view and the Do Not Disturb row. Stock GNOME gets away with it
    // because the list is tall enough that a centred placeholder clears the
    // controls at the bottom. In the shade the list is compressed - the system
    // block takes most of the column - and the two land on top of each other.
    //
    // Moving the placeholder into that vertical box, above the controls, puts it
    // in normal flow: it can no longer overlap them at any height.
    _unstackPlaceholder() {
        const list = this._messageList;
        const placeholder = list._placeholder;
        const scrollView = list._scrollView;
        const box = scrollView ? scrollView.get_parent() : null;

        if (!placeholder || !box || placeholder.get_parent() !== list)
            return;

        try {
            this._placeholder = placeholder;
            this._placeholderParent = list;
            this._placeholderExpand = placeholder.y_expand;
            this._placeholderAlign = placeholder.y_align;

            list.remove_child(placeholder);
            box.insert_child_at_index(
                placeholder, box.get_children().indexOf(scrollView));

            placeholder.y_expand = true;
            placeholder.y_align = Clutter.ActorAlign.CENTER;
        } catch (e) {
            logError(e, '[Adaptive Shade] moving the empty-state placeholder');
            this._placeholder = null;
        }
    }

    _restackPlaceholder() {
        if (!this._placeholder || !this._placeholderParent) {
            this._placeholder = null;
            this._placeholderParent = null;
            return;
        }

        try {
            const holder = this._placeholder.get_parent();
            if (holder)
                holder.remove_child(this._placeholder);

            this._placeholder.y_expand = this._placeholderExpand;
            this._placeholder.y_align = this._placeholderAlign;
            this._placeholderParent.add_child(this._placeholder);
        } catch (e) {
            logError(e, '[Adaptive Shade] restoring the empty-state placeholder');
        }

        this._placeholder = null;
        this._placeholderParent = null;
    }

    // --------------------------------------------------------------- detach

    detach() {
        if (this._telemetry) {
            this._telemetry.destroy();
            this._telemetry = null;
        }

        this._restoreStockNotifications();
        this._restackPlaceholder();

        if (this._openStateId && this._dateMenu) {
            try {
                this._dateMenu.menu.disconnect(this._openStateId);
            } catch (e) {
                logError(e, '[Adaptive Shade] disconnect open-state');
            }
        }
        this._openStateId = 0;

        // Order matters: the message list has to be back under its original
        // parent before the container that currently holds it is destroyed,
        // or destroying the container takes GNOME's list down with it.
        if (this._messageList && this._origParent) {
            try {
                const holder = this._messageList.get_parent();
                if (holder)
                    holder.remove_child(this._messageList);

                this._messageList.y_expand = this._origYExpand;

                const index = Math.max(0, Math.min(
                    this._origIndex, this._origParent.get_children().length));
                this._origParent.insert_child_at_index(this._messageList, index);
            } catch (e) {
                logError(e, '[Adaptive Shade] restoring the message list');
            }
        }

        this._destroySparklines();

        if (this._container) {
            try {
                this._container.destroy();
            } catch (e) {
                logError(e, '[Adaptive Shade] destroying the shade');
            }
            this._container = null;
        }

        this._messageList = null;
        this._origParent = null;
        this._origIndex = -1;
        this._origYExpand = true;
        this._dateMenu = null;
        this._attached = false;
    }

    close() {
        if (this._dateMenu && this._dateMenu.menu)
            this._dateMenu.menu.close();
    }

    // --------------------------------------------------------------- header

    _buildHeader() {
        const header = new St.BoxLayout({
            style_class: 'adaptive-shade-header',
            x_expand: true,
        });
        this._container.add_child(header);

        const text = new St.BoxLayout({
            vertical: true,
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        header.add_child(text);

        this._timeLabel = new St.Label({
            text: '',
            style_class: 'adaptive-shade-time',
        });
        text.add_child(this._timeLabel);

        this._dateLabel = new St.Label({
            text: '',
            style_class: 'adaptive-shade-date',
        });
        text.add_child(this._dateLabel);

        // Uptime belongs with the clock: both answer "how long has this been
        // going", and it keeps the system block to pure measurements.
        this._uptimeLabel = new St.Label({
            text: '',
            style_class: 'adaptive-shade-uptime',
            y_align: Clutter.ActorAlign.END,
        });
        header.add_child(this._uptimeLabel);

        this._updateClock();
    }

    _updateClock() {
        const now = GLib.DateTime.new_now_local();
        this._timeLabel.text = now.format('%H:%M');
        this._dateLabel.text = now.format('%A, %e %B');
    }

    // --------------------------------------------------------------- system

    _sectionTitle(parent, text) {
        parent.add_child(new St.Label({
            text,
            style_class: 'adaptive-shade-section-title',
        }));
    }

    _buildSystem() {
        // The system block is the one part of the shade with no natural bound:
        // sixteen cores, eleven sensors and five processes add up past the
        // screen on a laptop panel. It gets its own scroll view, sized against
        // the monitor when the popup opens, so the shade can never grow taller
        // than the display. GNOME's message list below keeps its own scrolling,
        // which is why this wraps the system section rather than everything -
        // nesting a scroll view inside a scroll view gives neither a sane size.
        this._systemScroll = new St.ScrollView({
            style_class: 'adaptive-shade-scroll vfade',
            overlay_scrollbars: true,
            x_expand: true,
        });
        this._systemScroll.set_policy(
            St.PolicyType.NEVER, St.PolicyType.AUTOMATIC);
        this._container.add_child(this._systemScroll);

        const section = new St.BoxLayout({
            vertical: true,
            style_class: 'adaptive-shade-system',
            x_expand: true,
        });
        this._systemScroll.add_actor(section);
        this._systemSection = section;

        this._sectionTitle(section, 'SYSTEM');

        this._cpuRow = new MetricRow('CPU', ACCENT_CPU);
        section.add_child(this._cpuRow);

        // Per-core load as a row of vertical bars: sixteen numbers would be
        // unreadable, sixteen bars show an imbalance instantly.
        this._coreBox = new St.BoxLayout({
            style_class: 'adaptive-shade-cores',
            x_expand: true,
        });
        section.add_child(this._coreBox);
        this._coreBars = [];

        this._loadLabel = new St.Label({
            text: '',
            style_class: 'adaptive-shade-load',
        });
        section.add_child(this._loadLabel);

        this._gpuRow = new MetricRow('GPU', ACCENT_GPU);
        section.add_child(this._gpuRow);

        this._memoryRow = new MeterRow('Memory');
        section.add_child(this._memoryRow);

        this._swapRow = new MeterRow('Swap');
        section.add_child(this._swapRow);

        this._diskBox = new St.BoxLayout({ vertical: true, x_expand: true });
        section.add_child(this._diskBox);
        this._diskRows = [];

        this._diskIOLabel = new St.Label({
            text: '',
            style_class: 'adaptive-shade-subline',
        });
        section.add_child(this._diskIOLabel);

        this._sectionTitle(section, 'NETWORK');
        this._netBox = new St.BoxLayout({ vertical: true, x_expand: true });
        section.add_child(this._netBox);
        this._netRows = [];

        this._sectionTitle(section, 'TEMPERATURES');
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

        this._sectionTitle(section, 'TOP PROCESSES');
        this._procBox = new St.BoxLayout({ vertical: true, x_expand: true });
        section.add_child(this._procBox);
        this._procRows = [];

        this._memoryHogsLabel = new St.Label({
            text: '',
            style_class: 'adaptive-shade-subline',
        });
        section.add_child(this._memoryHogsLabel);

        this._batteryLabel = new St.Label({
            text: '',
            style_class: 'adaptive-shade-footer-item',
        });
        section.add_child(this._batteryLabel);
    }

    // Give the system scroll view the smaller of what it wants and what the
    // screen can spare, so it scrolls only when it actually has to.
    _fitToMonitor() {
        if (!this._systemScroll || !this._systemSection)
            return;

        const monitor = Main.layoutManager.primaryMonitor;
        if (!monitor)
            return;

        const [, natural] = this._systemSection.get_preferred_height(-1);

        // Before the first allocation the section has no preferred height yet.
        // Capping to zero would collapse it to an empty strip, so leave it
        // unbounded and try again on the next tick.
        if (!(natural > 0))
            return;

        // Room kept for the panel, the popup's own chrome and header, and
        // enough of the notification list to be worth showing.
        const reserved = 170 + NOTIFICATION_MIN_HEIGHT;
        const cap = Math.max(MIN_SYSTEM_HEIGHT, monitor.height - reserved);
        const height = Math.min(natural, cap);

        if (this._systemHeight !== height) {
            this._systemHeight = height;
            this._systemScroll.set_height(height);
        }
    }

    _destroySparklines() {
        for (const row of [this._cpuRow, this._gpuRow]) {
            if (row && row.sparkline) {
                row.sparkline.destroy();
                row.sparkline = null;
            }
        }
    }

    // --------------------------------------------------------------- update

    _onOpenStateChanged(isOpen) {
        if (!this._telemetry)
            return;

        if (isOpen) {
            this._updateClock();
            this._fitToMonitor();
            // Charts start blank rather than resuming a trace from whenever the
            // shade was last open, which would read as history it is not.
            for (const row of [this._cpuRow, this._gpuRow]) {
                if (row && row.sparkline)
                    row.sparkline.reset();
            }
            this._telemetry.start();
        } else {
            this._telemetry.stop();
        }
    }

    _update(snapshot) {
        this._updateClock();
        // Sensors and process rows appear over the first few ticks, so the
        // section's natural height is not final when the popup opens.
        this._fitToMonitor();
        this._uptimeLabel.text = snapshot.uptimeSeconds
            ? `up ${Telemetry.formatDuration(snapshot.uptimeSeconds)}`
            : '';

        this._updateCpu(snapshot);
        this._updateGpu(snapshot);
        this._updateMemory(snapshot);
        this._updateDisks(snapshot);
        this._updateNetwork(snapshot);
        this._updateThermal(snapshot);
        this._updateProcesses(snapshot);
        this._updateBattery(snapshot);
    }

    _updateCpu(snapshot) {
        const cpu = snapshot.cpu;
        this._cpuRow.setValue(pct(cpu.percent));
        this._cpuRow.sparkline.push(cpu.percent);
        this._cpuRow.setMeta(`${mhz(cpu.freqMhz)}\n${degrees(cpu.tempC)}`);
        this._cpuRow.setMetaColor(Telemetry.tempColor(cpu.tempC));

        this._updateCores(snapshot);

        const load = snapshot.load;
        if (Number.isFinite(load.avg1)) {
            // /proc/loadavg's fourth field counts tasks - kernel threads
            // included - which is several times the number of processes. Say
            // "tasks" for it and take the process count from the /proc walk.
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

        // Core count is fixed for the life of the session, so the bars are
        // built once and only their heights move after that.
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
                // The track has no height on the frame it is created, so the
                // first fill would be zero-high. Reapply when it gets one.
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
            bar.fill.style = `background-color: ${color};`;
        }
    }

    _updateGpu(snapshot) {
        const gpu = snapshot.gpu;

        if (!gpu.available) {
            this._gpuRow.visible = false;
            return;
        }

        this._gpuRow.visible = true;
        this._gpuRow.setValue(pct(gpu.percent));
        this._gpuRow.sparkline.push(gpu.percent);

        // A powered-down render engine clocks at zero. Say so, rather than
        // printing "0 MHz" and looking like a dead sensor.
        const clock = Number.isFinite(gpu.freqMhz) && gpu.freqMhz > 0
            ? mhz(gpu.freqMhz)
            : 'Idle';
        const max = Number.isFinite(gpu.maxFreqMhz)
            ? `\nmax ${mhz(gpu.maxFreqMhz)}`
            : '';
        this._gpuRow.setMeta(`${clock}${max}`);
    }

    _updateMemory(snapshot) {
        const memory = snapshot.memory;

        this._memoryRow.meter.setFraction(memory.percent / 100);
        this._memoryRow.meter.setColor(
            memory.percent >= 90 ? DANGER
                : memory.percent >= 75 ? WARNING
                    : ACCENT_CPU);
        this._memoryRow.setValue(
            `${Telemetry.formatBytes(memory.usedBytes)} / ` +
            `${Telemetry.formatBytes(memory.totalBytes)}`);

        // Machines without swap should not be told about the swap they lack.
        const hasSwap = Number.isFinite(memory.swapTotalBytes) &&
            memory.swapTotalBytes > 0;
        this._swapRow.visible = hasSwap;
        if (hasSwap) {
            const fraction = memory.swapUsedBytes / memory.swapTotalBytes;
            this._swapRow.meter.setFraction(fraction);
            this._swapRow.meter.setColor(fraction >= 0.5 ? WARNING : ACCENT_GPU);
            this._swapRow.setValue(
                `${Telemetry.formatBytes(memory.swapUsedBytes)} / ` +
                `${Telemetry.formatBytes(memory.swapTotalBytes)}`);
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

        // The memory ranking rarely differs enough to deserve its own table,
        // but it answers a different question, so it gets one compact line.
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
        // UPower reports zero when it has not worked out a rate yet, and a
        // "0 minutes remaining" would be alarming and wrong.
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
};
