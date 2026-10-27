#!/usr/bin/env node
// Adaptive Home (apps/adaptive-tv), the launcher that runs on the LG TV:
// the tile logic and remote navigation, the WebSocket framing its service
// speaks to the TV's control socket, and that the package files agree.
// Needs no TV.

'use strict';

const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..', 'apps', 'adaptive-tv');
const M = require(path.join(root, 'app', 'model.js'));
const ssap = require(path.join(root, 'service', 'ssap.js'));

const failures = [];
function check(name, ok) {
    if (!ok) {
        failures.push(name);
        console.log('FAIL ' + name);
    }
}

// --- tiles ------------------------------------------------------------------

check('short title drops the tagline', M.shortTitle('JioCinema- Bigg Boss & Cricket') === 'JioCinema');
check('short title keeps a plain name', M.shortTitle('Room to Room Share') === 'Room to Room Share');
check('colour names', M.hexColor('white') === '#ffffff' && M.hexColor('#FD312E') === '#fd312e');
check('short hex expands', M.hexColor('#abc') === '#aabbcc');
check('no colour is the surface', M.tileColor({ iconColor: '', bgColor: '' }) === '#2c2c2e');
check('white brands glow blue', M.glowColor('#ffffff') === '#0a84ff' && M.glowColor('#000000') === '#0a84ff');
check('coloured brands glow their colour', M.glowColor('#d9008d') === '#d9008d');

const raw = [
    { id: 'hotstar', title: 'JioHotstar', iconColor: '#1492ff', icon: 'https://1.2.3.4:3001/resources/a/i.png' },
    { id: 'youtube.leanback.v4', title: 'YouTube', iconColor: '#ffffff' },
    { id: 'com.webos.app.browser', title: 'Web Browser', systemApp: true },
    { id: 'netflix', title: 'Netflix', iconColor: '#ffffff' },
    { id: M.OWN_ID, title: 'Adaptive Home' },
    { title: 'no id' },
];
const apps = M.buildApps(raw);
check('own app and broken entries left out', apps.length === 4 && apps.every((a) => a.id !== M.OWN_ID));
check('tile carries colour and icon', apps[0].color === '#1492ff' && apps[0].icon.indexOf('https://') === 0);

let fav = M.favourites(apps, [], {}, 6);
check('new TV: the TV order without system apps',
    fav.map((a) => a.id).join() === 'hotstar,youtube.leanback.v4,netflix');
fav = M.favourites(apps, ['netflix'], { 'youtube.leanback.v4': 3, 'com.webos.app.browser': 5 }, 6);
check('pins, then most used, then the TV order',
    fav.map((a) => a.id).join() === 'netflix,com.webos.app.browser,youtube.leanback.v4,hotstar');
check('favourites capped', M.favourites(apps, [], {}, 2).length === 2);
check('pins of removed apps ignored', M.favourites(apps, ['gone'], {}, 6)[0].id === 'hotstar');

const inputs = M.buildInputs([
    { id: 'HDMI_1', label: 'HDMI 1', connected: false, devices: ['PlayStation 5'] },
    { id: 'HDMI_2', label: 'HDMI 2', connected: true, devices: [] },
]);
check('input named after its device', inputs[0].title === 'PlayStation 5' && inputs[0].label === 'HDMI 1');
check('connected input is live', inputs[1].live && !inputs[0].live);

// --- the remote's arrows ----------------------------------------------------

// Row 1: three tiles; row 2: a grid of four, offset; row 3: one tile far left.
const box = (left, top) => ({ left: left, top: top, width: 100, height: 60 });
const rects = [box(0, 0), box(120, 0), box(240, 0), box(30, 120), box(150, 120), box(270, 120),
    box(390, 120), box(0, 240)];
check('right moves along the row', M.pickNext(rects[0], rects, 'right') === 1);
check('right at the row end stays', M.pickNext(rects[2], rects, 'right') === -1);
check('left at the row start stays', M.pickNext(rects[0], rects, 'left') === -1);
check('down goes to the tile below', M.pickNext(rects[1], rects, 'down') === 4);
check('down from the far end of a row lands near it', M.pickNext(rects[6], rects, 'down') === 7);
check('up from a short row goes to the nearest above', M.pickNext(rects[7], rects, 'up') === 3);
check('up from the first row stays', M.pickNext(rects[0], rects, 'up') === -1);
check('down skips nothing', M.pickNext(rects[2], rects, 'down') === 5);

check('greeting', M.greeting(8) === 'Good morning' && M.greeting(20) === 'Good evening'
    && M.greeting(2) === 'Good night');
check('weather text', M.weatherText(0) === 'Clear' && M.weatherText(63) === 'Rain' && M.weatherText(95) === 'Thunderstorm');

// --- WebSocket frames -------------------------------------------------------

function serverFrame(text, opcode, fin) {
    const payload = Buffer.from(text);
    const head = payload.length < 126 ? Buffer.from([(fin === false ? 0 : 0x80) | opcode, payload.length])
        : Buffer.from([(fin === false ? 0 : 0x80) | opcode, 126, payload.length >> 8, payload.length & 255]);
    return Buffer.concat([head, payload]);
}

function unmask(frame) {
    const decoded = ssap.decodeFrames(frame).frames[0];
    return decoded && decoded.payload.toString();
}

check('client frames are masked', (ssap.encodeFrame('hi')[1] & 0x80) !== 0);
check('short frame round trip', unmask(ssap.encodeFrame('{"a":1}')) === '{"a":1}');
const medium = 'x'.repeat(300);
check('16-bit length round trip', unmask(ssap.encodeFrame(medium)) === medium);
const large = 'y'.repeat(70000);
check('64-bit length round trip', unmask(ssap.encodeFrame(large)) === large);

const two = Buffer.concat([serverFrame('one', 1), serverFrame('two', 1)]);
let out = ssap.decodeFrames(two.slice(0, two.length - 2));
check('a split frame waits', out.frames.length === 1 && out.rest.length === 3);
out = ssap.decodeFrames(Buffer.concat([out.rest, two.slice(two.length - 2)]));
check('the rest completes it', out.frames.length === 1 && out.frames[0].payload.toString() === 'two');
out = ssap.decodeFrames(serverFrame('z'.repeat(200), 1).slice(0, 3));
check('a split 16-bit header waits', out.frames.length === 0 && out.rest.length === 3);
out = ssap.decodeFrames(Buffer.concat([serverFrame('{"a":', 1, false), serverFrame('1}', 0)]));
check('fragments come apart as frames', out.frames.length === 2 && !out.frames[0].fin && out.frames[1].opcode === 0);

ssap.fetchIcon('https://example.com/x.png').then(() => check('icon fetch refuses other hosts', false),
    () => {}).then(finish);

// --- the package ------------------------------------------------------------

function finish() {
    const info = JSON.parse(fs.readFileSync(path.join(root, 'app', 'appinfo.json')));
    const services = JSON.parse(fs.readFileSync(path.join(root, 'service', 'services.json')));
    const pkg = JSON.parse(fs.readFileSync(path.join(root, 'service', 'package.json')));
    check('app id matches the page', info.id === M.OWN_ID);
    check('service id starts with the app id', services.id.indexOf(info.id + '.') === 0);
    check('service names agree', pkg.name === services.id && services.services[0].name === services.id);
    const home = fs.readFileSync(path.join(root, 'app', 'home.js'), 'utf8');
    check('page calls its own service', home.indexOf("'luna://" + services.id + "/'") >= 0);
    ['icon', 'largeIcon', 'main'].forEach((key) => {
        check('appinfo ' + key + ' exists', fs.existsSync(path.join(root, 'app', info[key])));
    });
    const service = fs.readFileSync(path.join(root, 'service', 'service.js'), 'utf8');
    ['home', 'icon', 'launch', 'input', 'power'].forEach((name) => {
        check('service answers ' + name, new RegExp("(method|register)\\('" + name + "'").test(service));
    });
    check('socket requests retry once', service.indexOf('withConnection') >= 0 &&
        service.indexOf('error.connection') >= 0);
    check('page service calls time out', home.indexOf('SERVICE_WAIT_MS') >= 0);
    check('relaunch returns straight to full screen', info.handlesRelaunch === false);
    check('desktop wake watcher exists', fs.existsSync(path.join(root, 'auto_launch.py')));
    const unit = fs.readFileSync(path.join(root, '..', '..', 'services',
        'adaptive-tv-home-watch.service'), 'utf8');
    check('wake watcher has a restartable user service', unit.indexOf('auto_launch.py') >= 0 &&
        unit.indexOf('Restart=on-failure') >= 0);
    (home.match(/call\('([a-z]+)'/g) || []).forEach((use) => {
        const name = use.slice(6, -1);
        check('page calls a real method: ' + name, new RegExp("(method|register)\\('" + name + "'").test(service));
    });

    if (failures.length) {
        console.log(failures.length + ' check(s) failed');
        process.exit(1);
    }
    console.log('Adaptive Home: all checks passed');
}
