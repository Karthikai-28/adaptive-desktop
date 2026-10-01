#!/usr/bin/env node
//
// Check shell/adaptive-shell@local/adaptiveUtil.js under Node.
//
// The file has no imports on purpose, so the shipped code itself is loaded
// here (not a copy that could drift) and its decisions checked: git status
// parsing, the crash watchdog's rule, battery health, the verification
// summary, how a parked app is relaunched, and the clipboard history's bounds.
//
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const file = path.join(__dirname, '..', 'shell', 'adaptive-shell@local', 'adaptiveUtil.js');
const U = {};
vm.runInNewContext(`${fs.readFileSync(file, 'utf8')}
;Object.assign(exportsTo, { parseGitStatus, formatGitStatus, watchdogVerdict, WATCHDOG,
  batteryHealth, verificationSummary, classifyApp, clipboardPush, isSecretClipboard,
  clipboardPushImage, clipboardPin, clipboardClear, pngSize, formatBytes,
  CLIPBOARD_MAX_ITEMS, CLIPBOARD_MAX_CHARS, CLIPBOARD_MAX_PINS, CLIPBOARD_MAX_IMAGES,
  CLIPBOARD_MAX_IMAGE_BYTES, DROPDOWN_ROLE, dropdownTerminalKind, dropdownArgv, dropdownRect,
  isDropdownWindow });`, { exportsTo: U });

let failures = 0;
function check(ok, message) {
    console.log(`${ok ? 'OK  ' : 'FAIL'} ${message}`);
    if (!ok)
        failures++;
}
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

// git
const g = U.parseGitStatus('## main...origin/main [ahead 1, behind 2]\n M a.js\n?? b\n');
check(same(g, { branch: 'main', ahead: 1, behind: 2, dirty: 2, detached: false }), 'git: branch, ahead, behind, dirty');
check(U.formatGitStatus(g) === 'main ±2 ↑1 ↓2', 'git: top-bar text');
check(U.formatGitStatus(U.parseGitStatus('## feature/x\n')) === 'feature/x', 'git: clean branch without upstream');
check(U.parseGitStatus('## No commits yet on main\n').branch === 'main', 'git: empty repository');
check(U.parseGitStatus('## HEAD (no branch)\n').detached, 'git: detached HEAD');
check(U.parseGitStatus('fatal: not a git repository') === null, 'git: not a repository gives null');
check(U.formatGitStatus(null) === '', 'git: no status, no text');

// watchdog
const W = U.WATCHDOG;
let v = U.watchdogVerdict({}, 1000);
check(!v.tripped && same(v.state.starts, [1000]), 'watchdog: first start is fine');
v = U.watchdogVerdict(v.state, 1100);
check(!v.tripped, 'watchdog: second quick start is fine');
v = U.watchdogVerdict(v.state, 1200);
check(v.tripped && v.state.tripped, `watchdog: ${W.MAX_STARTS} starts inside the window trip it`);
check(U.watchdogVerdict(v.state, 99999).tripped, 'watchdog: stays tripped until re-armed');
v = U.watchdogVerdict({ starts: [0, 100] }, W.WINDOW_S + 200);
check(!v.tripped && same(v.state.starts, [W.WINDOW_S + 200]), 'watchdog: old starts age out');
check(!U.watchdogVerdict({ starts: 'junk' }, 5).tripped, 'watchdog: tolerates a corrupt file');
check(!U.watchdogVerdict(null, 5).tripped, 'watchdog: tolerates no file');

// battery
const b = U.batteryHealth({ energy_full: '48100000', energy_full_design: '55000000',
    cycle_count: '412', charge_control_end_threshold: '80' });
check(b.healthPct === 87 && b.unit === 'Wh' && b.cycles === 412 && b.limit === 80, 'battery: energy_* health');
const c = U.batteryHealth({ charge_full: '3000000', charge_full_design: '4000000', cycle_count: '0' });
check(c.healthPct === 75 && c.unit === 'Ah' && c.cycles === null, 'battery: charge_* fallback, zero cycles hidden');
check(U.batteryHealth({ charge_control_end_threshold: '100', energy_full: '1', energy_full_design: '1' }).limit === null,
    'battery: a 100% limit is no limit');
check(U.batteryHealth({}) === null, 'battery: no battery gives null');

// verification
let s = U.verificationSummary({ total: 15, checks: { a: { result: 'pass' }, b: { result: 'na' }, c: { result: 'fail' } } });
check(s.passed === 2 && s.failed === 1 && !s.complete && /2 of 15/.test(s.text) && /1 failing/.test(s.text),
    'verification: counts and text');
check(U.verificationSummary(null).text === 'Physical checks not started', 'verification: no report');
const all = {};
for (let i = 0; i < 3; i++)
    all[`k${i}`] = { result: 'pass' };
check(U.verificationSummary({ total: 3, checks: all }).complete, 'verification: complete when all pass');

// snapshots
check(U.classifyApp('org.gnome.Terminal.desktop', 'GNOME;GTK;System;TerminalEmulator;') === 'terminal', 'snapshot: terminal');
check(U.classifyApp('org.gnome.Nautilus.desktop', 'GNOME;GTK;Utility;Core;FileManager;') === 'folder', 'snapshot: Files opens the folder');
check(U.classifyApp('code.desktop', 'Utility;TextEditor;Development;IDE;') === 'folder', 'snapshot: editor opens the folder');
check(U.classifyApp('firefox.desktop', 'Network;WebBrowser;') === 'plain', 'snapshot: browser relaunches plain');

// clipboard
let items = [];
items = U.clipboardPush(items, 'a', 1);
items = U.clipboardPush(items, 'b', 2);
items = U.clipboardPush(items, 'a', 3);
check(same(items.map(i => i.text), ['a', 'b']) && items[0].at === 3, 'clipboard: newest first, no duplicates');
check(U.clipboardPush(items, '   ', 4).length === 2, 'clipboard: blank text ignored');
check(U.clipboardPush(items, 'x'.repeat(U.CLIPBOARD_MAX_CHARS + 1), 4).length === 2, 'clipboard: huge text ignored');
let many = [];
for (let i = 0; i < U.CLIPBOARD_MAX_ITEMS + 10; i++)
    many = U.clipboardPush(many, `t${i}`, i);
check(many.length === U.CLIPBOARD_MAX_ITEMS, 'clipboard: bounded');
check(U.isSecretClipboard(['text/plain', 'x-kde-passwordManagerHint']), 'clipboard: password manager copies skipped');
check(!U.isSecretClipboard(['text/plain']), 'clipboard: ordinary text kept');

// clipboard: pins
let pins = [];
pins = U.clipboardPush(pins, 'keep', 1, 1);
pins = U.clipboardPush(pins, 'other', 2, 2);
pins = U.clipboardPin(pins, 1, true);
check(pins.find(i => i.id === 1).pinned === true && !pins.find(i => i.id === 2).pinned, 'clipboard: an entry can be pinned');
check(same(U.clipboardPin(pins, 99, true), pins), 'clipboard: pinning an unknown id changes nothing');
for (let i = 0; i < U.CLIPBOARD_MAX_ITEMS + 10; i++)
    pins = U.clipboardPush(pins, `fill${i}`, 10 + i, 100 + i);
check(pins.length === U.CLIPBOARD_MAX_ITEMS && pins.some(i => i.text === 'keep'),
    'clipboard: a pinned entry survives the history filling up');
pins = U.clipboardPush(pins, 'keep', 999, 500);
check(pins[0].text === 'keep' && pins[0].pinned === true, 'clipboard: copying a pinned text again keeps its pin');
check(same(U.clipboardClear(pins).map(i => i.text), ['keep']), 'clipboard: clear keeps only what is pinned');
pins = U.clipboardPin(pins, 500, false);
check(U.clipboardClear(pins).length === 0, 'clipboard: unpinned, it is cleared like the rest');
let full = [];
for (let i = 1; i <= U.CLIPBOARD_MAX_PINS + 1; i++) {
    full = U.clipboardPush(full, `p${i}`, i, i);
    full = U.clipboardPin(full, i, true);
}
check(full.filter(i => i.pinned).length === U.CLIPBOARD_MAX_PINS, 'clipboard: pins are bounded');

// clipboard: images
let pics = U.clipboardPush([], 'text', 1, 1);
for (let i = 0; i < U.CLIPBOARD_MAX_IMAGES + 3; i++)
    pics = U.clipboardPushImage(pics, { id: 10 + i, at: 2 + i, mime: 'image/png', size: 100 + i, hash: i, width: 4, height: 3 });
check(pics.filter(i => i.kind === 'image').length === U.CLIPBOARD_MAX_IMAGES && pics.some(i => i.text === 'text'),
    'clipboard: images are bounded on their own, text is untouched');
const again = U.clipboardPushImage(pics, { id: 99, at: 50, mime: 'image/png', size: pics[1].size, hash: pics[1].hash });
check(again.filter(i => i.kind === 'image').length === U.CLIPBOARD_MAX_IMAGES && again[0].id === 99,
    'clipboard: the same image again moves to the top, not a second copy');
check(U.clipboardPushImage(pics, { id: 1, size: U.CLIPBOARD_MAX_IMAGE_BYTES + 1, hash: 1 }).length === pics.length,
    'clipboard: an oversized image is ignored');
check(U.clipboardPushImage(pics, null).length === pics.length, 'clipboard: no image, no entry');
const png = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 13, 0x49, 0x48, 0x44, 0x52, 0, 0, 7, 0x80, 0, 0, 4, 0xb0];
check(same(U.pngSize(png), { width: 1920, height: 1200 }), 'clipboard: PNG dimensions from the header');
check(U.pngSize([1, 2, 3]) === null && U.pngSize(new Array(24).fill(0)) === null, 'clipboard: not a PNG gives null');
check(U.formatBytes(912) === '912 B' && U.formatBytes(348160) === '340 KB' && U.formatBytes(1258291) === '1.2 MB',
    'clipboard: sizes read naturally');

// drop-down terminal
check(U.dropdownTerminalKind('gnome-terminal', () => true) === 'gnome-terminal', 'dropdown: the terminal asked for, if installed');
check(U.dropdownTerminalKind('gnome-terminal', n => n === 'terminator') === 'terminator', 'dropdown: falls back to what is installed');
check(U.dropdownTerminalKind('xterm; rm -rf', () => true) === 'terminator', 'dropdown: an unknown terminal name is never run');
check(U.dropdownTerminalKind(undefined, () => false) === '', 'dropdown: no terminal installed gives none');
check(same(U.dropdownArgv('gnome-terminal', '/p'), ['gnome-terminal', '--role=adaptive-dropdown', '--working-directory=/p']),
    'dropdown: GNOME Terminal command');
check(U.dropdownArgv('terminator', '/p').includes('--role=adaptive-dropdown'), 'dropdown: Terminator carries the role too');
check(U.isDropdownWindow('gnome-terminal', 'Gnome-terminal', 'adaptive-dropdown'), 'dropdown: found by role on X11');
check(!U.isDropdownWindow('gnome-terminal', 'Gnome-terminal', 'gnome-terminal-window-1'), 'dropdown: another terminal window is not ours');
check(U.isDropdownWindow('gnome-terminal', 'gnome-terminal-server', null), 'dropdown: with no role, by class');
check(!U.isDropdownWindow('gnome-terminal', 'firefox', null), 'dropdown: some other app is never adopted');
check(same(U.dropdownRect({ x: 0, y: 32, width: 1920, height: 1100 }, 0.5), { x: 0, y: 32, width: 1920, height: 550 }),
    'dropdown: across the top of the work area');
check(U.dropdownRect({ x: 0, y: 0, width: 100, height: 1000 }, 'junk').height === 450 &&
    U.dropdownRect({ x: 0, y: 0, width: 100, height: 1000 }, 5).height === 450, 'dropdown: a bad height falls back to the default');

console.log();
if (failures) {
    console.log(`${failures} check(s) failed`);
    process.exit(1);
}
console.log('Shell helper checks passed');
