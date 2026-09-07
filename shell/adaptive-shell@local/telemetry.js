// Adaptive Shade telemetry v1.7
//
// Reads CPU, GPU, memory, thermal, battery and network state straight out of
// procfs and sysfs. This runs inside the gnome-shell process, so the shape of
// the work matters more than the numbers:
//
//   - every device path is discovered once, at construction, and cached. Thermal
//     zone indices and DRM card numbers are not stable across boots, so nothing
//     may hardcode `thermal_zone10` or `card1`.
//   - a tick is a fixed, short list of small synchronous reads. procfs and sysfs
//     reads of this size are microseconds; an async round trip per file per
//     second would cost more than it saves.
//   - polling only runs while the shade is open. Closed shade, zero cost.
//
// Deliberately absent: package wattage (intel-rapl energy_uj is root-only and a
// setuid helper is not worth a number) and fan RPM (this machine exposes no
// tachometer).

/* exported Telemetry, THERMAL_OK, THERMAL_WARM, THERMAL_HOT, tempColor,
            formatBytes, formatRate, formatDuration */

const { GLib, Gio } = imports.gi;
const Main = imports.ui.main;

// Hoisted: a tick decodes about twenty-five small files and there is no reason
// to build a decoder for each one.
const DECODER = new TextDecoder();

// How often the process table is walked, in ticks. See _sample().
// A glanceable panel does not need per-second process rankings, and the walk is
// the single most expensive thing here after the slow sensors.
const PROCESS_INTERVAL_TICKS = 5;
// How often sensors that are expensive to read are re-read, in ticks.
const SLOW_ZONE_INTERVAL_TICKS = 10;
// A sensor slower than this is treated as expensive. Most sysfs temperatures
// are a few microseconds; the ones that are not are doing real I/O.
const SLOW_ZONE_MS = 2;
// How many processes the shade shows per ranking.
const PROCESS_ROWS = 5;
// Kernel clock ticks per second. _SC_CLK_TCK is 100 on every Linux/glibc
// platform this ships to; there is no way to query it from GJS.
const USER_HZ = 100;
// /proc/[pid]/stat reports RSS in pages. 4 KiB on x86_64, and likewise not
// queryable from GJS - sysconf is not bound anywhere reachable here.
const PAGE_SIZE = 4096;

// Thermal bands, from tokens/adaptive.tokens.json state.* colors.
var THERMAL_OK = '#65D9B5';
var THERMAL_WARM = '#F3C96B';
var THERMAL_HOT = '#FF7A90';

var tempColor = function (celsius) {
    if (!Number.isFinite(celsius))
        return THERMAL_OK;
    if (celsius >= 80)
        return THERMAL_HOT;
    if (celsius >= 60)
        return THERMAL_WARM;
    return THERMAL_OK;
};

var formatBytes = function (bytes) {
    if (!Number.isFinite(bytes) || bytes < 0)
        return '--';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let value = bytes;
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) {
        value /= 1024;
        unit += 1;
    }
    const digits = value >= 100 || unit === 0 ? 0 : 1;
    return `${value.toFixed(digits)} ${units[unit]}`;
};

var formatRate = function (bytesPerSecond) {
    if (!Number.isFinite(bytesPerSecond))
        return '--';
    return `${formatBytes(bytesPerSecond)}/s`;
};

// "3d 4h", "4h 12m", "12m" - the largest two units that carry information.
var formatDuration = function (seconds) {
    if (!Number.isFinite(seconds) || seconds < 0)
        return '--';

    const days = Math.floor(seconds / 86400);
    const hours = Math.floor(seconds % 86400 / 3600);
    const minutes = Math.floor(seconds % 3600 / 60);

    if (days > 0)
        return `${days}d ${hours}h`;
    if (hours > 0)
        return `${hours}h ${minutes}m`;
    return `${minutes}m`;
};

// Small synchronous read that never throws. Missing sysfs attributes are
// normal: hardware differs, permissions differ, and a driver can drop an
// attribute across a kernel upgrade.
function readText(path) {
    try {
        const [ok, contents] = GLib.file_get_contents(path);
        if (!ok || !contents)
            return null;
        return DECODER.decode(contents);
    } catch (e) {
        return null;
    }
}

function readNumber(path) {
    const text = readText(path);
    if (text === null)
        return NaN;
    const value = Number.parseFloat(text.trim());
    return Number.isFinite(value) ? value : NaN;
}

// Cheap directory listing. Used only during discovery, never per tick.
function listDir(path) {
    const names = [];
    try {
        const dir = Gio.File.new_for_path(path);
        const iter = dir.enumerate_children(
            'standard::name',
            Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS,
            null
        );
        let info;
        while ((info = iter.next_file(null)) !== null)
            names.push(info.get_name());
        iter.close(null);
    } catch (e) {
        // Directory absent on this machine. Callers handle an empty list.
    }
    names.sort();
    return names;
}

var Telemetry = class Telemetry {
    constructor() {
        this._timerId = 0;
        this._listeners = [];
        this._cancellable = new Gio.Cancellable();

        // Deltas need a previous sample. Everything below is "no reading yet".
        this._prevCpu = null;
        this._prevCores = null;
        this._prevGpu = null;
        this._prevNet = null;
        this._prevDiskIO = null;
        this._prevProcs = null;
        this._tick = 0;
        this._nextProcessTick = 1;
        this._nextSlowZoneTick = 1;

        this._discover();

        // Filesystem usage moves on the scale of minutes, not seconds. It is
        // refreshed when the shade opens, not on every tick.
        this._disks = [];

        this.snapshot = {
            cpu: { percent: NaN, cores: [], freqMhz: NaN, tempC: NaN },
            gpu: {
                percent: NaN, freqMhz: NaN, requestedMhz: NaN,
                maxFreqMhz: NaN, available: false,
            },
            memory: {
                usedBytes: NaN, totalBytes: NaN, percent: NaN,
                swapUsedBytes: NaN, swapTotalBytes: NaN,
            },
            thermal: [],
            battery: { percent: NaN, state: '', timeRemaining: 0, present: false },
            network: { rxRate: NaN, txRate: NaN, interfaces: [] },
            disks: [],
            diskIO: { readRate: NaN, writeRate: NaN },
            load: { avg1: NaN, avg5: NaN, avg15: NaN, running: NaN, total: NaN },
            uptimeSeconds: NaN,
            processes: { byCpu: [], byMemory: [], count: NaN },
        };
    }

    // ------------------------------------------------------------ discovery

    _discover() {
        this._discoverCpu();
        this._discoverThermal();
        this._timeZones();
        this._discoverGpu();
    }

    _discoverCpu() {
        // One scaling_cur_freq per policy, not per logical CPU: on intel_pstate
        // hybrid parts the policies already cover every core, and reading the
        // policy directory is a third of the files.
        this._cpuFreqPaths = listDir('/sys/devices/system/cpu/cpufreq')
            .filter(name => name.startsWith('policy'))
            .map(name => `/sys/devices/system/cpu/cpufreq/${name}/scaling_cur_freq`)
            .filter(path => GLib.file_test(path, GLib.FileTest.EXISTS));

        if (this._cpuFreqPaths.length === 0) {
            // Older or non-Intel setups keep the attribute under the CPU itself.
            this._cpuFreqPaths = listDir('/sys/devices/system/cpu')
                .filter(name => /^cpu\d+$/.test(name))
                .map(name => `/sys/devices/system/cpu/${name}/cpufreq/scaling_cur_freq`)
                .filter(path => GLib.file_test(path, GLib.FileTest.EXISTS));
        }
    }

    _discoverThermal() {
        // Zone numbering is assigned in probe order, so the package sensor is
        // not reliably zone 10 (or any fixed index). Resolve by `type`.
        this._zones = [];
        this._cpuTempPath = null;

        for (const name of listDir('/sys/class/thermal')) {
            if (!name.startsWith('thermal_zone'))
                continue;

            const base = `/sys/class/thermal/${name}`;
            const type = (readText(`${base}/type`) || '').trim();
            if (!type)
                continue;

            const path = `${base}/temp`;
            if (Number.isNaN(readNumber(path)))
                continue;

            // INT3400 is the ACPI thermal policy device rather than a sensor.
            // It reports a constant 20C and would sit in the grid as noise.
            if (type === 'INT3400 Thermal' || type.startsWith('INT3400'))
                continue;

            this._zones.push({ label: this._zoneLabel(type), type, path });

            if (type === 'x86_pkg_temp')
                this._cpuTempPath = path;
        }

        // hwmon carries the storage and per-core sensors that thermal zones miss.
        for (const name of listDir('/sys/class/hwmon')) {
            const base = `/sys/class/hwmon/${name}`;
            const hwName = (readText(`${base}/name`) || '').trim();

            if (hwName === 'nvme') {
                const path = `${base}/temp1_input`;
                if (!Number.isNaN(readNumber(path)))
                    this._zones.push({ label: 'Storage', type: hwName, path });
            }

            // Fall back to coretemp only when the package zone is missing,
            // otherwise the same reading would appear twice.
            if (hwName === 'coretemp' && !this._cpuTempPath) {
                const path = `${base}/temp1_input`;
                if (!Number.isNaN(readNumber(path)))
                    this._cpuTempPath = path;
            }
        }
    }

    // Reading a temperature is usually a few microseconds of sysfs. Some are
    // not: an NVMe hwmon temperature issues a SMART admin command to the drive
    // and costs ~27 ms on this machine, and ACPI zones can evaluate a _TMP
    // method. Blocking the compositor's main loop for that every second is a
    // visible stutter, so time each sensor once and read the slow ones rarely.
    //
    // Measured rather than hardcoded by name: which sensors are slow is a
    // property of the hardware and its driver, not of this code.
    _timeZones() {
        for (const zone of this._zones) {
            const started = GLib.get_monotonic_time();
            readNumber(zone.path);
            const elapsed = (GLib.get_monotonic_time() - started) / 1000;

            zone.slow = elapsed > SLOW_ZONE_MS;
            zone.celsius = NaN;

            if (zone.slow) {
                log(`[Adaptive Shade] slow sensor ${zone.label} ` +
                    `(${elapsed.toFixed(1)} ms); sampling every ` +
                    `${SLOW_ZONE_INTERVAL_TICKS}s`);
            }
        }
    }

    _zoneLabel(type) {
        // ACPI sensor names are opaque four-character IDs. Translate the ones
        // that have a meaning and let the rest through unchanged.
        const known = {
            x86_pkg_temp: 'CPU package',
            TCPU: 'CPU die',
            TCPU_PCI: 'CPU bus',
            acpitz: 'Mainboard',
            iwlwifi_1: 'Wi-Fi',
        };
        if (known[type])
            return known[type];
        if (/^SEN\d+$/.test(type))
            return `Sensor ${type.slice(3)}`;
        return type;
    }

    _discoverGpu() {
        // Intel exposes GT frequency per DRM card; the card number depends on
        // probe order, so find the card that actually has the attribute.
        this._gpu = null;

        for (const name of listDir('/sys/class/drm')) {
            if (!/^card\d+$/.test(name))
                continue;

            const base = `/sys/class/drm/${name}`;
            const actPath = `${base}/gt_act_freq_mhz`;
            if (Number.isNaN(readNumber(actPath)))
                continue;

            const rc6Path = `${base}/power/rc6_residency_ms`;
            this._gpu = {
                actPath,
                curPath: `${base}/gt_cur_freq_mhz`,
                maxPath: `${base}/gt_max_freq_mhz`,
                rc6Path: Number.isNaN(readNumber(rc6Path)) ? null : rc6Path,
            };
            break;
        }
    }

    // -------------------------------------------------------------- polling

    connect(callback) {
        this._listeners.push(callback);
    }

    start() {
        if (this._timerId)
            return;

        // A tick is a delta against the previous sample, so the first one after
        // opening would read as a spike measured from whenever the shade last
        // closed. Reset the baselines and take a throwaway sample instead.
        this._prevCpu = null;
        this._prevCores = null;
        this._prevGpu = null;
        this._prevNet = null;
        this._prevDiskIO = null;
        this._prevProcs = null;
        this._tick = 0;
        this._nextProcessTick = 1;
        this._nextSlowZoneTick = 2;

        this._refreshDisks();
        this._sample();

        this._timerId = GLib.timeout_add_seconds(
            GLib.PRIORITY_DEFAULT,
            1,
            () => {
                this._sample();
                this._emit();
                return GLib.SOURCE_CONTINUE;
            }
        );
    }

    stop() {
        if (this._timerId) {
            GLib.Source.remove(this._timerId);
            this._timerId = 0;
        }
    }

    destroy() {
        this.stop();
        // Any slow-sensor read still in flight must not call back into a
        // telemetry object the shade has already let go of.
        if (this._cancellable) {
            this._cancellable.cancel();
            this._cancellable = null;
        }
        for (const zone of this._zones)
            zone.pending = false;
        this._listeners = [];
    }

    _emit() {
        for (const callback of this._listeners) {
            try {
                callback(this.snapshot);
            } catch (e) {
                logError(e, '[Adaptive Shade] telemetry listener');
            }
        }
    }

    _sample() {
        this._tick += 1;

        this._sampleCpu();
        this._sampleGpu();
        this._sampleMemory();
        this._sampleBattery();
        this._sampleNetwork();
        this._sampleDiskIO();
        this._sampleLoad();

        // Two samplers here cost real milliseconds: walking /proc, and the
        // sensors that do device I/O. Each is cheap enough amortised, but both
        // in one tick is ~38 ms - two dropped frames, felt as a stutter. So at
        // most one expensive read happens per tick; the other waits its turn.
        let spent = false;

        if (this._tick >= this._nextProcessTick) {
            this._sampleProcesses();
            this._nextProcessTick = this._tick + PROCESS_INTERVAL_TICKS;
            spent = true;
        }

        this._sampleThermal(spent);
    }

    // ------------------------------------------------------------------ cpu

    _sampleCpu() {
        const stat = readText('/proc/stat');
        if (stat !== null) {
            const lines = stat.split('\n');
            const cores = [];
            let total = null;

            for (const line of lines) {
                if (!line.startsWith('cpu'))
                    break;

                const fields = line.split(/\s+/);
                const name = fields[0];
                const values = fields.slice(1).map(Number);
                if (values.length < 5 || values.some(Number.isNaN))
                    continue;

                // idle + iowait. Everything else counts as busy.
                const idle = values[3] + values[4];
                const sum = values.reduce((a, b) => a + b, 0);

                if (name === 'cpu')
                    total = { idle, sum };
                else
                    cores.push({ idle, sum });
            }

            if (total) {
                this.snapshot.cpu.percent = this._busyPercent(this._prevCpu, total);
                this._prevCpu = total;
            }

            if (cores.length > 0) {
                if (this._prevCores && this._prevCores.length === cores.length) {
                    this.snapshot.cpu.cores = cores.map(
                        (core, i) => this._busyPercent(this._prevCores[i], core)
                    );
                } else {
                    this.snapshot.cpu.cores = cores.map(() => NaN);
                }
                this._prevCores = cores;
            }
        }

        let freqSum = 0;
        let freqCount = 0;
        for (const path of this._cpuFreqPaths) {
            const khz = readNumber(path);
            if (!Number.isNaN(khz)) {
                freqSum += khz;
                freqCount += 1;
            }
        }
        this.snapshot.cpu.freqMhz = freqCount > 0
            ? freqSum / freqCount / 1000
            : NaN;

        this.snapshot.cpu.tempC = this._cpuTempPath
            ? readNumber(this._cpuTempPath) / 1000
            : NaN;
    }

    _busyPercent(prev, current) {
        if (!prev)
            return NaN;

        const sumDelta = current.sum - prev.sum;
        const idleDelta = current.idle - prev.idle;

        // A counter that did not move (or wrapped) says nothing about load.
        if (sumDelta <= 0)
            return NaN;

        return Math.max(0, Math.min(100, (1 - idleDelta / sumDelta) * 100));
    }

    // ------------------------------------------------------------------ gpu

    _sampleGpu() {
        if (!this._gpu) {
            this.snapshot.gpu.available = false;
            return;
        }

        this.snapshot.gpu.available = true;
        // Actual clock, which is 0 whenever the engine is asleep, and the clock
        // the driver is asking for, which stays meaningful either way.
        this.snapshot.gpu.freqMhz = readNumber(this._gpu.actPath);
        this.snapshot.gpu.requestedMhz = readNumber(this._gpu.curPath);
        this.snapshot.gpu.maxFreqMhz = readNumber(this._gpu.maxPath);

        if (!this._gpu.rc6Path) {
            this.snapshot.gpu.percent = NaN;
            return;
        }

        // RC6 is the render engine's sleep state, so the time it did not spend
        // asleep is the time it was busy. This is what intel_gpu_top reports
        // without needing perf access.
        const rc6 = readNumber(this._gpu.rc6Path);
        const now = GLib.get_monotonic_time() / 1000;

        if (Number.isNaN(rc6)) {
            this.snapshot.gpu.percent = NaN;
            this._prevGpu = null;
            return;
        }

        if (this._prevGpu) {
            const wallDelta = now - this._prevGpu.now;
            const rc6Delta = rc6 - this._prevGpu.rc6;

            if (wallDelta > 0 && rc6Delta >= 0) {
                const busy = (wallDelta - rc6Delta) / wallDelta * 100;
                this.snapshot.gpu.percent = Math.max(0, Math.min(100, busy));
            } else {
                this.snapshot.gpu.percent = NaN;
            }
        }

        this._prevGpu = { rc6, now };
    }

    // --------------------------------------------------------------- memory

    _sampleMemory() {
        const text = readText('/proc/meminfo');
        if (text === null)
            return;

        const values = {};
        for (const line of text.split('\n')) {
            const match = line.match(/^(\w+):\s+(\d+)/);
            if (match)
                values[match[1]] = Number(match[2]) * 1024;
        }

        const total = values.MemTotal;
        // MemAvailable is the kernel's own estimate of what a new allocation
        // could actually get, which is a truer "free" than MemFree.
        const available = values.MemAvailable !== undefined
            ? values.MemAvailable
            : values.MemFree;

        if (Number.isFinite(total) && Number.isFinite(available)) {
            this.snapshot.memory.totalBytes = total;
            this.snapshot.memory.usedBytes = total - available;
            this.snapshot.memory.percent = (total - available) / total * 100;
        }

        const swapTotal = values.SwapTotal;
        const swapFree = values.SwapFree;
        if (Number.isFinite(swapTotal) && Number.isFinite(swapFree)) {
            this.snapshot.memory.swapTotalBytes = swapTotal;
            this.snapshot.memory.swapUsedBytes = swapTotal - swapFree;
        }
    }

    // -------------------------------------------------------------- thermal

    // `deferSlow` is set when this tick has already spent its budget elsewhere.
    _sampleThermal(deferSlow = false) {
        for (const zone of this._zones) {
            // Slow sensors are read off the main loop; see _readSlowZones.
            if (zone.slow)
                continue;
            zone.celsius = readNumber(zone.path) / 1000;
        }

        if (!deferSlow && this._tick >= this._nextSlowZoneTick) {
            this._nextSlowZoneTick = this._tick + SLOW_ZONE_INTERVAL_TICKS;
            this._readSlowZones();
        }

        this.snapshot.thermal = this._zones
            .filter(zone => Number.isFinite(zone.celsius) && zone.celsius > 0)
            .map(zone => ({ label: zone.label, celsius: zone.celsius }));
    }

    // An NVMe hwmon temperature is a SMART admin command to the drive - ~27 ms
    // of real device I/O, which is nearly two dropped frames if it happens on
    // the compositor's main loop. Reading it asynchronously moves the wait off
    // that loop entirely; the value lands in the snapshot a moment later, which
    // is irrelevant for a number that is only re-read every ten seconds anyway.
    _readSlowZones() {
        for (const zone of this._zones) {
            if (!zone.slow || zone.pending)
                continue;

            zone.pending = true;
            try {
                Gio.File.new_for_path(zone.path).load_contents_async(
                    this._cancellable,
                    (file, result) => {
                        zone.pending = false;
                        try {
                            const [ok, contents] = file.load_contents_finish(result);
                            if (ok) {
                                const value = Number.parseFloat(
                                    DECODER.decode(contents).trim());
                                if (Number.isFinite(value))
                                    zone.celsius = value / 1000;
                            }
                        } catch (e) {
                            // Cancelled on teardown, or the sensor went away.
                        }
                    });
            } catch (e) {
                zone.pending = false;
            }
        }
    }

    // -------------------------------------------------------------- battery

    _sampleBattery() {
        // GNOME already keeps a UPower proxy alive for the panel indicator.
        // Reusing it means one less thing polling the battery.
        const power = Main.panel.statusArea.aggregateMenu
            ? Main.panel.statusArea.aggregateMenu._power
            : null;
        const proxy = power ? power._proxy : null;

        if (proxy && proxy.IsPresent) {
            this.snapshot.battery.present = true;
            this.snapshot.battery.percent = proxy.Percentage;
            this.snapshot.battery.state = this._batteryStateName(proxy.State);
            this.snapshot.battery.timeRemaining = proxy.State === 1
                ? proxy.TimeToFull
                : proxy.TimeToEmpty;
            return;
        }

        // No UPower proxy (or no battery on it): fall back to sysfs so a laptop
        // still reports something if the indicator is not up yet.
        const capacity = readNumber('/sys/class/power_supply/BAT0/capacity');
        if (Number.isNaN(capacity)) {
            this.snapshot.battery.present = false;
            return;
        }

        this.snapshot.battery.present = true;
        this.snapshot.battery.percent = capacity;
        this.snapshot.battery.state =
            (readText('/sys/class/power_supply/BAT0/status') || '').trim();
        this.snapshot.battery.timeRemaining = 0;
    }

    _batteryStateName(state) {
        // org.freedesktop.UPower.Device state enumeration.
        const names = {
            1: 'Charging',
            2: 'Discharging',
            3: 'Empty',
            4: 'Full',
            5: 'Charging',
            6: 'Discharging',
        };
        return names[state] || 'Unknown';
    }

    // -------------------------------------------------------------- network

    _sampleNetwork() {
        const text = readText('/proc/net/dev');
        if (text === null)
            return;

        let rx = 0;
        let tx = 0;
        const perInterface = [];

        for (const line of text.split('\n')) {
            const match = line.match(/^\s*([\w.-]+):\s*(.*)$/);
            if (!match)
                continue;

            const iface = match[1];
            // Loopback traffic is not network activity, and the virtual bridges
            // docker/libvirt create would double-count anything routed through them.
            if (iface === 'lo' || /^(docker|virbr|br-|veth)/.test(iface))
                continue;

            const fields = match[2].trim().split(/\s+/).map(Number);
            if (fields.length < 9)
                continue;

            rx += fields[0];
            tx += fields[8];
            perInterface.push({ name: iface, rx: fields[0], tx: fields[8] });
        }

        const now = GLib.get_monotonic_time() / 1000000;

        if (this._prevNet) {
            const seconds = now - this._prevNet.now;
            if (seconds > 0) {
                this.snapshot.network.rxRate =
                    Math.max(0, (rx - this._prevNet.rx) / seconds);
                this.snapshot.network.txRate =
                    Math.max(0, (tx - this._prevNet.tx) / seconds);

                const previous = this._prevNet.perInterface || [];
                this.snapshot.network.interfaces = perInterface.map(iface => {
                    const before = previous.find(p => p.name === iface.name);
                    if (!before)
                        return { name: iface.name, rxRate: NaN, txRate: NaN };
                    return {
                        name: iface.name,
                        rxRate: Math.max(0, (iface.rx - before.rx) / seconds),
                        txRate: Math.max(0, (iface.tx - before.tx) / seconds),
                    };
                // An interface that has never carried a byte is noise in a list
                // this short; drop it until it does something.
                }).filter(iface => iface.rxRate > 0 || iface.txRate > 0 ||
                    perInterface.find(p => p.name === iface.name).rx > 0);
            }
        }

        this._prevNet = { rx, tx, now, perInterface };
    }

    // ------------------------------------------------------------- disk I/O

    _sampleDiskIO() {
        const text = readText('/proc/diskstats');
        if (text === null)
            return;

        let readSectors = 0;
        let writeSectors = 0;

        for (const line of text.split('\n')) {
            const fields = line.trim().split(/\s+/);
            if (fields.length < 10)
                continue;

            const name = fields[2];
            // Whole devices only. Counting nvme0n1 and its partitions together
            // would report every byte two or three times over.
            if (!/^(nvme\d+n\d+|sd[a-z]|mmcblk\d+|vd[a-z])$/.test(name))
                continue;

            readSectors += Number(fields[5]);
            writeSectors += Number(fields[9]);
        }

        const now = GLib.get_monotonic_time() / 1000000;

        if (this._prevDiskIO) {
            const seconds = now - this._prevDiskIO.now;
            if (seconds > 0) {
                // Kernel diskstats are always in 512-byte sectors regardless of
                // the device's own logical block size.
                const perSector = 512;
                this.snapshot.diskIO.readRate = Math.max(0,
                    (readSectors - this._prevDiskIO.read) * perSector / seconds);
                this.snapshot.diskIO.writeRate = Math.max(0,
                    (writeSectors - this._prevDiskIO.write) * perSector / seconds);
            }
        }

        this._prevDiskIO = { read: readSectors, write: writeSectors, now };
    }

    // -------------------------------------------------------- load / uptime

    _sampleLoad() {
        const load = readText('/proc/loadavg');
        if (load !== null) {
            // "0.42 0.51 0.58 2/2859 326666"
            const fields = load.trim().split(/\s+/);
            this.snapshot.load.avg1 = Number.parseFloat(fields[0]);
            this.snapshot.load.avg5 = Number.parseFloat(fields[1]);
            this.snapshot.load.avg15 = Number.parseFloat(fields[2]);

            const procs = (fields[3] || '').split('/');
            this.snapshot.load.running = Number.parseInt(procs[0], 10);
            this.snapshot.load.total = Number.parseInt(procs[1], 10);
        }

        const uptime = readText('/proc/uptime');
        if (uptime !== null)
            this.snapshot.uptimeSeconds = Number.parseFloat(uptime.trim().split(/\s+/)[0]);
    }

    // ------------------------------------------------------------ processes

    _sampleProcesses() {
        const names = listDir('/proc');
        const current = new Map();
        let count = 0;

        for (const name of names) {
            // Numeric entries are the processes; everything else in /proc is
            // kernel state that would just cost a failed open.
            if (!/^\d+$/.test(name))
                continue;

            count += 1;

            const stat = readText(`/proc/${name}/stat`);
            if (stat === null)
                continue;

            // The command sits in parentheses and may itself contain spaces or
            // parentheses, so split on the LAST ')' rather than tokenising.
            const close = stat.lastIndexOf(')');
            const open = stat.indexOf('(');
            if (open < 0 || close < 0 || close < open)
                continue;

            const command = stat.slice(open + 1, close);
            const rest = stat.slice(close + 2).split(' ');

            // Fields after comm and state: utime is 11, stime is 12, rss is 21
            // (0-indexed into `rest`, which begins at field 3 of the record).
            const utime = Number(rest[11]);
            const stime = Number(rest[12]);
            const rssPages = Number(rest[21]);
            if (!Number.isFinite(utime) || !Number.isFinite(stime))
                continue;

            current.set(name, {
                command,
                jiffies: utime + stime,
                rssBytes: Number.isFinite(rssPages) ? rssPages * PAGE_SIZE : NaN,
            });
        }

        const now = GLib.get_monotonic_time() / 1000000;
        this.snapshot.processes.count = count;

        if (this._prevProcs) {
            const seconds = now - this._prevProcs.now;
            const rows = new Map();

            if (seconds > 0) {
                for (const [pid, proc] of current) {
                    const before = this._prevProcs.map.get(pid);
                    // A process that started since the last scan has no baseline
                    // to subtract, so it waits one round rather than reporting
                    // its whole lifetime's CPU as if it were spent just now.
                    if (!before)
                        continue;

                    const delta = proc.jiffies - before.jiffies;
                    if (delta < 0)
                        continue;

                    // Aggregate by command name. A browser is twenty processes
                    // called "chrome"; five rows that all say chrome tell you
                    // far less than one row that says what chrome costs.
                    const row = rows.get(proc.command) || {
                        command: proc.command,
                        percent: 0,
                        rssBytes: 0,
                        instances: 0,
                    };
                    row.percent += delta / USER_HZ / seconds * 100;
                    if (Number.isFinite(proc.rssBytes))
                        row.rssBytes += proc.rssBytes;
                    row.instances += 1;
                    rows.set(proc.command, row);
                }
            }

            const all = [...rows.values()];

            this.snapshot.processes.byCpu = all
                .slice()
                .sort((a, b) => b.percent - a.percent)
                .slice(0, PROCESS_ROWS);

            this.snapshot.processes.byMemory = all
                .slice()
                .sort((a, b) => b.rssBytes - a.rssBytes)
                .slice(0, PROCESS_ROWS);
        }

        this._prevProcs = { map: current, now };
    }

    // ----------------------------------------------------------------- disk

    _refreshDisks() {
        const mounts = [
            { label: 'Root', path: '/' },
            { label: 'Home', path: GLib.get_home_dir() },
        ];

        const seen = new Set();
        this._disks = [];

        for (const mount of mounts) {
            try {
                const info = Gio.File.new_for_path(mount.path)
                    .query_filesystem_info('filesystem::size,filesystem::used', null);

                const size = info.get_attribute_uint64('filesystem::size');
                const used = info.get_attribute_uint64('filesystem::used');
                if (!size)
                    continue;

                // / and $HOME are usually the same filesystem. Report it once.
                const key = `${size}:${used}`;
                if (seen.has(key))
                    continue;
                seen.add(key);

                this._disks.push({
                    label: mount.label,
                    usedBytes: used,
                    totalBytes: size,
                    percent: used / size * 100,
                });
            } catch (e) {
                // Unreadable mount point; skip it.
            }
        }

        this.snapshot.disks = this._disks;
    }
};
