// Adaptive Home: the launcher page. Draws the rows, moves focus with the
// remote (or the Magic Remote's pointer) and asks this app's service on the
// TV to open apps, switch inputs and turn the screen off. Nothing here talks
// to another machine except Open-Meteo, for the weather.

(function () {
    'use strict';

    var M = window.HomeModel;
    var SERVICE = 'luna://com.karthi.adaptivetv.service/';
    var SETTINGS_APP = 'com.palm.app.settings';
    var KEYS = { 37: 'left', 38: 'up', 39: 'right', 40: 'down', 13: 'ok', 461: 'back', 27: 'back',
        8: 'back', 406: 'pin', 80: 'pin' };
    var ICON_WORKERS = 4;

    var CONTROL_ICONS = {
        settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
        screenOff: '<rect x="2" y="4" width="20" height="13" rx="2"/><path d="M8 21h8M12 17v4M4 6l16 9"/>',
        off: '<path d="M18.4 6.6a9 9 0 1 1-12.8 0"/><path d="M12 2v10"/>',
        weather: '<path d="M17.5 19H8a5 5 0 1 1 1.4-9.8A6 6 0 0 1 21 11.5 3.8 3.8 0 0 1 17.5 19z"/>',
        refresh: '<path d="M21 12a9 9 0 1 1-2.6-6.4L21 8"/><path d="M21 3v5h-5"/>',
    };
    var CONTROLS = [
        { kind: 'control', id: 'settings', title: 'TV settings', meta: 'Picture, sound, network and more' },
        { kind: 'control', id: 'screenOff', title: 'Screen off', meta: 'Sound keeps playing; any key wakes the screen' },
        { kind: 'control', id: 'off', title: 'Turn off', meta: 'Press OK twice' },
        { kind: 'control', id: 'weather', title: 'Weather', meta: 'Choose the city for the weather' },
        { kind: 'control', id: 'refresh', title: 'Refresh', meta: 'Read the TV\'s apps and inputs again' },
    ];

    var state = {
        key: load('key', null), apps: load('apps', []), inputs: load('inputs', []),
        pins: load('pins', []), counts: load('counts', {}), place: load('place', null),
    };
    var tiles = [];          // [{el, item, section}]
    var focused = null;
    var focusKey = null;
    var armedOff = 0;
    var bridges = [];
    var iconQueue = [];
    var iconBusy = 0;
    var ambientFront = 'a';

    // --- storage ---------------------------------------------------------------

    function load(name, fallback) {
        try {
            var text = localStorage.getItem('home.' + name);
            return text === null ? fallback : JSON.parse(text);
        } catch (error) {
            return fallback;
        }
    }

    function save(name, value) {
        try {
            localStorage.setItem('home.' + name, JSON.stringify(value));
        } catch (error) { /* full or blocked: the page still works */ }
    }

    // --- this app's service --------------------------------------------------

    function call(method, params) {
        return new Promise(function (resolve, reject) {
            if (typeof PalmServiceBridge === 'undefined') {
                reject(new Error('Adaptive Home runs on the TV'));
                return;
            }
            var bridge = new PalmServiceBridge();
            bridges.push(bridge);   // a collected bridge never answers
            bridge.onservicecallback = function (text) {
                bridges.splice(bridges.indexOf(bridge), 1);
                var reply;
                try {
                    reply = JSON.parse(text);
                } catch (error) {
                    reject(error);
                    return;
                }
                if (reply.key && reply.key !== state.key) {
                    state.key = reply.key;
                    save('key', state.key);
                }
                if (reply.returnValue) resolve(reply);
                else reject(new Error(reply.errorText || 'The TV said no'));
            };
            var args = params || {};
            args.key = state.key;
            bridge.call(SERVICE + method, JSON.stringify(args));
        });
    }

    // webOSRelaunch and visibilitychange often arrive together: one read.
    var refreshing = null;
    function refresh() {
        if (!refreshing) {
            refreshing = readHome().then(function () { refreshing = null; });
        }
        return refreshing;
    }

    function readHome() {
        var pairing = document.getElementById('pairing');
        if (!state.key) pairing.classList.add('on');
        return call('home').then(function (reply) {
            pairing.classList.remove('on');
            state.apps = reply.apps || [];
            state.inputs = reply.inputs || [];
            save('apps', state.apps);
            save('inputs', state.inputs);
            render();
        }, function (error) {
            pairing.classList.remove('on');
            toast(error.message);
        });
    }

    // --- icons ----------------------------------------------------------------

    function iconFor(url, done) {
        var cached = load('icon:' + url, null);
        if (cached) {
            done(cached);
            return;
        }
        iconQueue.push({ url: url, done: done });
        pumpIcons();
    }

    function pumpIcons() {
        while (iconBusy < ICON_WORKERS && iconQueue.length) {
            var job = iconQueue.shift();
            iconBusy++;
            (function (job) {
                call('icon', { url: job.url }).then(function (reply) {
                    save('icon:' + job.url, reply.data);
                    job.done(reply.data);
                }, function () { /* the monogram stays */ }).then(function () {
                    iconBusy--;
                    pumpIcons();
                });
            })(job);
        }
    }

    // Full-bleed icons fill the tile; transparent glyphs sit small on glass.
    var glyphs = {};
    function isGlyph(data, done) {
        if (data in glyphs) {
            done(glyphs[data]);
            return;
        }
        var image = new Image();
        image.onload = function () {
            var canvas = document.createElement('canvas');
            canvas.width = image.width;
            canvas.height = image.height;
            var context = canvas.getContext('2d');
            context.drawImage(image, 0, 0);
            var edges = [[1, image.height >> 1], [image.width >> 1, 1],
                [image.width - 2, image.height >> 1], [image.width >> 1, image.height - 2]];
            var clear = edges.filter(function (point) {
                return context.getImageData(point[0], point[1], 1, 1).data[3] < 40;
            }).length;
            glyphs[data] = clear >= 3;
            done(glyphs[data]);
        };
        image.onerror = function () { done(false); };
        image.src = data;
    }

    // --- drawing --------------------------------------------------------------

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text) node.textContent = text;
        return node;
    }

    function render() {
        // Before the first list there is nothing worth focusing.
        if (!state.apps.length) return;
        var apps = M.buildApps(state.apps);
        var favourites = M.favourites(apps, state.pins, state.counts);
        var inputs = M.buildInputs(state.inputs);
        var scroller = document.getElementById('scroller');
        scroller.innerHTML = '';
        tiles = [];
        section(scroller, 'favourites', 'Favourites', favourites, state.pins.length ? '' : 'Blue button pins an app here');
        if (inputs.length) section(scroller, 'inputs', 'Inputs', inputs, '');
        section(scroller, 'apps', 'All apps', apps, apps.length + ' on this TV');
        section(scroller, 'controls', 'TV', CONTROLS, '');
        var again = tiles.filter(function (tile) { return tileKey(tile) === focusKey; })[0];
        focus(again || tiles[0], true);
    }

    function section(parent, id, title, items, note) {
        var box = el('section', 'section');
        var heading = el('h2', '', title);
        if (note) heading.appendChild(el('small', '', note));
        box.appendChild(heading);
        var track = el('div', 'track');
        box.appendChild(track);
        parent.appendChild(box);
        if (!items.length) track.appendChild(el('div', 'empty', 'Nothing here yet'));
        items.forEach(function (item) {
            var tile = { el: makeTile(item), item: item, section: id };
            tiles.push(tile);
            track.appendChild(tile.el);
            tile.el.addEventListener('mouseenter', function () { focus(tile, false); });
            tile.el.addEventListener('click', function () { focus(tile, false); activate(tile); });
        });
    }

    function makeTile(item) {
        var node = el('div', 'tile');
        var face = el('div', 'face');
        face.style.setProperty('--c', item.color || '');
        node.style.setProperty('--g', hexAlpha(item.glow || '#0a84ff', 0.75));
        if (item.kind === 'control') {
            face.innerHTML = '<svg viewBox="0 0 24 24">' + CONTROL_ICONS[item.id] + '</svg>';
            face.classList.add('glyph');
        } else {
            face.appendChild(el('div', 'monogram', item.title.charAt(0)));
            if (item.icon) {
                iconFor(item.icon, function (data) {
                    item.iconData = data;
                    isGlyph(data, function (glyph) {
                        item.glyph = glyph || item.kind === 'input';
                        face.classList.toggle('glyph', item.glyph);
                        var image = el('img');
                        image.onload = function () {
                            image.classList.add('ready');
                            var monogram = face.querySelector('.monogram');
                            if (monogram) monogram.remove();
                        };
                        image.src = data;
                        face.appendChild(image);
                        if (focused && focused.item === item) hero(focused, false);
                    });
                });
            }
        }
        if (item.kind === 'input' && item.live) {
            var badge = el('div', 'badge');
            badge.appendChild(el('i', 'dot'));
            badge.appendChild(document.createTextNode(item.label));
            face.appendChild(badge);
        }
        if (item.kind === 'app' && state.pins.indexOf(item.id) >= 0) face.appendChild(el('i', 'pin'));
        node.appendChild(face);
        node.appendChild(el('div', 'name', item.title));
        return node;
    }

    function hexAlpha(hex, alpha) {
        var n = parseInt(hex.slice(1), 16);
        return 'rgba(' + (n >> 16) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + alpha + ')';
    }

    // --- focus ----------------------------------------------------------------

    function tileKey(tile) {
        return tile.section + ':' + tile.item.kind + ':' + tile.item.id;
    }

    function focus(tile, scroll) {
        if (!tile) return;
        var changed = focused !== tile;
        if (focused) focused.el.classList.remove('focus');
        focused = tile;
        focusKey = tileKey(tile);
        tile.el.classList.add('focus');
        if (scroll !== false) keepInView(tile);
        if (changed) {
            armedOff = 0;
            hero(tile, true);
        }
    }

    function keepInView(tile) {
        var scroller = document.getElementById('scroller');
        var rows = document.getElementById('rows');
        var sectionBox = tile.el.parentNode.parentNode;
        var padding = parseFloat(getComputedStyle(scroller).paddingTop);
        // The focused section's heading where the first one's sits; deep in
        // a grid, the focused line there instead.
        var target = sectionBox.offsetTop - padding;
        if (tile.el.offsetTop - sectionBox.offsetTop > rows.clientHeight * 0.3) {
            target = tile.el.offsetTop - padding;
        }
        var limit = Math.max(0, scroller.scrollHeight - rows.clientHeight);
        target = Math.max(0, Math.min(target, limit));
        scroller.style.transform = 'translateY(' + (-target) + 'px)';
    }

    function move(direction) {
        if (!focused) return;
        var from = rectOf(focused.el);
        var rects = tiles.map(function (tile) { return rectOf(tile.el); });
        var index = M.pickNext(from, rects, direction);
        if (index >= 0) focus(tiles[index], true);
    }

    // Layout positions, unaffected by the scroll transform or the focus scale.
    function rectOf(node) {
        var left = 0;
        var top = 0;
        for (var at = node; at && at.id !== 'rows'; at = at.offsetParent) {
            left += at.offsetLeft;
            top += at.offsetTop;
        }
        return { left: left, top: top, width: node.offsetWidth, height: node.offsetHeight };
    }

    function hero(tile, animate) {
        var item = tile.item;
        var text = document.querySelector('.hero-text');
        var art = document.getElementById('hero-art');
        var face = document.getElementById('art-face');
        document.getElementById('hero-title').textContent = item.kind === 'app' ? item.fullTitle : item.title;
        document.getElementById('hero-eyebrow').textContent = eyebrow(tile);
        document.getElementById('hero-meta').textContent = meta(item);
        var pinnable = item.kind === 'app';
        document.getElementById('hint-pin').style.visibility = pinnable ? 'visible' : 'hidden';
        document.getElementById('hint-pin-text').textContent =
            state.pins.indexOf(item.id) >= 0 ? 'Unpin from favourites' : 'Pin to favourites';
        face.style.backgroundColor = item.kind === 'app' && !item.glyph ? item.color : '';
        face.style.backgroundImage = item.iconData ? 'url(' + item.iconData + ')' : 'none';
        face.innerHTML = item.kind === 'control' ? '<svg viewBox="0 0 24 24" style="width:40%;height:40%;margin:30%;fill:none;stroke:#f5f5f7;stroke-width:1.4;stroke-linecap:round;stroke-linejoin:round">' + CONTROL_ICONS[item.id] + '</svg>' : '';
        face.classList.toggle('glyph', !!item.glyph);
        face.style.setProperty('--glow', hexAlpha(item.glow || '#0a84ff', 0.55));
        ambient(item.glow || '#0a84ff');
        if (animate) {
            [text, art].forEach(function (node) {
                node.classList.remove('swap');
                void node.offsetWidth;
                node.classList.add('swap');
            });
        }
    }

    function eyebrow(tile) {
        if (tile.item.kind === 'input') return 'Input · ' + tile.item.label;
        if (tile.item.kind === 'control') return 'TV';
        if (tile.section === 'favourites') return state.pins.indexOf(tile.item.id) >= 0 ? 'Pinned' : 'Favourite';
        return tile.item.system ? 'LG app' : 'App';
    }

    function meta(item) {
        if (item.kind === 'control') return item.meta;
        if (item.kind === 'input') return item.live ? 'Connected' : 'Nothing connected';
        var opened = state.counts[item.id] || 0;
        return opened ? 'Opened ' + opened + (opened === 1 ? ' time' : ' times') + ' from here' : 'Not opened from here yet';
    }

    // Two layers, crossfaded, so the room changes colour without a jump.
    function ambient(color) {
        var next = ambientFront === 'a' ? 'b' : 'a';
        var layer = document.getElementById('ambient-' + next);
        layer.style.setProperty('--a1', hexAlpha(color, 0.9));
        layer.style.setProperty('--a2', hexAlpha(color, 0.45));
        layer.classList.add('on');
        document.getElementById('ambient-' + ambientFront).classList.remove('on');
        ambientFront = next;
    }

    // --- actions --------------------------------------------------------------

    function activate(tile) {
        var item = tile.item;
        tile.el.classList.add('press');
        setTimeout(function () { tile.el.classList.remove('press'); }, 160);
        if (item.kind === 'app') {
            state.counts[item.id] = (state.counts[item.id] || 0) + 1;
            save('counts', state.counts);
            launching(item);
            call('launch', { id: item.id, params: item.params }).catch(function (error) {
                launched();
                toast(error.message);
            });
        } else if (item.kind === 'input') {
            launching(item);
            call('input', { id: item.id }).catch(function (error) {
                launched();
                toast(error.message);
            });
        } else {
            control(item.id);
        }
    }

    function control(id) {
        if (id === 'settings') {
            call('launch', { id: SETTINGS_APP }).catch(function (error) { toast(error.message); });
        } else if (id === 'screenOff') {
            call('power', { what: 'screenOff' }).catch(function (error) { toast(error.message); });
        } else if (id === 'off') {
            if (Date.now() - armedOff < 4000) {
                call('power', { what: 'off' }).catch(function (error) { toast(error.message); });
            } else {
                armedOff = Date.now();
                toast('Press OK again to turn the TV off');
            }
        } else if (id === 'weather') {
            askCity();
        } else if (id === 'refresh') {
            refresh().then(function () { toast('Up to date'); });
        }
    }

    function launching(item) {
        var cover = document.getElementById('launch');
        var icon = document.getElementById('launch-icon');
        cover.style.setProperty('--lc', item.glow || '#0a84ff');
        icon.style.backgroundColor = item.glyph ? '' : item.color;
        icon.style.backgroundImage = item.iconData ? 'url(' + item.iconData + ')' : 'none';
        icon.classList.toggle('glyph', !!item.glyph);
        document.getElementById('launch-text').textContent = 'Opening ' + item.title;
        cover.classList.add('on');
        setTimeout(launched, 2400);
    }

    function launched() {
        document.getElementById('launch').classList.remove('on');
    }

    function togglePin() {
        if (!focused || focused.item.kind !== 'app') return;
        var id = focused.item.id;
        var at = state.pins.indexOf(id);
        if (at >= 0) state.pins.splice(at, 1);
        else state.pins.push(id);
        save('pins', state.pins);
        toast(at >= 0 ? 'Unpinned ' + focused.item.title : 'Pinned ' + focused.item.title);
        render();
    }

    var toastTimer = 0;
    function toast(text) {
        var node = document.getElementById('toast');
        node.textContent = text;
        node.classList.add('on');
        clearTimeout(toastTimer);
        toastTimer = setTimeout(function () { node.classList.remove('on'); }, 3200);
    }

    // --- weather ----------------------------------------------------------------

    function askCity() {
        var overlay = document.getElementById('city');
        var input = document.getElementById('city-input');
        input.value = state.place ? state.place.name : '';
        overlay.classList.add('on');
        setTimeout(function () { input.focus(); }, 50);
    }

    function closeCity() {
        document.getElementById('city').classList.remove('on');
        document.getElementById('city-input').blur();
    }

    function cityChosen(event) {
        event.preventDefault();
        var name = document.getElementById('city-input').value.trim();
        closeCity();
        if (!name) {
            state.place = null;
            save('place', null);
            weather();
            return;
        }
        fetch('https://geocoding-api.open-meteo.com/v1/search?count=1&name=' + encodeURIComponent(name))
            .then(function (reply) { return reply.json(); })
            .then(function (data) {
                var top = (data.results || [])[0];
                if (!top) throw new Error('No place called ' + name);
                state.place = { name: top.name, lat: top.latitude, lon: top.longitude };
                save('place', state.place);
                weather();
            })
            .catch(function (error) { toast(error.message || 'The weather service did not answer'); });
    }

    function weather() {
        var box = document.getElementById('weather');
        if (!state.place) {
            box.innerHTML = '';
            return;
        }
        var place = state.place;
        fetch('https://api.open-meteo.com/v1/forecast?current_weather=true&timezone=auto' +
              '&daily=temperature_2m_max,temperature_2m_min&forecast_days=1' +
              '&latitude=' + place.lat + '&longitude=' + place.lon)
            .then(function (reply) { return reply.json(); })
            .then(function (data) {
                var now = data.current_weather;
                var high = Math.round(data.daily.temperature_2m_max[0]);
                var low = Math.round(data.daily.temperature_2m_min[0]);
                box.innerHTML = '';
                box.appendChild(el('b', '', Math.round(now.temperature) + '°'));
                box.appendChild(document.createTextNode(' ' + M.weatherText(now.weathercode)));
                box.appendChild(el('br'));
                box.appendChild(document.createTextNode(place.name + ' · H ' + high + '° L ' + low + '°'));
            })
            .catch(function () { /* offline: keep what is shown */ });
    }

    // --- clock ------------------------------------------------------------------

    function tick() {
        var now = new Date();
        var pad = function (n) { return (n < 10 ? '0' : '') + n; };
        document.getElementById('clock').textContent = pad(now.getHours()) + ':' + pad(now.getMinutes());
        document.getElementById('date').textContent = now.toLocaleDateString(undefined,
            { weekday: 'long', day: 'numeric', month: 'long' });
        document.getElementById('greeting').textContent = M.greeting(now.getHours());
    }

    // --- keys -------------------------------------------------------------------

    document.addEventListener('keydown', function (event) {
        var action = KEYS[event.keyCode];
        if (document.getElementById('city').classList.contains('on')) {
            if (action === 'back' && event.keyCode !== 8) {
                event.preventDefault();
                closeCity();
            }
            return;
        }
        if (!action) return;
        event.preventDefault();
        if (action === 'ok') {
            if (focused) activate(focused);
        } else if (action === 'pin') {
            togglePin();
        } else if (action === 'back') {
            launched();
            focus(tiles[0], true);
        } else {
            move(action);
        }
    });

    document.getElementById('city-form').addEventListener('submit', cityChosen);
    // Coming back from an app: the lists may have changed (an app installed).
    document.addEventListener('webOSRelaunch', function () {
        launched();
        refresh();
    });
    document.addEventListener('visibilitychange', function () {
        if (!document.hidden) {
            launched();
            refresh();
        }
    });

    tick();
    setInterval(tick, 1000);
    weather();
    setInterval(weather, 15 * 60 * 1000);
    render();
    refresh();
})();
