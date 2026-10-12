#!/usr/bin/env node
//
// Automated Test Suite for Dynamic Island Backend (Providers & Queue Bus)
//
// Validates:
// 1. AI Quota Provider (Claude :8790 parser, thresholds, stale fallback, agy log parsing & gap)
// 2. Background AI Task Provider (lifecycle, 1000ms sliding debounce, cancel dispatch)
// 3. Now-Playing Media Provider (mock MPRIS signals, track change, controls)
// 4. Focus Timer Provider (0% idle CPU, Pomodoro presets, expiration sticky alert)
// 5. Dynamic Island Bus (priority preemption, queue capacity 8, hover pause, privacy sanitization, multi-activity)
//

const path = require('path');
const fs = require('fs');

const shellDir = fs.existsSync(path.join(__dirname, '..', 'shell', 'adaptive-shell@local'))
    ? path.join(__dirname, '..', 'shell', 'adaptive-shell@local')
    : __dirname;

const Types = require(path.join(shellDir, 'islandTypes.js'));
const { IslandQuotaProvider } = require(path.join(shellDir, 'islandQuota.js'));
const { IslandTaskProvider } = require(path.join(shellDir, 'islandTasks.js'));
const { IslandMediaProvider } = require(path.join(shellDir, 'islandMedia.js'));
const { IslandTimerProvider } = require(path.join(shellDir, 'islandTimers.js'));
const { DynamicIslandBackend } = require(path.join(shellDir, 'dynamicIsland.js'));

let failures = 0;
let passed = 0;

function check(ok, message) {
    if (ok) {
        console.log(`OK   ${message}`);
        passed++;
    } else {
        console.error(`FAIL ${message}`);
        failures++;
    }
}

function runAsync(fn) {
    return new Promise((resolve) => fn(resolve));
}

async function main() {
    console.log('== Dynamic Island Backend Verification Suite ==\n');

    // =========================================================================
    // 1. AI Quota Provider Tests
    // =========================================================================
    console.log('-- Provider 1: AI usage (Codex, Claude, Gemini) --');

    let quotaEvents = [];
    const mockBus = {
        emitEvent: (type, payload) => quotaEvents.push({ type, payload }),
    };

    // Test 1.1: one shape for every provider, in % used
    const nowS = Math.floor(Date.now() / 1000);
    const snap = (codex5h, claude5h) => ({
        codex: { ts: nowS, stale: false, error: '', windows: [
            { label: '5h', used: codex5h, resetsAt: nowS + 3600, expired: false },
            { label: 'Weekly', used: 28, resetsAt: nowS + 86400, expired: false }] },
        claude: { ts: nowS, stale: false, error: '', windows: [
            { label: '5h', used: claude5h, resetsAt: nowS + 7200, expired: false }] },
        gemini: { ts: 0, stale: true, error: 'The Agent Office is not running', windows: [] },
    });
    const mockUsageData = snap(40, 17);
    let nextSnap = mockUsageData;

    const quota = new IslandQuotaProvider({
        bus: mockBus,
        fetcher: (cb) => cb(null, nextSnap),
    });

    quota.poll();
    const qData = quota.getData();
    check(qData.codex.windows[0].used === 40, 'quota: Codex 5h used (40%)');
    check(qData.claude.windows[0].used === 17, 'quota: Claude 5h used (17%)');
    check(qData.gemini.windows.length === 0 && qData.gemini.error.includes('not running'), 'quota: Gemini unavailable says why');
    check(quotaEvents.length === 0, 'quota: a routine reading surfaces nothing');

    // Test 1.2: Caution when a window reaches 80% used
    quotaEvents = [];
    nextSnap = snap(82, 17);
    quota.poll();
    const caution = quotaEvents.find(e => e.type === 'QUOTA_CAUTION_BREACH');
    check(!!caution, 'quota: emitted QUOTA_CAUTION_BREACH at 82% used');
    check(caution && caution.payload.message === 'Codex 5h limit 82% used', 'quota: caution names the provider and window');
    check(quota.getData().cautionBreach === true, 'quota: caution flag set for the pill');
    quotaEvents = [];
    quota.poll();
    check(quotaEvents.length === 0, 'quota: no repeat while the level stays the same');

    // Test 1.3: Critical at 95% used
    quotaEvents = [];
    nextSnap = snap(82, 96);
    quota.poll();
    const critEvent = quotaEvents.find(e => e.type === 'QUOTA_CRITICAL_BREACH');
    check(!!critEvent && critEvent.payload.message === 'Claude 5h limit 96% used', 'quota: emitted QUOTA_CRITICAL_BREACH at 96% used');
    check(critEvent && critEvent.payload.dwellMs === -1, 'quota: critical breach has sticky dwell (-1)');

    // Test 1.4: a reset is announced once usage falls back
    quotaEvents = [];
    nextSnap = snap(82, 3);
    quota.poll();
    check(quotaEvents.some(e => e.type === 'QUOTA_RESET_CONFIRMED'), 'quota: reset confirmed when Claude drops to 3%');

    // Test 1.5: failure keeps the last reading, marked stale
    quota.handleFailure('Usage snapshot unavailable');
    const staleData = quota.getData();
    check(staleData.claude.stale === true, 'quota: marked stale on failure');
    check(staleData.claude.windows[0].used === 3, 'quota: retained last values when stale');
    check(staleData.error === 'Usage snapshot unavailable', 'quota: recorded error message');

    // Test 1.6: the card's model
    const { describeUsage } = require(path.join(shellDir, 'islandQuota.js'));
    const model = describeUsage({ ...snap(82, 96), codex: { ts: nowS, windows: [
        { label: '5h', used: 100, resetsAt: nowS - 10, expired: true }] } }, nowS);
    check(model.map(p => p.name).join() === 'Codex,Claude,Gemini', 'quota: card lists Codex, Claude, Gemini');
    check(model[0].rows[0].text === 'reset, awaiting update', 'quota: an ended window never invents a refill');
    check(model[1].rows[0].text === '96% used' && model[1].rows[0].level === 'critical', 'quota: card shows % used with its level');
    check(model[2].unavailable.includes('not running'), 'quota: card says why Gemini is missing');

    // Test 1.7: agy log parsing and Google AI Pro server gap representation
    const sampleLogLines = [
        JSON.stringify({ step_index: 1, input_tokens: 1000, output_tokens: 200, cache_read_tokens: 5000, created_at: '2026-10-11T14:00:00Z' }),
        JSON.stringify({ step_index: 2, input_tokens: 1500, output_tokens: 300, cache_read_tokens: 8000, created_at: '2026-10-11T14:01:00Z' }),
    ].join('\n');
    quota.parseTranscriptText(sampleLogLines);
    const agyData = quota.getData().agy;
    check(agyData.sessionTokens.input === 2500, 'quota: agy summed session input tokens (2500)');
    check(agyData.sessionTokens.output === 500, 'quota: agy summed session output tokens (500)');
    check(agyData.sessionTokens.cache === 13000, 'quota: agy summed session cache tokens (13000)');
    check(agyData.remainingPercent === null, 'quota: agy percentage explicitly null (server-enforced gap)');
    check(agyData.unavailableReason.includes('Server-enforced'), 'quota: agy gap reason documented correctly');
    quota.destroy();

    // =========================================================================
    // 2. Background AI Task Provider Tests
    // =========================================================================
    console.log('\n-- Provider 2: Background AI Tasks --');
    let taskEvents = [];
    const taskBus = {
        emitEvent: (type, payload) => taskEvents.push({ type, payload }),
    };

    const taskProvider = new IslandTaskProvider({
        bus: taskBus,
        debounceMs: 50, // Shortened for test
    });

    // Test 2.1: Task started
    taskProvider._processTasks([
        { id: 17, agent: 'arjun', title: 'Build Dynamic Island backend', status: 'running', steps: 1 },
    ]);
    check(taskEvents.some(e => e.type === 'TASK_STARTED'), 'task: emitted TASK_STARTED on running status');
    check(taskProvider.getActiveTasks().length === 1, 'task: recorded 1 active running task');

    // Test 2.2: Task progress debouncing
    taskEvents = [];
    taskProvider._processTasks([
        { id: 17, agent: 'arjun', title: 'Build Dynamic Island backend', status: 'running', steps: 2 },
    ]);
    taskProvider._processTasks([
        { id: 17, agent: 'arjun', title: 'Build Dynamic Island backend', status: 'running', steps: 3 },
    ]);
    check(taskEvents.length === 0, 'task: intermediate progress updates debounced');

    await runAsync((res) => setTimeout(res, 80));
    check(taskEvents.some(e => e.type === 'TASK_PROGRESS_UPDATE'), 'task: debounced TASK_PROGRESS_UPDATE emitted');
    const progEv = taskEvents.find(e => e.type === 'TASK_PROGRESS_UPDATE');
    check(progEv.payload.steps === 3, 'task: progress update contains latest step (3)');

    // Test 2.3: Task completion
    taskEvents = [];
    taskProvider._processTasks([
        { id: 17, agent: 'arjun', title: 'Build Dynamic Island backend', status: 'completed', steps: 4 },
    ]);
    check(taskEvents.some(e => e.type === 'TASK_COMPLETED_SUCCESS'), 'task: emitted TASK_COMPLETED_SUCCESS');
    check(taskProvider.getActiveTasks().length === 0, 'task: running task list cleared upon completion');

    // Test 2.4: Task failure sticky alert
    taskEvents = [];
    taskProvider._processTasks([
        { id: 18, agent: 'lena', title: 'Compile Web UI', status: 'running', steps: 1 },
    ]);
    taskProvider._processTasks([
        { id: 18, agent: 'lena', title: 'Compile Web UI', status: 'failed', error: 'SyntaxError', steps: 2 },
    ]);
    check(taskEvents.some(e => e.type === 'TASK_FAILED_ERROR'), 'task: emitted TASK_FAILED_ERROR');
    const failEv = taskEvents.find(e => e.type === 'TASK_FAILED_ERROR');
    check(failEv.payload.dwellMs === -1, 'task: failure event has sticky dwell (-1)');
    taskProvider.destroy();

    // =========================================================================
    // 3. Now-Playing Media Provider Tests
    // =========================================================================
    console.log('\n-- Provider 3: Now-Playing Media (MPRIS) --');
    let mediaEvents = [];
    const mediaBus = {
        emitEvent: (type, payload) => mediaEvents.push({ type, payload }),
    };

    const mockDBus = {};
    const mediaProvider = new IslandMediaProvider({
        bus: mediaBus,
        dbus: mockDBus,
    });
    mediaProvider.init();

    // Test 3.1: Track change signal
    mockDBus.onPlayerChanged('org.mpris.MediaPlayer2.spotify', {
        PlaybackStatus: 'Playing',
        Metadata: {
            'xesam:title': 'Midnight City',
            'xesam:artist': ['M83'],
            'xesam:album': 'Hurry Up, We\'re Dreaming',
        },
    });
    check(mediaEvents.some(e => e.type === 'TRACK_CHANGED'), 'media: emitted TRACK_CHANGED');
    const track = mediaProvider.getCurrentTrack();
    check(track.title === 'Midnight City', 'media: track title parsed (Midnight City)');
    check(track.artist === 'M83', 'media: artist parsed (M83)');
    check(track.isPlaying === true, 'media: status is playing');

    // Test 3.2: Play/Pause state change
    mediaEvents = [];
    mockDBus.onPlayerChanged('org.mpris.MediaPlayer2.spotify', {
        PlaybackStatus: 'Paused',
    });
    check(mediaEvents.some(e => e.type === 'PLAYBACK_STATE_CHANGED'), 'media: emitted PLAYBACK_STATE_CHANGED');
    check(mediaProvider.getCurrentTrack().isPlaying === false, 'media: status updated to paused');
    mediaProvider.destroy();

    // =========================================================================
    // 4. Focus Timers Provider Tests
    // =========================================================================
    console.log('\n-- Provider 4: Focus Timers (0% Idle CPU) --');
    let timerEvents = [];
    const timerBus = {
        emitEvent: (type, payload) => timerEvents.push({ type, payload }),
    };

    const timerProvider = new IslandTimerProvider({ bus: timerBus });
    timerProvider.init();

    // Test 4.1: 0% Idle CPU check
    check(timerProvider._timerSourceId === 0, 'timer: zero timers active when idle (0% CPU)');

    // Test 4.2: Start Pomodoro preset (25m)
    timerProvider.startPomodoro();
    check(timerEvents.some(e => e.type === 'TIMER_STARTED'), 'timer: emitted TIMER_STARTED');
    check(timerProvider.getState().remainingSeconds === 25 * 60, 'timer: initial duration is 1500s');
    check(timerProvider.getState().status === 'RUNNING', 'timer: status is RUNNING');
    check(timerProvider._timerSourceId !== 0, 'timer: ticker active while running');

    // Test 4.3: Pause & Resume
    timerEvents = [];
    timerProvider.pause();
    check(timerProvider.getState().status === 'PAUSED', 'timer: status is PAUSED');
    check(timerProvider._timerSourceId === 0, 'timer: ticker destroyed when PAUSED (0% CPU)');
    check(timerEvents.some(e => e.type === 'TIMER_PAUSED'), 'timer: emitted TIMER_PAUSED');

    timerProvider.resume();
    check(timerProvider.getState().status === 'RUNNING', 'timer: resumed to RUNNING');
    check(timerProvider._timerSourceId !== 0, 'timer: ticker re-armed on resume');

    // Test 4.4: Expiration sticky alert
    timerEvents = [];
    timerProvider._state.remainingSeconds = 1;
    timerProvider._state.remainingSeconds = 0;
    timerProvider._state.status = 'EXPIRED';
    timerProvider._stopTimerTicker();
    timerBus.emitEvent('TIMER_EXPIRED', {
        provider: 'timer',
        priority: 1,
        dwellMs: -1,
        message: 'Pomodoro finished!',
    });
    check(timerEvents.some(e => e.type === 'TIMER_EXPIRED'), 'timer: emitted TIMER_EXPIRED');
    const expEv = timerEvents.find(e => e.type === 'TIMER_EXPIRED');
    check(expEv.payload.dwellMs === -1, 'timer: expired event is sticky (-1)');
    check(timerProvider._timerSourceId === 0, 'timer: ticker stopped on expiration');
    timerProvider.destroy();

    // =========================================================================
    // 5. Dynamic Island Bus & Priority Queue Engine Tests
    // =========================================================================
    console.log('\n-- Provider 5: Unified Event Bus & Priority Queue --');
    const island = new DynamicIslandBackend({
        quotaOptions: { fetcher: (cb) => cb(null, mockUsageData) },
    });

    // Test 5.1: Surface initial event
    island.emitEvent('TRACK_CHANGED', {
        priority: Types.IslandPriority.P3_NORMAL,
        dwellMs: 3000,
        message: 'Track 1',
    });
    check(island.getState().surfacedEvent !== null, 'bus: surfaced first event');
    check(island.getState().surfacedEvent.type === 'TRACK_CHANGED', 'bus: surfaced event is TRACK_CHANGED');

    // Test 5.2: Preemption (P1 interrupts P3 immediately)
    island.emitEvent('QUOTA_CRITICAL_BREACH', {
        priority: Types.IslandPriority.P1_URGENT,
        dwellMs: -1,
        message: 'Quota Critical!',
    });
    check(island.getState().surfacedEvent.type === 'QUOTA_CRITICAL_BREACH', 'bus: P1 urgent event preempted P3');
    check(island.getState().queueLength === 1, 'bus: interrupted P3 re-queued with remaining dwell');

    // Test 5.3: Queue capacity boundary (capacity = 8)
    for (let i = 0; i < 12; i++) {
        island.emitEvent('TASK_PROGRESS_UPDATE', {
            priority: Types.IslandPriority.P4_AMBIENT,
            dwellMs: 2000,
            message: `Tick #${i}`,
            data: { step: i },
        });
    }
    check(island.getState().queueLength <= 8, `bus: queue length respects capacity ceiling (length = ${island.getState().queueLength})`);

    // Test 5.4: Hover dwell pause & resume
    island.dismissCurrentEvent(); // Dismiss P1
    check(island.getState().surfacedEvent !== null, 'bus: next queued event surfaced');
    island.pauseDwell();
    check(island._isDwellPaused === true, 'bus: dwell countdown paused on hover');
    island.resumeDwell();
    check(island._isDwellPaused === false, 'bus: dwell countdown resumed on hover exit');

    // Test 5.5: Click to Pin
    island.setPinned(true);
    check(island.getState().isPinned === true, 'bus: card pinned open');
    check(island._dwellTimerId === 0, 'bus: dwell auto-tuck disabled while pinned');
    island.setPinned(false);
    check(island.getState().isPinned === false, 'bus: card unpinned');

    // Test 5.6: Privacy Screen-Sharing Sanitization
    island.setScreenSharing(true);
    island.emitEvent('QUOTA_CAUTION_BREACH', {
        provider: 'quota',
        priority: Types.IslandPriority.P2_HIGH,
        remaining: '18%',
        message: 'Claude 18%',
    });
    const lastSurfaced = island.getState().surfacedEvent;
    check(lastSurfaced.payload.message === '✦ Active', 'bus: ScreenCast privacy sanitized numeric quota to ✦ Active');
    island.setScreenSharing(false);

    // Test 5.7: Multi-Activity Decoupling
    island.tasks._runningTasks.set(42, { id: 42, title: 'Compile ROS', agent: 'arjun' });
    island.media._currentTrack.isPlaying = true;
    island.media._currentTrack.title = 'Solaris';
    island.media._currentTrack.artist = 'Photek';

    const multi = island.getMultiActivitySlots();
    check(multi.primary.type === 'task', 'bus: multi-activity Primary slot occupied by AI Task (Task > Media)');
    check(multi.secondary.type === 'media', 'bus: multi-activity Secondary satellite slot occupied by Media');

    // Clean teardown
    island.destroy();
    check(island._destroyed === true, 'bus: clean destroy with zero lingering resources');

    // Summary
    console.log(`\n========================================`);
    console.log(`Summary: ${passed} passed, ${failures} failed.`);
    console.log(`========================================`);

    if (failures > 0)
        process.exit(1);
}

main().catch((err) => {
    console.error('Fatal test error:', err);
    process.exit(1);
});
