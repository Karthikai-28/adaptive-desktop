#!/usr/bin/env python3
"""Adaptive Command - the system-wide search palette.

Opens centred over the desktop on Alt+Space: one field that searches
applications, files and folders, projects, settings panels and desktop
actions, in the shape of the Command screen in the design system.

Heavy work stays out of the GNOME Shell process by living here (see
docs/COMMAND_PERMISSION_MODEL.md). File search goes through plocate's index
rather than walking the filesystem, and runs off the UI thread so typing never
stalls.
"""

import json
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

APP_ID = "com.karthi.AdaptiveCommand"
HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

# Typing should feel immediate, so results refresh on a short debounce rather
# than on every keystroke.
DEBOUNCE_MS = 90
# Focus can bounce for a moment after the window maps; auto-dismiss only
# once things have settled.
FOCUS_GRACE_S = 0.6
FILE_RESULTS = 8
APP_RESULTS = 6
MAX_ROWS = 24

# Category weights. A launcher is judged on short queries, where "set" means
# Settings and "fire" means the browser - a filename that merely starts with
# the same letters should not outrank them. Files carry no bonus and have their
# match score scaled down, so they win only when nothing else matches well.
WEIGHT_APP = 45
WEIGHT_SETTINGS = 40
WEIGHT_PROJECT = 35
WEIGHT_ACTION = 30
FILE_SCALE = 0.6

# Machine-owned trees. Matches here are real, but they are almost never what
# someone typing into a desktop search is reaching for.
SYSTEM_TREES = (
    "/boot", "/proc", "/sys", "/snap", "/var/lib", "/var/cache",
    "/usr/lib", "/usr/share/doc", "/usr/src",
)

# Section order, and the accent each one carries on its left edge.
GROUPS = [
    ("Applications", "accent"),
    ("Files & Folders", "cyan"),
    ("Projects", "violet"),
    ("Settings", "muted"),
    ("Actions", "accent"),
]


@dataclass
class Result:
    title: str
    subtitle: str
    group: str
    icon: str = "application-x-executable-symbolic"
    badge: str = ""
    gicon: object = None
    action: Optional[Callable] = None
    score: int = 0
    key_hint: str = ""


@dataclass
class Query:
    raw: str = ""
    folded: str = field(default="")

    @classmethod
    def make(cls, text):
        stripped = text.strip()
        return cls(raw=stripped, folded=stripped.casefold())


def score_match(query, *fields):
    """Rank a candidate. Higher is better, 0 means no match.

    Prefix beats word-start beats substring, so typing "fir" puts Firefox above
    a file that merely contains "fir" in the middle of its path.
    """
    if not query.folded:
        return 0

    best = 0
    for weight, value in enumerate(fields):
        if not value:
            continue

        folded = value.casefold()
        if query.folded not in folded:
            continue

        penalty = weight * 4

        if folded.startswith(query.folded):
            best = max(best, 100 - penalty)
        elif re.search(r"\b" + re.escape(query.folded), folded):
            best = max(best, 70 - penalty)
        else:
            best = max(best, 40 - penalty)

    return best


class Palette(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)

        self.set_decorated(False)
        self.set_resizable(False)
        self.set_default_size(720, -1)
        self.add_css_class("adaptive-command")

        self.results = []
        self.selected = 0
        self._debounce = 0
        self._search_serial = 0
        self._file_results = []
        self._apps = []
        self._was_active = False
        self._opened_at = time.monotonic()

        self._load_css()
        self._build()
        self._load_apps()
        self._refresh()

        self.connect("notify::is-active", self._on_active_changed)
        self.connect("map", lambda *_: GLib.idle_add(self._centre))

    def _centre(self):
        """Put the palette where Spotlight sits: centred, high on the screen.

        GTK4 deliberately has no window-move API, so on this X11-only target we
        move our own X window with xdotool - the same tool scripts/window-cli.py
        already uses for placement.
        """
        surface = self.get_surface()
        if surface is None or not shutil.which("xdotool"):
            return GLib.SOURCE_REMOVE

        try:
            xid = surface.get_xid()
        except AttributeError:
            return GLib.SOURCE_REMOVE  # not the X11 backend

        display = Gdk.Display.get_default()
        monitor = display.get_monitor_at_surface(surface)
        if monitor is None:
            return GLib.SOURCE_REMOVE

        area = monitor.get_geometry()
        width = self.get_width() or 720
        height = self.get_height() or 460

        x = area.x + max(0, (area.width - width) // 2)
        y = area.y + max(0, int(area.height * 0.16))

        # Move and focus in one go. Launched from a keybinding there is no
        # startup timestamp to present with, so mutter logs "_NET_ACTIVE_WINDOW
        # message with a timestamp of 0" and focus becomes a coin toss - and a
        # launcher that opens unfocused is useless.
        subprocess.run(
            ["xdotool", "windowmove", str(xid), str(x), str(y),
             "windowraise", str(xid), "windowfocus", str(xid)],
            capture_output=True,
            check=False,
        )

        self._opened_at = time.monotonic()
        return GLib.SOURCE_REMOVE

    # ---------------------------------------------------------------- chrome

    def _load_css(self):
        provider = Gtk.CssProvider()
        provider.load_from_path(str(HERE / "style.css"))
        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

    def _build(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.add_css_class("palette")
        self.set_child(root)

        # --- query row -----------------------------------------------------
        query_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        query_row.add_css_class("query-row")

        glass = Gtk.Image.new_from_icon_name("system-search-symbolic")
        glass.add_css_class("query-icon")
        query_row.append(glass)

        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("Open…")
        self.entry.add_css_class("query")
        self.entry.set_hexpand(True)
        self.entry.set_has_frame(False)
        self.entry.connect("changed", lambda *_: self._queue_refresh())
        self.entry.connect("activate", lambda *_: self._activate_selected())
        query_row.append(self.entry)

        esc = Gtk.Label(label="Esc")
        esc.add_css_class("chip")
        query_row.append(esc)

        root.append(query_row)

        divider = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        divider.add_css_class("rule")
        root.append(divider)

        # --- results -------------------------------------------------------
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_propagate_natural_height(True)
        self.scroll.set_max_content_height(420)
        self.scroll.add_css_class("results-scroll")

        self.results_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.results_box.add_css_class("results")
        self.scroll.set_child(self.results_box)
        root.append(self.scroll)

        # --- footer --------------------------------------------------------
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        footer.add_css_class("footer")

        for label in ("↑↓ navigate", "↵ open", "Esc close"):
            hint = Gtk.Label(label=label)
            hint.add_css_class("hint")
            footer.append(hint)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        footer.append(spacer)

        self.count_label = Gtk.Label(label="")
        self.count_label.add_css_class("hint")
        footer.append(self.count_label)

        root.append(footer)

        keys = Gtk.EventControllerKey()
        # Capture, so Esc and the arrows are ours before the entry sees them,
        # while every other key still reaches the field.
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

    # -------------------------------------------------------------- keyboard

    def _on_key(self, _controller, keyval, _keycode, _state):
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True

        if keyval in (Gdk.KEY_Down, Gdk.KEY_Tab):
            self._move(1)
            return True

        if keyval in (Gdk.KEY_Up, Gdk.KEY_ISO_Left_Tab):
            self._move(-1)
            return True

        return False

    def _move(self, delta):
        if not self.results:
            return

        self.selected = (self.selected + delta) % len(self.results)
        self._paint_selection()

    def _on_active_changed(self, *_):
        # Spotlight behaviour: clicking away dismisses the palette. Only once it
        # has actually held focus, and not during the settling moment right
        # after mapping, when focus can bounce before the window is really up.
        if self.is_active():
            self._was_active = True
            return

        if not self._was_active:
            return

        if time.monotonic() - self._opened_at < FOCUS_GRACE_S:
            return

        self.close()

    # ---------------------------------------------------------------- search

    def _queue_refresh(self):
        if self._debounce:
            GLib.source_remove(self._debounce)

        self._debounce = GLib.timeout_add(DEBOUNCE_MS, self._on_debounce)

    def _on_debounce(self):
        self._debounce = 0
        self._refresh()
        return GLib.SOURCE_REMOVE

    def _refresh(self):
        query = Query.make(self.entry.get_text() if hasattr(self, "entry") else "")

        results = []
        results.extend(self._provide_apps(query))
        results.extend(self._provide_projects(query))
        results.extend(self._provide_settings(query))
        results.extend(self._provide_actions(query))

        if query.folded:
            results.extend(self._file_results)
            self._start_file_search(query)
        else:
            self._file_results = []

        self.results = self._rank(results)
        self.selected = 0
        self._render()

    def _rank(self, results):
        order = {name: index for index, (name, _) in enumerate(GROUPS)}
        results.sort(key=lambda r: (-r.score, order.get(r.group, 99), r.title.casefold()))
        return results[:MAX_ROWS]

    def _start_file_search(self, query):
        if len(query.folded) < 2 or not shutil.which("plocate"):
            return

        self._search_serial += 1
        serial = self._search_serial

        def work():
            found = self._walk_home(query) + self._plocate(query)
            GLib.idle_add(self._file_search_done, serial, self._dedupe(found))

        threading.Thread(target=work, daemon=True).start()

    def _dedupe(self, results):
        """Merge the live and indexed sources, keeping the best score for each
        path and spreading results across folders."""
        best = {}
        for result in results:
            key = (result.subtitle, result.title)
            if key not in best or result.score > best[key].score:
                best[key] = result

        ordered = sorted(best.values(), key=lambda r: -r.score)

        per_folder = {}
        spread = []

        for result in ordered:
            seen = per_folder.get(result.subtitle, 0)
            if seen >= 2:
                continue

            per_folder[result.subtitle] = seen + 1
            spread.append(result)

            if len(spread) >= FILE_RESULTS:
                break

        return spread

    def _walk_home(self, query, budget=0.18):
        """Live scan of home, to cover what the index has not caught up with.

        plocate's database is rebuilt by a daily timer, so anything created
        since - today's work, most of the time - simply does not exist as far
        as it is concerned. This walk is breadth-first, shallow and time-boxed,
        and runs on the worker thread, never the UI one.
        """
        home = Path.home()
        deadline = time.monotonic() + budget
        skip = {
            "node_modules", "__pycache__", "venv", ".venv", "build", "dist",
            "snap", "Trash", "site-packages", "target",
        }

        found = []
        queue = [(home, 0)]

        while queue and time.monotonic() < deadline:
            directory, depth = queue.pop(0)

            try:
                entries = list(directory.iterdir())
            except (PermissionError, OSError):
                continue

            for entry in entries:
                name = entry.name

                if name.startswith(".") or name in skip:
                    continue

                if depth < 4 and entry.is_dir():
                    queue.append((entry, depth + 1))

                score = score_match(query, name)
                if not score:
                    continue

                is_dir = entry.is_dir()
                found.append(
                    Result(
                        title=name,
                        subtitle=str(entry.parent).replace(str(home), "~"),
                        group="Files & Folders",
                        icon="folder-symbolic" if is_dir else "text-x-generic-symbolic",
                        badge="Folder" if is_dir else "File",
                        action=lambda p=entry: self._open_path(p),
                        # Live hits are current by definition, so they edge out
                        # equally-good matches from the stale index.
                        score=int(score * FILE_SCALE) + 10 - min(depth, 6),
                    )
                )

        return found

    def _plocate(self, query):
        try:
            # Ask for far more than is shown. plocate answers in tens of
            # milliseconds, and a small raw limit would let one crowded folder
            # use up the whole budget before ranking ever runs.
            out = subprocess.run(
                ["plocate", "-i", "-l", "400", "-b", query.raw],
                capture_output=True,
                text=True,
                timeout=2,
            ).stdout
        except Exception:
            return []

        home = str(Path.home())
        found = []

        for line in out.splitlines():
            path = Path(line)
            name = path.name

            if name.startswith(".") or "/." in line:
                continue

            score = score_match(query, name)
            if not score:
                continue

            score = int(score * FILE_SCALE)

            # A search for "term" should surface your own files before
            # /boot/grub/terminal.mod, so home outweighs everything else and
            # machine-owned trees are pushed down.
            if line.startswith(home):
                score += 12
            elif any(line.startswith(p) for p in SYSTEM_TREES):
                score -= 25

            score -= min(len(path.parts), 12)

            is_dir = path.is_dir()
            found.append(
                Result(
                    title=name,
                    subtitle=str(path.parent).replace(home, "~"),
                    group="Files & Folders",
                    icon="folder-symbolic" if is_dir else "text-x-generic-symbolic",
                    badge="Folder" if is_dir else "File",
                    action=lambda p=path: self._open_path(p),
                    score=score,
                )
            )

        found.sort(key=lambda r: -r.score)
        return found[: FILE_RESULTS * 4]

    def _file_search_done(self, serial, found):
        if serial != self._search_serial:
            return GLib.SOURCE_REMOVE

        self._file_results = found
        merged = [r for r in self.results if r.group != "Files & Folders"] + found
        self.results = self._rank(merged)
        self.selected = min(self.selected, max(0, len(self.results) - 1))
        self._render()
        return GLib.SOURCE_REMOVE

    # ------------------------------------------------------------- providers

    def _load_apps(self):
        for app in Gio.AppInfo.get_all():
            if app.should_show():
                self._apps.append(app)

    def _provide_apps(self, query):
        if not query.folded:
            return []

        results = []
        for app in self._apps:
            name = app.get_display_name() or app.get_name() or ""
            score = score_match(query, name, app.get_description() or "")
            if not score:
                continue

            results.append(
                Result(
                    title=name,
                    subtitle=app.get_description() or "Application",
                    group="Applications",
                    gicon=app.get_icon(),
                    badge="App",
                    action=lambda a=app: a.launch([], None),
                    score=score + WEIGHT_APP,
                )
            )

        results.sort(key=lambda r: -r.score)
        return results[:APP_RESULTS]

    def _provide_projects(self, query):
        path = Path.home() / ".config/adaptive-desktop/projects.json"
        if not path.exists():
            return []

        try:
            projects = json.loads(path.read_text(encoding="utf-8")).get("projects", {})
        except Exception:
            return []

        home = str(Path.home())

        results = []
        for pid, project in projects.items():
            name = project.get("name", pid)
            where = project.get("path", "")

            # Match the path below home only. The "/home/<user>" prefix is in
            # every project path, so searching your own username would
            # otherwise score every project as a hit.
            below_home = where[len(home):] if where.startswith(home) else where

            score = score_match(query, name, below_home) if query.folded else 60

            if not score:
                continue

            results.append(
                Result(
                    title=name,
                    subtitle=where.replace(str(Path.home()), "~"),
                    group="Projects",
                    icon="folder-open-symbolic",
                    badge="Project",
                    action=lambda target=pid: self._run(["./scripts/project-cli.py", "switch", target]),
                    score=score + WEIGHT_PROJECT,
                )
            )

        return results

    def _provide_settings(self, query):
        panels = [
            ("Appearance", "appearance"),
            ("Display & Graphics", "display"),
            ("Sound", "sound"),
            ("Input & Gestures", "keyboard"),
            ("Network & Connectivity", "network"),
            ("Power & Battery", "power"),
            ("Privacy & Security", "privacy"),
            ("Accessibility", "universal-access"),
            ("Accounts & Sync", "online-accounts"),
            ("About", "info-overview"),
        ]

        results = []
        for title, panel in panels:
            score = score_match(query, title, "settings")
            if not score:
                continue

            results.append(
                Result(
                    title=f"{title} Settings",
                    subtitle="System settings",
                    group="Settings",
                    icon="preferences-system-symbolic",
                    badge="Settings",
                    action=lambda p=panel: self._run(["gnome-control-center", p]),
                    score=score + WEIGHT_SETTINGS,
                )
            )

        return results

    def _provide_actions(self, query):
        actions = [
            ("Open Files", "Browse your files", "folder-symbolic", "R",
             lambda: self._open_path(Path.home())),
            ("Open Terminal Here", "New terminal in home", "utilities-terminal-symbolic", "T",
             lambda: self._run(["gnome-terminal"])),
            ("Enter Focus Mode", "Hold notifications", "weather-clear-night-symbolic", "F",
             lambda: self._run(["./scripts/focus-cli.py", "on"])),
            ("Exit Focus Mode", "Show notifications again", "weather-clear-symbolic", "",
             lambda: self._run(["./scripts/focus-cli.py", "off"])),
            ("System Center", "Settings and system control", "preferences-system-symbolic", "S",
             lambda: self._run(["gnome-control-center"])),
            ("Smart Tile Window", "Tile the active window", "view-grid-symbolic", "",
             lambda: self._run(["./scripts/window-cli.py", "tile", "smart"])),
            ("Toggle Fullscreen", "Fullscreen the active window", "view-fullscreen-symbolic", "",
             lambda: self._run(["./scripts/window-cli.py", "fullscreen"])),
            ("Save Window Placement", "Remember this project's layout", "document-save-symbolic", "",
             lambda: self._run(["./scripts/window-cli.py", "save-project"])),
            ("Restore Window Placement", "Restore this project's layout", "view-restore-symbolic", "",
             lambda: self._run(["./scripts/window-cli.py", "restore-project"])),
            ("Return to Ubuntu", "Log out of the Adaptive session", "system-log-out-symbolic", "",
             lambda: self._run(["gnome-session-quit", "--logout"])),
        ]

        results = []
        for title, subtitle, icon, key, action in actions:
            # With an empty field the palette shows what it can do, like the
            # ACTIONS list in the design.
            score = score_match(query, title, subtitle) if query.folded else 50

            if not score:
                continue

            results.append(
                Result(
                    title=title,
                    subtitle=subtitle,
                    group="Actions",
                    icon=icon,
                    badge="Action",
                    key_hint=key,
                    action=action,
                    score=score + WEIGHT_ACTION,
                )
            )

        return results

    # ---------------------------------------------------------------- render

    def _render(self):
        child = self.results_box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.results_box.remove(child)
            child = nxt

        self.row_widgets = []

        if not self.results:
            empty = Gtk.Label(label="No results")
            empty.add_css_class("empty")
            self.results_box.append(empty)
            self.count_label.set_text("")
            return

        accents = dict(GROUPS)
        rendered_groups = set()

        for index, result in enumerate(self.results):
            # The strongest hit gets its own section, as in the design.
            if index == 0:
                self.results_box.append(self._section("Best match"))
            elif result.group not in rendered_groups:
                self.results_box.append(self._section(result.group))
                rendered_groups.add(result.group)

            row = self._row(result, accents.get(result.group, "accent"))
            self.results_box.append(row)
            self.row_widgets.append(row)

        self.count_label.set_text(f"{len(self.results)} results")
        self._paint_selection()

    def _section(self, title):
        label = Gtk.Label(label=title.upper(), xalign=0)
        label.add_css_class("section")
        return label

    def _row(self, result, accent):
        button = Gtk.Button()
        button.add_css_class("row")
        button.add_css_class(f"accent-{accent}")
        button.connect("clicked", lambda _b, r=result: self._activate(r))

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        if result.gicon is not None:
            icon = Gtk.Image.new_from_gicon(result.gicon)
        else:
            icon = Gtk.Image.new_from_icon_name(result.icon)
        icon.add_css_class("row-icon")
        icon.set_pixel_size(22)
        box.append(icon)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        text.set_hexpand(True)

        title = Gtk.Label(label=result.title, xalign=0)
        title.add_css_class("row-title")
        title.set_ellipsize(Pango.EllipsizeMode.END)
        text.append(title)

        if result.subtitle:
            subtitle = Gtk.Label(label=result.subtitle, xalign=0)
            subtitle.add_css_class("row-subtitle")
            subtitle.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            text.append(subtitle)

        box.append(text)

        if result.badge:
            badge = Gtk.Label(label=result.badge)
            badge.add_css_class("badge")
            box.append(badge)

        if result.key_hint:
            key = Gtk.Label(label=result.key_hint)
            key.add_css_class("chip")
            box.append(key)

        button.set_child(box)
        return button

    def _paint_selection(self):
        # Selection is drawn, never focused. Focusing the row would move focus
        # off the entry and silently swallow everything typed next.
        selected_row = None

        for index, row in enumerate(getattr(self, "row_widgets", [])):
            if index == self.selected:
                row.add_css_class("selected")
                selected_row = row
            else:
                row.remove_css_class("selected")

        if selected_row is not None:
            self._scroll_into_view(selected_row)

    def _scroll_into_view(self, row):
        adjustment = self.scroll.get_vadjustment()
        if adjustment is None:
            return

        ok, rect = row.compute_bounds(self.results_box)
        if not ok:
            return

        top = rect.origin.y
        bottom = top + rect.size.height
        page = adjustment.get_page_size()
        value = adjustment.get_value()

        if top < value:
            adjustment.set_value(top)
        elif bottom > value + page:
            adjustment.set_value(bottom - page)

    # --------------------------------------------------------------- actions

    def _activate_selected(self):
        if self.results:
            self._activate(self.results[self.selected])

    def _activate(self, result):
        self.close()

        if result.action is None:
            return

        try:
            result.action()
        except Exception as error:  # noqa: BLE001 - surface, never crash the palette
            print(f"adaptive-command: {result.title} failed: {error}")

    def _run(self, argv):
        subprocess.Popen(argv, cwd=str(REPO), start_new_session=True)

    def _open_path(self, path):
        Gio.AppInfo.launch_default_for_uri(Path(path).as_uri(), None)

    def reset(self):
        self.entry.set_text("")
        self._file_results = []
        self._refresh()
        self.entry.grab_focus()


class CommandApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)

    def do_activate(self):
        window = self.props.active_window

        # Re-triggering the shortcut while it is open should toggle it away,
        # the way Spotlight does.
        if window and window.is_visible():
            window.close()
            return

        window = Palette(self)
        window.present()
        window.reset()


if __name__ == "__main__":
    # Without this the palette reports WM_CLASS "python3", which loses it its
    # icon and makes it invisible to window rules and scripted lookups.
    GLib.set_prgname(APP_ID)
    CommandApp().run()
