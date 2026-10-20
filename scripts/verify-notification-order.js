#!/usr/bin/env node

const { compareMessages, compareGroups } = require(
    '../shell/adaptive-shell@local/notificationOrder.js');

let failed = 0;
function check(value, message) {
    if (value)
        console.log(`OK   notifications: ${message}`);
    else {
        console.error(`FAIL notifications: ${message}`);
        failed++;
    }
}

const messages = [
    { name: 'old', urgent: false, sequence: 1 },
    { name: 'critical', urgent: true, sequence: 2 },
    { name: 'new', urgent: false, sequence: 3 },
].sort(compareMessages);
check(messages.map(item => item.name).join(',') === 'critical,new,old',
    'critical first, then newest normal message');
check(messages.slice(0, 2).some(item => item.name === 'new'),
    'collapsed preview includes the newest normal message');

const groups = [
    { name: 'A', urgent: false, latestSequence: 1 },
    { name: 'B', urgent: false, latestSequence: 2 },
    { name: 'A-again', urgent: false, latestSequence: 3 },
    { name: 'critical', urgent: true, latestSequence: 1 },
].sort(compareGroups);
check(groups.map(item => item.name).join(',') === 'critical,A-again,B,A',
    'urgent group first and normal groups ordered by latest activity');

if (failed)
    process.exit(1);
