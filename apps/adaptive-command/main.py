#!/usr/bin/env python3
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gio, Gtk, Gdk

APP_ID = "com.karthi.AdaptiveCommand"


@dataclass
class Result:
    title: str
    subtitle: str
    action: callable


class CommandWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("Command")
        self.set_default_size(720, 520)
        self.set_size_request(560, 360)
        self.results = []

        self._load_css()
        self._build()
        self._refresh("")

    def _load_css(self):
        provider = Gtk.CssProvider()
        provider.load_from_path("apps/adaptive-command/style.css")
        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def _build(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        root.add_css_class("root")
        root.set_margin_top(14)
        root.set_margin_bottom(14)
        root.set_margin_start(14)
        root.set_margin_end(14)
        self.set_child(root)

        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Search apps, settings, projects, files")
        self.search.connect("search-changed", lambda *_: self._refresh(self.search.get_text()))
        self.search.connect("activate", lambda *_: self._activate_first())
        root.append(self.search)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        root.append(scroll)

        self.list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        scroll.set_child(self.list_box)

    def _refresh(self, query):
        query = query.strip().casefold()
        self.results = self._providers(query)
        self._render()

    def _providers(self, query):
        results = []
        results.extend(self._actions(query))
        results.extend(self._apps(query))
        results.extend(self._settings(query))
        results.extend(self._projects(query))
        results.extend(self._files(query))
        return results[:40]

    def _actions(self, query):
        actions = [
            Result("Open Adaptive Files", "Desktop action", lambda: self._spawn(["gio", "open", str(Path.home())])),
            Result("Open Adaptive Settings", "Desktop action", lambda: self._spawn(["gnome-control-center"])),
            Result("Focus On", "Hide notification banners", lambda: self._spawn(["./scripts/focus-cli.py", "on"])),
            Result("Focus Off", "Show notification banners", lambda: self._spawn(["./scripts/focus-cli.py", "off"])),
            Result("Smart Tile Window", "Window action", lambda: self._spawn(["./scripts/window-cli.py", "tile", "smart"])),
            Result("Toggle Fullscreen Window", "Window action", lambda: self._spawn(["./scripts/window-cli.py", "fullscreen"])),
            Result("Save Project Window Placement", "Window action", lambda: self._spawn(["./scripts/window-cli.py", "save-project"])),
            Result("Restore Project Window Placement", "Window action", lambda: self._spawn(["./scripts/window-cli.py", "restore-project"])),
        ]
        return [item for item in actions if self._match(item, query)]

    def _apps(self, query):
        results = []
        for app in Gio.AppInfo.get_all():
            if not app.should_show():
                continue
            title = app.get_display_name() or app.get_name()
            result = Result(title, "Application", lambda a=app: a.launch([], None))
            if self._match(result, query):
                results.append(result)
        return sorted(results, key=lambda item: item.title.casefold())[:12]

    def _settings(self, query):
        sections = [
            ("Appearance Settings", ["gnome-control-center", "appearance"]),
            ("Display Settings", ["gnome-control-center", "display"]),
            ("Sound Settings", ["gnome-control-center", "sound"]),
            ("Keyboard Settings", ["gnome-control-center", "keyboard"]),
            ("Network Settings", ["gnome-control-center", "network"]),
            ("Power Settings", ["gnome-control-center", "power"]),
            ("Privacy Settings", ["gnome-control-center", "privacy"]),
            ("Accessibility Settings", ["gnome-control-center", "universal-access"]),
        ]
        results = [
            Result(title, "Settings", lambda c=command: self._spawn(c))
            for title, command in sections
        ]
        return [item for item in results if self._match(item, query)]

    def _projects(self, query):
        path = Path.home() / ".config/adaptive-desktop/projects.json"
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            projects = data.get("projects", {})
        except Exception:
            return []

        results = []
        for pid, project in projects.items():
            result = Result(
                project.get("name", pid),
                project.get("path", "Project"),
                lambda target=pid: self._spawn(["./scripts/project-cli.py", "switch", target]),
            )
            if self._match(result, query):
                results.append(result)
        return results

    def _files(self, query):
        if len(query) < 2:
            return []

        roots = [Path.home() / name for name in ("Desktop", "Documents", "Downloads")]
        results = []
        for root in roots:
            if not root.exists():
                continue
            try:
                for path in root.rglob("*"):
                    if len(results) >= 10:
                        return results
                    if query in path.name.casefold():
                        results.append(Result(path.name, str(path), lambda p=path: self._spawn(["xdg-open", str(p)])))
            except Exception:
                continue
        return results

    def _match(self, result, query):
        if not query:
            return result.subtitle in {"Desktop action", "Settings"}
        return query in f"{result.title} {result.subtitle}".casefold()

    def _render(self):
        self._clear(self.list_box)
        if not self.results:
            empty = Gtk.Label(label="No results", xalign=0.5)
            empty.add_css_class("empty")
            self.list_box.append(empty)
            return

        for result in self.results:
            button = Gtk.Button()
            button.add_css_class("result")
            button.connect("clicked", lambda _button, r=result: self._activate(r))

            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            title = Gtk.Label(label=result.title, xalign=0)
            title.add_css_class("result-title")
            subtitle = Gtk.Label(label=result.subtitle, xalign=0)
            subtitle.add_css_class("result-subtitle")
            box.append(title)
            box.append(subtitle)
            button.set_child(box)
            self.list_box.append(button)

    def _activate_first(self):
        if self.results:
            self._activate(self.results[0])

    def _activate(self, result):
        result.action()
        self.close()

    def _spawn(self, command):
        subprocess.Popen(command, cwd="/home/karthi/adaptive-desktop")

    def _clear(self, box):
        child = box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            box.remove(child)
            child = nxt


class CommandApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = CommandWindow(self)
        win.present()
        win.search.grab_focus()


if __name__ == "__main__":
    CommandApp().run()
