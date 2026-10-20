// Pure ordering helpers for Adaptive notification groups.
//
// Kept free of GJS imports so the ordering contract can be exercised by the
// headless verification suite as well as by GNOME Shell.

/* exported compareMessages, compareGroups, ArrivalJournal */
/* global module */

function compareMessages(a, b) {
    if (!!a.urgent !== !!b.urgent)
        return a.urgent ? -1 : 1;
    return (b.sequence || 0) - (a.sequence || 0);
}

function compareGroups(a, b) {
    if (!!a.urgent !== !!b.urgent)
        return a.urgent ? -1 : 1;
    return (b.latestSequence || 0) - (a.latestSequence || 0);
}

// A small durable arrival ledger for Focus summaries. Keeping arrivals apart
// from the actors currently in the tray means a notification still counts when
// its application withdraws it before the focus session ends. Fingerprints
// avoid counting actors adopted again after a Shell restart twice.
var ArrivalJournal = class ArrivalJournal {
    constructor(saved = null, limit = 2048) {
        this._limit = Math.max(128, Number(limit) || 2048);
        this.sequence = Math.max(0, Number(saved && saved.sequence) || 0);
        this._entries = Array.isArray(saved && saved.entries)
            ? saved.entries.filter(entry => entry && Number(entry.sequence) > 0 && entry.appKey)
                .map(entry => ({
                    sequence: Number(entry.sequence),
                    appKey: String(entry.appKey),
                    fingerprint: String(entry.fingerprint || ''),
                })).slice(-this._limit)
            : [];
        for (const entry of this._entries)
            this.sequence = Math.max(this.sequence, entry.sequence);
        this._reindex();
    }

    _reindex() {
        this._fingerprints = new Map();
        for (const entry of this._entries) {
            if (entry.fingerprint)
                this._fingerprints.set(entry.fingerprint, entry.sequence);
        }
    }

    record(appKey, fingerprint = '') {
        const known = fingerprint ? this._fingerprints.get(fingerprint) : 0;
        if (known)
            return { sequence: known, added: false };

        const entry = {
            sequence: ++this.sequence,
            appKey: String(appKey || 'unknown'),
            fingerprint: String(fingerprint || ''),
        };
        this._entries.push(entry);
        if (entry.fingerprint)
            this._fingerprints.set(entry.fingerprint, entry.sequence);
        if (this._entries.length > this._limit) {
            this._entries.splice(0, this._entries.length - this._limit);
            this._reindex();
        }
        return { sequence: entry.sequence, added: true };
    }

    summarySince(sequence) {
        const apps = new Set();
        let count = 0;
        for (const entry of this._entries) {
            if (entry.sequence <= sequence)
                continue;
            count++;
            apps.add(entry.appKey);
        }
        return { count, apps: apps.size };
    }

    snapshot() {
        return { sequence: this.sequence, entries: this._entries.slice() };
    }
};

if (typeof module !== 'undefined' && module.exports)
    module.exports = { compareMessages, compareGroups, ArrivalJournal };
