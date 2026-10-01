#!/usr/bin/env python3
"""Quick note - one line into the active project's inbox, from anywhere.

Super+Alt+N (scripts/install-keybindings.sh), the project menu in the top bar,
or the Command palette. Type, press Enter, and the line is appended with the
time to

    ~/.local/share/adaptive-desktop/notes/<project>/Inbox.md

the same notes folder the Projects app keeps, named the same way, so nothing
lands inside the repository. With no project active it goes to General/.
Esc closes without saving.
"""

import re
import sys
import time
from pathlib import Path

NOTES_DIR = Path.home() / ".local/share/adaptive-desktop/notes"
INBOX = "Inbox.md"
GENERAL = "General"
RECENT = 3


def inbox_path(project_name):
    """Same folder naming as apps/adaptive-projects (_notes_path)."""
    safe = re.sub(r"[^\w.-]", "_", project_name or GENERAL)
    return NOTES_DIR / safe / INBOX


def format_entry(text, now=None):
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(now))
    # One line per note: a pasted paragraph is folded rather than breaking
    # the list.
    line = " ".join(text.split())
    return f"- {stamp}  {line}\n"


def append_note(path, text, now=None):
    if not text.strip():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "" if path.exists() else f"# {path.parent.name} inbox\n\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(header + format_entry(text, now))
    return True


def recent_notes(path, count=RECENT):
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [line[2:] for line in lines if line.startswith("- ")][-count:]


def active_project_name():
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        reply = bus.call_sync(
            "org.adaptive.ProjectContext", "/org/adaptive/ProjectContext",
            "org.adaptive.ProjectContext", "GetActiveProject", None, None,
            Gio.DBusCallFlags.NO_AUTO_START, 1500, None)
        pid, name, _path = reply.unpack()
        return name if pid else ""
    except Exception:
        return ""


def main():
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    from gi.repository import Gdk, Gio, Gtk, Pango

    project = active_project_name()
    target = inbox_path(project)

    css = b"""
    window.quick-note { background-color: #1C1C1E; color: #F5F5F7; font-family: Inter, sans-serif; }
    .qn-box { padding: 16px 18px; }
    .qn-title { font-size: 13px; font-weight: 600; color: #98989D; }
    .qn-entry { min-height: 38px; font-size: 15px; border-radius: 10px;
                background-color: #141416; color: #F5F5F7; }
    .qn-recent { font-size: 12px; color: #8E8E93; }
    """

    class QuickNote(Gtk.ApplicationWindow):
        def __init__(self, app):
            super().__init__(application=app, title="Quick Note")
            self.add_css_class("quick-note")
            self.set_default_size(560, -1)
            self.set_resizable(False)
            Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)
            provider = Gtk.CssProvider()
            provider.load_from_data(css)
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            box.add_css_class("qn-box")
            title = Gtk.Label(xalign=0, label=f"Note to {project or GENERAL} inbox  ·  Enter saves, Esc closes")
            title.add_css_class("qn-title")
            box.append(title)

            self.entry = Gtk.Entry(placeholder_text="What's on your mind?")
            self.entry.add_css_class("qn-entry")
            self.entry.connect("activate", self._save)
            box.append(self.entry)

            for line in recent_notes(target):
                recent = Gtk.Label(xalign=0, label=line, ellipsize=Pango.EllipsizeMode.END)
                recent.add_css_class("qn-recent")
                box.append(recent)

            bar = Gtk.Box(spacing=8)
            open_button = Gtk.Button(label="Open inbox")
            open_button.connect("clicked", self._open)
            bar.append(open_button)
            box.append(bar)
            self.set_child(box)

            keys = Gtk.EventControllerKey()
            keys.connect("key-pressed", lambda _c, keyval, *_: (
                self.close() or True) if keyval == Gdk.KEY_Escape else False)
            self.add_controller(keys)

        def _save(self, *_):
            if append_note(target, self.entry.get_text()):
                self.close()

        def _open(self, *_):
            if not target.exists():
                append_note(target, "Inbox started")
            Gio.AppInfo.launch_default_for_uri(target.as_uri(), None)
            self.close()

    app = Gtk.Application(application_id="com.karthi.AdaptiveQuickNote")
    app.connect("activate", lambda a: (a.get_active_window() or QuickNote(a)).present())
    return app.run(None)


if __name__ == "__main__":
    sys.exit(main())
