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

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "services" / "project-context"))
import extras  # noqa: E402 - git, time, startup, tasks and templates, GTK-free

TEMPLATE_DIRS = (REPO / "config" / "project-templates", extras.USER_TEMPLATES)

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

def do_rename(args):
    proxy = get_proxy()
    pid = resolve_project_id(proxy, args.target)
    if not pid:
        print(f"Project '{args.target}' not found.")
        return

    res = proxy.call_sync(
        "RenameProject",
        GLib.Variant("(ss)", (pid, args.name)),
        Gio.DBusCallFlags.NONE,
        -1,
        None,
    )
    print(f"Renamed project: {res.unpack()[0]}")

def do_remove(args):
    proxy = get_proxy()
    pid = resolve_project_id(proxy, args.target)
    if not pid:
        print(f"Project '{args.target}' not found.")
        return

    res = proxy.call_sync(
        "RemoveProject",
        GLib.Variant("(s)", (pid,)),
        Gio.DBusCallFlags.NONE,
        -1,
        None,
    )
    print(f"Removed project: {res.unpack()[0]}")

def do_update(args):
    proxy = get_proxy()
    pid = resolve_project_id(proxy, args.target)
    if not pid:
        print(f"Project '{args.target}' not found.")
        return

    patch = {}
    if args.accent is not None:
        patch["accent"] = args.accent
    if args.workspace is not None:
        patch["workspace_index"] = args.workspace
    if args.pin:
        patch["pinned_dirs"] = [str(Path(path).resolve()) for path in args.pin]
    if args.focus is not None:
        patch["metadata"] = {"focus": args.focus}

    res = proxy.call_sync(
        "UpdateProject",
        GLib.Variant("(ss)", (pid, json.dumps(patch))),
        Gio.DBusCallFlags.NONE,
        -1,
        None,
    )
    print(f"Updated project: {res.unpack()[0]}")

def resolve_project_id(proxy, target):
    res = proxy.call_sync("ListProjects", None, Gio.DBusCallFlags.NONE, -1, None)
    projects = json.loads(res.unpack()[0])

    if target in projects:
        return target

    for pid, pdata in projects.items():
        if pdata["name"].lower() == target.lower():
            return pid

    return None

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

def all_projects(proxy):
    res = proxy.call_sync("ListProjects", None, Gio.DBusCallFlags.NONE, -1, None)
    return json.loads(res.unpack()[0])

def project_or_active(proxy, target):
    """(id, project) for a name or id; the active project when target is empty."""
    projects = all_projects(proxy)
    if target:
        pid = resolve_project_id(proxy, target)
    else:
        pid = proxy.call_sync("GetActiveProject", None, Gio.DBusCallFlags.NONE, -1, None).unpack()[0]
    if not pid or pid not in projects:
        print(f"Project '{target}' not found." if target else "No active project.")
        return None, None
    return pid, projects[pid]

def update_metadata(proxy, pid, metadata):
    res = proxy.call_sync(
        "UpdateProject",
        GLib.Variant("(ss)", (pid, json.dumps({"metadata": metadata}))),
        Gio.DBusCallFlags.NONE,
        -1,
        None,
    )
    return res.unpack()[0]

def do_git(args):
    """Every project's branch and what is uncommitted, unpushed or unpulled."""
    rows = extras.git_overview(all_projects(get_proxy()))
    if not rows:
        print("No projects registered.")
        return
    width = max(len(row["name"]) for row in rows)
    for row in rows:
        mark = "!" if row["attention"] else " "
        print(f"{mark} {row['name']:<{width}}  {row['text']}")
    waiting = sum(1 for row in rows if row["attention"])
    print(f"\n{waiting} of {len(rows)} project(s) have work to commit, push or pull.")

def do_time(args):
    """Time at the machine per project, today and over the last seven days."""
    proxy = get_proxy()
    res = proxy.call_sync("GetTimeReport", None, Gio.DBusCallFlags.NONE, -1, None)
    rows = json.loads(res.unpack()[0])
    if not rows:
        print("No project time recorded yet.")
        return
    width = max(len(row["name"]) for row in rows)
    print(f"{'':<{width}}  {'today':>12}  {'7 days':>12}")
    for row in rows:
        print(f"{row['name']:<{width}}  {extras.format_duration(row['today']):>12}  "
              f"{extras.format_duration(row['week']):>12}")

def do_startup(args):
    """Commands a project runs when it is resumed."""
    proxy = get_proxy()
    pid, project = project_or_active(proxy, args.target)
    if not pid:
        return 1
    entries = extras.normalize_startup(project.get("metadata", {}).get("startup"))

    if args.action == "list":
        if not entries:
            print(f"{project['name']} runs nothing on resume.")
        for index, entry in enumerate(entries, 1):
            where = "terminal" if entry["terminal"] else "background"
            print(f"{index}. [{where}] {entry['command']}")
    elif args.action == "add":
        entries.append({"command": " ".join(args.words), "terminal": not args.background})
        entries = extras.normalize_startup(entries)
        update_metadata(proxy, pid, {"startup": entries})
        print(f"{project['name']} now runs {len(entries)} command(s) on resume.")
    elif args.action == "clear":
        update_metadata(proxy, pid, {"startup": []})
        print(f"{project['name']} runs nothing on resume.")
    elif args.action == "run":
        import subprocess
        for entry in entries:
            try:
                subprocess.Popen(extras.startup_argv(entry, project["path"]), cwd=project["path"],
                                 start_new_session=True,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
                print(f"Started: {entry['command']}")
            except OSError as e:
                print(f"Could not start '{entry['command']}': {e}")
    return 0

def do_tasks(args):
    """The project's quick-note inbox as a task list."""
    proxy = get_proxy()
    if args.target:
        pid, project = project_or_active(proxy, args.target)
        if not pid:
            return 1
        name = project["name"]
    else:
        pid, name, _path = proxy.call_sync("GetActiveProject", None, Gio.DBusCallFlags.NONE, -1, None).unpack()
        name = name if pid else ""
    path = extras.tasks_path(name)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        text = ""
    tasks = extras.parse_tasks(text)

    if args.done is not None:
        open_tasks = [task for task in tasks if not task["done"]]
        if not 1 <= args.done <= len(open_tasks):
            print(f"There is no open task {args.done}.")
            return 1
        task = open_tasks[args.done - 1]
        path.write_text(extras.set_task_done(text, task["line"]), encoding="utf-8")
        print(f"Done: {task['text']}")
        return 0

    open_tasks = [task for task in tasks if not task["done"]]
    if not open_tasks:
        print(f"No open tasks in the {name or 'General'} inbox.")
    for index, task in enumerate(open_tasks, 1):
        print(f"{index}. {task['text']}" + (f"  ({task['stamp']})" if task["stamp"] else ""))
    return 0

def do_templates(args):
    templates = extras.load_templates(TEMPLATE_DIRS)
    if not templates:
        print("No project templates found.")
    for name, template in sorted(templates.items()):
        print(f"{name:<12} {template.get('description', '')}")

def do_new(args):
    """Create a project folder from a template and register it."""
    import subprocess
    templates = extras.load_templates(TEMPLATE_DIRS)
    template = {}
    if args.template:
        if args.template not in templates:
            print(f"No template '{args.template}'. Available: {', '.join(sorted(templates)) or 'none'}")
            return 1
        template = templates[args.template]

    root = Path(args.path).expanduser().resolve()
    created, patch = extras.apply_template(template, root)
    if template.get("git") and not (root / ".git").exists():
        subprocess.run(["git", "-C", str(root), "init", "-q"], check=False)

    proxy = get_proxy()
    name = args.name or root.name
    pid = proxy.call_sync("AddProject", GLib.Variant("(ss)", (str(root), name)),
                          Gio.DBusCallFlags.NONE, -1, None).unpack()[0]
    if patch:
        proxy.call_sync("UpdateProject", GLib.Variant("(ss)", (pid, json.dumps(patch))),
                        Gio.DBusCallFlags.NONE, -1, None)
    if args.active:
        proxy.call_sync("SetActiveProject", GLib.Variant("(s)", (pid,)), Gio.DBusCallFlags.NONE, -1, None)
    print(f"Created project '{name}' at {root} ({len(created)} new item(s)), ID: {pid}")
    return 0

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

    rename_p = sub.add_parser("rename", help="Rename a project")
    rename_p.add_argument("target", help="Project ID or name")
    rename_p.add_argument("name", help="New display name")

    remove_p = sub.add_parser("remove", help="Remove a project")
    remove_p.add_argument("target", help="Project ID or name")

    update_p = sub.add_parser("update", help="Update optional project metadata")
    update_p.add_argument("target", help="Project ID or name")
    update_p.add_argument("--accent", help="Optional project accent color")
    update_p.add_argument("--workspace", type=int, help="Workspace index to associate")
    update_p.add_argument("--pin", action="append", help="Pinned project folder; repeat for more")
    update_p.add_argument("--focus", choices=["on", "off"], help="Project focus preference")
    
    sub.add_parser("git", help="Git status of every project")
    sub.add_parser("time", help="Time per project, today and this week")
    sub.add_parser("templates", help="List project templates")

    startup_p = sub.add_parser("startup", help="Commands a project runs on resume")
    startup_sub = startup_p.add_subparsers(dest="action", required=True)
    for action, text in (("list", "Show them"), ("clear", "Remove them all"), ("run", "Run them now")):
        action_p = startup_sub.add_parser(action, help=text)
        action_p.add_argument("--target", default="", help="Project ID or name (default: active)")
    startup_add = startup_sub.add_parser(
        "add", help="Add one", epilog="Put -- before a command that has options of its own: "
                                     "startup add -- npm run dev --host")
    startup_add.add_argument("--target", default="", help="Project ID or name (default: active)")
    startup_add.add_argument("--background", action="store_true", help="Run without a terminal")
    startup_add.add_argument("words", nargs="+", metavar="command", help="The command")

    tasks_p = sub.add_parser("tasks", help="Open tasks from the quick-note inbox")
    tasks_p.add_argument("--target", default="", help="Project ID or name (default: active)")
    tasks_p.add_argument("--done", type=int, help="Mark open task N as done")

    new_p = sub.add_parser("new", help="Create a project from a template")
    new_p.add_argument("path", help="Folder to create or adopt")
    new_p.add_argument("--template", help="Template name (see: templates)")
    new_p.add_argument("--name", help="Display name (default: the folder name)")
    new_p.add_argument("--active", action="store_true", help="Set as active immediately")

    args = parser.parse_args()
    
    if args.command == "status":
        do_status(args)
    elif args.command == "list":
        do_list(args)
    elif args.command == "add":
        do_add(args)
    elif args.command == "switch":
        do_switch(args)
    elif args.command == "rename":
        do_rename(args)
    elif args.command == "remove":
        do_remove(args)
    elif args.command == "update":
        do_update(args)
    elif args.command == "clear":
        do_clear(args)
    elif args.command == "git":
        do_git(args)
    elif args.command == "time":
        do_time(args)
    elif args.command == "templates":
        do_templates(args)
    elif args.command == "startup":
        sys.exit(do_startup(args))
    elif args.command == "tasks":
        sys.exit(do_tasks(args))
    elif args.command == "new":
        sys.exit(do_new(args))

if __name__ == "__main__":
    main()
