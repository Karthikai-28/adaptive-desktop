#!/usr/bin/env node

const { compareMessages, compareGroups, ArrivalJournal } = require(
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

const journal = new ArrivalJournal();
journal.record('app:mail', 'mail-1');
const mark = journal.sequence;
journal.record('app:chat', 'chat-1');
journal.record('app:chat', 'chat-2');
const duplicate = journal.record('app:chat', 'chat-2');
check(journal.summarySince(mark).count === 2 && journal.summarySince(mark).apps === 1,
    'focus ledger counts arrivals after the mark even without live actors');
check(!duplicate.added, 'focus ledger de-duplicates notifications adopted after restart');
const restored = new ArrivalJournal(journal.snapshot());
restored.record('app:mail', 'mail-2');
check(restored.summarySince(mark).count === 3 && restored.summarySince(mark).apps === 2,
    'focus ledger and sequence survive a shell restart');

if (failed)
    process.exit(1);
