"""Versioned phone layouts. Only public layout data crosses this boundary."""
import copy
import json
import os
import re
import tempfile
import uuid
from pathlib import Path

ID = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
KINDS = {"action", "keys", "text", "launch", "command", "delay", "wait-window", "layout", "media", "volume"}


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def string(value, limit=8000):
    if not isinstance(value, str) or len(value) > limit or "\0" in value:
        raise ValueError("invalid or oversized text")
    return value


def binding(value):
    if not isinstance(value, dict) or value.get("kind") not in KINDS:
        raise ValueError("unknown control kind")
    kind = value["kind"]
    scope = value.get("scope", "app")
    if scope not in ("app", "global"):
        raise ValueError("invalid scope")
    result = {"kind": kind, "scope": scope, "value": string(value.get("value", "")),
              "cwd": string(value.get("cwd", "~"), 4096), "prompt": bool(value.get("prompt", False))}
    args = value.get("args", {})
    if not isinstance(args, dict) or len(json.dumps(args)) > 8192:
        raise ValueError("invalid action arguments")
    result["args"] = copy.deepcopy(args)
    if kind == "delay":
        seconds = float(result["value"])
        if not 0 <= seconds <= 10:
            raise ValueError("a delay must be between 0 and 10 seconds")
    if kind == "launch" and args.get("type", "app") not in ("app", "file", "folder", "url"):
        raise ValueError("invalid launch type")
    return result


def validate_profile(value):
    if not isinstance(value, dict) or value.get("schema", 1) != 1:
        raise ValueError("unsupported layout version")
    ident = value.get("id", "")
    if not isinstance(ident, str) or not ID.fullmatch(ident):
        raise ValueError("invalid layout ID")
    name = string(value.get("name", ""), 80).strip()
    if not name:
        raise ValueError("a layout needs a name")
    pages = value.get("pages", ["Main"])
    if not isinstance(pages, list) or not 1 <= len(pages) <= 12:
        raise ValueError("use 1 to 12 pages")
    pages = list(dict.fromkeys(string(p, 40).strip() for p in pages))
    if any(not p for p in pages):
        raise ValueError("pages need names")
    controls = value.get("controls", [])
    if not isinstance(controls, list) or len(controls) > 120:
        raise ValueError("use at most 120 controls per layout")
    made, seen = [], set()
    for control in controls:
        if not isinstance(control, dict):
            raise ValueError("invalid control")
        cid = control.get("id", "")
        if not isinstance(cid, str) or not ID.fullmatch(cid) or cid in seen:
            raise ValueError("invalid or duplicate control ID")
        seen.add(cid)
        label = string(control.get("label", ""), 80).strip()
        if not label:
            raise ValueError("a control needs a label")
        page = control.get("page", pages[0])
        if page not in pages:
            raise ValueError("control page does not exist")
        steps = control.get("steps", [])
        if not isinstance(steps, list) or not 1 <= len(steps) <= 30:
            raise ValueError("use 1 to 30 steps per control")
        steps = [binding(step) for step in steps]
        mode = control.get("mode", "button")
        if mode not in ("button", "hold", "slider", "toggle"):
            raise ValueError("unknown control mode")
        if mode == "hold" and (len(steps) != 1 or steps[0]["kind"] != "keys" or "+" in steps[0]["value"]):
            raise ValueError("a hold control needs one key")
        if mode in ("slider", "toggle") and (len(steps) != 1 or steps[0]["kind"] != "volume"):
            raise ValueError("this control requires readable volume state")
        made.append({"id": cid, "label": label, "icon": string(control.get("icon", ""), 24),
                     "page": page, "wide": bool(control.get("wide")), "emphasis": bool(control.get("emphasis")),
                     "mode": mode, "steps": steps})
    return {"schema": 1, "id": ident, "name": name, "app_id": string(value.get("app_id", ""), 250),
            "default": bool(value.get("default")), "pages": pages, "controls": made}


class Profiles:
    def __init__(self, folder):
        self.path = Path(folder) / "control-profiles.json"
        self.data = {"schema": 1, "revision": 0, "profiles": []}
        self.problem = ""
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                if data.get("schema") != 1:
                    raise ValueError("unsupported stored layout version")
                for item in data["profiles"]:
                    validate_profile(item)
                self.data = data
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                self.problem = "Stored layouts need recovery; the original file is preserved"

    def snapshot(self):
        return copy.deepcopy(self.data)

    def save(self, value, base):
        if self.problem:
            raise ValueError(self.problem)
        item = validate_profile(value)
        old = next((p for p in self.data["profiles"] if p["id"] == item["id"]), None)
        conflict = (old is not None and old["revision"] != base) or (old is None and base != 0)
        if conflict:
            item["id"] = str(uuid.uuid4())
            item["name"] = item["name"][:64] + " (conflict copy)"
            item["default"] = False
        data = self.snapshot()
        data["revision"] += 1
        item["revision"] = data["revision"]
        data["profiles"] = [p for p in data["profiles"] if p["id"] != item["id"]]
        if item["default"]:
            for other in data["profiles"]:
                if other["app_id"] == item["app_id"]:
                    other["default"] = False
                    other["revision"] = data["revision"]
        if len(data["profiles"]) >= 500:
            raise ValueError("layout limit reached")
        data["profiles"].append(item)
        atomic_json(self.path, data)
        self.data = data
        return {"ok": True, "profile": copy.deepcopy(item), "conflict": conflict}

    def delete(self, ident, base):
        if self.problem:
            raise ValueError(self.problem)
        old = next((p for p in self.data["profiles"] if p["id"] == ident), None)
        if old is None:
            return {"ok": True}
        if old["revision"] != base:
            return {"ok": False, "conflict": True, "error": "layout changed; refresh before deleting"}
        data = self.snapshot()
        data["profiles"] = [p for p in data["profiles"] if p["id"] != ident]
        data["revision"] += 1
        atomic_json(self.path, data)
        self.data = data
        return {"ok": True}
