// Pure ordering helpers for Adaptive notification groups.
//
// Kept free of GJS imports so the ordering contract can be exercised by the
// headless verification suite as well as by GNOME Shell.

/* exported compareMessages, compareGroups */
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

if (typeof module !== 'undefined' && module.exports)
    module.exports = { compareMessages, compareGroups };
