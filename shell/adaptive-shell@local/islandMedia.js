// Dynamic Island Now-Playing Media Provider
//
// 100% event-driven via Linux MPRIS D-Bus signals (org.mpris.MediaPlayer2).
// Zero polling loops; consumes 0.0% CPU when idle.
//
// Signals arrive from a player's unique name (":1.234"), while players are
// listed under their well-known name (org.mpris.MediaPlayer2.spotify); the
// owner map joins the two. MPRIS never signals Position as it changes, so the
// provider reads it on status changes and Seeked, and extrapolates between.

/* exported IslandMediaProvider */
/* global module */

let Gio, GLib;
try {
    Gio = imports.gi.Gio;
    GLib = imports.gi.GLib;
} catch (e) {
    // Headless test harness
}

const MPRIS_PREFIX = 'org.mpris.MediaPlayer2.';
const MPRIS_PATH = '/org/mpris/MediaPlayer2';
const PLAYER_IFACE = 'org.mpris.MediaPlayer2.Player';

function _emptyTrack() {
    return {
        title: '',
        artist: '',
        album: '',
        artUrl: '',
        playbackStatus: 'Stopped',
        playerName: '',
        playerBusName: '',
        identity: '',
        isPlaying: false,
        lengthUs: 0,
        canSeek: false,
        canGoNext: false,
        canGoPrevious: false,
    };
}

// GLib.Variant values from a{sv} are still variants after deep_unpack();
// tests pass plain values. Accept both.
function _plain(value) {
    if (value && typeof value === 'object' && typeof value.recursiveUnpack === 'function')
        return value.recursiveUnpack();
    return value;
}

function _plainDict(dict) {
    const out = {};
    for (const [k, v] of Object.entries(dict || {}))
        out[k] = _plain(v);
    return out;
}

var IslandMediaProvider = class IslandMediaProvider {
    constructor(options = {}) {
        this._bus = options.bus || null;
        this._dbus = options.dbus || null; // for tests/mocking
        this._now = options.now || (() => Date.now());
        // busName -> { name, owner, identity, metadata, status, positionUs, positionTs, rate, ... }
        this._players = new Map();
        this._owners = new Map(); // unique name -> well-known name
        this._activePlayerName = null;
        this._selectedPlayerName = null; // the user's explicit choice, if any
        this._destroyed = false;

        this._nameOwnerSubId = 0;
        this._propChangeSubId = 0;
        this._seekedSubId = 0;

        this._currentTrack = _emptyTrack();

        this._prevTitle = '';
        this._prevStatus = 'Stopped';
    }

    init() {
        this._destroyed = false;
        this._subscribeDBus();
    }

    _session() {
        try {
            return typeof Gio !== 'undefined' && Gio.DBus ? Gio.DBus.session : null;
        } catch (e) {
            return null;
        }
    }

    _subscribeDBus() {
        if (this._dbus) {
            // Test mock subscription
            this._dbus.onPlayerChanged = (name, props) => this._handlePlayerUpdate(name, props);
            return;
        }

        const session = this._session();
        if (!session)
            return;

        try {
            // 1. Players appearing, vanishing, or changing owner
            this._nameOwnerSubId = session.signal_subscribe(
                'org.freedesktop.DBus',
                'org.freedesktop.DBus',
                'NameOwnerChanged',
                '/org/freedesktop/DBus',
                'org.mpris.MediaPlayer2',
                Gio.DBusSignalFlags.MATCH_ARG0_NAMESPACE,
                (_c, _s, _p, _i, _sig, params) => {
                    const [name, , newOwner] = params.deep_unpack();
                    if (!newOwner)
                        this._removePlayer(name);
                    else
                        this._addPlayer(name, newOwner);
                }
            );

            // 2. Playback state and track metadata
            this._propChangeSubId = session.signal_subscribe(
                null,
                'org.freedesktop.DBus.Properties',
                'PropertiesChanged',
                MPRIS_PATH,
                null,
                Gio.DBusSignalFlags.NONE,
                (_c, sender, _p, _i, _sig, params) => {
                    const [iface, changed] = params.deep_unpack();
                    const name = this._owners.get(sender);
                    if (iface === PLAYER_IFACE && name)
                        this._handlePlayerUpdate(name, _plainDict(changed));
                }
            );

            // 3. Jumps in position (the only time MPRIS reports it)
            this._seekedSubId = session.signal_subscribe(
                null,
                PLAYER_IFACE,
                'Seeked',
                MPRIS_PATH,
                null,
                Gio.DBusSignalFlags.NONE,
                (_c, sender, _p, _i, _sig, params) => {
                    const name = this._owners.get(sender);
                    if (name)
                        this._setPosition(name, Number(params.deep_unpack()[0]) || 0);
                }
            );

            // 4. Players already running
            session.call(
                'org.freedesktop.DBus',
                '/org/freedesktop/DBus',
                'org.freedesktop.DBus',
                'ListNames',
                null,
                new GLib.VariantType('(as)'),
                Gio.DBusCallFlags.NONE,
                -1,
                null,
                (conn, res) => {
                    try {
                        const [names] = conn.call_finish(res).deep_unpack();
                        for (const name of names) {
                            if (name.startsWith(MPRIS_PREFIX))
                                this._addPlayer(name, null);
                        }
                    } catch (e) {
                        // DBus query error
                    }
                }
            );
        } catch (e) {
            // DBus not available in headless test harness
        }
    }

    _addPlayer(name, owner) {
        if (this._destroyed)
            return;
        let info = this._players.get(name);
        if (!info) {
            info = {
                name, owner: null, identity: '', metadata: {}, status: 'Stopped',
                positionUs: 0, positionTs: this._now(), rate: 1, canSeek: false,
                canGoNext: true, canGoPrevious: true, seenTs: this._now(),
            };
            this._players.set(name, info);
            if (!this._activePlayerName)
                this._activePlayerName = name;
        }
        if (info.owner)
            this._owners.delete(info.owner);
        info.owner = owner;
        if (owner)
            this._owners.set(owner, name);
        else
            this._resolveOwner(name);
        this._queryPlayer(name);
    }

    _removePlayer(name) {
        const info = this._players.get(name);
        if (info && info.owner)
            this._owners.delete(info.owner);
        this._players.delete(name);
        if (this._selectedPlayerName === name)
            this._selectedPlayerName = null;
        if (this._activePlayerName === name)
            this._activePlayerName = this._pickFallbackPlayer();
        this._rebuildTrack();
        this._notifyState();
    }

    _pickFallbackPlayer() {
        let best = null;
        for (const info of this._players.values()) {
            if (!best || (info.status === 'Playing') > (best.status === 'Playing') ||
                ((info.status === 'Playing') === (best.status === 'Playing') && info.seenTs > best.seenTs))
                best = info;
        }
        return best ? best.name : null;
    }

    _resolveOwner(name) {
        const session = this._session();
        if (!session)
            return;
        session.call('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
            'GetNameOwner', new GLib.Variant('(s)', [name]), new GLib.VariantType('(s)'),
            Gio.DBusCallFlags.NONE, -1, null, (conn, res) => {
                try {
                    const [owner] = conn.call_finish(res).deep_unpack();
                    const info = this._players.get(name);
                    if (info && owner) {
                        info.owner = owner;
                        this._owners.set(owner, name);
                    }
                } catch (e) {}
            });
    }

    _queryPlayer(name) {
        const session = this._session();
        if (!session)
            return;
        session.call(name, MPRIS_PATH, 'org.freedesktop.DBus.Properties', 'GetAll',
            new GLib.Variant('(s)', [PLAYER_IFACE]), new GLib.VariantType('(a{sv})'),
            Gio.DBusCallFlags.NONE, -1, null, (conn, res) => {
                try {
                    const [props] = conn.call_finish(res).deep_unpack();
                    this._handlePlayerUpdate(name, _plainDict(props));
                } catch (e) {
                    // Ignore transient call errors
                }
            });
        session.call(name, MPRIS_PATH, 'org.freedesktop.DBus.Properties', 'Get',
            new GLib.Variant('(ss)', ['org.mpris.MediaPlayer2', 'Identity']),
            new GLib.VariantType('(v)'), Gio.DBusCallFlags.NONE, -1, null, (conn, res) => {
                try {
                    const [identity] = conn.call_finish(res).deep_unpack();
                    const info = this._players.get(name);
                    if (info) {
                        info.identity = String(_plain(identity) || '');
                        this._rebuildTrack();
                        this._notifyState();
                    }
                } catch (e) {}
            });
    }

    // Position is not signalled; read it when it matters (status changes, the
    // Music card opening) and extrapolate in between.
    refreshPosition(name = this._activePlayerName) {
        const session = this._session();
        if (!session || !name || !this._players.has(name))
            return;
        session.call(name, MPRIS_PATH, 'org.freedesktop.DBus.Properties', 'Get',
            new GLib.Variant('(ss)', [PLAYER_IFACE, 'Position']),
            new GLib.VariantType('(v)'), Gio.DBusCallFlags.NONE, -1, null, (conn, res) => {
                try {
                    const [position] = conn.call_finish(res).deep_unpack();
                    this._setPosition(name, Number(_plain(position)) || 0);
                } catch (e) {}
            });
    }

    _setPosition(name, positionUs) {
        const info = this._players.get(name);
        if (!info)
            return;
        info.positionUs = Math.max(0, positionUs);
        info.positionTs = this._now();
        if (name === this._activePlayerName)
            this._notifyState();
    }

    _handlePlayerUpdate(name, rawProps) {
        if (!rawProps) return;
        const props = _plainDict(rawProps);

        const info = this._players.get(name) || {
            name, owner: null, identity: '', metadata: {}, status: 'Stopped',
            positionUs: 0, positionTs: this._now(), rate: 1, canSeek: false,
            canGoNext: true, canGoPrevious: true, seenTs: this._now(),
        };
        const wasStatus = info.status;
        // Freeze the extrapolated position before the rate or status changes.
        info.positionUs = this._extrapolate(info);
        info.positionTs = this._now();

        if (props.Metadata) {
            const prevTrack = info.metadata && info.metadata['mpris:trackid'];
            info.metadata = _plainDict(props.Metadata);
            if (info.metadata['mpris:trackid'] !== prevTrack)
                info.positionUs = 0;
        }
        if (props.PlaybackStatus)
            info.status = String(props.PlaybackStatus);
        if (typeof props.Position === 'number')
            info.positionUs = props.Position;
        if (typeof props.Rate === 'number')
            info.rate = props.Rate;
        if (typeof props.CanSeek === 'boolean')
            info.canSeek = props.CanSeek;
        if (typeof props.CanGoNext === 'boolean')
            info.canGoNext = props.CanGoNext;
        if (typeof props.CanGoPrevious === 'boolean')
            info.canGoPrevious = props.CanGoPrevious;
        info.seenTs = this._now();
        this._players.set(name, info);

        // Follow whichever player started playing, unless the user picked one.
        if (!this._selectedPlayerName &&
            (info.status === 'Playing' || !this._activePlayerName ||
             !this._players.has(this._activePlayerName)))
            this._activePlayerName = name;

        if (props.PlaybackStatus && info.status !== wasStatus && !this._dbus)
            this.refreshPosition(name);

        if (name !== this._activePlayerName) {
            this._notifyState();
            return;
        }

        this._rebuildTrack();
        const { title, artist, album, artUrl, playbackStatus } = this._currentTrack;

        // Determine event triggering
        if (title && title !== this._prevTitle) {
            // Track changed
            this._prevTitle = title;
            this._prevStatus = playbackStatus;
            if (this._bus) {
                this._bus.emitEvent('TRACK_CHANGED', {
                    provider: 'media',
                    priority: 3, // P3_NORMAL
                    dwellMs: 3000,
                    title,
                    artist,
                    album,
                    artUrl,
                    playbackStatus,
                    message: `${title}${artist ? ` · ${artist}` : ''}`,
                    data: { ...this._currentTrack },
                });
            }
        } else if (playbackStatus !== this._prevStatus) {
            // Playback state toggle
            this._prevStatus = playbackStatus;
            if (this._bus) {
                this._bus.emitEvent('PLAYBACK_STATE_CHANGED', {
                    provider: 'media',
                    priority: 4, // P4_AMBIENT
                    dwellMs: 2000,
                    playbackStatus,
                    title,
                    artist,
                    message: `${playbackStatus}: ${title}`,
                    data: { ...this._currentTrack },
                });
            }
        } else {
            this._notifyState();
        }
    }

    _rebuildTrack() {
        const info = this._activePlayerName ? this._players.get(this._activePlayerName) : null;
        if (!info) {
            this._currentTrack = _emptyTrack();
            return;
        }
        const m = info.metadata || {};
        const artist = m['xesam:artist'];
        const status = info.status || 'Stopped';
        this._currentTrack = {
            title: m['xesam:title'] ? String(m['xesam:title']) : '',
            artist: Array.isArray(artist) ? artist.join(', ') : artist ? String(artist) : '',
            album: m['xesam:album'] ? String(m['xesam:album']) : '',
            artUrl: m['mpris:artUrl'] ? String(m['mpris:artUrl']) : '',
            playbackStatus: status,
            playerName: info.name.replace(MPRIS_PREFIX, ''),
            playerBusName: info.name,
            identity: info.identity || this._prettyName(info.name),
            isPlaying: status === 'Playing',
            lengthUs: Number(m['mpris:length']) || 0,
            canSeek: !!info.canSeek && Number(m['mpris:length']) > 0,
            canGoNext: info.canGoNext !== false,
            canGoPrevious: info.canGoPrevious !== false,
        };
    }

    _prettyName(busName) {
        const base = busName.replace(MPRIS_PREFIX, '').split('.')[0];
        return base ? base.charAt(0).toUpperCase() + base.slice(1) : 'Player';
    }

    _extrapolate(info) {
        let pos = info.positionUs || 0;
        if (info.status === 'Playing')
            pos += (this._now() - info.positionTs) * 1000 * (info.rate || 1);
        const length = Number(info.metadata && info.metadata['mpris:length']) || 0;
        return length > 0 ? Math.min(pos, length) : pos;
    }

    _notifyState() {
        if (this._bus && this._bus.notifyStateChange)
            this._bus.notifyStateChange();
    }

    getCurrentTrack() {
        const info = this._activePlayerName ? this._players.get(this._activePlayerName) : null;
        return {
            ...this._currentTrack,
            positionUs: info ? this._extrapolate(info) : 0,
        };
    }

    getPlayers() {
        return [...this._players.values()].map(info => ({
            name: info.name,
            identity: info.identity || this._prettyName(info.name),
            isPlaying: info.status === 'Playing',
            active: info.name === this._activePlayerName,
        }));
    }

    selectPlayer(name) {
        if (!this._players.has(name))
            return;
        this._selectedPlayerName = name;
        this._activePlayerName = name;
        this._prevTitle = '';
        this._rebuildTrack();
        this._prevTitle = this._currentTrack.title;
        this._prevStatus = this._currentTrack.playbackStatus;
        if (!this._dbus)
            this.refreshPosition(name);
        this._notifyState();
    }

    // Step to the next player; used by the card's player switcher.
    cyclePlayer() {
        const names = [...this._players.keys()];
        if (names.length < 2)
            return;
        const i = names.indexOf(this._activePlayerName);
        this.selectPlayer(names[(i + 1) % names.length]);
    }

    playPause() {
        this._callPlayerMethod('PlayPause');
    }

    next() {
        this._callPlayerMethod('Next');
    }

    previous() {
        this._callPlayerMethod('Previous');
    }

    // Seek to a fraction (0..1) of the current track.
    seekToFraction(fraction) {
        const track = this.getCurrentTrack();
        if (!track.canSeek || !(track.lengthUs > 0))
            return;
        this.seekTo(Math.round(Math.max(0, Math.min(1, fraction)) * track.lengthUs));
    }

    // Seek to an absolute position in microseconds.
    seekTo(positionUs) {
        const info = this._activePlayerName ? this._players.get(this._activePlayerName) : null;
        if (!info || !this._currentTrack.canSeek)
            return;
        const target = Math.max(0, Math.min(positionUs, this._currentTrack.lengthUs || positionUs));
        const trackId = info.metadata && info.metadata['mpris:trackid'];
        if (trackId && typeof GLib !== 'undefined')
            this._callPlayerMethod('SetPosition', new GLib.Variant('(ox)', [String(trackId), target]));
        else if (typeof GLib !== 'undefined')
            this._callPlayerMethod('Seek', new GLib.Variant('(x)', [target - this._extrapolate(info)]));
        // Show the jump at once; Seeked confirms or corrects it.
        info.positionUs = target;
        info.positionTs = this._now();
        this._notifyState();
    }

    // Relative seek in seconds (keyboard arrows on the scrubber).
    seekBy(seconds) {
        const info = this._activePlayerName ? this._players.get(this._activePlayerName) : null;
        if (!info)
            return;
        this.seekTo(this._extrapolate(info) + seconds * 1e6);
    }

    _callPlayerMethod(method, params = null) {
        if (!this._activePlayerName)
            return;
        const session = this._session();
        if (!session)
            return;
        try {
            session.call(this._activePlayerName, MPRIS_PATH, PLAYER_IFACE, method, params,
                null, Gio.DBusCallFlags.NONE, -1, null, null);
        } catch (e) {
            // DBus call failure
        }
    }

    destroy() {
        this._destroyed = true;
        const session = this._session();
        if (session) {
            try {
                for (const id of [this._nameOwnerSubId, this._propChangeSubId, this._seekedSubId]) {
                    if (id)
                        session.signal_unsubscribe(id);
                }
            } catch (e) {
                // Session bus already disconnected or unavailable
            }
        }
        this._nameOwnerSubId = 0;
        this._propChangeSubId = 0;
        this._seekedSubId = 0;
        this._players.clear();
        this._owners.clear();
    }
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { IslandMediaProvider };
}
