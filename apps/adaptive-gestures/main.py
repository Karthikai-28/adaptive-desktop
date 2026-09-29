#!/usr/bin/env python3
"""Touchpad Gestures - the settings page for scripts/adaptive-gestures.py.

Laid out like Windows 11's Touchpad > gestures page: a preset per finger count
("Switch apps and show desktop", ...) or a custom action per direction, a tap
action for four fingers, sensitivity, and a "Try it" row that shows the last
gesture the daemon recognised. Every change is saved at once to
~/.config/adaptive-desktop/gestures.json, which the daemon re-reads before the
next swipe - there is no Apply button because nothing needs restarting.

The action and preset lists come from the daemon module itself, so the two
cannot drift apart.
"""

import importlib.util
import json
import math
import os
import subprocess
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

APP_ID = "com.karthi.AdaptiveGestures"
HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
DAEMON = REPO / "scripts" / "adaptive-gestures.py"


def _load_daemon():
    spec = importlib.util.spec_from_file_location("adaptive_gestures", DAEMON)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


G = _load_daemon()

PRESET_IDS = ["switch-apps", "switch-desktops", "audio", "custom", "nothing"]
PRESET_LABELS = [G.PRESETS[p]["label"] if p != "custom" else "Custom" for p in PRESET_IDS]
ACTION_IDS = list(G.ACTIONS)
ACTION_LABELS = [G.ACTIONS[a] for a in ACTION_IDS]
SENSITIVITY_IDS = ["low", "medium", "high"]
SENSITIVITY_LABELS = ["Low - long swipes only", "Medium", "High - short swipes count"]
ARROWS = {"up": "↑", "down": "↓", "left": "←", "right": "→"}


def load_settings():
    settings = json.loads(json.dumps(G.DEFAULTS))
    try:
        stored = json.loads(G.CONFIG_FILE.read_text(encoding="utf-8"))
        for key, value in stored.items():
            if isinstance(value, dict) and isinstance(settings.get(key), dict):
                settings[key].update(value)
            else:
                settings[key] = value
    except (OSError, ValueError):
        pass
    return settings


def save_settings(settings):
    G.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = G.CONFIG_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    os.replace(temp, G.CONFIG_FILE)


def mapping(settings, fingers):
    group = settings[str(fingers)]
    preset = group.get("preset", "nothing")
    if preset == "custom":
        return {d: group.get("custom", {}).get(d, "none") for d in G.DIRECTIONS}
    return {d: G.PRESETS.get(preset, G.PRESETS["nothing"])[d] for d in G.DIRECTIONS}


class GestureDiagram(Gtk.DrawingArea):
    """A touchpad with the fingers on it and what each direction does."""

    def __init__(self, fingers):
        super().__init__()
        self.fingers = fingers
        self.labels = {}
        self.flash = None
        self.set_content_width(420)
        self.set_content_height(200)
        self.set_draw_func(self._draw)

    def update(self, labels):
        self.labels = labels
        self.queue_draw()

    def pulse(self, direction):
        self.flash = direction
        self.queue_draw()
        GLib.timeout_add(700, self._unpulse)

    def _unpulse(self):
        self.flash = None
        self.queue_draw()
        return GLib.SOURCE_REMOVE

    def _draw(self, _area, cr, width, height):
        cx, cy = width / 2, height / 2
        pad_w, pad_h = 132, 86

        def rounded(x, y, w, h, r):
            cr.new_sub_path()
            cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
            cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
            cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
            cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
            cr.close_path()

        # Touchpad
        rounded(cx - pad_w / 2, cy - pad_h / 2, pad_w, pad_h, 14)
        cr.set_source_rgba(1, 1, 1, 0.06)
        cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, 0.14)
        cr.set_line_width(1)
        cr.stroke()

        # Fingers
        spacing = 16
        start = cx - spacing * (self.fingers - 1) / 2
        for i in range(self.fingers):
            cr.arc(start + i * spacing, cy, 5.5, 0, math.tau)
            cr.set_source_rgb(0.04, 0.52, 1.0)
            cr.fill()

        # Arrows and labels
        cr.select_font_face("Inter")
        cr.set_font_size(12.5)
        spots = {
            "up": (cx, cy - pad_h / 2 - 12, 0, -1),
            "down": (cx, cy + pad_h / 2 + 12, 0, 1),
            "left": (cx - pad_w / 2 - 12, cy, -1, 0),
            "right": (cx + pad_w / 2 + 12, cy, 1, 0),
        }
        for direction, (x, y, ux, uy) in spots.items():
            active = self.flash == direction
            label = self.labels.get(direction, "")
            idle = label in ("", "Nothing")
            if active:
                cr.set_source_rgb(0.04, 0.52, 1.0)
            elif idle:
                cr.set_source_rgba(1, 1, 1, 0.22)
            else:
                cr.set_source_rgba(1, 1, 1, 0.70)

            # arrow shaft + head
            tip_x, tip_y = x + ux * 14, y + uy * 14
            cr.set_line_width(2)
            cr.move_to(x, y)
            cr.line_to(tip_x, tip_y)
            cr.stroke()
            px, py = -uy, ux
            cr.move_to(tip_x + ux * 4, tip_y + uy * 4)
            cr.line_to(tip_x - ux * 3 + px * 5, tip_y - uy * 3 + py * 5)
            cr.line_to(tip_x - ux * 3 - px * 5, tip_y - uy * 3 - py * 5)
            cr.close_path()
            cr.fill()

            # label
            if active:
                cr.set_source_rgb(0.04, 0.52, 1.0)
            elif idle:
                cr.set_source_rgba(0.60, 0.60, 0.62, 0.8)
            else:
                cr.set_source_rgb(0.96, 0.96, 0.97)
            extents = cr.text_extents(label)
            if direction == "up":
                lx, ly = cx - extents.width / 2, tip_y - 10
            elif direction == "down":
                lx, ly = cx - extents.width / 2, tip_y + 22
            elif direction == "left":
                lx, ly = tip_x - 12 - extents.width, cy + 4.5
            else:
                lx, ly = tip_x + 12, cy + 4.5
            cr.move_to(lx, ly)
            cr.show_text(label)


class GestureWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Touchpad Gestures")
        self.set_default_size(760, 820)
        self.add_css_class("adaptive-gestures")
        self.settings = load_settings()
        self.diagrams = {}
        self.custom_boxes = {}
        self.last_seen = 0.0

        self._load_css()

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.set_child(scroll)

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        page.add_css_class("page")
        scroll.set_child(page)

        page.append(self._header())
        self.banner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.banner.add_css_class("banner")
        self.banner.set_visible(False)
        page.append(self.banner)

        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        page.append(self.content)
        self.content.append(self._finger_card(3))
        self.content.append(self._finger_card(4))
        self.content.append(self._general_card())
        self.content.append(self._try_card())

        reset = Gtk.Button(label="Reset to Windows defaults")
        reset.add_css_class("quiet")
        reset.set_halign(Gtk.Align.START)
        reset.connect("clicked", self._reset)
        page.append(reset)

        self._sync_enabled()
        self._check_daemon()
        GLib.timeout_add(250, self._poll_last)
        GLib.timeout_add_seconds(4, self._check_daemon)

    # ---------------------------------------------------------- layout

    def _load_css(self):
        # GTK4 without libadwaita does not follow the desktop's colour scheme;
        # ask for its dark variant so dropdowns and popovers are dark too.
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)
        provider = Gtk.CssProvider()
        provider.load_from_path(str(HERE / "style.css"))
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def _header(self):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.add_css_class("header")
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text.set_hexpand(True)
        title = Gtk.Label(label="Touchpad gestures", xalign=0)
        title.add_css_class("title")
        sub = Gtk.Label(
            label="Swipe with three or four fingers. Changes apply right away.",
            xalign=0)
        sub.add_css_class("subtitle")
        text.append(title)
        text.append(sub)
        box.append(text)

        self.enabled = Gtk.Switch()
        self.enabled.set_valign(Gtk.Align.CENTER)
        self.enabled.set_active(self.settings.get("enabled", True))
        self.enabled.connect("notify::active", self._on_enabled)
        box.append(self.enabled)
        return box

    def _card(self, title, subtitle=None):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        card.add_css_class("card")
        head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        head.add_css_class("card-head")
        label = Gtk.Label(label=title, xalign=0)
        label.add_css_class("card-title")
        head.append(label)
        if subtitle:
            sub = Gtk.Label(label=subtitle, xalign=0)
            sub.set_wrap(True)
            sub.add_css_class("card-subtitle")
            head.append(sub)
        card.append(head)
        return card

    def _row(self, title, widget, hint=None):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add_css_class("row")
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        text.set_hexpand(True)
        text.set_valign(Gtk.Align.CENTER)
        label = Gtk.Label(label=title, xalign=0)
        label.add_css_class("row-title")
        text.append(label)
        if hint:
            sub = Gtk.Label(label=hint, xalign=0)
            sub.set_wrap(True)
            sub.add_css_class("row-hint")
            text.append(sub)
        row.append(text)
        widget.set_valign(Gtk.Align.CENTER)
        row.append(widget)
        return row

    def _dropdown(self, labels, selected, on_change):
        dropdown = Gtk.DropDown.new_from_strings(labels)
        dropdown.set_selected(max(0, selected))
        dropdown.add_css_class("choice")
        dropdown.connect("notify::selected", lambda d, _p: on_change(d.get_selected()))
        return dropdown

    def _finger_card(self, fingers):
        word = {3: "Three", 4: "Four"}[fingers]
        group = self.settings[str(fingers)]
        card = self._card(f"{word}-finger gestures")

        diagram = GestureDiagram(fingers)
        diagram.add_css_class("diagram")
        self.diagrams[fingers] = diagram
        card.append(diagram)

        preset = group.get("preset", "nothing")
        card.append(self._row(
            "Swipes",
            self._dropdown(PRESET_LABELS, PRESET_IDS.index(preset) if preset in PRESET_IDS else 4,
                           lambda i, f=fingers: self._set_preset(f, PRESET_IDS[i]))))

        custom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.custom_boxes[fingers] = custom
        for direction in G.DIRECTIONS:
            current = group.get("custom", {}).get(direction) or \
                G.PRESETS["switch-apps" if fingers == 3 else "switch-desktops"][direction]
            dropdown = self._dropdown(
                ACTION_LABELS, ACTION_IDS.index(current) if current in ACTION_IDS else 0,
                lambda i, f=fingers, d=direction: self._set_custom(f, d, ACTION_IDS[i]))
            custom.append(self._row(f"Swipe {direction} {ARROWS[direction]}", dropdown))

            entry = Gtk.Entry()
            entry.set_placeholder_text("e.g. ctrl+shift+t")
            entry.set_text((group.get("shortcut") or {}).get(direction, ""))
            entry.set_width_chars(18)
            entry.connect("changed", lambda e, f=fingers, d=direction: self._set_shortcut(f, d, e.get_text()))
            shortcut_row = self._row(f"Shortcut for swipe {direction}", entry,
                                     hint="Keys as xdotool names them, joined with +")
            shortcut_row.add_css_class("sub-row")
            shortcut_row.set_visible(current == "custom")
            dropdown.connect("notify::selected",
                             lambda d, _p, r=shortcut_row: r.set_visible(ACTION_IDS[d.get_selected()] == "custom"))
            custom.append(shortcut_row)
        card.append(custom)

        if fingers == 3:
            note = Gtk.Label(label="Middle click", xalign=1)
            note.add_css_class("fixed-value")
            card.append(self._row(
                "Tap", note,
                hint="The touchpad driver turns a three-finger tap into a middle click."))
        else:
            tap = group.get("tap", "none")
            card.append(self._row(
                "Tap",
                self._dropdown(ACTION_LABELS, ACTION_IDS.index(tap) if tap in ACTION_IDS else 0,
                               lambda i: self._set_tap(ACTION_IDS[i]))))

        self._refresh_card(fingers)
        return card

    def _general_card(self):
        card = self._card("Sensitivity")
        level = self.settings.get("sensitivity", "medium")
        card.append(self._row(
            "How far a swipe must travel",
            self._dropdown(SENSITIVITY_LABELS,
                           SENSITIVITY_IDS.index(level) if level in SENSITIVITY_IDS else 1,
                           lambda i: self._set("sensitivity", SENSITIVITY_IDS[i]))))
        return card

    def _try_card(self):
        card = self._card("Try it", "Swipe on the touchpad; the gesture and what it did show here.")
        self.try_label = Gtk.Label(label="Waiting for a gesture…", xalign=0)
        self.try_label.add_css_class("try")
        box = Gtk.Box()
        box.add_css_class("row")
        box.append(self.try_label)
        card.append(box)
        return card

    # ---------------------------------------------------------- state

    def _refresh_card(self, fingers):
        labels = {d: G.ACTIONS.get(a, a) for d, a in mapping(self.settings, fingers).items()}
        self.diagrams[fingers].update(labels)
        self.custom_boxes[fingers].set_visible(self.settings[str(fingers)].get("preset") == "custom")

    def _save(self):
        try:
            save_settings(self.settings)
        except OSError as error:
            self._show_banner(f"Couldn't save settings: {error}", None)

    def _set(self, key, value):
        self.settings[key] = value
        self._save()

    def _set_preset(self, fingers, preset):
        group = self.settings[str(fingers)]
        if preset == "custom" and not group.get("custom"):
            # Start a custom set from what was showing, as Windows does.
            group["custom"] = mapping(self.settings, fingers)
        group["preset"] = preset
        self._save()
        self._refresh_card(fingers)

    def _set_custom(self, fingers, direction, action):
        group = self.settings[str(fingers)]
        group.setdefault("custom", {})[direction] = action
        self._save()
        self._refresh_card(fingers)

    def _set_shortcut(self, fingers, direction, text):
        group = self.settings[str(fingers)]
        group.setdefault("shortcut", {})[direction] = text.strip()
        self._save()

    def _set_tap(self, action):
        self.settings["4"]["tap"] = action
        self._save()

    def _on_enabled(self, switch, _pspec):
        self._set("enabled", switch.get_active())
        self._sync_enabled()

    def _sync_enabled(self):
        self.content.set_sensitive(self.settings.get("enabled", True))

    def _reset(self, _button):
        self.settings = json.loads(json.dumps(G.DEFAULTS))
        self._save()
        app = self.get_application()
        self.close()
        app.activate()

    # ---------------------------------------------------------- daemon

    def _show_banner(self, text, button_label, callback=None):
        child = self.banner.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            self.banner.remove(child)
            child = following
        label = Gtk.Label(label=text, xalign=0)
        label.set_wrap(True)
        label.set_hexpand(True)
        self.banner.append(label)
        if button_label:
            button = Gtk.Button(label=button_label)
            button.add_css_class("accent")
            button.connect("clicked", lambda *_: callback())
            self.banner.append(button)
        self.banner.set_visible(True)

    def _check_daemon(self):
        try:
            out = subprocess.run([str(DAEMON), "--status"], capture_output=True,
                                 text=True, timeout=5).stdout
            state = json.loads(out)
        except Exception:
            state = {"readable": True, "running": True}

        if not state.get("readable"):
            self._show_banner(
                "Gestures can't read the touchpad yet. Log out and back in "
                "(your account was added to the input group).", None)
        elif not state.get("running"):
            self._show_banner("The gesture service isn't running.", "Start", self._start_daemon)
        else:
            self.banner.set_visible(False)
        return GLib.SOURCE_CONTINUE

    def _start_daemon(self):
        subprocess.Popen([str(DAEMON), "--daemon"], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        GLib.timeout_add(800, lambda: self._check_daemon() and False)

    def _poll_last(self):
        try:
            record = json.loads(G.LAST_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return GLib.SOURCE_CONTINUE
        if record.get("at", 0) > self.last_seen:
            fresh = self.last_seen != 0.0
            self.last_seen = record["at"]
            if fresh:
                gesture = record.get("gesture", "")
                self.try_label.set_text(f"{gesture.capitalize()}  →  {record.get('label', '')}")
                self.try_label.add_css_class("hit")
                GLib.timeout_add(900, lambda: self.try_label.remove_css_class("hit") or False)
                parts = gesture.split()
                if len(parts) >= 3 and parts[1] == "swipe":
                    fingers = int(parts[0].split("-")[0])
                    if fingers in self.diagrams:
                        self.diagrams[fingers].pulse(parts[2])
        return GLib.SOURCE_CONTINUE


class GestureApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):
        window = self.get_active_window() or GestureWindow(self)
        window.present()


if __name__ == "__main__":
    raise SystemExit(GestureApp().run(None))
