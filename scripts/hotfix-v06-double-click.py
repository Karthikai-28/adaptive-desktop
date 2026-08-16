#!/usr/bin/env python3
from pathlib import Path
import shutil

path = Path.home() / "adaptive-desktop/apps/adaptive-files/main.py"

if not path.exists():
    raise SystemExit(f"Not found: {path}")

src = path.read_text()
backup = path.with_name("main.py.before-v07-double-click-hotfix")

if not backup.exists():
    shutil.copy2(path, backup)

old = '        gesture = Gtk.GestureClick.new()\n        gesture.connect("pressed", self._item_pressed, item, button)\n        button.add_controller(gesture)\n'

new = '        # Capture clicks before Gtk.Button consumes the sequence.\n        # Single click previews; n_press == 2 opens/navigates.\n        gesture = Gtk.GestureClick.new()\n        gesture.set_button(0)\n        gesture.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)\n        gesture.connect("pressed", self._item_pressed, item, button)\n        button.add_controller(gesture)\n'

if old not in src:
    raise SystemExit(
        "Expected v0.5/v0.6 click block was not found. "
        "No changes written."
    )

path.write_text(src.replace(old, new, 1))

print(f"Patched: {path}")
print(f"Backup:  {backup}")
print("Now run: python3 -m py_compile apps/adaptive-files/main.py")
