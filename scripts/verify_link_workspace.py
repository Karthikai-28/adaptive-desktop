"""Focused workspace regression cases, also run by verify-link.py."""
import asyncio
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def sample():
    return {"schema": 1, "id": "browser-reading", "name": "Reading", "app_id": "firefox.desktop", "pages": ["Main"],
            "controls": [{"id": "save", "label": "Save", "steps": [{"kind": "keys", "value": "ctrl+s"}]}]}


def checks(check):
    import control_profiles as cp
    import app_workspace as aw
    with tempfile.TemporaryDirectory() as folder:
        store = cp.Profiles(folder)
        first = store.save(sample(), 0)["profile"]
        check(cp.Profiles(folder).snapshot()["profiles"][0] == first, "layouts: atomic saved copy survives restart")
        changed = dict(first, name="Updated")
        second = store.save(changed, first["revision"])["profile"]
        conflict = store.save(dict(first, name="Offline edit"), first["revision"])
        check(conflict["conflict"] and len(store.snapshot()["profiles"]) == 2 and second in store.snapshot()["profiles"],
              "layouts: concurrent edits preserve both copies")
        check(not store.delete(second["id"], first["revision"])["ok"], "layouts: stale deletion cannot erase a newer edit")
        check(store.delete(second["id"], second["revision"])["ok"], "layouts: matching revision can delete")
        replay = store.save(second, second["revision"])
        check(replay["conflict"] and replay["profile"]["id"] != second["id"], "layouts: offline edit after deletion becomes a separate copy")
        for bad in (dict(sample(), schema=2), dict(sample(), name=""), dict(sample(), controls=[{"id": "x", "label": "X", "steps": []}]),
                    dict(sample(), controls=[{"id": "x", "label": "X", "steps": [{"kind": "delay", "value": "nan"}]}])):
            try:
                cp.validate_profile(bad)
                check(False, "layouts: malformed layout rejected")
            except (ValueError, TypeError):
                check(True, "layouts: malformed layout rejected")
        before = store.path.read_text()
        try:
            with patch.object(cp.os, "replace", side_effect=OSError("simulated interrupted write")):
                store.save(dict(sample(), id="new"), 0)
        except OSError:
            pass
        check(store.path.read_text() == before and cp.Profiles(folder).snapshot() == store.snapshot(),
              "layouts: failed atomic replace keeps previous disk and memory state")
        projected = cp.validate_profile(dict(sample(), private_key="must not survive", owner="must not survive"))
        check("private_key" not in projected and "owner" not in projected, "layouts: unknown private fields never enter stored layouts")
    apps = [{"id": "a.desktop", "wm_class": "Browser", "executable": "/bin/a"},
            {"id": "b.desktop", "wm_class": "Browser", "executable": "/bin/b"}]
    check(len(aw.matches({"app": "Browser"}, apps, {})) == 2, "apps: ambiguous window classes remain ambiguous")
    check(aw.matches({"app": "Browser"}, apps, {"browser": "b.desktop"}) == ["b.desktop"], "apps: explicit remembered association wins")
    check(aw.matches({"application_id": "a", "title": "b.desktop"}, apps, {}) == ["a.desktop"], "apps: stable ID wins over window title")
    check(aw.adapter("code_code.desktop") == "editor" and aw.adapter("new.desktop") == "universal", "apps: unknown apps retain universal controls")
    check(aw.key_event("ctrl+shift+s") == {"t": "key", "k": "s", "m": ["ctrl", "shift"]}, "controls: shortcuts use validated key events")
    asyncio.run(async_checks(check))


async def async_checks(check):
    import app_workspace as aw
    class Request(dict):
        def __init__(self, body=None, owner="phone", query=None):
            super().__init__(phone={"fingerprint": owner}, peer="test")
            self.body, self.query = body or {}, query or {}
        async def json(self):
            return self.body
    class Input:
        screen = (1920, 1080)
        def __init__(self): self.events = []
        async def send(self, event): self.events.append(event); return True
    with tempfile.TemporaryDirectory() as folder:
        permissions = {"allow_input": True, "allow_exec": True, "allow_files": True}
        recorded = []
        async def do(ident, args, peer, confirmed):
            recorded.append(ident)
            return ident != "fail", "", 0
        link = SimpleNamespace(link_dir=Path(folder), input=Input(), _allowed=lambda p: permissions.get(p, False),
            _risk=lambda i, a: "destroys" if i == "shutdown" else "safe", _do=do,
            phones=[{"fingerprint": "phone"}, {"fingerprint": "second"}], audit=SimpleNamespace(write=lambda *args: None))
        work = aw.Workspace(link)
        work.control_owner = "phone"
        session = {"id": "session", "owner": "phone", "window_id": 7, "app_id": "a.desktop", "display": "", "seen": time.monotonic()}
        work.sessions["session"] = session
        windows = [{"id": 7, "title": "Main", "app": "A", "active": False}, {"id": 8, "title": "Dialog", "app": "A", "active": True, "parent": 7}]
        with patch.object(aw.machine, "windows", return_value=windows), patch.object(aw.phone_display, "_geometry", return_value=(100, 50, 800, 600)):
            public = await work.get_sessions(Request(query={"id": "session"}))
            check(public["session"]["target"] == 8 and public["session"]["region"] == [100, 50, 800, 600], "workspace: active child dialog supplies target and crop")
            check("owner" not in public["session"], "workspace: public state excludes phone identity")
            try:
                await work.get_sessions(Request(owner="second", query={"id": "session"}))
                check(False, "workspace: another phone cannot read a private workspace")
            except ValueError:
                check(True, "workspace: another phone cannot read a private workspace")
            async def start(ident, steps, **extra):
                return await work.change_run(Request({"request_id": ident, "session": "session", "steps": steps, **extra}))
            async def finish(ident):
                task = work.tasks.get(ident)
                if task: await task
                return work.runs[ident]
            safe = lambda value: {"kind": "action", "value": value, "scope": "global"}
            await start("ordered", [safe("first"), safe("fail"), safe("never")])
            ended = await finish("ordered")
            check(recorded == ["first", "fail"] and ended["state"] == "failed" and ended["step"] == 2,
                  "macros: ordered execution stops on first failure")
            await start("ordered", [safe("again")])
            check(recorded == ["first", "fail"], "macros: duplicate request does not execute again")
            answer = await start("confirm", [safe("shutdown")])
            check(answer.get("confirm") and "confirm" not in work.runs, "macros: destructive step requires explicit confirmation")
            await start("cancel", [{"kind": "delay", "value": "10"}, safe("never")])
            await asyncio.sleep(0.02)
            await work.change_run(Request({"operation": "cancel", "id": "cancel"}))
            check((await finish("cancel"))["state"] == "cancelled" and "never" not in recorded, "macros: cancel interrupts a delay and prevents subsequent steps")
            await start("held", [{"kind": "keys", "value": "w"}], hold=True)
            await asyncio.sleep(0.05)
            permissions["allow_input"] = False
            check((await finish("held"))["state"] == "failed" and link.input.events[-1] == {"t": "keyup", "k": "w"},
                  "controls: revoking input releases a held key")
            permissions["allow_input"] = True
            await start("disconnect", [{"kind": "delay", "value": "10"}, safe("never")])
            work.runs["disconnect"]["seen"] = time.monotonic() - 20
            check((await finish("disconnect"))["state"] == "cancelled", "macros: missing heartbeat cancels execution")
            work.control_owner = "second"
            await start("global-keys", [{"kind": "keys", "value": "x", "scope": "global"}])
            check((await finish("global-keys"))["state"] == "failed", "controls: global shortcuts cannot bypass input ownership")
            work.control_owner = "phone"
            opened = []
            launch_file = {"kind": "launch", "value": "~/run.desktop", "scope": "global", "args": {"type": "file"}}
            with patch.object(aw.desktop, "opens_as_program", return_value=True), \
                    patch.object(aw.desktop, "open_path", side_effect=lambda path: opened.append(path) or True):
                permissions["allow_exec"] = False
                await start("program-file", [launch_file])
                check((await finish("program-file"))["state"] == "failed" and not opened,
                      "controls: opening a file that runs as a program needs allow_exec")
                permissions["allow_exec"] = True
                await start("program-file-allowed", [launch_file])
                check((await finish("program-file-allowed"))["state"] == "completed" and opened == ["~/run.desktop"],
                      "controls: with allow_exec the same file opens")
            with patch.object(aw.machine, "windows", return_value=windows) as listing:
                await work.focus("session", "phone")
                for _ in range(20):
                    await work.focus("session", "phone", fresh=False)
                check(listing.call_count == 1, "workspace: live input reuses a recent window check")
                await work.focus("session", "phone")
                check(listing.call_count == 2, "workspace: control steps always check the window again")
            windows.clear()
            result = await work.get_sessions(Request(query={"id": "session"}))
            check(result["session"]["closed"], "workspace: closed windows are reported rather than retargeted")
        await work.close()


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "services" / "adaptive-link"))
    failed = []
    def check(ok, message):
        print(("PASS " if ok else "FAIL ") + message)
        if not ok: failed.append(message)
    checks(check)
    raise SystemExit(bool(failed))
