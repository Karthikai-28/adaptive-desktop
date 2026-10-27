// Adaptive Home's service on the TV: what the launcher page cannot do itself.
//
//   home     the TV's apps (in the TV's own order) and its inputs
//   icon     one app icon as a data: URL
//   launch   open an app            input   switch to an input
//   power    "screenOff" or "off"
//
// Every call takes the client key the page keeps ({key}) and answers with the
// key in use, which is new after the TV's one-time "Allow?" prompt.

'use strict';

const Service = require('webos-service');
const ssap = require('./ssap');

const service = new Service('com.karthi.adaptivetv.service');
const POWER = {
    screenOff: 'ssap://com.webos.service.tvpower/power/turnOffScreen',
    off: 'ssap://system/turnOff',
};

let tv = null;
let opening = null;
const icons = {};

function connected(key) {
    if (tv && tv.ready && (!key || key === tv.key)) return Promise.resolve(tv);
    if (opening) return opening;
    if (tv) tv.close();
    const next = new ssap.Tv('127.0.0.1', 3001);
    opening = next.open(key || null).then(() => {
        tv = next;
        opening = null;
        return tv;
    }, (error) => {
        opening = null;
        throw error;
    });
    return opening;
}

function reset(link) {
    if (link) link.close();
    if (tv === link) tv = null;
}

// The TV sometimes closes its local control socket while an app is hidden or
// while waking. Re-open it and replay one idempotent request instead of making
// the page show a transient failure.
function withConnection(key, work, retried) {
    return connected(key).then((link) => work(link).catch((error) => {
        if (retried || !error.connection) throw error;
        reset(link);
        return new Promise((resolve) => setTimeout(resolve, 180))
            .then(() => withConnection(key, work, true));
    }), (error) => {
        if (retried || !error.connection) throw error;
        return new Promise((resolve) => setTimeout(resolve, 180))
            .then(() => withConnection(key, work, true));
    });
}

function answer(message, work) {
    work.then((out) => message.respond(Object.assign({ returnValue: true, key: tv && tv.key }, out)),
        (error) => message.respond({ returnValue: false, errorText: String((error && error.message) || error) }));
}

function method(name, work) {
    service.register(name, (message) => {
        const args = message.payload || {};
        answer(message, withConnection(args.key, (link) => work(link, args), false));
    });
}

method('home', (link) => Promise.all([
    link.request('ssap://com.webos.applicationManager/listLaunchPoints'),
    link.request('ssap://tv/getExternalInputList').catch(() => ({ devices: [] })),
]).then((replies) => ({
    apps: (replies[0].launchPoints || []).map((point) => ({
        id: point.id, title: point.title, iconColor: point.iconColor, bgColor: point.bgColor,
        icon: point.largeIcon || point.icon, smallIcon: point.icon, systemApp: !!point.systemApp,
        params: point.params,
    })),
    inputs: (replies[1].devices || []).map((device) => ({
        id: device.id, label: device.label, connected: !!device.connected,
        signal: !!device.hdmiSignalExist, icon: device.icon, appId: device.appId,
        devices: (device.subList || []).map((sub) => sub.osdName).filter(Boolean),
    })),
})));

method('launch', (link, args) => link.request('ssap://system.launcher/launch',
    args.params ? { id: args.id, params: args.params } : { id: args.id }).then(() => ({})));

method('input', (link, args) => link.request('ssap://tv/switchInput', { inputId: args.id })
    .then(() => ({})));

method('power', (link, args) => {
    if (!POWER[args.what]) return Promise.reject(new Error('Unknown power action'));
    return link.request(POWER[args.what]).then(() => ({}));
});

// Icons need no registration, only the TV's certificate skipped.
service.register('icon', (message) => {
    const url = (message.payload || {}).url;
    if (!icons[url]) {
        icons[url] = ssap.fetchIcon(url);
        icons[url].catch(() => delete icons[url]);
    }
    answer(message, icons[url].then((data) => ({ data: data })));
});
