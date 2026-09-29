#!/usr/bin/env python3
"""Check that every this._method() a shell module calls is actually defined.

GJS resolves method names at call time, so a method that has been deleted or
renamed is not a syntax error - `node --check` passes and the extension loads
cleanly. It fails later, when something finally calls it, which for a menu
handler means the first time the user opens the popup.

That is a bad way to find out. This is a cheap static pass over the same class
bodies: collect the method definitions, collect the `this._x(` call sites, and
report anything called but never defined.
"""
import re
import sys
from pathlib import Path

# Anything reached through this. that is not defined in the file itself:
# inherited St/Clutter/GObject API and the GNOME widgets we subclass.
INHERITED = {
    "connect", "disconnect", "emit", "notify", "destroy", "add_child",
    "remove_child", "insert_child_at_index", "set_child_at_index",
    "get_children", "get_parent", "add_style_class_name", "hide", "show",
    "remove_style_class_name", "set_child", "get_width", "get_height",
    "set_width", "set_height", "set_position", "set_size", "queue_repaint",
    "get_context", "get_surface_size", "add_actor", "set_policy",
    "destroy_all_children", "get_preferred_height", "connectObject",
    "disconnectObject", "get_theme_node", "grab_key_focus", "has_key_focus",
    "ease", "set", "get_allocation_box", "add_constraint", "bind_property",
    "block_signal_handler", "unblock_signal_handler", "startDragging",
    "canClose", "close", "setIcon", "setTitle", "setBody", "setSecondaryActor",
    "setUseBodyMarkup", "createIcon", "push_volume", "change_is_muted",
}

failed = False

for path in sys.argv[1:]:
    source = Path(path).read_text()

    # Method definitions: `name(args) {` at class-body indentation, plus the
    # `var X = class ... { name() {` forms these modules use.
    defined = set(re.findall(r"^\s{4}(?:\*\s*)?([A-Za-z_]\w*)\s*\([^)]*\)\s*\{",
                             source, re.M))
    defined |= set(re.findall(r"^\s{4}(?:get|set)\s+([A-Za-z_]\w*)\s*\(",
                              source, re.M))
    defined |= {"constructor"}

    called = set(re.findall(r"this\.(_[A-Za-z]\w*)\s*\(", source))

    missing = sorted(c for c in called if c not in defined and c not in INHERITED)
    if missing:
        failed = True
        print(f"FAIL {path}")
        for name in missing:
            line = next((i for i, l in enumerate(source.splitlines(), 1)
                         if f"this.{name}(" in l), "?")
            print(f"  this.{name}() called at line {line} but never defined")
    else:
        print(f"OK {Path(path).name}: {len(called)} internal calls all defined")

sys.exit(1 if failed else 0)
