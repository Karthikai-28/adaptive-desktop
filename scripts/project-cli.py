#!/usr/bin/env python3
import sys
import json
import argparse
from pathlib import Path

import gi
gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib

BUS_NAME = "org.adaptive.ProjectContext"
OBJECT_PATH = "/org/adaptive/ProjectContext"

def get_proxy():
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        proxy = Gio.DBusProxy.new_sync(
            bus,
            Gio.DBusProxyFlags.NONE,
            None,
            BUS_NAME,
            OBJECT_PATH,
            BUS_NAME,
            None
        )
        return proxy
    except Exception as e:
        print(f"Error connecting to Project Context Service: {e}")
        sys.exit(1)

def do_status(args):
    proxy = get_proxy()
    res = proxy.call_sync("GetActiveProject", None, Gio.DBusCallFlags.NONE, -1, None)
    pid, name, path = res.unpack()
    if pid:
        print(f"Active Project: {name}")
        print(f"Path: {path}")
        print(f"ID: {pid}")
    else:
        print("No active project.")

def do_add(args):
    proxy = get_proxy()
    abs_path = str(Path(args.path).resolve())
    res = proxy.call_sync("AddProject", GLib.Variant("(ss)", (abs_path, args.name)), Gio.DBusCallFlags.NONE, -1, None)
    pid = res.unpack()[0]
    print(f"Added project '{args.name}' with ID: {pid}")
    if args.active:
        res = proxy.call_sync("SetActiveProject", GLib.Variant("(s)", (pid,)), Gio.DBusCallFlags.NONE, -1, None)
        print(f"Set as active project: {res.unpack()[0]}")

def do_switch(args):
    proxy = get_proxy()
    # To support switching by name or ID, we list projects first
    res = proxy.call_sync("ListProjects", None, Gio.DBusCallFlags.NONE, -1, None)
    projects = json.loads(res.unpack()[0])
    
    target_id = None
    if args.target in projects:
        target_id = args.target
    else:
        for pid, pdata in projects.items():
            if pdata["name"].lower() == args.target.lower():
                target_id = pid
                break
                
    if target_id:
        res = proxy.call_sync("SetActiveProject", GLib.Variant("(s)", (target_id,)), Gio.DBusCallFlags.NONE, -1, None)
        print(f"Switched to project: {projects[target_id]['name']}")
    else:
        print(f"Project '{args.target}' not found.")

def do_list(args):
    proxy = get_proxy()
    res = proxy.call_sync("ListProjects", None, Gio.DBusCallFlags.NONE, -1, None)
    projects = json.loads(res.unpack()[0])
    
    res = proxy.call_sync("GetActiveProject", None, Gio.DBusCallFlags.NONE, -1, None)
    active_id, _, _ = res.unpack()
    
    if not projects:
        print("No projects registered.")
        return
        
    for pid, pdata in projects.items():
        prefix = "* " if pid == active_id else "  "
        print(f"{prefix}{pdata['name']} [{pid}] -> {pdata['path']}")

def do_clear(args):
    proxy = get_proxy()
    res = proxy.call_sync("SetActiveProject", GLib.Variant("(s)", ("",)), Gio.DBusCallFlags.NONE, -1, None)
    print("Cleared active project.")

def main():
    parser = argparse.ArgumentParser(description="Adaptive Desktop Project Context CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    
    sub.add_parser("status", help="Show the active project")
    sub.add_parser("list", help="List all registered projects")
    sub.add_parser("clear", help="Clear the active project")
    
    add_p = sub.add_parser("add", help="Add a new project")
    add_p.add_argument("path", help="Directory path for the project")
    add_p.add_argument("name", help="Display name for the project")
    add_p.add_argument("--active", action="store_true", help="Set as active immediately")
    
    sw_p = sub.add_parser("switch", help="Switch active project")
    sw_p.add_argument("target", help="Project ID or name to switch to")
    
    args = parser.parse_args()
    
    if args.command == "status":
        do_status(args)
    elif args.command == "list":
        do_list(args)
    elif args.command == "add":
        do_add(args)
    elif args.command == "switch":
        do_switch(args)
    elif args.command == "clear":
        do_clear(args)

if __name__ == "__main__":
    main()
