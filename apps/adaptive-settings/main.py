#!/usr/bin/env python3
import subprocess
from dataclasses import dataclass

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gio, Gtk, Gdk

APP_ID = "com.karthi.AdaptiveSettings"


@dataclass
class Section:
    name: str
    detail: str
    command: list[str] | None = None


SECTIONS = [
    Section("Home", "Adaptive Desktop status, recovery, and common actions."),
    Section("Appearance", "Theme, shell visuals, dock, typography, and contrast.", ["gnome-control-center", "appearance"]),
    Section("Projects & Workspaces", "Project registry, active project, and workspace mapping.", ["./scripts/project-cli.py", "list"]),
    Section("Windows & Multitasking", "Window switching, workspaces, and multitasking behavior.", ["./scripts/window-cli.py", "tile", "center"]),
    Section("Notifications & Focus", "Notification policy and focus behavior.", ["./scripts/focus-cli.py", "status"]),
    Section("Search & Commands", "Command menu and search providers."),
    Section("Display & Graphics", "Monitors, scale, refresh, and graphics.", ["gnome-control-center", "display"]),
    Section("Sound", "Volume and audio devices.", ["gnome-control-center", "sound"]),
    Section("Input & Gestures", "Keyboard, mouse, touchpad, and shortcuts.", ["gnome-control-center", "keyboard"]),
    Section("Network & Connectivity", "Network, Bluetooth, and remote access.", ["gnome-control-center", "network"]),
    Section("Files & Storage", "Adaptive Files, storage overview, pins, and remotes.", ["./scripts/adaptive-files-launch-v1.6.sh"]),
    Section("Privacy & Security", "Permissions, screen lock, and privacy controls.", ["gnome-control-center", "privacy"]),
    Section("Accounts & Sync", "Users and online accounts.", ["gnome-control-center", "online-accounts"]),
    Section("Power & Battery", "Power mode, suspend, and battery behavior.", ["gnome-control-center", "power"]),
    Section("Accessibility", "Visual, hearing, typing, and pointing accessibility.", ["gnome-control-center", "universal-access"]),
    Section("Developer & Advanced", "Diagnostics, shell verification, and project CLI.", ["./scripts/verify-shell-source.sh"]),
    Section("Updates, Recovery & Session", "Recovery runbook, validation scripts, and uninstall flow.", ["./scripts/verify-session-isolation.sh"]),
    Section("About", "Adaptive Desktop version and Ubuntu base.", ["gnome-control-center", "info-overview"]),
]


class AdaptiveSettingsWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("Adaptive Settings")
        self.set_default_size(980, 680)
        self.set_size_request(760, 500)

        self.sections = SECTIONS
        self.active = SECTIONS[0]
        self.buttons = []

        self._load_css()
        self._build()
        self._render_sidebar()
        self._render_section(self.active)

    def _load_css(self):
        provider = Gtk.CssProvider()
        provider.load_from_path("apps/adaptive-settings/style.css")
        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display,
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

    def _build(self):
        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        root.add_css_class("root")
        self.set_child(root)

        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        sidebar.add_css_class("sidebar")
        sidebar.set_size_request(252, -1)
        root.append(sidebar)

        title = Gtk.Label(label="Settings", xalign=0)
        title.add_css_class("app-title")
        sidebar.append(title)

        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Search settings")
        self.search.connect("search-changed", lambda *_: self._render_sidebar())
        sidebar.append(self.search)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        sidebar.append(scroll)

        self.sidebar_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        scroll.set_child(self.sidebar_list)

        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.content.add_css_class("content")
        self.content.set_hexpand(True)
        root.append(self.content)

    def _render_sidebar(self):
        self._clear(self.sidebar_list)
        self.buttons = []
        query = self.search.get_text().strip().casefold()

        for section in self.sections:
            haystack = f"{section.name} {section.detail}".casefold()
            if query and query not in haystack:
                continue

            button = Gtk.Button(label=section.name)
            button.add_css_class("nav-item")
            if section == self.active:
                button.add_css_class("active")
            button.connect("clicked", lambda _button, s=section: self._select(s))
            self.sidebar_list.append(button)
            self.buttons.append(button)

    def _select(self, section):
        self.active = section
        self._render_sidebar()
        self._render_section(section)

    def _render_section(self, section):
        self._clear(self.content)

        heading = Gtk.Label(label=section.name, xalign=0)
        heading.add_css_class("section-title")
        self.content.append(heading)

        detail = Gtk.Label(label=section.detail, xalign=0)
        detail.set_wrap(True)
        detail.add_css_class("section-detail")
        self.content.append(detail)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.add_css_class("card")
        self.content.append(card)

        state = Gtk.Label(label=self._section_state(section), xalign=0)
        state.set_wrap(True)
        state.add_css_class("state")
        card.append(state)

        if section.command:
            action = Gtk.Button(label="Open")
            action.add_css_class("primary-action")
            action.connect("clicked", lambda *_: self._run(section.command))
            card.append(action)

    def _section_state(self, section):
        if section.name == "Home":
            return "Adaptive Desktop is installed as a reversible Ubuntu session. Use Recovery & Session before risky changes."
        if section.name == "Search & Commands":
            return "The shell Command menu exposes desktop actions, application launch, and project switching."
        if section.name == "Updates, Recovery & Session":
            return "Recovery runbooks and validation scripts are stored in docs/ and scripts/."
        return "This section routes to the safest available local control surface for now."

    def _run(self, command):
        try:
            subprocess.Popen(command, cwd="/home/karthi/adaptive-desktop")
        except Exception as error:
            dialog = Gtk.AlertDialog(message="Could not open setting", detail=str(error))
            dialog.show(self)

    def _clear(self, box):
        child = box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            box.remove(child)
            child = nxt


class AdaptiveSettingsApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = AdaptiveSettingsWindow(self)
        win.present()


if __name__ == "__main__":
    AdaptiveSettingsApp().run()
