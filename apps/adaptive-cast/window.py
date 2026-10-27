"""The Cast window.

Left: the TVs nearby, or - while casting - a live preview of exactly what
the TV shows, the connection steps, and the stream's numbers. Right: tabs
for the picture, what is drawn on it, privacy, the TV itself, and media
that plays without mirroring.

Every control writes through controller.Cast, so a change made here takes
effect on the TV at once and is remembered for next time.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

import desk  # noqa: E402
import stream  # noqa: E402
import wfd  # noqa: E402

STEPS = (("preparing", "TV ready"), ("connecting", "Joining"), ("negotiating", "Handshake"),
         ("streaming", "Live"))
ACTIVE = ("preparing", "connecting", "negotiating", "streaming", "reconnecting")
# Below this width (the phone, through Adaptive Link) the tabs go under the
# main area instead of beside it.
NARROW_PX = 820

SOURCES = ("Whole screen", "One window", "Left half", "Right half")
FITS = (("fit", "Fit, with bars"), ("fill", "Fill, cropping edges"), ("safe", "Safe margins"))
SOUNDS = (("tv", "On the TV"), ("laptop", "On the laptop"), ("both", "On both"))
CURSORS = (("off", "Off"), ("ring", "Ring"), ("spotlight", "Spotlight"))
TV_ENDS = (("restore", "Go back to what it showed"), ("off", "Turn the TV off"),
           ("nothing", "Leave it on Screen Share"))


def label(text, *classes, xalign=0, wrap=False):
    widget = Gtk.Label(label=text, xalign=xalign, wrap=wrap)
    if wrap:
        widget.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    for name in classes:
        widget.add_css_class(name)
    return widget


def button(text, callback, *classes):
    widget = Gtk.Button(label=text)
    for name in classes:
        widget.add_css_class(name)
    widget.connect("clicked", lambda *_: callback())
    return widget


def dropdown(choices, current, callback):
    """choices: [(value, label)]. callback(value) on change."""
    widget = Gtk.DropDown.new_from_strings([text for _, text in choices])
    values = [value for value, _ in choices]
    if current in values:
        widget.set_selected(values.index(current))
    widget.connect("notify::selected", lambda w, _p: callback(values[w.get_selected()]))
    return widget


class Window(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Cast")
        self.set_default_size(1060, 700)
        self.add_css_class("adaptive-cast")
        self.app = app
        self.cast = app.ensure_cast()
        app.listeners.append(self)
        self.windows = []
        self.media_playing = False

        root = Gtk.Box()
        root.add_css_class("root")
        self.root_box = root
        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        root.append(main)
        self.side = self._sidebar()
        root.append(self.side)
        # Narrow, the whole window scrolls instead of each half.
        self.set_child(Gtk.ScrolledWindow(child=root, hscrollbar_policy=Gtk.PolicyType.NEVER))
        self.narrow = None

        main.append(self._header())
        self.banner = label("", "banner", wrap=True)
        self.banner.set_selectable(True)
        main.append(self.banner)
        self.stage = Gtk.Stack(vexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.stage.add_named(self._pick_page(), "pick")
        self.stage.add_named(self._live_page(), "live")
        main.append(self.stage)

        missing = stream.missing_elements()
        if not self.cast.link.ready:
            self._banner("This laptop has no Wi-Fi Direct device, so it cannot cast.")
        elif missing:
            self._banner("Needs a video encoder first. In a terminal:\n"
                         "sudo apt install " + " ".join(missing))
        else:
            self.banner.set_visible(False)

        self.on_displays(self.cast.link.displays())
        self.on_state(self.cast.state, self.cast.text)
        self._refresh_tv()
        self.tick = GLib.timeout_add(250, self._tick)
        self.connect("close-request", self._closing)

    def do_size_allocate(self, width, height, baseline):
        Gtk.ApplicationWindow.do_size_allocate(self, width, height, baseline)
        narrow = width < NARROW_PX
        if narrow != self.narrow:
            self.narrow = narrow
            # Not during allocation: changing the layout queues another one.
            GLib.idle_add(self._apply_width, narrow)

    def _apply_width(self, narrow):
        self.root_box.set_orientation(Gtk.Orientation.VERTICAL if narrow
                                      else Gtk.Orientation.HORIZONTAL)
        (self.add_css_class if narrow else self.remove_css_class)("narrow")
        return GLib.SOURCE_REMOVE

    # --- header ----------------------------------------------------------

    def _header(self):
        box = Gtk.Box(spacing=16)
        box.add_css_class("header")
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        text.append(label("Cast", "title"))
        self.subtitle = label("Wireless display over Wi-Fi Direct. Your Wi-Fi stays connected.",
                              "muted", wrap=True)
        text.append(self.subtitle)
        box.append(text)
        self.tv_chip = label("", "chip")
        self.tv_chip.set_valign(Gtk.Align.CENTER)
        box.append(self.tv_chip)
        return box

    def _banner(self, text):
        self.banner.set_label(text)
        self.banner.set_visible(True)

    # --- choosing a TV ---------------------------------------------------

    def _pick_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.add_css_class("page")
        box.append(label("TVs nearby", "section"))
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.append(self.list)
        hint = label("Searching all the time while this window is open. The TV needs to be on; "
                     "if it is paired (TV tab) Cast can wake it from standby too.", "muted",
                     wrap=True)
        box.append(hint)
        self.pick_status = label("", "status", wrap=True)
        box.append(self.pick_status)
        return box

    def on_displays(self, displays):
        while (child := self.list.get_first_child()) is not None:
            self.list.remove(child)
        if not displays:
            empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            empty.add_css_class("empty")
            spinner = Gtk.Spinner(spinning=True)
            empty.append(spinner)
            empty.append(label("Looking for TVs. Turn the TV on, or open Screen Share on it.",
                               "muted", xalign=0.5, wrap=True))
            self.list.append(empty)
            return
        last = (self.cast.prefs.get("last_display") or {}).get("address")
        blocked = self.banner.get_visible()
        for display in displays:
            card = Gtk.Box(spacing=16)
            card.add_css_class("display")
            if display.address == last:
                card.add_css_class("last")
            icon = Gtk.Image.new_from_icon_name("video-display-symbolic")
            icon.set_pixel_size(40)
            icon.add_css_class("tv-icon")
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True,
                           valign=Gtk.Align.CENTER)
            name = label(display.name, "name")
            name.set_ellipsize(Pango.EllipsizeMode.END)
            text.append(name)
            bits = ["Ready" if display.available else "Busy", self._bars(display.strength)]
            if self.cast.tv.known_for(display.name):
                bits.append("paired for control")
            if display.address == last:
                bits.append("last used")
            text.append(label(" · ".join(bits), "muted", wrap=True))
            go = button("Cast", lambda d=display: self._start(d), "cast")
            go.set_valign(Gtk.Align.CENTER)
            go.set_sensitive(not blocked and not self.cast.casting)
            card.append(icon)
            card.append(text)
            card.append(go)
            self.list.append(card)

    @staticmethod
    def _bars(strength):
        filled = max(1, min(4, round(strength / 25)))
        return "▮" * filled + "▯" * (4 - filled)

    def _start(self, display):
        self.cast.start(display, self._source())

    # --- live ------------------------------------------------------------

    def _live_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.add_css_class("page")
        frame = Gtk.Overlay()
        frame.add_css_class("preview")
        self.preview = Gtk.Picture(can_shrink=True, hexpand=True, vexpand=True)
        self.preview.set_size_request(280, 158)
        frame.set_child(self.preview)
        self.preview_note = label("", "preview-note", xalign=0.5)
        self.preview_note.set_halign(Gtk.Align.CENTER)
        self.preview_note.set_valign(Gtk.Align.CENTER)
        frame.add_overlay(self.preview_note)
        self.live_dot = label("● LIVE", "live-dot")
        self.live_dot.set_halign(Gtk.Align.START)
        self.live_dot.set_valign(Gtk.Align.START)
        frame.add_overlay(self.live_dot)
        box.append(frame)

        self.steps = Gtk.Box(spacing=8, homogeneous=True)
        self.step_labels = {}
        for key, text in STEPS:
            step = label(text, "step", xalign=0.5)
            self.step_labels[key] = step
            self.steps.append(step)
        box.append(self.steps)

        self.live_status = label("", "status", wrap=True)
        box.append(self.live_status)
        self.stats = label("", "stats", wrap=True)
        box.append(self.stats)

        actions = Gtk.Box(spacing=10)
        self.freeze_button = Gtk.ToggleButton(label="Freeze")
        self.freeze_button.add_css_class("action")
        self.freeze_button.connect("toggled", lambda b: self.cast.freeze(b.get_active()))
        self.curtain_button = Gtk.ToggleButton(label="Curtain")
        self.curtain_button.add_css_class("action")
        self.curtain_button.connect("toggled", self._curtain_toggled)
        stop = button("Stop casting", self.cast.stop, "stop")
        stop.set_hexpand(True)
        stop.set_halign(Gtk.Align.END)
        actions.append(self.freeze_button)
        actions.append(self.curtain_button)
        actions.append(stop)
        box.append(actions)
        return box

    def _curtain_toggled(self, toggle):
        text = self.curtain_text.get_text().strip() if hasattr(self, "curtain_text") else ""
        self.cast.set_curtain((text or "Back in a moment") if toggle.get_active() else None)

    def on_state(self, state, text):
        active = state in ACTIVE
        self.stage.set_visible_child_name("live" if active else "pick")
        self.live_status.set_label(text or "")
        if not active:
            self.pick_status.set_label(text if state in ("ended", "failed") else "")
            self.pick_status.remove_css_class("error")
            if state == "failed":
                self.pick_status.add_css_class("error")
            self.freeze_button.set_active(False)
            self.curtain_button.set_active(False)
        reached = True
        order = [key for key, _ in STEPS]
        current = "connecting" if state == "reconnecting" else state
        for key in order:
            widget = self.step_labels[key]
            for name in ("done", "current"):
                widget.remove_css_class(name)
            if not active:
                continue
            if key == current:
                widget.add_css_class("current" if state != "streaming" else "done")
                reached = False
            elif reached:
                widget.add_css_class("done")
        self.live_dot.set_visible(state == "streaming")
        self.preview_note.set_visible(state != "streaming")
        self.preview_note.set_label({"preparing": "Waking the TV", "connecting": "Joining the TV",
                                     "negotiating": "Agreeing on a picture",
                                     "reconnecting": "Reconnecting"}.get(state, ""))
        tv = self.cast.display.name if self.cast.display else None
        self.subtitle.set_label(f"Casting to {tv}" if state == "streaming" and tv else
                                "Wireless display over Wi-Fi Direct. Your Wi-Fi stays connected.")
        self.on_displays(self.cast.link.displays())

    def _tick(self):
        if self.cast.state == "streaming":
            frame = self.cast.preview_frame()
            if frame:
                data, width, height, stride = frame
                texture = Gdk.MemoryTexture.new(width, height, Gdk.MemoryFormat.R8G8B8,
                                                GLib.Bytes.new(data), stride)
                self.preview.set_paintable(texture)
            stats = self.cast.stats()
            if stats:
                seconds = stats["seconds"]
                clock = f"{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"
                parts = [clock, f"{stats['width']}x{stats['height']}",
                         f"{stats['fps']}/{stats['mode_fps']} fps",
                         f"{stats['kbps'] / 1000:.1f} Mbps", f"{stats['dropped']} dropped",
                         {"vaapih264enc": "Intel GPU"}.get(stats["encoder"], stats["encoder"])]
                if stats["recording"]:
                    parts.append("● recording")
                self.stats.set_label("   ·   ".join(parts))
        else:
            self.stats.set_label("")
        return GLib.SOURCE_CONTINUE

    # --- sidebar ---------------------------------------------------------

    def _sidebar(self):
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        side.add_css_class("sidebar")
        pages = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT, vexpand=True)
        switcher = Gtk.StackSwitcher(stack=pages)
        switcher.add_css_class("tabs")
        side.append(switcher)
        for name, title, build in (("picture", "Picture", self._picture_tab),
                                   ("overlay", "Overlay", self._overlay_tab),
                                   ("privacy", "Privacy", self._privacy_tab),
                                   ("tv", "TV", self._tv_tab),
                                   ("media", "Media", self._media_tab)):
            # Sized to the content, at most 400 px wide; the window scrolls.
            scroller = Gtk.ScrolledWindow(child=build(), hscrollbar_policy=Gtk.PolicyType.NEVER,
                                          vscrollbar_policy=Gtk.PolicyType.NEVER,
                                          propagate_natural_width=True, max_content_width=400)
            pages.add_titled(scroller, name, title)
        side.append(pages)
        return side

    def _tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.add_css_class("tab")
        return box

    def _row(self, box, title, widget, detail=None):
        row = Gtk.Box(spacing=12)
        row.add_css_class("row")
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
        text.append(label(title, "row-title"))
        if detail:
            text.append(label(detail, "muted", wrap=True))
        row.append(text)
        widget.set_valign(Gtk.Align.CENTER)
        row.append(widget)
        box.append(row)
        return row

    def _switch(self, key):
        widget = Gtk.Switch(active=bool(self.cast.prefs.get(key)))
        widget.connect("notify::active", lambda w, _p: self.cast.set_option(key, w.get_active()))
        return widget

    def _entry(self, key, placeholder, apply=None):
        widget = Gtk.Entry(text=self.cast.prefs.get(key) or "", placeholder_text=placeholder,
                           hexpand=True)
        handler = apply or (lambda text: self.cast.set_option(key, text))
        widget.connect("activate", lambda w: handler(w.get_text().strip()))
        widget.connect("notify::has-focus", lambda w, _p: None if w.has_focus()
                       else handler(w.get_text().strip()))
        return widget

    # picture ------------------------------------------------------------

    def _picture_tab(self):
        box = self._tab()
        box.append(label("What to send", "section"))
        self.source_choice = Gtk.DropDown.new_from_strings(list(SOURCES))
        self.source_choice.connect("notify::selected", lambda *_: self._source_changed())
        self._row(box, "Show", self.source_choice)
        self.window_choice = Gtk.DropDown.new_from_strings([])
        self.window_choice.set_size_request(200, -1)
        self.window_choice.connect("notify::selected", lambda *_: self._source_changed())
        self.window_row = self._row(box, "Window", self.window_choice,
                                    "Only this window reaches the TV")
        self.window_row.set_visible(False)

        box.append(label("Quality", "section"))
        group = None
        current = self.cast.prefs.get("quality", "sharp")
        for key, preset in wfd.QUALITY.items():
            toggle = Gtk.ToggleButton()
            toggle.add_css_class("preset")
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            inner.append(label(preset["label"], "row-title"))
            inner.append(label(preset["detail"], "muted"))
            toggle.set_child(inner)
            if group:
                toggle.set_group(group)
            group = group or toggle
            toggle.set_active(key == current)
            toggle.connect("toggled", lambda t, k=key: t.get_active() and
                           self.cast.set_option("quality", k))
            box.append(toggle)

        box.append(label("Fit and sound", "section"))
        self._row(box, "Picture", dropdown(FITS, self.cast.prefs.get("fit"),
                                           lambda v: self.cast.set_option("fit", v)),
                  "Safe margins keep the edges inside TVs that crop")
        self._row(box, "Sound", dropdown(SOUNDS, self.cast.prefs.get("sound"),
                                         lambda v: self.cast.set_option("sound", v)),
                  "On both: the laptop plays slightly ahead of the TV")
        self._row(box, "Record", self._switch("record"), "Keep a copy in Videos/Cast")
        return box

    def _source(self):
        choice = self.source_choice.get_selected() if hasattr(self, "source_choice") else 0
        width, height = desk.screen_size()
        if choice == 1 and self.windows:
            index = self.window_choice.get_selected()
            if 0 <= index < len(self.windows):
                win = self.windows[index]
                return {"kind": "window", "xid": win["xid"], "title": win["title"][:60]}
        if choice == 2:
            return {"kind": "region", "x": 0, "y": 0, "w": width // 2 // 2 * 2, "h": height,
                    "title": "Left half"}
        if choice == 3:
            half = width // 2 // 2 * 2
            return {"kind": "region", "x": width - half, "y": 0, "w": half, "h": height,
                    "title": "Right half"}
        return {"kind": "screen"}

    def _source_changed(self):
        one_window = self.source_choice.get_selected() == 1
        self.window_row.set_visible(one_window)
        if one_window and not self.windows:
            self.windows = [w for w in desk.windows() if "Cast" != w["title"]]
            names = [f"{w['title'][:40]}" for w in self.windows]
            self.window_choice.set_model(Gtk.StringList.new(names))
            return
        if not one_window:
            self.windows = []
        self.cast.set_source(self._source())

    # overlay ------------------------------------------------------------

    def _overlay_tab(self):
        box = self._tab()
        box.append(label("Pointer", "section"))
        self._row(box, "Highlight", dropdown(CURSORS, self.cast.prefs.get("cursor"),
                                             lambda v: self.cast.set_option("cursor", v)),
                  "So people across the room can follow the mouse")
        box.append(label("On the picture", "section"))
        self._row(box, "Clock", self._switch("clock"), "Top right corner")
        box.append(label("Badge (top left)", "row-title"))
        box.append(self._entry("badge", "Presenting: Karthi"))
        box.append(label("Caption (along the bottom)", "row-title"))
        box.append(self._entry("caption", "Type and press Enter; clear it to hide"))
        return box

    # privacy ------------------------------------------------------------

    def _privacy_tab(self):
        box = self._tab()
        box.append(label("While casting", "section"))
        self._row(box, "Quiet notifications", self._switch("quiet"),
                  "No banners pop up on the TV")
        self._row(box, "Hide private windows", self._switch("hide_windows"),
                  "Blacked out on the TV, still visible here")
        box.append(label("Windows to hide (name or app, comma separated)", "row-title", wrap=True))
        box.append(self._entry("hidden_classes", "keepassxc, bitwarden",
                               lambda text: self.cast.set_option(
                                   "hidden_classes", [p.strip() for p in text.split(",")
                                                      if p.strip()])))
        current = self.cast.prefs.get("hidden_classes") or []
        box.get_last_child().set_text(", ".join(current))
        box.append(label("Curtain", "section"))
        box.append(label("Curtain covers the TV with a clock and this line; Freeze holds the "
                         "last picture. Both are on the live view.", "muted", wrap=True))
        self.curtain_text = Gtk.Entry(placeholder_text="Back in a moment")
        box.append(self.curtain_text)
        box.append(label("Connection", "section"))
        self._row(box, "Reconnect by itself", self._switch("reconnect"),
                  "If the TV link drops, rejoin up to three times")
        return box

    # tv -----------------------------------------------------------------

    def _tv_tab(self):
        box = self._tab()
        box.append(label("Pairing", "section"))
        self.pair_status = label("", "muted", wrap=True)
        box.append(self.pair_status)
        pair_row = Gtk.Box(spacing=8)
        self.pair_button = button("Pair with the TV", self._pair, "action")
        self.forget_button = button("Forget", self._forget, "action")
        pair_row.append(self.pair_button)
        pair_row.append(self.forget_button)
        box.append(pair_row)

        self.tv_controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.append(self.tv_controls)
        c = self.tv_controls
        c.append(label("Power", "section"))
        power = Gtk.Box(spacing=8, homogeneous=True)
        power.append(button("Turn on", lambda: self.cast.tv.power_on(), "action"))
        power.append(button("Turn off", lambda: self.cast.tv.power_off(), "action"))
        c.append(power)

        c.append(label("Volume", "section"))
        volume = Gtk.Box(spacing=8)
        self.volume = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.volume.set_hexpand(True)
        self.volume.set_draw_value(True)
        self._volume_guard = False
        self.volume.connect("value-changed", self._volume_changed)
        mute = Gtk.ToggleButton(icon_name="audio-volume-muted-symbolic")
        mute.connect("toggled", lambda b: self.cast.tv.set_mute(b.get_active()))
        volume.append(self.volume)
        volume.append(mute)
        c.append(volume)

        c.append(label("Remote", "section"))
        pad = Gtk.Grid(column_spacing=6, row_spacing=6, halign=Gtk.Align.CENTER)
        keys = {(1, 0): ("go-up-symbolic", "UP"), (0, 1): ("go-previous-symbolic", "LEFT"),
                (1, 1): (None, "ENTER"), (2, 1): ("go-next-symbolic", "RIGHT"),
                (1, 2): ("go-down-symbolic", "DOWN"), (0, 0): ("edit-undo-symbolic", "BACK"),
                (2, 0): ("go-home-symbolic", "HOME"), (0, 2): ("list-remove-symbolic", "VOLUMEDOWN"),
                (2, 2): ("list-add-symbolic", "VOLUMEUP")}
        for (x, y), (icon, name) in keys.items():
            key = Gtk.Button(icon_name=icon) if icon else Gtk.Button(label="OK")
            key.add_css_class("key")
            key.connect("clicked", lambda _b, n=name: self.cast.tv.button(n))
            pad.attach(key, x, y, 1, 1)
        c.append(pad)

        c.append(label("Message on the TV", "section"))
        message = Gtk.Entry(placeholder_text="Dinner is ready")
        message.connect("activate", lambda w: (self.cast.tv.toast(w.get_text().strip()),
                                               w.set_text("")))
        c.append(message)

        c.append(label("Around a cast", "section"))
        self._row(c, "Get the TV ready", self._switch("tv_setup"),
                  "Wake it and open Screen Share before joining")
        self._row(c, "Afterwards", dropdown(TV_ENDS, self.cast.prefs.get("tv_end"),
                                            lambda v: self.cast.set_option("tv_end", v)))
        return box

    def _refresh_tv(self):
        paired = self.cast.tv.paired()
        if paired:
            name = next(iter(paired.values())).get("name", "the TV")
            self.pair_status.set_label(f"Paired with {name}. Cast can wake it, open Screen "
                                       "Share and put it back afterwards.")
            self.tv_chip.set_label(name)
            self.tv_chip.set_visible(True)
            self.cast.tv.volume(self._got_volume)
        else:
            self.pair_status.set_label("Pair once so Cast can wake the TV, open Screen Share, "
                                       "change the volume and play media on it. The TV will "
                                       "ask you to accept.")
            self.tv_chip.set_visible(False)
        self.pair_button.set_visible(not paired)
        self.forget_button.set_visible(bool(paired))
        self.tv_controls.set_sensitive(bool(paired))
        self.media_box.set_sensitive(bool(paired))

    def _got_volume(self, payload):
        if not payload:
            return
        level = (payload.get("volumeStatus") or payload).get("volume")
        if level is not None:
            self._volume_guard = True
            self.volume.set_value(level)
            self._volume_guard = False

    def _volume_changed(self, scale):
        if not self._volume_guard:
            self.cast.tv.set_volume(scale.get_value())

    def _pair(self):
        self.pair_status.set_label("Look at the TV and press Accept with the remote.")
        self.pair_button.set_sensitive(False)

        def done(ok, text):
            self.pair_button.set_sensitive(True)
            self._refresh_tv()
            if not ok:
                self.pair_status.set_label(text)
        self.cast.tv.pair(done)

    def _forget(self):
        self.cast.tv.forget()
        self._refresh_tv()

    # media --------------------------------------------------------------

    def _media_tab(self):
        box = self._tab()
        self.media_box = box
        box.append(label("Play on the TV", "section"))
        box.append(label("The TV plays the file itself, at full quality, while the laptop "
                         "stays free. No mirroring.", "muted", wrap=True))
        box.append(button("Choose a video, song or photo…", self._choose_file, "action"))
        transport = Gtk.Box(spacing=8, homogeneous=True)
        for icon, action in (("media-playback-start-symbolic", "Play"),
                             ("media-playback-pause-symbolic", "Pause"),
                             ("media-playback-stop-symbolic", "Stop")):
            key = Gtk.Button(icon_name=icon)
            key.add_css_class("key")
            key.connect("clicked", lambda _b, a=action: self._transport(a))
            transport.append(key)
        box.append(transport)
        self.media_status = label("", "muted", wrap=True)
        box.append(self.media_status)

        box.append(label("YouTube", "section"))
        youtube = Gtk.Entry(placeholder_text="Paste a YouTube link, press Enter")
        youtube.connect("activate", self._youtube)
        box.append(youtube)

        box.append(label("Wall display", "section"))
        box.append(label("A clock, the weather and this laptop's vitals on the TV, shown by "
                         "the TV's browser.", "muted", wrap=True))
        place = (self.cast.prefs.get("wall_place") or {}).get("name", "")
        city = Gtk.Entry(text=place, placeholder_text="City for the weather, press Enter")
        city.connect("activate", self._set_city)
        box.append(city)
        box.append(button("Show the wall on the TV", self.app.show_wall, "action"))
        return box

    def _choose_file(self):
        chooser = Gtk.FileChooserNative.new("Play on the TV", self, Gtk.FileChooserAction.OPEN,
                                            "Play", "Cancel")
        media_filter = Gtk.FileFilter()
        media_filter.set_name("Videos, music and photos")
        for kind in ("video/*", "audio/*", "image/*"):
            media_filter.add_mime_type(kind)
        chooser.add_filter(media_filter)

        def answered(dialog, response):
            if response == Gtk.ResponseType.ACCEPT:
                path = dialog.get_file().get_path()
                self.media_status.set_label("Sending to the TV…")
                self.app.play_file(path, lambda ok, text: self.media_status.set_label(text))
            dialog.destroy()
        chooser.connect("response", answered)
        chooser.show()

    def _transport(self, action):
        self.app.send_media(action.lower())

    def _youtube(self, entry):
        if self.cast.tv.youtube(entry.get_text().strip()):
            self.media_status.set_label("Opening it in the TV's YouTube app")
            entry.set_text("")
        else:
            self.media_status.set_label("That does not look like a YouTube video link")

    def _set_city(self, entry):
        import threading
        import media
        city = entry.get_text().strip()
        if not city:
            self.cast.set_option("wall_place", None)
            return

        def work():
            try:
                place = media.geocode(city)
            except OSError:
                place = None
            GLib.idle_add(lambda: self._city_found(entry, city, place) or False)
        threading.Thread(target=work, daemon=True).start()

    def _city_found(self, entry, city, place):
        if place:
            self.cast.set_option("wall_place", place)
            entry.set_text(place["name"])
        else:
            entry.set_text("")
            entry.set_placeholder_text(f"Could not find {city}")

    # --- closing ---------------------------------------------------------

    def _closing(self, *_):
        if self.tick:
            GLib.source_remove(self.tick)
            self.tick = 0
        return False
