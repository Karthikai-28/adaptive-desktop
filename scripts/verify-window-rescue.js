#!/usr/bin/env node
//
// Check the geometry the window rescue depends on.
//
// The rescue itself only runs when a display disappears, and mutter clamps
// ordinary window moves, so the stranded state cannot be manufactured by hand
// on a working machine. The arithmetic that decides "this window is gone" can
// be checked, and this reads it out of the shipped extension rather than
// keeping a copy that could drift.
//
const fs = require('fs');
const path = require('path');

const source = fs.readFileSync(
    path.join(__dirname, '..', 'shell', 'adaptive-shell@local', 'extension.js'),
    'utf8'
);

const match = source.match(
    /_windowVisibleFraction\(rect, monitors\) \{([\s\S]*?)\n    \}/
);

if (!match) {
    console.error('FAIL: _windowVisibleFraction not found in extension.js');
    process.exit(1);
}

const visibleFraction = new Function('rect', 'monitors', match[1]);

const laptop = { x: 0, y: 0, width: 1920, height: 1200 };
const right = { x: 1920, y: 0, width: 1024, height: 768 };

const cases = [
    ['fully on the laptop screen',
     { x: 100, y: 100, width: 800, height: 600 }, [laptop], 1],
    ['on a monitor that is gone',
     { x: 2400, y: 300, width: 800, height: 600 }, [laptop], 0],
    ['half off the right edge',
     { x: 1520, y: 100, width: 800, height: 600 }, [laptop], 0.5],
    ['on the second monitor while it exists',
     { x: 2000, y: 100, width: 800, height: 600 }, [laptop, right], 1],
    ['the same window once that monitor is unplugged',
     { x: 2000, y: 100, width: 800, height: 600 }, [laptop], 0],
    ['mostly below the bottom edge',
     { x: 100, y: 1150, width: 800, height: 600 }, [laptop], 50 / 600],
    ['zero area is never treated as lost',
     { x: 0, y: 0, width: 0, height: 0 }, [laptop], 1],
];

let failed = 0;

for (const [name, rect, monitors, expected] of cases) {
    const got = visibleFraction(rect, monitors);
    const ok = Math.abs(got - expected) < 1e-9;

    console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${name}: ` +
                `${(got * 100).toFixed(1)}% visible`);

    if (!ok) {
        console.log(`       expected ${(expected * 100).toFixed(1)}%`);
        failed += 1;
    }

    // The rescue triggers below half visible; state that in the test so the
    // threshold cannot be changed without a case here changing with it.
    const rescued = got < 0.5;
    console.log(`       -> ${rescued ? 'rescued' : 'left alone'}`);
}

if (failed) {
    console.error(`\n${failed} case(s) failed`);
    process.exit(1);
}

console.log('\nWindow rescue geometry verified.');
