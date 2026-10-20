#!/usr/bin/env bash
set -Eeuo pipefail

. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/adaptive-paths.sh"
REPO="$ADAPTIVE_REPO"
UUID="adaptive-shell@local"
PROBE="adaptive-probe@local"
SCREEN_DIR="$HOME/.local/share/adaptive-desktop/agent-office/company/projects/dynamic-island/build-screens"
mkdir -p "$SCREEN_DIR"

SANDBOX="$(mktemp -d /tmp/island-nested-XXXXXX)"
chmod 700 "$SANDBOX"
trap "rm -rf $SANDBOX 2>/dev/null || true" EXIT

export HOME="$SANDBOX"
export XDG_DATA_HOME="$SANDBOX/share"
export XDG_CONFIG_HOME="$SANDBOX/config"
export ADAPTIVE_NESTED_SANDBOX="$SANDBOX"
mkdir -p "$XDG_DATA_HOME/gnome-shell/extensions" "$XDG_CONFIG_HOME"

# Copy extension and probe
cp -r "$REPO/shell/adaptive-shell@local" "$XDG_DATA_HOME/gnome-shell/extensions/"
cp -r "$REPO/scripts/nested-probe/adaptive-probe@local" "$XDG_DATA_HOME/gnome-shell/extensions/"

xvfb-run -a --server-args="-screen 0 1920x1080x24" dbus-run-session bash << 'INNER_EOF'
set -Eeuo pipefail
SANDBOX="$HOME"
REPO="$ADAPTIVE_REPO"
UUID="adaptive-shell@local"
PROBE="adaptive-probe@local"
SCREEN_DIR="$HOME/.local/share/adaptive-desktop/agent-office/company/projects/dynamic-island/build-screens"
mkdir -p "$SCREEN_DIR"

gsettings set org.gnome.shell disable-user-extensions false
gsettings set org.gnome.shell disable-extension-version-validation true
gsettings set org.gnome.shell enabled-extensions "['$PROBE']"

MUTTER_DEBUG_DUMMY_MODE_SPECS=1920x1080 gnome-shell --nested --wayland >"$SANDBOX/shell.log" 2>&1 &
SHELL_PID=$!
trap "kill $SHELL_PID 2>/dev/null || true" EXIT

echo "Waiting for nested gnome-shell (PID $SHELL_PID) to start..."
for i in {1..40}; do
    if gdbus call --session -d org.gnome.Shell -o /org/gnome/Shell -m org.freedesktop.DBus.Peer.Ping >/dev/null 2>&1; then
        echo "Nested GNOME Shell ready."
        break
    fi
    sleep 0.5
done

# Enable probe first
gnome-extensions enable "$PROBE" >/dev/null 2>&1 || true
sleep 1

# Measure idle CPU BEFORE enabling adaptive-shell@local
echo "Measuring idle CPU before enabling extension (PID $SHELL_PID)..."
CPU_BEFORE="$(top -b -n 3 -d 1 -p $SHELL_PID | awk -v pid="$SHELL_PID" '$1 == pid { sum += $9; count++ } END { if (count > 0) printf "%.2f", sum/count; else print "0.00" }')"
echo "CPU_BEFORE: ${CPU_BEFORE}%"

# Enable adaptive-shell@local
echo "Enabling $UUID..."
gnome-extensions enable "$UUID" >/dev/null 2>&1 || true
sleep 4

# Measure idle CPU AFTER enabling adaptive-shell@local (settled idle state)
echo "Measuring idle CPU after enabling extension (PID $SHELL_PID)..."
CPU_AFTER="$(top -b -n 3 -d 1 -p $SHELL_PID | awk -v pid="$SHELL_PID" '$1 == pid { sum += $9; count++ } END { if (count > 0) printf "%.2f", sum/count; else print "0.00" }')"
echo "CPU_AFTER: ${CPU_AFTER}%"

echo "BEFORE=$CPU_BEFORE, AFTER=$CPU_AFTER" > "$SANDBOX/cpu_metrics.txt"

# Helper for evaluating JS inside the shell
probe() {
    gdbus call --session -d org.gnome.Shell -o /org/adaptive/Probe \
        -m org.adaptive.Probe.Eval "$1" 2>&1 |
        python3 -c 'import ast,sys; print(ast.literal_eval(sys.stdin.read().strip())[0])' 2>/dev/null
}

# Helper to take screenshot
take_shot() {
    local outfile="$1"
    sleep 0.5
    if command -v scrot >/dev/null 2>&1; then
        scrot -o "$outfile"
    elif command -v import >/dev/null 2>&1; then
        import -window root "$outfile"
    else
        gdbus call --session -d org.gnome.Shell.Screenshot -o /org/gnome/Shell/Screenshot \
            -m org.gnome.Shell.Screenshot.Screenshot true true "$outfile" >/dev/null 2>&1 || true
    fi
    echo "Saved: $outfile"
}

# Verify extension is enabled
EXT_STATE="$(probe "
if (!Main._dynamicIsland) {
    const ext = Main.extensionManager ? Main.extensionManager.lookup('$UUID') : null;
    if (ext && ext.state !== 1 && Main.extensionManager.enableExtension) {
        Main.extensionManager.enableExtension('$UUID');
    }
}
return (typeof adaptive !== 'undefined' && adaptive) || (Main && Main._dynamicIsland) ? true : false;
")"
echo "Adaptive extension lookup: $EXT_STATE"

# Check if dynamicIsland is attached
ISLAND_ACTIVE="$(probe "return (Main && Main._dynamicIsland) ? true : false")"
echo "Dynamic Island attached: $ISLAND_ACTIVE"

# 1. Screenshot: IDLE State
echo "Capturing 01_idle_state.png..."
probe "
const island = Main._dynamicIsland;
if (island && island._backend) {
    island._backend._surfacedEvent = null;
    island._backend._queue = [];
    if (island._backend._dwellTimerId) {
        GLib.source_remove(island._backend._dwellTimerId);
        island._backend._dwellTimerId = 0;
    }
}
island._anchor.syncClock('19:15');
island.contract({
    surfacedEvent: null,
    multiActivity: { primary: null, secondary: null },
    quota: {},
    tasks: [],
    media: {},
    timer: {}
});
return true;
"
take_shot "$SCREEN_DIR/01_idle_state.png"
cp "$SCREEN_DIR/01_idle_state.png" "$SCREEN_DIR/fix_idle.png"

# 2. Screenshot: COMPACT Quota
echo "Capturing 02_compact_quota.png..."
probe "
const island = Main._dynamicIsland;
island.contract({
    surfacedEvent: {
        type: 'QUOTA_CAUTION_BREACH',
        priority: 2,
        payload: { message: 'Codex 5h limit 82% used', source: 'codex', used: 82 }
    },
    multiActivity: { primary: null, secondary: null },
    quota: {
        codex: { ts: Date.now() / 1000, windows: [{ label: '5h', used: 78, resetsAt: Date.now() / 1000 + 9000 }, { label: 'Weekly', used: 28, resetsAt: Date.now() / 1000 + 400000 }] },
        claude: { ts: Date.now() / 1000, windows: [{ label: '5h', used: 17, resetsAt: Date.now() / 1000 + 12000 }, { label: 'Weekly', used: 31, resetsAt: Date.now() / 1000 + 300000 }] },
        gemini: { ts: Date.now() / 1000, windows: [{ label: '5h', used: 100, resetsAt: Date.now() / 1000 + 3000 }, { label: 'Weekly', used: 85, resetsAt: Date.now() / 1000 + 250000 }] },
        cautionBreach: true,
        criticalBreach: false
    },
    tasks: [],
    media: {},
    timer: {}
});
return true;
"
take_shot "$SCREEN_DIR/02_compact_quota.png"
cp "$SCREEN_DIR/02_compact_quota.png" "$SCREEN_DIR/fix_compact.png"

# 3. Screenshot: COMPACT Task
echo "Capturing 03_compact_task.png..."
probe "
const island = Main._dynamicIsland;
island.contract({
    surfacedEvent: {
        type: 'TASK_STARTED',
        priority: 3,
        payload: { title: 'Task #14', data: { title: 'Task #14', progress: 45 } }
    },
    multiActivity: { primary: null, secondary: null },
    quota: {},
    tasks: [{ id: 14, title: 'Task #14', agent: 'Lena', progress: 45 }],
    media: {},
    timer: {}
});
return true;
"
take_shot "$SCREEN_DIR/03_compact_task.png"

# 4. Screenshot: COMPACT Media
echo "Capturing 04_compact_media.png..."
probe "
const island = Main._dynamicIsland;
island.contract({
    surfacedEvent: {
        type: 'TRACK_CHANGED',
        priority: 3,
        payload: { title: 'Midnight City', artist: 'M83' }
    },
    multiActivity: { primary: null, secondary: null },
    quota: {},
    tasks: [],
    media: { title: 'Midnight City', artist: 'M83', isPlaying: true },
    timer: {}
});
return true;
"
take_shot "$SCREEN_DIR/04_compact_media.png"

# 5. Screenshot: COMPACT Timer
echo "Capturing 05_compact_timer.png..."
probe "
const island = Main._dynamicIsland;
island.contract({
    surfacedEvent: {
        type: 'TIMER_STARTED',
        priority: 3,
        payload: { formatted: '18:42' }
    },
    multiActivity: { primary: null, secondary: null },
    quota: {},
    tasks: [],
    media: {},
    timer: { status: 'RUNNING', formatted: '18:42' }
});
return true;
"
take_shot "$SCREEN_DIR/05_compact_timer.png"

# 6. Screenshot: SATELLITE (Multi-Activity)
echo "Capturing 06_satellite_multi_activity.png..."
probe "
const island = Main._dynamicIsland;
island.contract({
    surfacedEvent: null,
    multiActivity: {
        primary: { type: 'task', title: 'Task #38', data: { progress: 85 } },
        secondary: { type: 'media', title: 'Solaris', artist: 'Photek' }
    },
    quota: {},
    tasks: [{ id: 38, title: 'Task #38', agent: 'Lena', progress: 85 }],
    media: { title: 'Solaris', artist: 'Photek', isPlaying: true },
    timer: {}
});
return true;
"
take_shot "$SCREEN_DIR/06_satellite_multi_activity.png"

# 7. Screenshot: EXPANDED AI Quota (Liquid Glass)
echo "Capturing 07_expanded_quota_liquid_glass.png..."
probe "
const island = Main._dynamicIsland;
island.setTheme('liquid-glass');
const state = {
    surfacedEvent: null,
    multiActivity: { primary: null, secondary: null },
    quota: {
        codex: { ts: Date.now() / 1000, windows: [{ label: '5h', used: 78, resetsAt: Date.now() / 1000 + 9000 }, { label: 'Weekly', used: 28, resetsAt: Date.now() / 1000 + 400000 }] },
        claude: { ts: Date.now() / 1000, windows: [{ label: '5h', used: 17, resetsAt: Date.now() / 1000 + 12000 }, { label: 'Weekly', used: 31, resetsAt: Date.now() / 1000 + 300000 }] },
        gemini: { ts: Date.now() / 1000, windows: [{ label: '5h', used: 100, resetsAt: Date.now() / 1000 + 3000 }, { label: 'Weekly', used: 85, resetsAt: Date.now() / 1000 + 250000 }] },
        cautionBreach: false,
        criticalBreach: false
    },
    tasks: [],
    media: {},
    timer: {},
    isPinned: false
};
island.expand('quota', state);
const ov = island._overlay.getActor();
if (ov) { ov.opacity = 255; ov.translation_y = 0; }
return true;
"
take_shot "$SCREEN_DIR/07_expanded_quota_liquid_glass.png"
cp "$SCREEN_DIR/07_expanded_quota_liquid_glass.png" "$SCREEN_DIR/fix_expanded.png"

# 8. Screenshot: EXPANDED Background Tasks (Liquid Glass)
echo "Capturing 08_expanded_tasks_liquid_glass.png..."
probe "
const island = Main._dynamicIsland;
island.setTheme('liquid-glass');
const state = {
    surfacedEvent: null,
    multiActivity: { primary: null, secondary: null },
    quota: {},
    tasks: [{
        id: 14,
        title: 'Dynamic Island Frontend UI',
        agent: 'Lena',
        step: 2,
        totalSteps: 4,
        progress: 65,
        logs: ['Compiling GJS components...', 'Mounted IslandAnchor onto dateMenu', 'Rendering St overlay HUD...']
    }],
    media: {},
    timer: {},
    isPinned: false
};
island.expand('tasks', state);
const ov = island._overlay.getActor();
if (ov) { ov.opacity = 255; ov.translation_y = 0; }
return true;
"
take_shot "$SCREEN_DIR/08_expanded_tasks_liquid_glass.png"

# 9. Screenshot: EXPANDED Media Controls (Liquid Glass)
echo "Capturing 09_expanded_media_liquid_glass.png..."
probe "
const island = Main._dynamicIsland;
island.setTheme('liquid-glass');
const state = {
    surfacedEvent: null,
    multiActivity: { primary: null, secondary: null },
    quota: {},
    tasks: [],
    media: {
        isPlaying: true,
        title: 'Midnight City',
        artist: 'M83',
        album: 'Hurry Up, We are Dreaming',
        positionSec: 142,
        durationSec: 244
    },
    timer: {},
    isPinned: false
};
island.expand('media', state);
const ov = island._overlay.getActor();
if (ov) { ov.opacity = 255; ov.translation_y = 0; }
return true;
"
take_shot "$SCREEN_DIR/09_expanded_media_liquid_glass.png"

# 10. Screenshot: EXPANDED Focus Timers (Liquid Glass)
echo "Capturing 10_expanded_timer_liquid_glass.png..."
probe "
const island = Main._dynamicIsland;
island.setTheme('liquid-glass');
const state = {
    surfacedEvent: null,
    multiActivity: { primary: null, secondary: null },
    quota: {},
    tasks: [],
    media: {},
    timer: {
        status: 'RUNNING',
        formatted: '18:42',
        remainingSec: 1122,
        totalSec: 1500,
        presetName: 'Pomodoro'
    },
    isPinned: false
};
island.expand('timer', state);
const ov = island._overlay.getActor();
if (ov) { ov.opacity = 255; ov.translation_y = 0; }
return true;
"
take_shot "$SCREEN_DIR/10_expanded_timer_liquid_glass.png"

# 11. Screenshot: EXPANDED Dark Precision Theme
echo "Capturing 11_expanded_dark_precision.png..."
probe "
const island = Main._dynamicIsland;
island.setTheme('dark-precision');
const state = {
    surfacedEvent: null,
    multiActivity: { primary: null, secondary: null },
    quota: {
        codex: { ts: Date.now() / 1000, windows: [{ label: '5h', used: 82, resetsAt: Date.now() / 1000 + 9000 }, { label: 'Weekly', used: 40, resetsAt: Date.now() / 1000 + 400000 }] },
        claude: { ts: Date.now() / 1000, windows: [{ label: '5h', used: 28, resetsAt: Date.now() / 1000 + 12000 }, { label: 'Weekly', used: 55, resetsAt: Date.now() / 1000 + 300000 }] },
        gemini: { ts: Date.now() / 1000, windows: [{ label: '5h', used: 12, resetsAt: Date.now() / 1000 + 3000 }, { label: 'Weekly', used: 60, resetsAt: Date.now() / 1000 + 250000 }] },
        cautionBreach: true,
        criticalBreach: false
    },
    tasks: [],
    media: {},
    timer: {},
    isPinned: false
};
island.expand('quota', state);
const ov = island._overlay.getActor();
if (ov) { ov.opacity = 255; ov.translation_y = 0; }
return true;
"
take_shot "$SCREEN_DIR/11_expanded_dark_precision.png"

# 12. Screenshot: EXPANDED Dark Precision Tasks
echo "Capturing 12_expanded_dark_precision_tasks.png..."
probe "
const island = Main._dynamicIsland;
island.setTheme('dark-precision');
const state = {
    surfacedEvent: null,
    multiActivity: { primary: null, secondary: null },
    quota: {},
    tasks: [{
        id: 38,
        title: 'Build: Dynamic Island frontend',
        agent: 'Lena',
        step: 3,
        totalSteps: 3,
        progress: 95,
        logs: ['Running verify-dynamic-island.js (57/57)', 'Running verify-all.sh --quick (13/13)', 'Capturing 12 nested state screenshots']
    }],
    media: {},
    timer: {},
    isPinned: false
};
island.expand('tasks', state);
const ov = island._overlay.getActor();
if (ov) { ov.opacity = 255; ov.translation_y = 0; }
return true;
"
take_shot "$SCREEN_DIR/12_expanded_dark_precision_tasks.png"

echo "All nested screenshots successfully captured."
INNER_EOF

cat "$SANDBOX/cpu_metrics.txt" 2>/dev/null || true
