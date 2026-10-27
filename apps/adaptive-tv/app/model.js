// Adaptive Home's logic that needs no TV: tiles from the TV's lists, the
// favourites row, and which tile the remote's arrows move to. Loaded as a
// plain script on the TV and with require() by scripts/verify-tv-home.js.

(function (root) {
    'use strict';

    var OWN_ID = 'com.karthi.adaptivetv';
    var FAVOURITES = 6;
    var SURFACE = '#2c2c2e';

    // "JioCinema- Bigg Boss & Cricket" -> "JioCinema"
    function shortTitle(title) {
        var text = String(title || '').trim();
        var head = text.split(/\s*[-:|]\s+/)[0];
        return head || text;
    }

    function hexColor(value) {
        var text = String(value || '').trim().toLowerCase();
        if (text === 'white') return '#ffffff';
        if (text === 'black') return '#000000';
        if (/^#[0-9a-f]{6}$/.test(text)) return text;
        if (/^#[0-9a-f]{3}$/.test(text)) {
            return '#' + text[1] + text[1] + text[2] + text[2] + text[3] + text[3];
        }
        return null;
    }

    // The colour behind an app's icon: its own, or the dark surface.
    function tileColor(app) {
        return hexColor(app.iconColor) || hexColor(app.bgColor) || SURFACE;
    }

    // Relative luminance, 0 (black) to 1 (white).
    function luminance(hex) {
        var parts = [1, 3, 5].map(function (at) {
            var c = parseInt(hex.substr(at, 2), 16) / 255;
            return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
        });
        return 0.2126 * parts[0] + 0.7152 * parts[1] + 0.0722 * parts[2];
    }

    // The glow behind a focused tile: white and black brands glow in the accent.
    function glowColor(hex) {
        var light = luminance(hex);
        return light > 0.8 || light < 0.01 ? '#0a84ff' : hex;
    }

    function buildApps(apps) {
        return (apps || []).filter(function (app) {
            return app && app.id && app.id !== OWN_ID;
        }).map(function (app) {
            var color = tileColor(app);
            return {
                kind: 'app', id: app.id, title: shortTitle(app.title || app.id),
                fullTitle: app.title || app.id, color: color, glow: glowColor(color),
                icon: app.icon || app.smallIcon || null, system: !!app.systemApp,
                params: app.params || null,
            };
        });
    }

    // Pinned apps first (in pin order), then the most opened, then the rest of
    // the TV's own order, which is how its owner arranged the LG home bar.
    function favourites(apps, pins, counts, size) {
        var limit = size || FAVOURITES;
        var byId = {};
        apps.forEach(function (app) { byId[app.id] = app; });
        var out = (pins || []).filter(function (id) { return byId[id]; }).map(function (id) {
            return byId[id];
        });
        var used = apps.filter(function (app) {
            return (counts || {})[app.id] && out.indexOf(app) < 0;
        }).sort(function (a, b) { return counts[b.id] - counts[a.id]; });
        out = out.concat(used);
        apps.forEach(function (app) {
            if (!app.system && out.indexOf(app) < 0) out.push(app);
        });
        return out.slice(0, limit);
    }

    function buildInputs(inputs) {
        return (inputs || []).filter(function (input) { return input && input.id; }).map(function (input) {
            var device = (input.devices || [])[0];
            return {
                kind: 'input', id: input.id, title: device || input.label || input.id,
                label: input.label || input.id, live: !!(input.connected || input.signal),
                icon: input.icon || null, color: SURFACE, glow: '#0a84ff',
            };
        });
    }

    // From the focused rectangle, the best rectangle in a direction, by index;
    // -1 when there is none. Rectangles are {left, top, width, height}.
    function pickNext(from, rects, direction) {
        var best = -1;
        var bestScore = Infinity;
        var fx = from.left + from.width / 2;
        var fy = from.top + from.height / 2;
        rects.forEach(function (rect, index) {
            var cx = rect.left + rect.width / 2;
            var cy = rect.top + rect.height / 2;
            var along, across;
            if (direction === 'left' || direction === 'right') {
                along = direction === 'right' ? rect.left - (from.left + from.width) : from.left - (rect.left + rect.width);
                if ((direction === 'right' ? cx - fx : fx - cx) <= 1) return;
                across = gap(from.top, from.top + from.height, rect.top, rect.top + rect.height);
                // Sideways stays in the row: at its end, nothing happens.
                if (across > 0) return;
            } else {
                along = direction === 'down' ? rect.top - (from.top + from.height) : from.top - (rect.top + rect.height);
                if ((direction === 'down' ? cy - fy : fy - cy) <= 1) return;
                across = gap(from.left, from.left + from.width, rect.left, rect.left + rect.width);
            }
            // The next row, then the tile most in line with this one.
            var score = Math.max(0, along) * 2 + across * 3 + Math.abs(direction === 'up' || direction === 'down' ? cx - fx : cy - fy) / 4;
            if (score < bestScore) {
                bestScore = score;
                best = index;
            }
        });
        return best;
    }

    function gap(a0, a1, b0, b1) {
        if (b1 < a0) return a0 - b1;
        if (b0 > a1) return b0 - a1;
        return 0;
    }

    function greeting(hour) {
        if (hour < 5) return 'Good night';
        if (hour < 12) return 'Good morning';
        if (hour < 17) return 'Good afternoon';
        return 'Good evening';
    }

    // WMO weather codes, as Open-Meteo reports them.
    function weatherText(code) {
        if (code === 0) return 'Clear';
        if (code <= 2) return 'Partly cloudy';
        if (code === 3) return 'Cloudy';
        if (code === 45 || code === 48) return 'Fog';
        if (code >= 51 && code <= 57) return 'Drizzle';
        if (code >= 61 && code <= 67) return code === 65 ? 'Heavy rain' : 'Rain';
        if (code >= 71 && code <= 77) return 'Snow';
        if (code >= 80 && code <= 82) return 'Showers';
        if (code >= 95) return 'Thunderstorm';
        return '';
    }

    var api = {
        OWN_ID: OWN_ID, shortTitle: shortTitle, hexColor: hexColor, tileColor: tileColor,
        glowColor: glowColor, buildApps: buildApps, favourites: favourites,
        buildInputs: buildInputs, pickNext: pickNext, greeting: greeting, weatherText: weatherText,
    };
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    else root.HomeModel = api;
})(this);
