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
  CLIPBOARD_MAX_ITEMS, CLIPBOARD_MAX_CHARS });`, { exportsTo: U });

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

console.log();
if (failures) {
    console.log(`${failures} check(s) failed`);
    process.exit(1);
}
console.log('Shell helper checks passed');
