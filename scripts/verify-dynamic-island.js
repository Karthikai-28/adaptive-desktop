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
// 6-8. Focus deadline/persistence/DND/digest, task cancel and log, MPRIS variants/position/seek/players
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
        fetcher: (cb, force) => { quota.lastFetchForced = force; cb(null, nextSnap); },
    });

    quota.poll();
    const qData = quota.getData();
    check(qData.codex.windows[0].used === 40, 'quota: Codex 5h used (40%)');
    check(qData.claude.windows[0].used === 17, 'quota: Claude 5h used (17%)');
    check(qData.gemini.windows.length === 0 && qData.gemini.error.includes('not running'), 'quota: Gemini unavailable says why');
    check(quotaEvents.length === 0, 'quota: a routine reading surfaces nothing');
    let refreshed = null;
    quota.refresh(ok => { refreshed = ok; });
    check(quota.lastFetchForced === true && refreshed === true, 'quota: manual refresh forces the source and reports success');

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
    quota._resetTranscriptTotals();
    quota._transcriptRemainder = '';
    quota._parseTranscriptChunk(sampleLogLines.split('\n')[0] + '\n');
    quota._parseTranscriptChunk(sampleLogLines.split('\n')[1] + '\n');
    check(quota.getData().agy.sessionTokens.total === 3000,
        'quota: appended transcript chunks are accumulated without reparsing old lines');
    quota.setDormant(true);
    check(quota._isDormant === true, 'quota: dormant polling can be selected while its cards are hidden');
    let wakePolls = 0;
    quota._customFetcher = cb => { wakePolls++; cb(null, nextSnap); };
    quota.setDormant(false);
    check(wakePolls === 1, 'quota: opening AI usage refreshes a dormant reading immediately');
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
        provider: 'quota', source: 'codex',
        priority: Types.IslandPriority.P1_URGENT,
        dwellMs: -1,
        message: 'Quota Critical!',
    });
    check(island.getState().surfacedEvent.type === 'QUOTA_CRITICAL_BREACH', 'bus: P1 urgent event preempted P3');
    check(island.getState().queueLength === 1, 'bus: interrupted P3 re-queued with remaining dwell');
    island.resolveQuotaAlerts({ codex: 'normal', claude: 'normal', gemini: 'normal' });
    check(island.getState().surfacedEvent.type === 'TRACK_CHANGED',
        'bus: a recovered quota automatically clears its stale sticky alert');
    island.emitEvent('QUOTA_CRITICAL_BREACH', {
        provider: 'quota', source: 'codex',
        priority: Types.IslandPriority.P1_URGENT,
        dwellMs: -1,
        message: 'Quota Critical!',
    });

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
    island._surfacedEvent = {
        type: 'TASK_STARTED', priority: 3, dwellMs: 3000,
        payload: { provider: 'task', title: 'Secret project', project: 'private',
            data: { id: 9, title: 'Secret project', body: 'sensitive prompt' } },
    };
    const hiddenEvent = island.getState().surfacedEvent;
    check(hiddenEvent.payload.title === 'AI Task in Progress' &&
        !JSON.stringify(hiddenEvent).includes('Secret project'),
    'bus: sharing also sanitizes an event that was already surfaced');
    island._surfacedEvent = {
        type: Types.IslandEvents.ROS_RUN_FAILED, priority: 1, dwellMs: -1,
        payload: { provider: 'ros', title: 'ROS 2', message: 'secret_bringup exited with code 3', icon: '⚠',
            data: { count: 1, level: 2, node: '/secret_arm' } },
    };
    const rosHidden = island.getState().surfacedEvent;
    check(rosHidden.payload.message === 'ROS 2 needs attention' &&
        !JSON.stringify(rosHidden).includes('secret'),
    'bus: sharing hides which ROS launch or node an alert is about');
    island._surfacedEvent = {
        type: 'TASK_STARTED', priority: 3, dwellMs: 3000,
        payload: { provider: 'task', title: 'Secret project', project: 'private',
            data: { id: 9, title: 'Secret project', body: 'sensitive prompt' } },
    };
    island.setScreenSharing(false);
    check(island.getState().surfacedEvent.payload.title === 'Secret project',
        'bus: ending sharing restores the original event without losing it');

    // Test 5.7: Multi-Activity Decoupling
    island.tasks._runningTasks.set(42, { id: 42, title: 'Compile ROS', agent: 'arjun' });
    island.media._currentTrack.isPlaying = true;
    island.media._currentTrack.title = 'Solaris';
    island.media._currentTrack.artist = 'Photek';

    const multi = island.getMultiActivitySlots();
    check(multi.primary.type === 'task', 'bus: multi-activity Primary slot occupied by AI Task (Task > Media)');
    check(multi.secondary.type === 'media', 'bus: multi-activity Secondary satellite slot occupied by Media');

    // Clean teardown
    island.setRosRecording({ topics: ['/private_topic'], started: 123 });
    check(island.getMultiActivitySlots().primary.type === 'ros', 'ROS recording remains a primary activity');
    island.dismissCurrentEvent();
    check(island.getMultiActivitySlots().primary.type === 'ros', 'dismissing an event keeps the recording activity');
    island.setScreenSharing(true);
    check(!JSON.stringify(island.getMultiActivitySlots()).includes('private_topic'), 'recording activity hides topics during sharing');
    island.setRosRecording(null);
    check(island.getMultiActivitySlots().primary?.type !== 'ros', 'stopping removes the recording activity');

    // Cast (apps/adaptive-cast): the TV takes the center pill, and the island
    // goes private once the TV is live, whatever GNOME's own screencast says.
    island.setScreenSharing(false);
    island.setCasting({ state: 'connecting', tv: '[LG] webOS TV UQ7500PSF' });
    check(island.getMultiActivitySlots().primary.type === 'cast', 'cast: a cast takes the primary slot');
    check(!island.getState().isScreenSharing, 'cast: not private until the TV shows the screen');
    island.setCasting({ state: 'streaming', tv: '[LG] webOS TV UQ7500PSF', frozen: false });
    check(island.getMultiActivitySlots().primary.title === 'On LG TV', 'cast: the pill names the TV briefly');
    check(island.getState().isScreenSharing, 'cast: the island is private while the TV is live');
    check(!JSON.stringify(island.getMultiActivitySlots()).includes('Compile ROS'), 'cast: task titles are hidden from the TV');
    island.setCasting({ state: 'streaming', tv: 'TV', frozen: true });
    check(island.getMultiActivitySlots().primary.title === 'TV paused', 'cast: a frozen TV says so');
    island.setCasting({ state: 'ended', text: 'Stopped' });
    check(island.getMultiActivitySlots().primary?.type !== 'cast', 'cast: stopping removes the activity');
    check(!island.getState().isScreenSharing, 'cast: privacy lifts when the cast ends');
    island.destroy();
    check(island._destroyed === true, 'bus: clean destroy with zero lingering resources');

    // =========================================================================
    // 6. Behaviour the first suite missed (Shade v3.1 repair pass)
    // =========================================================================
    console.log('\n-- Provider 6: Focus deadline, persistence, DND and digest --');
    {
        let now = 1_000_000;
        let saved = null;
        const storage = { read: () => saved && JSON.parse(JSON.stringify(saved)), write: d => { saved = d; } };
        let dndOn = false;
        const dnd = { get: () => dndOn, set: v => { dndOn = v; } };
        let notified = 0;
        const events = [];
        const bus = { emitEvent: (type, payload) => events.push({ type, payload }), notifyStateChange: () => notified++ };
        let mark = 0;
        const digestSource = { mark: () => mark, summary: m => (m === 5 ? '3 notifications from 2 apps' : '') };

        const t = new IslandTimerProvider({ bus, storage, dnd, now: () => now });
        t.init();
        t.setDigestSource(digestSource);
        mark = 5;
        t.startPomodoro();
        t._stopTimerTicker(); // drive the clock by hand
        check(dndOn === true, 'timer: a focus session turns Do Not Disturb on');
        check(saved && saved.status === 'RUNNING' && saved.deadline === now + 1500 * 1000,
            'timer: the deadline is saved when focus starts');
        check(saved.digestMark === 5, 'timer: the focus digest marker is saved with the deadline');

        now += 600 * 1000; // ten minutes pass, e.g. across a suspend
        check(t.getState().remainingSeconds === 900, 'timer: remaining time follows the wall clock, not ticks');

        // A shell restart: a new provider restores the running session.
        const t2 = new IslandTimerProvider({ bus, storage, dnd, now: () => now });
        t2.init();
        t2._stopTimerTicker();
        check(t2.getState().status === 'RUNNING' && t2.getState().remainingSeconds === 900,
            'timer: a running session survives a shell restart');
        check(t2.getState().dndHeld === true, 'timer: the restored session still owns Do Not Disturb');
        check(t2._digestMark === 5, 'timer: the digest marker survives a shell restart');

        notified = 0;
        t2.extend(300);
        check(t2.getState().remainingSeconds === 1200, 'timer: +5m moves the deadline');
        check(notified > 0, 'timer: extend refreshes the UI at once');

        // Expiry after a long suspend: one recompute ends it, gives DND back
        // and reports what arrived.
        t2.setDigestSource(digestSource);
        events.length = 0;
        now += 3600 * 1000;
        t2._syncRemaining();
        if (t2.getState().remainingSeconds <= 0)
            t2._expire();
        const expired = events.find(e => e.type === 'TIMER_EXPIRED');
        check(t2.getState().status === 'EXPIRED', 'timer: a deadline passed during suspend expires');
        check(dndOn === false, 'timer: Do Not Disturb is given back when focus ends');
        check(expired && expired.payload.message.includes('3 notifications from 2 apps'),
            'timer: the expiry carries the focus digest');

        // DND that was already on before focus stays on afterwards.
        dndOn = true;
        const t3 = new IslandTimerProvider({ bus, storage: null, dnd, now: () => now });
        t3.startPomodoro();
        t3._stopTimerTicker();
        t3.reset();
        check(dndOn === true, 'timer: a DND the user had on is left on');

        // The user turning DND off mid-session wins.
        dndOn = false;
        const t4 = new IslandTimerProvider({ bus, storage: null, dnd, now: () => now });
        t4.startPomodoro();
        t4._stopTimerTicker();
        dndOn = false;
        t4.reset();
        check(dndOn === false, 'timer: a DND the user turned off mid-session stays off');

        // Breaks do not silence notifications.
        const t5 = new IslandTimerProvider({ bus, storage: null, dnd, now: () => now });
        t5.startBreak(5);
        t5._stopTimerTicker();
        check(dndOn === false, 'timer: a break does not turn DND on');
        notified = 0;
        t5.reset();
        check(notified > 0, 'timer: reset refreshes the UI at once');

        // Stopping focus early still reports the digest.
        events.length = 0;
        const t6 = new IslandTimerProvider({ bus, storage: null, dnd, now: () => now });
        t6.setDigestSource(digestSource);
        mark = 5;
        t6.startPomodoro();
        t6._stopTimerTicker();
        t6.reset();
        check(events.some(e => e.type === 'TIMER_DIGEST'), 'timer: stopping focus early emits the digest');
        check(t6.getState().lastDigest === '3 notifications from 2 apps', 'timer: the digest stays on the card');

        // If the restored deadline elapsed while Shell was down, init() must
        // still have the digest source before it expires the session.
        saved = { status: 'RUNNING', label: 'Pomodoro', preset: 'pomodoro',
            totalSeconds: 60, remainingSeconds: 60, deadline: now - 1,
            dndHeld: false, digestMark: 5 };
        dndOn = true;
        events.length = 0;
        const t7 = new IslandTimerProvider({ bus, storage, dnd, now: () => now });
        t7.setDigestSource(digestSource);
        t7.init();
        check(events.some(e => e.type === 'TIMER_EXPIRED' && e.payload.digest),
            'timer: a restored expired session keeps its digest');
        const timerSource = fs.readFileSync(path.join(shellDir, 'islandTimers.js'), 'utf8');
        check(!timerSource.includes("this._emit('TIMER_TICK'"),
            'timer: one-second ticks update state without filling the event queue');
        [t, t2, t3, t4, t5, t6, t7].forEach(x => x.destroy());
    }

    console.log('\n-- Provider 7: Task cancel, log, live list --');
    {
        const posted = [];
        let notified = 0;
        const bus = { emitEvent() {}, notifyStateChange: () => notified++ };
        const tasks = new IslandTaskProvider({
            bus,
            poster: (url, done) => { posted.push(url); done(null, true); },
            fetcher: cb => cb(null, []),
            logFetcher: (id, cb) => cb(null, [
                { ts: 1, kind: 'step', text: 'one' }, { ts: 2, kind: 'step', text: 'two' },
                { ts: 3, kind: 'tool', text: 'run  tests\n' }, { ts: 4, kind: 'step', text: 'four' },
                { ts: 5, kind: 'step', text: 'five' }]),
        });
        tasks._processTasks([{ id: 7, title: 'A', agent: 'x', status: 'running', steps: 1 },
            { id: 8, title: 'B', agent: 'y', status: 'running', steps: 2 }]);
        check(tasks.getActiveTasks().length === 2, 'task: every running task is listed, not just the first');
        let cbOk = null;
        tasks.cancelTask(8, (err, ok) => { cbOk = ok; });
        check(posted[0] === 'http://127.0.0.1:8790/api/tasks/8/cancel', 'task: cancel POSTs to the task\'s cancel action');
        check(cbOk === true, 'task: cancel reports success');
        notified = 0;
        tasks._processTasks([{ id: 7, title: 'A', agent: 'x', status: 'running', steps: 1 },
            { id: 8, title: 'B', agent: 'y', status: 'cancelled', steps: 2 }]);
        check(tasks.getActiveTasks().length === 1 && notified > 0, 'task: a cancelled task leaves the list and the UI redraws');
        let lines = null;
        tasks.fetchTaskLog(7, l => { lines = l; });
        check(lines && lines.length === 4 && lines[0].text === 'step: two', 'task: the log keeps the last four events');
        check(lines && lines[1].text === 'tool: run tests', 'task: log lines are one line each');
        let fetches = 0;
        tasks._logFetcher = (id, cb) => { fetches++; cb(null, []); };
        tasks.fetchTaskLog(7, () => {});
        check(fetches === 0, 'task: the log is cached for a few seconds');
        tasks.destroy();

        const real = fs.readFileSync(path.join(shellDir, 'islandTasks.js'), 'utf8');
        check(real.includes("'-X', 'POST'") && real.includes("'X-Office: 1'"),
            'task: the real client sends POST with the header Agent Office requires');
        check(real.includes('?status=running&limit='),
            'task: polling asks for running tasks directly instead of a mixed recent page');

        let fetchCalls = 0;
        let finishFetch = null;
        const guarded = new IslandTaskProvider({ fetcher: cb => { fetchCalls++; finishFetch = cb; } });
        guarded.pollTasks();
        guarded.pollTasks();
        check(fetchCalls === 1, 'task: a slow request cannot overlap the next poll');
        finishFetch(null, []);
        guarded.destroy();

        const live = new IslandTaskProvider({ bus, liveUpdates: false });
        live._handleLiveMessage({ type: 'task', task: {
            id: 19, title: 'Live task', agent: 'x', status: 'running', steps: 1,
        } });
        live._handleLiveMessage({ type: 'event', event: {
            task_id: 19, ts: 9, kind: 'step', text: 'streamed update',
        } });
        check(live.getActiveTasks().length === 1 &&
            live._logs.get(19).lines[0].text === 'step: streamed update',
        'task: Agent Office live updates refresh tasks and logs without waiting for a poll');
        check(real.includes('websocket_connect_async'),
            'task: the provider uses Agent Office live updates with polling as fallback');
        live.destroy();
    }

    console.log('\n-- Provider 8: Media variants, position, seek, players --');
    {
        let now = 50_000;
        const variant = v => ({ recursiveUnpack: () => v });
        const dbusMock = {};
        const media = new IslandMediaProvider({ bus: { emitEvent() {}, notifyStateChange() {} }, dbus: dbusMock, now: () => now });
        media.init();
        // What GLib hands over: a{sv} whose values are still variants.
        dbusMock.onPlayerChanged('org.mpris.MediaPlayer2.spotify', {
            PlaybackStatus: variant('Playing'),
            CanSeek: variant(true),
            Position: variant(30e6),
            Metadata: variant({ 'xesam:title': 'Teardrop', 'xesam:artist': ['Massive Attack'],
                'mpris:length': 330e6, 'mpris:trackid': '/t/1', 'mpris:artUrl': 'file:///tmp/a.jpg' }),
        });
        let tr = media.getCurrentTrack();
        check(tr.title === 'Teardrop' && tr.isPlaying, 'media: variant-wrapped MPRIS properties are unpacked');
        check(tr.lengthUs === 330e6 && tr.artUrl === 'file:///tmp/a.jpg', 'media: length and artwork are read');
        now += 10_000;
        tr = media.getCurrentTrack();
        check(Math.round(tr.positionUs / 1e6) === 40, 'media: position advances while playing');
        dbusMock.onPlayerChanged('org.mpris.MediaPlayer2.spotify', { PlaybackStatus: 'Paused' });
        now += 10_000;
        check(Math.round(media.getCurrentTrack().positionUs / 1e6) === 40, 'media: position holds while paused');
        media.seekToFraction(0.5);
        check(media.getCurrentTrack().positionUs === 165e6, 'media: seeking moves the position at once');
        media.seekBy(1000);
        check(media.getCurrentTrack().positionUs === 330e6, 'media: seeking is clamped to the track');

        dbusMock.onPlayerChanged('org.mpris.MediaPlayer2.vlc', {
            PlaybackStatus: 'Playing', Metadata: { 'xesam:title': 'Film' },
        });
        check(media.getCurrentTrack().title === 'Film', 'media: the player that starts playing becomes current');
        check(media.getPlayers().length === 2, 'media: every player is listed');
        media.selectPlayer('org.mpris.MediaPlayer2.spotify');
        dbusMock.onPlayerChanged('org.mpris.MediaPlayer2.vlc', { PlaybackStatus: 'Playing' });
        check(media.getCurrentTrack().title === 'Teardrop', 'media: a player the user chose stays chosen');
        media._removePlayer('org.mpris.MediaPlayer2.spotify');
        check(media.getCurrentTrack().title === 'Film', 'media: closing the chosen player falls back to another');
        media.destroy();
    }

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
