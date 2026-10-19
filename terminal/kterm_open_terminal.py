"""Open local folders in Terminal from Nautilus 42."""

import os
from pathlib import Path
import subprocess

from gi.repository import GObject, Nautilus


class KTermOpenTerminal(GObject.GObject, Nautilus.MenuProvider):
    def _items(self, info):
        path = info.get_location().get_path() if info else None
        if not path:
            return []
        if not info.is_directory():
            path = str(Path(path).parent)
        launcher = Path.home() / ".local/bin/kterm-terminal"
        if not launcher.is_file() or not os.path.isdir(path):
            return []
        item = Nautilus.MenuItem(name="KTerm::OpenTerminal", label="Open in Terminal",
                                tip="Open this folder in Terminal", icon="kterm-terminal")
        item.connect("activate", lambda *_: subprocess.Popen(
            [str(launcher), "--working-directory", path], start_new_session=True))
        return [item]

    def get_background_items(self, *args):
        return self._items(args[-1] if args else None)

    def get_file_items(self, *args):
        files = args[-1] if args else []
        return self._items(files[0]) if len(files) == 1 else []
