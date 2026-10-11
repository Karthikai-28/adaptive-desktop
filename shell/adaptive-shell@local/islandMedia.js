// Dynamic Island Now-Playing Media Provider
//
// 100% event-driven via Linux MPRIS D-Bus signals (org.mpris.MediaPlayer2).
// Zero polling loops; consumes 0.0% CPU when idle.

/* exported IslandMediaProvider */
/* global module */

let Gio, GLib;
try {
    Gio = imports.gi.Gio;
    GLib = imports.gi.GLib;
} catch (e) {
    // Headless test harness
}

var IslandMediaProvider = class IslandMediaProvider {
    constructor(options = {}) {
        this._bus = options.bus || null;
        this._dbus = options.dbus || null; // for tests/mocking
        this._players = new Map(); // busName -> { proxy, metadata, status }
        this._activePlayerName = null;
        this._destroyed = false;

        this._nameOwnerSubId = 0;
        this._propChangeSubId = 0;

        this._currentTrack = {
            title: '',
            artist: '',
            album: '',
            artUrl: '',
            playbackStatus: 'Stopped',
            playerName: '',
            isPlaying: false,
        };

        this._prevTitle = '';
        this._prevStatus = 'Stopped';
    }

    init() {
        this._destroyed = false;
        this._subscribeDBus();
    }

    _subscribeDBus() {
        if (this._dbus) {
            // Test mock subscription
            this._dbus.onPlayerChanged = (name, props) => this._handlePlayerUpdate(name, props);
            return;
        }

        let session = null;
        try {
            if (typeof Gio === 'undefined' || !Gio.DBus)
                return;
            session = Gio.DBus.session;
            if (!session)
                return;
        } catch (e) {
            // DBus session unavailable (e.g. headless sandbox or unstarted bus)
            return;
        }

        // 1. Watch for new media players appearing or vanishing
        try {
            this._nameOwnerSubId = session.signal_subscribe(
                'org.freedesktop.DBus',
                'org.freedesktop.DBus',
                'NameOwnerChanged',
                '/org/freedesktop/DBus',
                'org.mpris.MediaPlayer2',
                Gio.DBusSignalFlags.MATCH_ARG0_NAMESPACE,
                (_c, _s, _p, _i, _sig, params) => {
                    const [name, oldOwner, newOwner] = params.deep_unpack();
                    if (!newOwner)
                        this._removePlayer(name);
                    else
                        this._addPlayer(name);
                }
            );

            // 2. Watch for playback state & track metadata changes
            this._propChangeSubId = session.signal_subscribe(
                null,
                'org.freedesktop.DBus.Properties',
                'PropertiesChanged',
                '/org/mpris/MediaPlayer2',
                null,
                Gio.DBusSignalFlags.NONE,
                (_c, sender, _p, _i, _sig, params) => {
                    const [iface, changedProps] = params.deep_unpack();
                    if (iface === 'org.mpris.MediaPlayer2.Player')
                        this._handlePropertiesChanged(sender, changedProps);
                }
            );

            // 3. Scan initial running players asynchronously
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
                            if (name.startsWith('org.mpris.MediaPlayer2.'))
                                this._addPlayer(name);
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

    _addPlayer(name) {
        if (this._players.has(name))
            return;
        this._players.set(name, { name, metadata: {}, status: 'Stopped' });
        this._activePlayerName = name;
        this._queryPlayer(name);
    }

    _removePlayer(name) {
        this._players.delete(name);
        if (this._activePlayerName === name) {
            const next = this._players.keys().next();
            this._activePlayerName = next.done ? null : next.value;
            if (!this._activePlayerName) {
                this._currentTrack = {
                    title: '',
                    artist: '',
                    album: '',
                    artUrl: '',
                    playbackStatus: 'Stopped',
                    playerName: '',
                    isPlaying: false,
                };
            }
        }
    }

    _queryPlayer(name) {
        if (typeof Gio === 'undefined' || !Gio.DBus) return;
        Gio.DBus.session.call(
            name,
            '/org/mpris/MediaPlayer2',
            'org.freedesktop.DBus.Properties',
            'GetAll',
            new GLib.Variant('(s)', ['org.mpris.MediaPlayer2.Player']),
            new GLib.VariantType('(a{sv})'),
            Gio.DBusCallFlags.NONE,
            -1,
            null,
            (conn, res) => {
                try {
                    const [props] = conn.call_finish(res).deep_unpack();
                    this._handlePlayerUpdate(name, props);
                } catch (e) {
                    // Ignore transient call errors
                }
            }
        );
    }

    _handlePropertiesChanged(sender, changedProps) {
        this._handlePlayerUpdate(sender, changedProps);
    }

    _handlePlayerUpdate(name, props) {
        if (!props) return;

        let meta = props.Metadata;
        let status = props.PlaybackStatus;

        const info = this._players.get(name) || { name, metadata: {}, status: 'Stopped' };
        if (meta) info.metadata = meta;
        if (status) info.status = status;
        this._players.set(name, info);
        this._activePlayerName = name;

        // Parse standard MPRIS metadata
        let title = '';
        let artist = '';
        let album = '';
        let artUrl = '';

        const m = info.metadata || {};
        if (m['xesam:title'])
            title = String(m['xesam:title']);
        if (m['xesam:artist']) {
            artist = Array.isArray(m['xesam:artist'])
                ? m['xesam:artist'].join(', ')
                : String(m['xesam:artist']);
        }
        if (m['xesam:album'])
            album = String(m['xesam:album']);
        if (m['mpris:artUrl'])
            artUrl = String(m['mpris:artUrl']);

        const playbackStatus = info.status || 'Stopped';
        const isPlaying = playbackStatus === 'Playing';

        this._currentTrack = {
            title,
            artist,
            album,
            artUrl,
            playbackStatus,
            playerName: name.replace('org.mpris.MediaPlayer2.', ''),
            isPlaying,
        };

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
        }
    }

    getCurrentTrack() {
        return { ...this._currentTrack };
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

    _callPlayerMethod(method) {
        if (!this._activePlayerName || typeof Gio === 'undefined')
            return;
        try {
            Gio.DBus.session.call(
                this._activePlayerName,
                '/org/mpris/MediaPlayer2',
                'org.mpris.MediaPlayer2.Player',
                method,
                null,
                null,
                Gio.DBusCallFlags.NONE,
                -1,
                null,
                null
            );
        } catch (e) {
            // DBus call failure
        }
    }

    destroy() {
        this._destroyed = true;
        if (this._nameOwnerSubId || this._propChangeSubId) {
            try {
                const session = (typeof Gio !== 'undefined' && Gio.DBus) ? Gio.DBus.session : null;
                if (session) {
                    if (this._nameOwnerSubId) {
                        session.signal_unsubscribe(this._nameOwnerSubId);
                        this._nameOwnerSubId = 0;
                    }
                    if (this._propChangeSubId) {
                        session.signal_unsubscribe(this._propChangeSubId);
                        this._propChangeSubId = 0;
                    }
                }
            } catch (e) {
                // Session bus already disconnected or unavailable
            }
        }
        this._nameOwnerSubId = 0;
        this._propChangeSubId = 0;
        this._players.clear();
    }
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { IslandMediaProvider };
}
