// Adaptive Control Center - now playing and sound.
//
// Part of the one ControlCenter object in controlCenter.js, kept in its own
// file by subject. The methods of the class below are copied onto that object
// when the extension loads, so `this` here is the Control Center itself.

/* exported CcMedia */

const { Clutter, Gio, GLib, Shell, St } = imports.gi;
const Mpris = imports.ui.mpris;
const Slider = imports.ui.slider;

const Me = imports.misc.extensionUtils.getCurrentExtension();
const CcUtil = Me.imports.ccUtil;
const {
    readConfig,
    friendlyAppName,
    describeSink,
    makeHeading,
    makeRow,
} = CcUtil;

var CcMedia = class CcMedia {
    // -------------------------------------------------------- now playing

    _buildMediaCard() {
        const actor = new St.BoxLayout({
            style_class: 'adaptive-cc-media',
            x_expand: true,
            visible: false,
        });

        const art = new St.Icon({
            style_class: 'adaptive-cc-media-art',
            icon_size: 44,
            fallback_icon_name: 'audio-x-generic-symbolic',
        });
        actor.add_child(new St.Bin({
            style_class: 'adaptive-cc-media-art-bin',
            child: art,
            y_align: Clutter.ActorAlign.CENTER,
        }));

        // The text raises the player, the way tapping Now Playing does on a Mac.
        const body = new St.Button({
            style_class: 'adaptive-cc-media-body',
            can_focus: true,
            x_expand: true,
        });
        const text = new St.BoxLayout({ vertical: true, x_expand: true, y_align: Clutter.ActorAlign.CENTER });
        const title = new St.Label({ style_class: 'adaptive-cc-media-title' });
        const artist = new St.Label({ style_class: 'adaptive-cc-media-artist' });
        const app = new St.Label({ style_class: 'adaptive-cc-media-app' });
        text.add_child(title);
        text.add_child(artist);
        text.add_child(app);
        body.set_child(text);
        body.connect('clicked', () => {
            const player = this._currentPlayer();
            if (player) {
                this._closeMenu();
                player.raise();
            }
        });
        actor.add_child(body);

        const control = (icon, name, fn) => {
            const button = new St.Button({
                style_class: 'adaptive-cc-media-button',
                can_focus: true,
                accessible_name: name,
                child: new St.Icon({ icon_name: icon }),
                y_align: Clutter.ActorAlign.CENTER,
            });
            button.connect('clicked', () => {
                const player = this._currentPlayer();
                if (player)
                    fn(player);
            });
            actor.add_child(button);
            return button;
        };
        const prev = control('media-skip-backward-symbolic', 'Previous', p => p.previous());
        const play = control('media-playback-start-symbolic', 'Play', p => p.playPause());
        const next = control('media-skip-forward-symbolic', 'Next', p => p.next());
        play.add_style_class_name('adaptive-cc-media-play');

        this._media = { actor, art, title, artist, app, prev, play, next };
        this._players = new Map();
        return actor;
    }

    // MPRIS players come and go with their apps; the list of bus names is read
    // when the panel opens and followed while it stays open.
    _startMpris() {
        this._stopMpris();

        Gio.DBus.session.call('org.freedesktop.DBus', '/org/freedesktop/DBus',
            'org.freedesktop.DBus', 'ListNames', null, new GLib.VariantType('(as)'),
            Gio.DBusCallFlags.NONE, -1, null, (conn, res) => {
                try {
                    const [names] = conn.call_finish(res).deep_unpack();
                    for (const name of names) {
                        if (name.startsWith('org.mpris.MediaPlayer2.'))
                            this._addPlayer(name);
                    }
                } catch (e) {
                    logError(e, '[Adaptive Control Center] listing media players');
                }
                this._syncMedia();
            });

        this._mprisSub = Gio.DBus.session.signal_subscribe('org.freedesktop.DBus',
            'org.freedesktop.DBus', 'NameOwnerChanged', '/org/freedesktop/DBus',
            'org.mpris.MediaPlayer2', Gio.DBusSignalFlags.MATCH_ARG0_NAMESPACE,
            (_c, _s, _p, _i, _sig, params) => {
                const [name, , newOwner] = params.deep_unpack();
                if (newOwner)
                    this._addPlayer(name);
            });
    }

    _stopMpris() {
        if (this._mprisSub) {
            Gio.DBus.session.signal_unsubscribe(this._mprisSub);
            this._mprisSub = 0;
        }
    }

    _addPlayer(name) {
        if (this._players.has(name))
            return;
        try {
            const player = new Mpris.MprisPlayer(name);
            // 'changed' fires before the player updates whether it can play;
            // 'show' and 'hide' follow that update.
            const ids = [
                player.connect('changed', () => this._syncMedia()),
                player.connect('show', () => this._syncMedia()),
                player.connect('hide', () => this._syncMedia()),
                player.connect('closed', () => {
                    for (const id of ids)
                        player.disconnect(id);
                    this._players.delete(name);
                    this._syncMedia();
                }),
            ];
            this._players.set(name, player);
        } catch (e) {
            logError(e, `[Adaptive Control Center] media player ${name}`);
        }
    }

    // The one playing, else the most recently seen one with a track.
    _currentPlayer() {
        const players = [...this._players.values()].filter(p => {
            try {
                // Like GNOME's own media widget: only a player that says it
                // can play. One with no Player interface at all otherwise
                // shows up as "Unknown title".
                return p._playerProxy && p._visible === true && p.trackTitle;
            } catch (e) {
                return false;
            }
        });
        return players.find(p => p.status === 'Playing') || players[players.length - 1] || null;
    }

    _syncMedia() {
        const media = this._media;
        if (!media)
            return;

        const player = this._currentPlayer();
        const show = !!player && readConfig().showMedia !== false;
        media.actor.visible = show;
        if (!show)
            return;

        media.title.text = player.trackTitle || 'Unknown title';
        const artists = Array.isArray(player.trackArtists) ? player.trackArtists.join(', ') : '';
        media.artist.text = artists;
        media.artist.visible = !!artists;

        let appName = '';
        try {
            appName = (player._mprisProxy && player._mprisProxy.Identity) || '';
        } catch (e) {
        }
        media.app.text = appName;
        media.app.visible = !!appName;

        const url = player.trackCoverUrl || '';
        if (url.startsWith('file://')) {
            media.art.gicon = new Gio.FileIcon({ file: Gio.File.new_for_uri(url) });
        } else if (url.startsWith('http')) {
            // Remote art is not fetched from inside the shell.
            media.art.gicon = null;
            media.art.icon_name = 'audio-x-generic-symbolic';
        } else {
            media.art.gicon = null;
            media.art.icon_name = 'audio-x-generic-symbolic';
        }

        const playing = player.status === 'Playing';
        media.play.child.icon_name = playing ? 'media-playback-pause-symbolic' : 'media-playback-start-symbolic';
        media.play.accessible_name = playing ? 'Pause' : 'Play';

        for (const [button, can] of [[media.prev, player.canGoPrevious], [media.next, player.canGoNext]]) {
            button.reactive = !!can;
            if (can)
                button.remove_style_pseudo_class('insensitive');
            else
                button.add_style_pseudo_class('insensitive');
        }
    }

    // --------------------------------------------------------------- sound

    _syncSoundPage(force = false) {
        const page = this._pages.sound;
        if (!force && this._holdForPointer(page))
            return;

        const sink = this._mixer.get_default_sink();
        const source = this._mixer.get_default_source();
        const sinks = this._mixer.get_sinks() || [];
        const sources = (this._mixer.get_sources() || [])
            .filter(s => !/\.monitor$/.test(s.get_name() || ''));
        const apps = (this._mixer.get_sink_inputs() || []).filter(s => !s.is_event_stream);

        // Per-app sliders are dragged in place; rebuilding the list would drop
        // the drag, so only a change in what is listed rebuilds it.
        const signature = [
            sinks.map(s => s.get_id()).join(','), sink ? sink.get_id() : '',
            sources.map(s => s.get_id()).join(','), source ? source.get_id() : '',
            apps.map(s => `${s.get_id()}:${s.get_name()}`).join(','),
        ].join('|');
        if (!force && signature === this._soundSignature && page.list.get_n_children() > 0)
            return;
        this._soundSignature = signature;

        const rows = [makeHeading('Output')];
        for (const s of sinks) {
            const active = !!sink && s.get_id() === sink.get_id();
            const { title, subtitle, icon } = describeSink(this._mixer, s);
            rows.push(makeRow({
                icon, title, subtitle,
                trailing: active ? ['object-select-symbolic'] : [],
                active,
                onActivate: active ? null : () => {
                    this._mixer.set_default_sink(s);
                    this._queueSync();
                },
            }));
        }

        if (sources.length) {
            rows.push(makeHeading('Input'));
            for (const s of sources) {
                const active = !!source && s.get_id() === source.get_id();
                const { title, subtitle } = describeSink(this._mixer, s);
                rows.push(makeRow({
                    icon: /head(set|phone)/i.test(title) ? 'audio-headset-symbolic' : 'audio-input-microphone-symbolic',
                    title, subtitle,
                    trailing: active ? ['object-select-symbolic'] : [],
                    active,
                    onActivate: active ? null : () => {
                        this._mixer.set_default_source(s);
                        this._queueSync();
                    },
                }));
            }
        }

        if (apps.length) {
            rows.push(makeHeading('Apps'));
            for (const stream of apps)
                rows.push(this._appVolumeRow(stream));
        }

        this._fillPage(page, rows, sinks.length ? '' : 'No sound outputs were found.');
    }

    _appVolumeRow(stream) {
        const id = stream.get_application_id() || '';
        const app = id ? Shell.AppSystem.get_default().lookup_app(`${id}.desktop`) : null;
        const name = friendlyAppName(id, stream.get_name() || 'App');
        const max = this._mixer.get_vol_max_norm();

        const row = new St.BoxLayout({ style_class: 'adaptive-cc-app-volume', x_expand: true });

        const mute = new St.Button({
            style_class: 'adaptive-cc-slider-icon-button',
            can_focus: true,
            accessible_name: `Mute ${name}`,
            child: app ? app.create_icon_texture(20)
                : new St.Icon({ icon_name: stream.get_icon_name() || 'applications-multimedia-symbolic', icon_size: 20 }),
            y_align: Clutter.ActorAlign.CENTER,
        });
        if (stream.is_muted)
            mute.add_style_pseudo_class('checked');
        mute.connect('clicked', () => {
            stream.change_is_muted(!stream.is_muted);
            if (!stream.is_muted)
                mute.add_style_pseudo_class('checked');
            else
                mute.remove_style_pseudo_class('checked');
        });
        row.add_child(mute);

        const column = new St.BoxLayout({ vertical: true, x_expand: true, y_align: Clutter.ActorAlign.CENTER });
        column.add_child(new St.Label({ text: name, style_class: 'adaptive-cc-app-volume-name' }));
        const slider = new Slider.Slider(stream.is_muted ? 0 : Math.min(stream.volume / max, 1));
        slider.add_style_class_name('adaptive-cc-slider');
        slider.accessible_name = `${name} volume`;
        slider.connect('notify::value', () => {
            stream.volume = slider.value * max;
            if (stream.is_muted && slider.value > 0)
                stream.change_is_muted(false);
            stream.push_volume();
        });
        column.add_child(slider);
        row.add_child(column);
        return row;
    }
};
