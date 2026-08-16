#!/usr/bin/env python3
import json
import os
import signal
import sys
from pathlib import Path

import gi
gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib

BUS_NAME = "org.adaptive.ProjectContext"
OBJECT_PATH = "/org/adaptive/ProjectContext"

INTERFACE_XML = """
<node>
  <interface name="org.adaptive.ProjectContext">
    <method name="GetActiveProject">
      <arg type="s" name="id" direction="out"/>
      <arg type="s" name="name" direction="out"/>
      <arg type="s" name="path" direction="out"/>
    </method>
    <method name="SetActiveProject">
      <arg type="s" name="id" direction="in"/>
      <arg type="b" name="success" direction="out"/>
    </method>
    <method name="AddProject">
      <arg type="s" name="path" direction="in"/>
      <arg type="s" name="name" direction="in"/>
      <arg type="s" name="id" direction="out"/>
    </method>
    <method name="RemoveProject">
      <arg type="s" name="id" direction="in"/>
      <arg type="b" name="success" direction="out"/>
    </method>
    <method name="ListProjects">
      <arg type="s" name="json_data" direction="out"/>
    </method>
    <signal name="ActiveProjectChanged">
      <arg type="s" name="id"/>
      <arg type="s" name="name"/>
      <arg type="s" name="path"/>
    </signal>
    <signal name="ProjectListChanged">
    </signal>
  </interface>
</node>
"""

class ProjectContextService:
    def __init__(self):
        self.config_dir = Path.home() / ".config" / "adaptive-desktop"
        self.config_file = self.config_dir / "projects.json"
        self.active_id = None
        self.projects = {}

        self._load_state()

        self.dbus_node_info = Gio.DBusNodeInfo.new_for_xml(INTERFACE_XML)
        self.dbus_connection = None

        Gio.bus_own_name(
            Gio.BusType.SESSION,
            BUS_NAME,
            Gio.BusNameOwnerFlags.NONE,
            self.on_bus_acquired,
            self.on_name_acquired,
            self.on_name_lost,
        )

    def _load_state(self):
        if self.config_file.exists():
            try:
                with open(self.config_file, "r") as f:
                    data = json.load(f)
                    self.projects = data.get("projects", {})
                    self.active_id = data.get("active_id")
            except Exception as e:
                print(f"Error loading projects: {e}")
        else:
            self.projects = {}
            self.active_id = None

    def _save_state(self):
        self.config_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.config_file, "w") as f:
                json.dump({
                    "projects": self.projects,
                    "active_id": self.active_id,
                }, f, indent=2)
        except Exception as e:
            print(f"Error saving projects: {e}")

    def on_bus_acquired(self, connection, name):
        self.dbus_connection = connection
        connection.register_object(
            OBJECT_PATH,
            self.dbus_node_info.interfaces[0],
            self.handle_method_call,
            None,
            None
        )
        print(f"Bus acquired: {name}")

    def on_name_acquired(self, connection, name):
        print(f"Name acquired: {name}")

    def on_name_lost(self, connection, name):
        print(f"Name lost: {name}")
        sys.exit(1)

    def emit_active_changed(self):
        if not self.dbus_connection:
            return
        
        project = self.projects.get(self.active_id, {})
        name = project.get("name", "NONE") if self.active_id else "NONE"
        path = project.get("path", "") if self.active_id else ""
        
        self.dbus_connection.emit_signal(
            None,
            OBJECT_PATH,
            BUS_NAME,
            "ActiveProjectChanged",
            GLib.Variant("(sss)", (self.active_id or "", name, path))
        )

    def emit_list_changed(self):
        if not self.dbus_connection:
            return
        
        self.dbus_connection.emit_signal(
            None,
            OBJECT_PATH,
            BUS_NAME,
            "ProjectListChanged",
            None
        )

    def handle_method_call(self, connection, sender, object_path, interface_name, method_name, parameters, invocation):
        try:
            if method_name == "GetActiveProject":
                project = self.projects.get(self.active_id, {})
                name = project.get("name", "NONE") if self.active_id else "NONE"
                path = project.get("path", "") if self.active_id else ""
                invocation.return_value(GLib.Variant("(sss)", (self.active_id or "", name, path)))

            elif method_name == "SetActiveProject":
                new_id = parameters.unpack()[0]
                if new_id in self.projects or new_id == "":
                    self.active_id = new_id if new_id else None
                    self._save_state()
                    self.emit_active_changed()
                    invocation.return_value(GLib.Variant("(b)", (True,)))
                else:
                    invocation.return_value(GLib.Variant("(b)", (False,)))

            elif method_name == "AddProject":
                path, name = parameters.unpack()
                import hashlib
                pid = hashlib.sha1(path.encode()).hexdigest()[:8]
                self.projects[pid] = {"name": name, "path": path}
                self._save_state()
                self.emit_list_changed()
                invocation.return_value(GLib.Variant("(s)", (pid,)))

            elif method_name == "RemoveProject":
                pid = parameters.unpack()[0]
                if pid in self.projects:
                    del self.projects[pid]
                    if self.active_id == pid:
                        self.active_id = None
                        self.emit_active_changed()
                    self._save_state()
                    self.emit_list_changed()
                    invocation.return_value(GLib.Variant("(b)", (True,)))
                else:
                    invocation.return_value(GLib.Variant("(b)", (False,)))

            elif method_name == "ListProjects":
                data = json.dumps(self.projects)
                invocation.return_value(GLib.Variant("(s)", (data,)))
            else:
                invocation.return_error_literal(Gio.DBusError.UNKNOWN_METHOD, "Unknown method")
        except Exception as e:
            invocation.return_error_literal(Gio.DBusError.FAILED, str(e))


if __name__ == "__main__":
    service = ProjectContextService()
    loop = GLib.MainLoop()

    def sigint_handler(sig, frame):
        loop.quit()

    signal.signal(signal.SIGINT, sigint_handler)
    
    print("Project Context Service started")
    loop.run()
