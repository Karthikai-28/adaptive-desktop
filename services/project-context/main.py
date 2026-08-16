#!/usr/bin/env python3
import json
import os
import signal
import sys
import tempfile
import time
from pathlib import Path

import gi
gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib

BUS_NAME = "org.adaptive.ProjectContext"
OBJECT_PATH = "/org/adaptive/ProjectContext"
SCHEMA_VERSION = 1

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
    <method name="GetProject">
      <arg type="s" name="id" direction="in"/>
      <arg type="s" name="json_data" direction="out"/>
    </method>
    <method name="RenameProject">
      <arg type="s" name="id" direction="in"/>
      <arg type="s" name="name" direction="in"/>
      <arg type="b" name="success" direction="out"/>
    </method>
    <method name="UpdateProject">
      <arg type="s" name="id" direction="in"/>
      <arg type="s" name="json_patch" direction="in"/>
      <arg type="b" name="success" direction="out"/>
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
  <interface name="org.gnome.Shell.SearchProvider2">
    <method name="GetInitialResultSet">
      <arg type="as" name="terms" direction="in"/>
      <arg type="as" name="results" direction="out"/>
    </method>
    <method name="GetSubsearchResultSet">
      <arg type="as" name="previous_results" direction="in"/>
      <arg type="as" name="terms" direction="in"/>
      <arg type="as" name="results" direction="out"/>
    </method>
    <method name="GetResultMetas">
      <arg type="as" name="identifiers" direction="in"/>
      <arg type="aa{sv}" name="metas" direction="out"/>
    </method>
    <method name="ActivateResult">
      <arg type="s" name="identifier" direction="in"/>
      <arg type="as" name="terms" direction="in"/>
      <arg type="u" name="timestamp" direction="in"/>
    </method>
    <method name="LaunchSearch">
      <arg type="as" name="terms" direction="in"/>
      <arg type="u" name="timestamp" direction="in"/>
    </method>
  </interface>
</node>
"""

class ProjectContextService:
    def __init__(self):
        self.config_dir = Path.home() / ".config" / "adaptive-desktop"
        self.config_file = self.config_dir / "projects.json"
        self.active_id = None
        self.recent_ids = []
        self.projects = {}

        self._load_state()

        self.dbus_node_info = Gio.DBusNodeInfo.new_for_xml(INTERFACE_XML)
        self.dbus_connection = None
        self._registration_ids = []

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
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.projects = {
                        pid: self._normalize_project(pid, pdata)
                        for pid, pdata in data.get("projects", {}).items()
                    }
                    self.active_id = data.get("active_id")
                    self.recent_ids = [
                        pid for pid in data.get("recent_ids", []) if pid in self.projects
                    ]
            except Exception as e:
                print(f"Error loading projects: {e}")
                self.projects = {}
                self.active_id = None
                self.recent_ids = []
        else:
            self.projects = {}
            self.active_id = None
            self.recent_ids = []

        if self.active_id not in self.projects:
            self.active_id = None

    def _now(self):
        return int(time.time())

    def _display_name_for_path(self, path):
        return Path(path).name or str(path)

    def _project_id_for_path(self, path):
        import hashlib
        return hashlib.sha1(path.encode("utf-8")).hexdigest()[:10]

    def _normalize_path(self, raw_path):
        path = Path(os.path.expanduser(raw_path)).resolve()
        if not path.exists():
            raise ValueError(f"Project path does not exist: {path}")
        if not path.is_dir():
            raise ValueError(f"Project path is not a directory: {path}")
        return str(path)

    def _normalize_project(self, pid, data):
        now = self._now()
        path = str(Path(os.path.expanduser(data.get("path", ""))).resolve())
        name = str(data.get("name") or self._display_name_for_path(path)).strip()

        return {
            "id": str(data.get("id") or pid),
            "name": name or "Untitled Project",
            "path": path,
            "pinned_dirs": list(data.get("pinned_dirs", [])),
            "actions": list(data.get("actions", [])),
            "accent": str(data.get("accent", "") or ""),
            "workspace_index": int(data.get("workspace_index", -1)),
            "metadata": dict(data.get("metadata", {})),
            "created_at": int(data.get("created_at", now)),
            "updated_at": int(data.get("updated_at", now)),
            "last_active_at": int(data.get("last_active_at", 0)),
        }

    def _touch_recent(self, pid):
        if not pid or pid not in self.projects:
            return

        self.projects[pid]["last_active_at"] = self._now()
        self.recent_ids = [item for item in self.recent_ids if item != pid]
        self.recent_ids.insert(0, pid)
        self.recent_ids = self.recent_ids[:12]

    def _save_state(self):
        self.config_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "projects": self.projects,
            "active_id": self.active_id,
            "recent_ids": [pid for pid in self.recent_ids if pid in self.projects],
        }

        fd = None
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(
                prefix="projects.",
                suffix=".json",
                dir=str(self.config_dir),
                text=True,
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                fd = None
                json.dump(payload, f, indent=2, sort_keys=True)
                f.write("\n")
            os.replace(tmp_path, self.config_file)
        except Exception as e:
            print(f"Error saving projects: {e}")
            if fd is not None:
                os.close(fd)
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except FileNotFoundError:
                    pass

    def on_bus_acquired(self, connection, name):
        self.dbus_connection = connection
        for interface in self.dbus_node_info.interfaces:
            registration_id = connection.register_object(
                OBJECT_PATH,
                interface,
                self.handle_method_call,
                None,
                None
            )
            self._registration_ids.append(registration_id)
        print(f"Bus acquired: {name}")

    def shutdown(self):
        if not self.dbus_connection:
            return

        for registration_id in self._registration_ids:
            try:
                self.dbus_connection.unregister_object(registration_id)
            except Exception as e:
                print(f"Error unregistering DBus object: {e}")

        self._registration_ids = []

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
                    self._touch_recent(self.active_id)
                    self._save_state()
                    self.emit_active_changed()
                    invocation.return_value(GLib.Variant("(b)", (True,)))
                else:
                    invocation.return_value(GLib.Variant("(b)", (False,)))

            elif method_name == "AddProject":
                path, name = parameters.unpack()
                normalized_path = self._normalize_path(path)
                pid = self._project_id_for_path(normalized_path)
                now = self._now()
                self.projects[pid] = self._normalize_project(pid, {
                    "id": pid,
                    "name": name.strip() or self._display_name_for_path(normalized_path),
                    "path": normalized_path,
                    "created_at": self.projects.get(pid, {}).get("created_at", now),
                    "updated_at": now,
                })
                self._save_state()
                self.emit_list_changed()
                invocation.return_value(GLib.Variant("(s)", (pid,)))

            elif method_name == "GetProject":
                pid = parameters.unpack()[0]
                invocation.return_value(
                    GLib.Variant("(s)", (json.dumps(self.projects.get(pid, {})),))
                )

            elif method_name == "RenameProject":
                pid, name = parameters.unpack()
                if pid in self.projects and name.strip():
                    self.projects[pid]["name"] = name.strip()
                    self.projects[pid]["updated_at"] = self._now()
                    self._save_state()
                    self.emit_list_changed()
                    if self.active_id == pid:
                        self.emit_active_changed()
                    invocation.return_value(GLib.Variant("(b)", (True,)))
                else:
                    invocation.return_value(GLib.Variant("(b)", (False,)))

            elif method_name == "UpdateProject":
                pid, raw_patch = parameters.unpack()
                if pid not in self.projects:
                    invocation.return_value(GLib.Variant("(b)", (False,)))
                    return

                patch = json.loads(raw_patch)
                project = self.projects[pid]
                for key in ("pinned_dirs", "actions"):
                    if key in patch and isinstance(patch[key], list):
                        project[key] = patch[key]
                if "accent" in patch:
                    project["accent"] = str(patch["accent"] or "")
                if "workspace_index" in patch:
                    project["workspace_index"] = int(patch["workspace_index"])
                if "metadata" in patch and isinstance(patch["metadata"], dict):
                    project["metadata"].update(patch["metadata"])

                project["updated_at"] = self._now()
                self._save_state()
                self.emit_list_changed()
                if self.active_id == pid:
                    self.emit_active_changed()
                invocation.return_value(GLib.Variant("(b)", (True,)))

            elif method_name == "RemoveProject":
                pid = parameters.unpack()[0]
                if pid in self.projects:
                    del self.projects[pid]
                    self.recent_ids = [item for item in self.recent_ids if item != pid]
                    if self.active_id == pid:
                        self.active_id = None
                        self.emit_active_changed()
                    self._save_state()
                    self.emit_list_changed()
                    invocation.return_value(GLib.Variant("(b)", (True,)))
                else:
                    invocation.return_value(GLib.Variant("(b)", (False,)))

            elif method_name == "ListProjects":
                ordered = dict(
                    sorted(
                        self.projects.items(),
                        key=lambda item: item[1].get("name", "").casefold(),
                    )
                )
                data = json.dumps(ordered)
                invocation.return_value(GLib.Variant("(s)", (data,)))
                
            elif method_name == "GetInitialResultSet":
                terms = parameters.unpack()[0]
                query = " ".join(terms).lower()
                results = []
                for pid, pdata in self.projects.items():
                    if query in pdata["name"].lower() or query in pdata["path"].lower():
                        results.append(pid)
                invocation.return_value(GLib.Variant("(as)", (results,)))

            elif method_name == "GetSubsearchResultSet":
                previous_results, terms = parameters.unpack()
                query = " ".join(terms).lower()
                results = []
                for pid in previous_results:
                    if pid in self.projects:
                        pdata = self.projects[pid]
                        if query in pdata["name"].lower() or query in pdata["path"].lower():
                            results.append(pid)
                invocation.return_value(GLib.Variant("(as)", (results,)))

            elif method_name == "GetResultMetas":
                identifiers = parameters.unpack()[0]
                metas = []
                for pid in identifiers:
                    if pid in self.projects:
                        pdata = self.projects[pid]
                        meta = {
                            "id": GLib.Variant("s", pid),
                            "name": GLib.Variant("s", pdata["name"]),
                            "description": GLib.Variant("s", pdata["path"]),
                            "gicon": GLib.Variant("s", "folder-symbolic")
                        }
                        metas.append(meta)
                invocation.return_value(GLib.Variant("(aa{sv})", (metas,)))

            elif method_name == "ActivateResult":
                identifier, terms, timestamp = parameters.unpack()
                if identifier in self.projects:
                    self.active_id = identifier
                    self._touch_recent(identifier)
                    self._save_state()
                    self.emit_active_changed()
                invocation.return_value(None)

            elif method_name == "LaunchSearch":
                invocation.return_value(None)
                
            else:
                invocation.return_error_literal(Gio.DBusError.UNKNOWN_METHOD, "Unknown method")
        except Exception as e:
            invocation.return_error_literal(Gio.DBusError.FAILED, str(e))


if __name__ == "__main__":
    service = ProjectContextService()
    loop = GLib.MainLoop()

    def sigint_handler(sig, frame):
        service.shutdown()
        loop.quit()

    signal.signal(signal.SIGINT, sigint_handler)
    
    print("Project Context Service started")
    loop.run()
