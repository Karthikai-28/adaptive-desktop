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
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import providers as P  # noqa: E402
import modes as M  # noqa: E402

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
# An answer to the question typed (a sum, a conversion) or an explicit mode
# (":" for emoji, "clip" for the clipboard) is what was asked for, so it
# outranks every ordinary match.
WEIGHT_ANSWER = 300
WEIGHT_WINDOW = 42
WEIGHT_WORKSPACE = 25
WINDOW_RESULTS = 6
CLIPBOARD_RESULTS = 10

# Machine-owned trees. Matches here are real, but they are almost never what
# someone typing into a desktop search is reaching for.
SYSTEM_TREES = (
    "/boot", "/proc", "/sys", "/snap", "/var/lib", "/var/cache",
    "/usr/lib", "/usr/share/doc", "/usr/src",
)

# Section order, and the accent each one carries on its left edge.
GROUPS = [
    ("Calculator", "accent"),
    ("Computer", "accent"),
    ("Clipboard", "violet"),
    ("Emoji", "accent"),
    ("Snippets", "accent"),
    ("Tasks", "accent"),
    ("In Files", "cyan"),
    ("Git", "violet"),
    ("Time", "muted"),
    ("Processes", "accent"),
    ("SSH", "cyan"),
    ("Branches", "violet"),
    ("Timer", "accent"),
    ("Shortcuts", "muted"),
    ("New Project", "violet"),
    ("Windows", "cyan"),
    ("Applications", "accent"),
    ("Files & Folders", "cyan"),
    ("Projects", "violet"),
    ("Settings", "muted"),
    ("Actions", "accent"),
    ("Workspaces", "muted"),
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
    # Text to put in the field instead of running anything: how a mode is entered.
    fill: str = ""
    # A second thing to do with the row, on Ctrl+P, that keeps the palette
    # open (pinning a clipboard entry), and the footer hint that says so.
    alt: Optional[Callable] = None
    alt_hint: str = ""
    # Said in place of the subtitle on the first Enter; only a second Enter
    # on the same row runs it. For what cannot be taken back.
    confirm: str = ""


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
        self._armed = None   # the row waiting for its second Enter
        self._file_results = []
        self._mode_results = []
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

        # What Ctrl+P does on the selected row, when it does anything.
        self.alt_label = Gtk.Label(label="")
        self.alt_label.add_css_class("hint")
        footer.append(self.alt_label)

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

    def _on_key(self, _controller, keyval, _keycode, state):
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True

        if keyval in (Gdk.KEY_p, Gdk.KEY_P) and state & Gdk.ModifierType.CONTROL_MASK:
            self._alt_selected()
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

    def _alt_selected(self):
        """Ctrl+P: the selected row's second action, keeping the palette open."""
        if not self.results or self.results[self.selected].alt is None:
            return
        keep = self.selected
        try:
            self.results[keep].alt()
        except Exception as error:  # noqa: BLE001 - surface, never crash the palette
            print(f"adaptive-command: {self.results[keep].title} failed: {error}")
        self._refresh()
        self.selected = min(keep, max(0, len(self.results) - 1))
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
        results.extend(self._provide_answers(query))
        results.extend(self._provide_clipboard(query))
        results.extend(self._provide_emoji(query))
        results.extend(self._provide_modes(query))
        results.extend(self._provide_windows(query))
        results.extend(self._provide_workspaces(query))
        results.extend(self._provide_apps(query))
        results.extend(self._provide_projects(query))
        results.extend(self._provide_settings(query))
        results.extend(self._provide_actions(query))

        if query.folded:
            results.extend(self._file_results)
            results.extend(self._mode_results)
            self._start_file_search(query)
        else:
            self._file_results = []
            self._mode_results = []

        self.results = self._rank(results)
        self.selected = 0
        self._render()

    def _rank(self, results):
        order = {name: index for index, (name, _) in enumerate(GROUPS)}
        results.sort(key=lambda r: (-r.score, order.get(r.group, 99), r.title.casefold()))
        return results[:MAX_ROWS]

    def _start_file_search(self, query):
        """Everything too slow for the UI thread: files, and the modes that
        run git or ripgrep. One worker per keystroke; a stale one is ignored."""
        if len(query.folded) < 2:
            return

        self._search_serial += 1
        serial = self._search_serial
        mode, rest = M.mode_of(query.raw)

        def work():
            found = []
            if mode is None:
                found = self._walk_home(query)
                if shutil.which("plocate"):
                    found += self._fresh_index(query) + self._plocate(query)
            slow = self._slow_mode_rows(mode, rest)
            # Said in ordinary words, something for the computer to do
            # ("turn off bluetooth", "what's using the memory").
            asked = P.ask_link(query.raw) if mode is None else []
            GLib.idle_add(self._file_search_done, serial, self._dedupe(found), slow, asked)

        threading.Thread(target=work, daemon=True).start()

    def _slow_mode_rows(self, mode, rest):
        if mode == "git":
            return M.git_rows(self._projects())
        if mode == "grep":
            _pid, _name, root = self._active_project()
            if not root:
                return [M.row("No active project", "Searching inside files works on the active project",
                              "In Files", "text-x-generic-symbolic", score=WEIGHT_ANSWER)]
            if len(rest) < M.CONTENT_MIN_CHARS:
                return [M.row("Search inside the project", f"Type at least {M.CONTENT_MIN_CHARS} characters",
                              "In Files", "text-x-generic-symbolic", score=WEIGHT_ANSWER)]
            rows = M.content_rows(M.content_search(root, rest), root)
            return rows or [M.row("Nothing in the project's files matches", root.replace(str(Path.home()), "~"),
                                  "In Files", "text-x-generic-symbolic", score=WEIGHT_ANSWER)]
        return []

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

    def _fresh_index(self, query):
        """The home index kept fresh by scripts/adaptive-index.sh, if it is
        there: plocate's system database is rebuilt once a day at best."""
        database = Path.home() / ".cache/adaptive-desktop/home.plocate.db"
        return self._plocate(query, database) if database.exists() else []

    def _plocate(self, query, database=None):
        try:
            # Ask for far more than is shown. plocate answers in tens of
            # milliseconds, and a small raw limit would let one crowded folder
            # use up the whole budget before ranking ever runs.
            out = subprocess.run(
                ["plocate", "-i", "-l", "400", "-b"]
                + (["-d", str(database)] if database else []) + [query.raw],
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

    def _ask_rows(self, asked):
        """What the words typed could mean for the computer to do, each as a
        row that says exactly what Enter will do.

        One that could cut the computer off or lose work (sleep, restart,
        shut down, Wi-Fi off) is never put first - "restart firefox" and
        "sleep tracker" are not asking for that - and Enter on it only asks
        for a second Enter."""
        rows = []
        for match in asked[:3]:
            careful = {"cuts": "May disconnect the phone", "destroys": "Cannot be undone"}.get(match.get("risk"), "")
            rows.append(Result(
                title=match["say"], subtitle=careful or "Enter does it", group="Computer",
                icon="system-run-symbolic", badge="Careful" if careful else "Do",
                action=lambda m=match, sure=bool(careful): self._do_asked(m, confirmed=sure),
                confirm=f"{careful} - press Enter again to do it" if careful else "",
                # Clearly meant: above everything. Only possibly meant, or careful: among the rest.
                score=WEIGHT_ANSWER - 10 if match.get("sure") and not careful else 30))
        return rows

    def _do_asked(self, match, confirmed=False):
        def work():
            done, said = P.do_link(match["id"], match.get("args") or {}, confirmed=confirmed)
            GLib.idle_add(self._notify, said or (match["say"] if done else "It did not work"))
        threading.Thread(target=work, daemon=True).start()

    def _file_search_done(self, serial, found, slow_rows=(), asked=()):
        if serial != self._search_serial:
            return GLib.SOURCE_REMOVE

        self._file_results = found
        self._mode_results = [self._as_result(r) for r in slow_rows] + self._ask_rows(list(asked))
        slow_groups = {"Git", "In Files", "Computer"}
        merged = [r for r in self.results
                  if r.group != "Files & Folders" and r.group not in slow_groups]
        merged += found + self._mode_results
        self.results = self._rank(merged)
        self.selected = min(self.selected, max(0, len(self.results) - 1))
        self._render()
        return GLib.SOURCE_REMOVE

    # ------------------------------------------------------------- providers

    def _load_apps(self):
        for app in Gio.AppInfo.get_all():
            if app.should_show():
                self._apps.append(app)

    # ----------------------------------------- answers, shell-backed results

    def _provide_answers(self, query):
        results = []
        value = P.calculate(query.raw)
        if value is not None:
            results.append(Result(
                title=f"= {value}", subtitle="Enter copies the result", group="Calculator",
                icon="accessories-calculator-symbolic", badge="Copy",
                action=lambda v=value: self._copy(v), score=WEIGHT_ANSWER))
        converted = P.convert(query.raw)
        if converted is not None:
            answer = converted.split(" = ", 1)[1].split(" ")[0]
            results.append(Result(
                title=converted, subtitle="Enter copies the number", group="Calculator",
                icon="accessories-calculator-symbolic", badge="Copy",
                action=lambda v=answer: self._copy(v), score=WEIGHT_ANSWER))
        return results

    def _provide_clipboard(self, query):
        wanted = P.clipboard_query(query.raw)
        if wanted is None:
            return []
        history = P.shell_json("ClipboardHistory", default=None)
        if history is None:
            return [Result(title="Clipboard history is unavailable",
                           subtitle="It lives in the Adaptive shell, which is not answering",
                           group="Clipboard", icon="edit-paste-symbolic", score=WEIGHT_ANSWER)]
        results = []
        for rank, item in enumerate(P.clipboard_entries(history, wanted, CLIPBOARD_RESULTS)):
            pinned = bool(item.get("pinned"))
            is_image = item.get("kind") == "image"
            # An image has no text to hand back, and an entry with an id is
            # copied by it; older shells without ids still copy the text.
            if item.get("id"):
                copy = lambda i=item["id"], t=item.get("text", ""): (  # noqa: E731
                    P.shell_call("ClipboardCopyItem", "(u)", (i,)) or (t and self._copy(t)))
            else:
                copy = lambda t=item.get("text", ""): self._copy(t)  # noqa: E731
            result = Result(
                title=item["title"],
                subtitle=" · ".join(x for x in ("Pinned" if pinned else "", self._ago(item.get("at", 0)),
                                                 item["detail"]) if x),
                group="Clipboard",
                icon="image-x-generic-symbolic" if is_image else "edit-paste-symbolic",
                badge="Copy", action=copy, score=WEIGHT_ANSWER - rank)
            if item.get("id"):
                result.alt = lambda i=item["id"], p=pinned: P.shell_call("ClipboardPin", "(ub)", (i, not p))
                result.alt_hint = "Ctrl+P unpin" if pinned else "Ctrl+P pin"
            results.append(result)
        if not results:
            results.append(Result(title="Nothing copied yet" if not wanted else "No match in the clipboard",
                                  subtitle="Text and images you copy this session show up here",
                                  group="Clipboard", icon="edit-paste-symbolic", score=WEIGHT_ANSWER))
        return results

    def _provide_emoji(self, query):
        return [
            Result(title=f"{char}  {name}", subtitle="Enter copies it", group="Emoji",
                   icon="face-smile-symbolic", badge="Copy",
                   action=lambda c=char: self._copy(c), score=WEIGHT_ANSWER - rank)
            for rank, (char, name) in enumerate(P.emoji(query.raw))
        ]

    def _provide_windows(self, query):
        if len(query.folded) < 2 or P.clipboard_query(query.raw) is not None or query.raw.startswith(":"):
            return []
        windows = P.match_windows(P.shell_json("ListWindows", default=[]), query.raw)
        results = []
        for window in windows[:WINDOW_RESULTS]:
            where = window.get("workspaceName") or (
                f"Workspace {window['workspace'] + 1}" if window.get("workspace", -1) >= 0 else "")
            subtitle = " · ".join(x for x in (window.get("appName", ""), where,
                                               "minimized" if window.get("minimized") else "") if x)
            gicon = None
            if window.get("app"):
                try:
                    info = Gio.DesktopAppInfo.new(window["app"])
                    gicon = info.get_icon() if info else None
                except TypeError:
                    gicon = None
            results.append(Result(
                title=window.get("title") or window.get("appName", "Window"), subtitle=subtitle,
                group="Windows", gicon=gicon, icon="focus-windows-symbolic", badge="Window",
                action=lambda i=window["id"]: P.shell_call("ActivateWindow", "(u)", (i,)),
                score=score_match(query, window.get("title", ""), window.get("appName", "")) + WEIGHT_WINDOW))
        return results

    def _provide_workspaces(self, query):
        if len(query.folded) < 2:
            return []
        try:
            source = Gio.SettingsSchemaSource.get_default()
            if not source or not source.lookup("org.gnome.desktop.wm.preferences", True):
                return []
            names = Gio.Settings.new("org.gnome.desktop.wm.preferences").get_strv("workspace-names")
        except GLib.Error:
            return []
        results = []
        for index, name in enumerate(names):
            score = score_match(query, name, "workspace") if name else 0
            if score:
                results.append(Result(
                    title=f"Go to {name}", subtitle=f"Workspace {index + 1}", group="Workspaces",
                    icon="view-grid-symbolic", badge="Workspace",
                    action=lambda i=index: P.shell_call("ActivateWorkspace", "(i)", (i,)),
                    score=score + WEIGHT_WORKSPACE))
        return results

    # ------------------------------------------------------------------ modes

    def _projects(self):
        try:
            path = Path.home() / ".config/adaptive-desktop/projects.json"
            return json.loads(path.read_text(encoding="utf-8")).get("projects", {})
        except (OSError, ValueError):
            return {}

    def _project_call(self, method):
        """One call to the Project Context Service; None if it is not answering."""
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            reply = bus.call_sync(
                "org.adaptive.ProjectContext", "/org/adaptive/ProjectContext",
                "org.adaptive.ProjectContext", method, None, None,
                Gio.DBusCallFlags.NO_AUTO_START, 1500, None)
            return reply.unpack()
        except GLib.Error:
            return None

    def _active_project(self):
        """(id, name, path); empty strings when no project is active."""
        return self._project_call("GetActiveProject") or ("", "", "")

    def _as_result(self, data):
        spec = data.get("action")
        return Result(
            title=data["title"], subtitle=data["subtitle"], group=data["group"],
            icon=data["icon"], badge=data["badge"], score=data["score"],
            action=(lambda a=spec: self._perform(a)) if spec else None)

    def _provide_modes(self, query):
        mode, rest = M.mode_of(query.raw)
        if mode is None or mode in ("git", "grep"):
            return []  # git and grep run on the worker thread
        if mode == "snip":
            rows = M.snippet_rows(rest)
        elif mode == "todo":
            rows = M.task_rows(rest, self._active_project()[1])
        elif mode == "time":
            reply = self._project_call("GetTimeReport")
            try:
                report = json.loads(reply[0]) if reply else None
            except ValueError:
                report = None
            rows = M.time_rows(report)
        elif mode == "kill":
            rows = M.process_rows(rest, M.list_processes() if len(rest) >= 2 else [])
        elif mode == "ssh":
            try:
                config = (Path.home() / ".ssh" / "config").read_text(encoding="utf-8", errors="replace")
            except OSError:
                config = ""
            rows = M.ssh_rows(rest, M.parse_ssh_hosts(config))
        elif mode == "branch":
            _pid, _name, root = self._active_project()
            branches, current = M.list_branches(root) if root else ([], "")
            rows = M.branch_rows(rest, root, branches, current)
        elif mode == "timer":
            rows = M.timer_rows(rest)
        elif mode == "keys":
            rows = M.shortcut_rows(rest, self._shortcuts())
        elif mode == "new":
            rows = M.new_project_rows(rest, M.extras.load_templates(
                (REPO / "config" / "project-templates", M.extras.USER_TEMPLATES)))
        else:
            rows = []
        return [self._as_result(r) for r in rows]

    def _shortcuts(self):
        """[(title, accelerator)]: Adaptive's own, then the GNOME ones worth
        knowing. Read from gsettings, so an edited shortcut shows as it is."""
        found = []
        source = Gio.SettingsSchemaSource.get_default()

        def settings(schema):
            return Gio.Settings.new(schema) if source and source.lookup(schema, True) else None

        media = settings("org.gnome.settings-daemon.plugins.media-keys")
        if media:
            for path in media.get_strv("custom-keybindings"):
                if "/adaptive-" not in path:
                    continue
                custom = Gio.Settings.new_with_path(
                    "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding", path)
                found.append((custom.get_string("name").replace("Adaptive ", "", 1),
                              custom.get_string("binding")))

        gnome = (
            ("org.gnome.shell.keybindings", "toggle-overview", "Overview"),
            ("org.gnome.shell.keybindings", "toggle-application-view", "Applications"),
            ("org.gnome.shell.keybindings", "toggle-message-tray", "Notifications (Shade)"),
            ("org.gnome.shell.keybindings", "show-screenshot-ui", "Screenshot and screen recording"),
            ("org.gnome.desktop.wm.keybindings", "switch-applications", "Switch applications"),
            ("org.gnome.desktop.wm.keybindings", "switch-windows", "Switch windows"),
            ("org.gnome.desktop.wm.keybindings", "close", "Close window"),
            ("org.gnome.desktop.wm.keybindings", "minimize", "Minimize window"),
            ("org.gnome.desktop.wm.keybindings", "toggle-maximized", "Maximize or restore window"),
            ("org.gnome.desktop.wm.keybindings", "activate-window-menu", "Window menu"),
            ("org.gnome.desktop.wm.keybindings", "switch-to-workspace-left", "Workspace to the left"),
            ("org.gnome.desktop.wm.keybindings", "switch-to-workspace-right", "Workspace to the right"),
            ("org.gnome.desktop.wm.keybindings", "move-to-workspace-left", "Move window one workspace left"),
            ("org.gnome.desktop.wm.keybindings", "move-to-workspace-right", "Move window one workspace right"),
            ("org.gnome.mutter.keybindings", "switch-monitor", "Switch display mode"),
            ("org.gnome.settings-daemon.plugins.media-keys", "screensaver", "Lock screen"),
        )
        for schema, key, title in gnome:
            group = settings(schema)
            if group and group.props.settings_schema.has_key(key):
                for accel in group.get_strv(key)[:1]:
                    found.append((title, accel))

        found.append(("Open the dock app in that position", "<Super>1"))
        return found

    def _perform(self, spec):
        """Carry out a mode row's action (see modes.py for the forms)."""
        kind = spec[0]
        if kind == "copy":
            self._copy(spec[1])
        elif kind == "run":
            subprocess.Popen(spec[1], cwd=spec[2] or str(REPO), start_new_session=True)
        elif kind == "run-notify":
            self._run_notify(spec[1], spec[2], spec[3])
        elif kind == "open":
            argv = M.editor_argv(spec[1], spec[2])
            if argv:
                subprocess.Popen(argv, start_new_session=True)
            else:
                self._open_path(spec[1])
        elif kind == "signal":
            ok = M.end_process(spec[1], spec[2])
            self._notify("Asked the process to quit" if ok else "That process had already gone")
        elif kind == "task-done":
            M.complete_task(spec[1], spec[2])
        elif kind == "snippet-save":
            self._save_snippet(spec[1])
        elif kind == "snippet-delete":
            M.delete_snippet(spec[1])
        elif kind == "timer":
            subprocess.Popen(M.timer_argv(spec[1], spec[2]), start_new_session=True)

    def _run_notify(self, title, argv, cwd=None):
        subprocess.Popen([str(REPO / "scripts" / "adaptive-run-notify.py"), title, "--", *argv],
                         cwd=cwd or str(REPO), start_new_session=True)

    def _notify(self, body):
        subprocess.Popen(["notify-send", "--app-name=Adaptive Command", "Command", body],
                         start_new_session=True)

    def _save_snippet(self, name):
        # The newest clipboard entry, from the shell's history when it is
        # there, otherwise from the clipboard itself.
        history = P.shell_json("ClipboardHistory", default=None)
        if history:
            error = M.add_snippet(name, history[0].get("text", ""))
            self._notify(error or f"Saved snippet “{name}”")
            return

        app = self.get_application()
        app.hold()  # the window is closing; stay alive for the read

        def done(clipboard, result):
            try:
                text = clipboard.read_text_finish(result) or ""
            except GLib.Error:
                text = ""
            error = M.add_snippet(name, text)
            self._notify(error or f"Saved snippet “{name}”")
            app.release()

        Gdk.Display.get_default().get_clipboard().read_text_async(None, done)

    def _copy(self, text):
        # Through the shell, which owns the clipboard after the palette closes.
        if P.shell_call("ClipboardCopy", "(s)", (text,)) is None:
            clipboard = Gdk.Display.get_default().get_clipboard()
            clipboard.set_content(Gdk.ContentProvider.new_for_value(text))

    def _in_background(self, method, signature=None, args=None):
        threading.Thread(target=P.shell_call, args=(method, signature, args, 15000),
                         daemon=True).start()

    @staticmethod
    def _ago(stamp):
        if not stamp:
            return ""
        delta = max(0, int(time.time()) - int(stamp))
        for size, unit in ((86400, "d"), (3600, "h"), (60, "min")):
            if delta >= size:
                return f"{delta // size} {unit} ago"
        return "just now"

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

        # The Adaptive-only sections live in apps/adaptive-settings, because
        # gnome-control-center has no panel for them. Keywords cover what each
        # section holds, so "shortcut" or "verification" finds the right one.
        adaptive = [
            ("Projects & Workspaces", "projects", "project workspace focus"),
            ("Search & Commands", "search", "shortcut keybinding index plocate palette"),
            ("Updates & Recovery", "system", "update session recovery ubuntu verification lid"),
        ]
        for title, section, keywords in adaptive:
            score = score_match(query, title, "settings", keywords)
            if not score:
                continue

            results.append(
                Result(
                    title=title,
                    subtitle="Adaptive settings",
                    group="Settings",
                    icon="preferences-desktop-symbolic",
                    badge="Settings",
                    action=lambda s=section: self._run(
                        ["./scripts/adaptive-settings-launch.sh", "--section", s]),
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
            ("Park Project", "Save and close the active project's windows", "media-playback-pause-symbolic", "",
             lambda: self._in_background("ParkProject", "(s)", ("",))),
            ("Resume Project", "Reopen the active project's parked windows", "media-playback-start-symbolic", "",
             lambda: self._in_background("ResumeProject", "(s)", ("",))),
            ("Quick Note", "One line into the project's inbox", "document-edit-symbolic", "",
             lambda: self._run(["./scripts/adaptive-quick-note.py"])),
            ("Copy Text from Screen", "Select an area and copy the words in it", "insert-text-symbolic", "",
             lambda: self._in_background("CopyScreenText")),
            ("Clear Clipboard History", "Forget what was copied, except what is pinned", "edit-clear-all-symbolic", "",
             lambda: self._in_background("ClipboardClear")),
            ("Annotate a Screenshot", "Select an area, then draw on it", "applets-screenshooter-symbolic", "",
             lambda: self._run(["./apps/adaptive-annotate/main.py"])),
            ("Drop-down Terminal", "Show or hide the terminal at the top of the screen", "utilities-terminal-symbolic", "",
             lambda: self._in_background("Run", "(s)", ("dropdown-terminal",))),
            ("Pair Phone", "Show the code the Adaptive Link app scans", "phone-symbolic", "",
             lambda: self._run(["./scripts/link-cli.py", "pair"])),
            ("Turn Phone Link Off", "Stop accepting the paired phone, and end what it is doing", "network-offline-symbolic", "",
             lambda: self._run_notify("Phone link", ["./scripts/link-cli.py", "off"])),
            ("Turn Phone Link On", "Accept the paired phone again", "network-transmit-receive-symbolic", "",
             lambda: self._run_notify("Phone link", ["./scripts/link-cli.py", "on"])),
            ("Send Clipboard to Phone", "To the first paired phone in reach", "phone-symbolic", "",
             lambda: self._run(["python3", "./shell/adaptive-shell@local/tools/phone_info.py", "clipboard-first", "--notify"])),
            ("Export Adaptive Settings", "One archive, to move to another machine", "document-send-symbolic", "",
             lambda: self._run_notify("Export Adaptive settings", ["./scripts/adaptive-backup.py", "export"])),
            ("Rebuild File Index", "Refresh the index of your home folder now", "view-refresh-symbolic", "",
             lambda: self._run_notify("File index", ["bash", "-c",
                                      "./scripts/adaptive-index.sh && ./scripts/adaptive-index.sh --status"])),
            ("Return to Ubuntu", "Log out of the Adaptive session", "system-log-out-symbolic", "",
             lambda: self._run(["gnome-session-quit", "--logout"])),
        ]

        for command in M.user_commands():
            actions.append((command["title"], command["description"], "system-run-symbolic", "",
                            lambda c=command: self._run_notify(c["title"], [c["path"]], str(Path.home()))))

        modes = [
            ("Snippets", "snip ", "Saved text: snip, snip save <name>", "edit-paste-symbolic"),
            ("Tasks", "todo ", "The project's quick-note inbox as tasks", "checkbox-checked-symbolic"),
            ("Git Status of All Projects", "git ", "Branches and uncommitted or unpushed work", "emblem-important-symbolic"),
            ("Project Time", "time ", "Time per project, today and this week", "preferences-system-time-symbolic"),
            ("Search Inside Project Files", "grep ", "Type /text or grep text", "text-x-generic-symbolic"),
            ("Switch Git Branch", "branch ", "Branches of the active project", "media-playlist-shuffle-symbolic"),
            ("Start a Timer", "timer ", "timer 10m tea", "alarm-symbolic"),
            ("Keyboard Shortcuts", "keys ", "Every Adaptive shortcut", "input-keyboard-symbolic"),
            ("End a Process", "kill ", "kill <name>", "process-stop-symbolic"),
            ("SSH to a Host", "ssh ", "Hosts from ~/.ssh/config", "network-server-symbolic"),
            ("New Project from Template", "new ", "new <template> <folder>", "folder-new-symbolic"),
        ]

        results = []
        in_mode = M.mode_of(query.raw)[0] is not None
        for title, prefix, subtitle, icon in modes:
            # A mode is entered, not run: Enter types its word into the field.
            score = score_match(query, title, subtitle) if query.folded and not in_mode else 0
            if score:
                results.append(Result(
                    title=title, subtitle=subtitle, group="Actions", icon=icon, badge="Mode",
                    score=score + WEIGHT_ACTION - 1, key_hint=prefix.strip(), fill=prefix))

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
            self.alt_label.set_text("")
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

        chosen = self.results[self.selected] if self.selected < len(self.results) else None
        self.alt_label.set_text(chosen.alt_hint if chosen else "")

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
        if result.confirm and self._armed is not result:
            self._armed = result
            result.subtitle, result.badge = result.confirm, "Enter again"
            keep = self.selected
            self._render()
            self.selected = min(keep, max(0, len(self.results) - 1))
            self._paint_selection()
            return

        if result.fill:
            self.entry.set_text(result.fill)
            self.entry.set_position(-1)
            self.entry.grab_focus_without_selecting()
            return

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

    def reset(self, query=None):
        self.entry.set_text(query or "")
        self._file_results = []
        self._mode_results = []
        self._refresh()
        self.entry.grab_focus_without_selecting()
        self.entry.set_position(-1)


class CommandApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)

    def do_command_line(self, command_line):
        # "--query todo" opens the palette already in a mode, for the menus
        # that lead into one (the project menu's Tasks, for instance).
        arguments = command_line.get_arguments()[1:]
        query = None
        if "--query" in arguments and arguments.index("--query") + 1 < len(arguments):
            query = arguments[arguments.index("--query") + 1]
        self._open(query)
        return 0

    def do_activate(self):
        self._open(None)

    def _open(self, query):
        window = self.props.active_window

        # Re-triggering the shortcut while it is open should toggle it away,
        # the way Spotlight does. Asked for a mode, it switches to it instead.
        if window and window.is_visible():
            if query is None:
                window.close()
                return
            window.reset(query)
            return

        window = Palette(self)
        window.present()
        window.reset(query)


if __name__ == "__main__":
    # Without this the palette reports WM_CLASS "python3", which loses it its
    # icon and makes it invisible to window rules and scripted lookups.
    GLib.set_prgname(APP_ID)
    CommandApp().run(sys.argv)
