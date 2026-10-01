// Adaptive Tasks panel
//
// A top-bar indicator next to the USB panel: what is running right now and
// what it costs, with one click to end it - the part of a task manager that
// is needed often, without opening one.
//
//   Apps       running applications (the shell's own list), with their
//              windows, and CPU and memory summed over every process they
//              started - Chrome's renderers count against Chrome
//   Processes  your other busiest processes, by CPU or by memory
//
// End asks politely first (SIGTERM, what closing does) and follows with
// SIGKILL if the process is still there a few seconds later. Only your own
// processes are listed, and the ones the session cannot survive losing (the
// shell, X, the audio server, D-Bus, systemd) are never offered.
//
// Everything is read from /proc, only while the popup is open, every
// REFRESH_MS. Rows are updated in place and the list is only rebuilt when the
// set of apps or processes changes and the pointer is not over it, so a row
// never moves out from under a click.

/* exported TaskPanel */

const { Clutter, Gio, GLib, Shell, St } = imports.gi;
const Main = imports.ui.main;
const PanelMenu = imports.ui.panelMenu;

const Me = imports.misc.extensionUtils.getCurrentExtension();
const CC = Me.imports.ccUtil;

const REFRESH_MS = 2000;
const TERM_GRACE_MS = 3000;
const LIST_MAX_HEIGHT = 620;
const PROCESS_ROWS = 12;
const PAGE_SIZE = 4096;
const CLOCK_TICKS = 100;

// Never offered for ending: losing any of these takes the session with it.
const PROTECTED = new Set([
    'gnome-shell', 'Xorg', 'Xwayland', 'gnome-session-b', 'gnome-session-c',
    'systemd', 'dbus-daemon', 'dbus-broker', 'pipewire', 'pipewire-pulse',
    'wireplumber', 'pulseaudio', 'at-spi-bus-laun', 'at-spi2-registr',
    'ibus-daemon', 'ibus-x11', 'ibus-extension-', 'ibus-engine-sim',
    'gvfsd', 'gvfsd-fuse', 'xdg-desktop-por', 'xdg-document-po',
    'xdg-permission-', 'evolution-sourc', 'goa-daemon', 'gdm-x-session',
    'gnome-keyring-d', 'ssh-agent', 'gpg-agent', 'polkit-gnome-au',
]);

function readText(path) {
    try {
        const [ok, bytes] = GLib.file_get_contents(path);
        return ok ? new TextDecoder().decode(bytes) : null;
    } catch (e) {
        return null;
    }
}

function formatBytes(bytes) {
    if (bytes >= 1024 ** 3)
        return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
    if (bytes >= 1024 ** 2)
        return `${Math.round(bytes / 1024 ** 2)} MB`;
    return `${Math.round(bytes / 1024)} KB`;
}

function formatCpu(percent) {
    if (percent >= 10)
        return `${Math.round(percent)}%`;
    return `${percent.toFixed(1)}%`;
}

// One snapshot of every process this user owns.
function readProcesses(uid) {
    const table = new Map();
    let dir;
    try {
        dir = Gio.File.new_for_path('/proc').enumerate_children(
            'standard::name,unix::uid', Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, null);
    } catch (e) {
        return table;
    }

    let info;
    while ((info = dir.next_file(null)) !== null) {
        const name = info.get_name();
        if (!/^\d+$/.test(name) || info.get_attribute_uint32('unix::uid') !== uid)
            continue;

        const stat = readText(`/proc/${name}/stat`);
        const statm = readText(`/proc/${name}/statm`);
        if (!stat || !statm)
            continue;

        // comm is in parentheses and may itself hold spaces or parentheses.
        const open = stat.indexOf('(');
        const close = stat.lastIndexOf(')');
        const comm = stat.slice(open + 1, close);
        const fields = stat.slice(close + 2).split(' ');
        table.set(Number(name), {
            pid: Number(name),
            comm,
            state: fields[0],
            ppid: Number(fields[1]),
            ticks: Number(fields[11]) + Number(fields[12]),
            rss: Number(statm.split(' ')[1]) * PAGE_SIZE,
        });
    }
    dir.close(null);
    return table;
}

const INTERPRETERS = /^(python[\d.]*|node|nodejs|gjs|bash|sh|zsh|perl|ruby|java)$/;

function commandName(pid, comm) {
    const cmdline = readText(`/proc/${pid}/cmdline`) || '';
    const argv = cmdline.split('\0').filter(Boolean);

    // A script: name it by the script, not the interpreter running it.
    if (INTERPRETERS.test(comm)) {
        const rest = argv.slice(1);
        const module = rest.indexOf('-m');
        if (module >= 0 && rest[module + 1])
            return `${rest[module + 1]} (${comm} -m)`;
        // Inline code (-c) has no name worth showing.
        if (rest.includes('-c'))
            return `${comm} -c`;
        const script = rest.find(arg => !arg.startsWith('-'));
        return script ? `${GLib.path_get_basename(script)} (${comm})` : comm;
    }

    // comm is the kernel's name for the process and is cut at 15 characters;
    // only then is the command line worth reading. Electron and Chromium
    // rewrite theirs into one space-separated string, so take its first word.
    // Some programs rename their process (Files becomes "org.gnome.Nauti"),
    // and there the program's own file name reads better too.
    if (comm.length >= 15 && argv.length) {
        const first = GLib.path_get_basename(argv[0].split(' ')[0]);
        if (first)
            return first;
    }
    return comm;
}

var TaskPanel = class TaskPanel {
    constructor() {
        this._button = null;
        this._timerId = 0;
        this._openStateId = 0;
        this._sessionId = 0;
        this._uid = new Gio.Credentials().get_unix_user();
        this._selfPid = new Gio.Credentials().get_unix_pid();
        this._lastTicks = new Map();
        this._lastTime = 0;
        this._cpu = new Map();
        this._sortBy = 'cpu';
        this._ending = new Map();
        this._rows = new Map();
        this._structure = '';
        this._stale = false;
        this._totalCpu = { busy: 0, total: 0, percent: 0 };
    }

    attach() {
        this._button = new PanelMenu.Button(0.5, 'Tasks', false);
        this._button.add_child(new St.Icon({
            icon_name: 'utilities-system-monitor-symbolic',
            style_class: 'system-status-icon',
        }));

        this._button.menu.box.add_style_class_name('adaptive-cc-menu');
        const root = new St.BoxLayout({
            style_class: 'adaptive-cc adaptive-tasks',
            vertical: true,
            x_expand: true,
        });
        this._button.menu.box.add_child(root);

        const header = new St.BoxLayout({ style_class: 'adaptive-usb-header', x_expand: true });
        header.add_child(new St.Label({
            text: 'Tasks',
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
        root.add_child(this._scroll);

        const footer = new St.BoxLayout({ style_class: 'adaptive-tasks-footer', x_expand: true });
        const monitor = new St.Button({
            style_class: 'adaptive-cc-form-button',
            label: 'Open System Monitor',
            can_focus: true,
        });
        monitor.connect('clicked', () => {
            this._button.menu.close();
            const app = Shell.AppSystem.get_default().lookup_app('gnome-system-monitor.desktop');
            if (app)
                app.activate();
        });
        footer.add_child(monitor);
        root.add_child(footer);

        // Just left of the USB panel, or of the system menu without it.
        const rightBox = Main.panel._rightBox;
        const neighbour = Main.panel.statusArea['adaptive-usb'] || Main.panel.statusArea.aggregateMenu;
        const index = neighbour ? Math.max(0, rightBox.get_children().indexOf(neighbour.container)) : 0;
        Main.panel.addToStatusArea('adaptive-tasks', this._button, index, 'right');

        this._openStateId = this._button.menu.connect('open-state-changed', (_m, open) => {
            if (open)
                this._start();
            else
                this._stop();
        });
        this._scroll.connect('notify::hover', () => {
            if (!this._scroll.hover && this._stale)
                this._render();
        });
        this._sessionId = Main.sessionMode.connect('updated', () => this._syncSession());
        this._syncSession();
        log('[Adaptive Tasks] panel indicator installed');
    }

    detach() {
        this._stop();
        for (const pending of this._ending.values()) {
            if (pending.timer)
                GLib.Source.remove(pending.timer);
        }
        this._ending.clear();
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

    _start() {
        this._lastTicks.clear();
        this._structure = '';
        this._sample();
        // A second sample shortly after gives CPU figures right away instead
        // of a row of zeros for the first two seconds.
        this._timerId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 400, () => {
            this._sample();
            this._timerId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, REFRESH_MS, () => {
                this._sample();
                return GLib.SOURCE_CONTINUE;
            });
            return GLib.SOURCE_REMOVE;
        });
    }

    _stop() {
        if (this._timerId) {
            GLib.Source.remove(this._timerId);
            this._timerId = 0;
        }
    }

    _sample() {
        const now = GLib.get_monotonic_time() / 1e6;
        const procs = readProcesses(this._uid);
        const elapsed = this._lastTime ? now - this._lastTime : 0;
        const cpus = GLib.get_num_processors();

        // Share of the whole machine, as Windows' Task Manager shows it.
        this._cpu.clear();
        for (const [pid, p] of procs) {
            const before = this._lastTicks.get(pid);
            const percent = before !== undefined && elapsed > 0
                ? Math.max(0, (p.ticks - before) / CLOCK_TICKS / elapsed / cpus * 100) : 0;
            this._cpu.set(pid, percent);
        }
        this._lastTicks = new Map([...procs].map(([pid, p]) => [pid, p.ticks]));
        this._lastTime = now;
        this._procs = procs;

        this._readSystem();
        this._buildModel();
        this._render();
    }

    _readSystem() {
        const stat = readText('/proc/stat');
        if (stat) {
            const values = stat.split('\n')[0].trim().split(/\s+/).slice(1).map(Number);
            const idle = values[3] + (values[4] || 0);
            const total = values.reduce((a, b) => a + b, 0);
            const dTotal = total - this._totalCpu.total;
            const dBusy = (total - idle) - this._totalCpu.busy;
            if (this._totalCpu.total && dTotal > 0)
                this._totalCpu.percent = dBusy / dTotal * 100;
            this._totalCpu.total = total;
            this._totalCpu.busy = total - idle;
        }
        const meminfo = readText('/proc/meminfo') || '';
        const kb = key => Number((meminfo.match(new RegExp(`^${key}:\\s+(\\d+)`, 'm')) || [])[1] || 0) * 1024;
        this._memory = { total: kb('MemTotal'), used: kb('MemTotal') - kb('MemAvailable') };
    }

    _buildModel() {
        const procs = this._procs;
        const children = new Map();
        for (const p of procs.values()) {
            if (!children.has(p.ppid))
                children.set(p.ppid, []);
            children.get(p.ppid).push(p.pid);
        }
        const tree = rootPids => {
            const seen = new Set();
            const stack = [...rootPids];
            while (stack.length) {
                const pid = stack.pop();
                if (seen.has(pid) || !procs.has(pid))
                    continue;
                seen.add(pid);
                stack.push(...(children.get(pid) || []));
            }
            return seen;
        };

        // Apps: the shell's running list, costs summed over each process tree.
        const owned = new Set();
        const apps = [];
        for (const app of Shell.AppSystem.get_default().get_running()) {
            const pids = tree(app.get_pids().filter(pid => pid !== this._selfPid));
            pids.forEach(pid => owned.add(pid));
            let cpu = 0;
            let rss = 0;
            for (const pid of pids) {
                cpu += this._cpu.get(pid) || 0;
                rss += procs.get(pid).rss;
            }
            apps.push({
                key: `app:${app.get_id()}`,
                app,
                pids: [...pids],
                name: app.get_name(),
                windows: app.get_windows().length,
                cpu,
                rss,
            });
        }
        apps.sort((a, b) => a.name.localeCompare(b.name));

        // Processes: everything else of yours, busiest first.
        const others = [];
        for (const p of procs.values()) {
            if (owned.has(p.pid) || p.pid === this._selfPid || PROTECTED.has(p.comm) ||
                p.comm.startsWith('gsd-') || p.state === 'Z')
                continue;
            others.push({
                key: `pid:${p.pid}`,
                pids: [p.pid],
                pid: p.pid,
                comm: p.comm,
                cpu: this._cpu.get(p.pid) || 0,
                rss: p.rss,
            });
        }
        const metric = this._sortBy === 'cpu'
            ? (a, b) => b.cpu - a.cpu || b.rss - a.rss
            : (a, b) => b.rss - a.rss || b.cpu - a.cpu;
        others.sort(metric);
        this._apps = apps;
        this._others = others.slice(0, PROCESS_ROWS);

        // Drop pending ends whose processes are all gone.
        for (const [key, pending] of this._ending) {
            if (pending.pids.every(pid => !procs.has(pid))) {
                if (pending.timer)
                    GLib.Source.remove(pending.timer);
                this._ending.delete(key);
            }
        }
    }

    // ------------------------------------------------------------- render

    _render() {
        const memory = this._memory || { used: 0, total: 0 };
        this._summary.text = `CPU ${Math.round(this._totalCpu.percent)}% · ` +
            `${formatBytes(memory.used)} of ${formatBytes(memory.total)}`;

        const structure = [...this._apps, ...this._others].map(e => e.key).join('|') + `|${this._sortBy}`;
        if (structure === this._structure) {
            this._updateRows();
            return;
        }
        // Rows would come and go; wait until the pointer is not over the list.
        if (this._scroll.hover && this._list.get_n_children() > 0) {
            this._stale = true;
            this._updateRows();
            return;
        }
        this._stale = false;
        this._structure = structure;
        this._rebuild();
    }

    _rebuild() {
        this._list.destroy_all_children();
        this._rows.clear();

        this._list.add_child(CC.makeHeading(`Apps · ${this._apps.length}`));
        if (!this._apps.length) {
            this._list.add_child(CC.makeRow({
                icon: 'view-app-grid-symbolic',
                title: 'No apps running',
            }));
        }
        for (const entry of this._apps)
            this._addRow(entry, entry.app.get_icon(), entry.name);

        const heading = new St.BoxLayout({ style_class: 'adaptive-tasks-heading', x_expand: true });
        heading.add_child(new St.Label({
            text: 'Processes',
            style_class: 'adaptive-cc-list-heading',
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        }));
        for (const [key, label] of [['cpu', 'CPU'], ['memory', 'Memory']]) {
            const chip = new St.Button({
                style_class: 'adaptive-tasks-sort',
                label,
                can_focus: true,
                y_align: Clutter.ActorAlign.CENTER,
            });
            if (this._sortBy === key)
                chip.add_style_pseudo_class('checked');
            chip.connect('clicked', () => {
                this._sortBy = key;
                this._buildModel();
                this._structure = '';
                this._rebuild();
            });
            heading.add_child(chip);
        }
        this._list.add_child(heading);

        for (const entry of this._others)
            this._addRow(entry, 'application-x-executable-symbolic', commandName(entry.pid, entry.comm));

        const [, natural] = this._list.get_preferred_height(-1);
        this._scroll.set_height(Math.min(natural, LIST_MAX_HEIGHT));
    }

    _addRow(entry, icon, title) {
        const button = new St.Button({
            style_class: 'adaptive-cc-row adaptive-tasks-row',
            reactive: true,
            x_expand: true,
        });
        const box = new St.BoxLayout({ style_class: 'adaptive-cc-row-box', x_expand: true });
        button.set_child(box);

        box.add_child(new St.Icon({
            ...(typeof icon === 'string' ? { icon_name: icon } : { gicon: icon }),
            style_class: 'adaptive-cc-row-icon adaptive-tasks-icon',
            y_align: Clutter.ActorAlign.CENTER,
        }));

        const text = new St.BoxLayout({ vertical: true, x_expand: true, y_align: Clutter.ActorAlign.CENTER });
        const titleLabel = new St.Label({ text: title, style_class: 'adaptive-cc-row-title' });
        titleLabel.clutter_text.ellipsize = imports.gi.Pango.EllipsizeMode.END;
        text.add_child(titleLabel);
        const subtitle = new St.Label({ style_class: 'adaptive-cc-row-subtitle adaptive-tasks-meta' });
        text.add_child(subtitle);
        box.add_child(text);

        const cpu = new St.Label({ style_class: 'adaptive-tasks-cpu', y_align: Clutter.ActorAlign.CENTER });
        box.add_child(cpu);

        const end = new St.Button({
            style_class: 'adaptive-cc-pill-button adaptive-cc-pill-quiet adaptive-tasks-end',
            label: 'End',
            can_focus: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        end.connect('clicked', () => this._end(entry.key));
        box.add_child(end);

        // Clicking an app's row brings it forward, as the dock would.
        if (entry.app) {
            button.connect('clicked', () => {
                this._button.menu.close();
                entry.app.activate();
            });
        }

        this._list.add_child(button);
        this._rows.set(entry.key, { subtitle, cpu, end });
        this._fill(entry);
    }

    _updateRows() {
        const live = new Set();
        for (const entry of [...this._apps, ...this._others]) {
            live.add(entry.key);
            this._fill(entry);
        }
        // Rows kept only because the pointer is over the list: say they are
        // gone rather than showing their last figures.
        for (const [key, row] of this._rows) {
            if (live.has(key))
                continue;
            row.subtitle.text = 'Ended';
            row.cpu.text = '';
            row.end.visible = false;
            row.subtitle.get_parent().get_parent().opacity = 110;
        }
    }

    _fill(entry) {
        const row = this._rows.get(entry.key);
        if (!row)
            return;
        const pending = this._ending.get(entry.key);
        const parts = [];
        if (entry.app) {
            parts.push(entry.windows === 1 ? '1 window' : `${entry.windows} windows`);
            if (entry.pids.length > 1)
                parts.push(`${entry.pids.length} processes`);
        } else {
            parts.push(`PID ${entry.pid}`);
        }
        parts.push(formatBytes(entry.rss));
        row.subtitle.text = pending ? pending.status : parts.join(' · ');
        row.cpu.text = formatCpu(entry.cpu);
        row.cpu.style_class = entry.cpu >= 50 ? 'adaptive-tasks-cpu adaptive-tasks-hot'
            : entry.cpu >= 15 ? 'adaptive-tasks-cpu adaptive-tasks-warm' : 'adaptive-tasks-cpu';
        row.end.reactive = !pending;
        row.end.label = pending ? '…' : 'End';
    }

    // ---------------------------------------------------------------- end

    _end(key) {
        const entry = [...this._apps, ...this._others].find(e => e.key === key);
        if (!entry || this._ending.has(key) || !entry.pids.length)
            return;

        const pids = entry.pids.filter(pid => pid !== this._selfPid);
        const pending = { pids, status: 'Ending…', timer: 0 };
        this._ending.set(key, pending);
        this._fill(entry);

        this._signal('TERM', pids, ok => {
            if (!ok)
                pending.status = 'Couldn’t end - it may belong to another user';
        });

        // Anything that ignored the polite request is stopped outright.
        pending.timer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, TERM_GRACE_MS, () => {
            pending.timer = 0;
            const alive = pids.filter(pid => GLib.file_test(`/proc/${pid}`, GLib.FileTest.EXISTS));
            if (alive.length) {
                pending.status = 'Not responding - forcing…';
                this._signal('KILL', alive, () => {});
            }
            return GLib.SOURCE_REMOVE;
        });
    }

    _signal(name, pids, done) {
        try {
            const proc = Gio.Subprocess.new(['kill', `-${name}`, ...pids.map(String)],
                Gio.SubprocessFlags.STDERR_SILENCE);
            proc.wait_check_async(null, (p, result) => {
                let ok = true;
                try {
                    p.wait_check_finish(result);
                } catch (e) {
                    ok = false;
                }
                done(ok);
            });
        } catch (e) {
            logError(e, '[Adaptive Tasks] kill');
            done(false);
        }
    }
};
