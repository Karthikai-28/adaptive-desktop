#!/usr/bin/env python3
"""Mario Hub: the live data behind Mario's Home, and Mario's ask box. Loopback only.

    python3 hub.py [--port 8791] [--config FILE] [--once]

  GET  /                 the Home page (apps/mario-home/static), /panel the Mario panel
  GET  /api/state        every card, the Next step list and Mario's presence
  GET  /ws               the same, pushed: {"type": "card" | "next" | "presence" | "handoff", ...}
  POST /api/ask          {"text"} -> an answer (instant, LOOM, or Ollama) or a Claude Code plan
  POST /api/handoff/ID   {"decision": "run" | "cancel"}: runs a plan only after you say so
  POST /api/action       {"id", "arg"}: a short whitelist (open a repo's terminal, a folder, ...)
  POST /api/presence     {"state", "detail"}: for the voice listener (listening, ...)
  POST /api/task         {"text", "project"?}: a task into a Quick Note inbox (General by default)
  POST /api/task/done    {"path", "line"}: tick a task in a Quick Note inbox
  POST /api/note         {"text"}: add a line to Jot (~/.local/share/adaptive-desktop/mario/notes.md)

Collectors (collectors.py) run on their own intervals in threads; a card is pushed only when it
changed. --once prints one full state as JSON and exits (the check uses it).
"""
import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from aiohttp import web, WSMsgType

sys.path.insert(0, str(Path(__file__).resolve().parent))
import brain  # noqa: E402
import collectors  # noqa: E402
import config as config_mod  # noqa: E402

STATIC = config_mod.ADAPTIVE_REPO / "apps" / "mario-home" / "static"
PRESENCE = ("ready", "listening", "thinking", "doing", "needs_you")
OPEN_URL_PREFIXES = ("https://claude.ai/", "https://gemini.google.com/", "https://docs.google.com/", "https://github.com/",
                     "https://mail.google.com/", "https://calendar.google.com/",
                     "https://myaccount.google.com/apppasswords",
                     "https://www.instagram.com/", "http://127.0.0.1:", "http://localhost:")
REPO = config_mod.ADAPTIVE_REPO


def editor():
    """The code editor: VS Code's `code` when it is installed, else Antigravity IDE (a VS Code
    fork, the editor on this laptop) through its command-line launcher, which opens a folder in
    the running window. A missing editor leaves the Code launcher dimmed."""
    for cand in (shutil.which("code"), "/opt/antigravity-ide/bin/antigravity-ide",
                 shutil.which("antigravity-ide"), shutil.which("antigravity")):
        if cand and Path(cand).exists():
            return [cand]
    return ["code"]


# Commands Home may start: the Apps card, and the Phone card (the phone's screen).
# Only these run; a missing program shows its launcher dimmed.
LAUNCH = {
    "terminal": ["gnome-terminal"],
    "files": ["xdg-open", str(Path.home())],
    "code": editor(),
    "browser": ["sh", "-c", 'gtk-launch "$(xdg-settings get default-web-browser)"'],
    "settings": ["gnome-control-center"],
    "phone": [sys.executable, str(REPO / "apps" / "adaptive-phone" / "phone.py")],
    # GNOME 42's own screenshot screen has no command; Adaptive Annotate selects an area, then
    # lets you mark it up, copy or save it (the same as Super+Shift+S)
    "screenshot": ([shutil.which("gnome-screenshot"), "--interactive"] if shutil.which("gnome-screenshot")
                   else [sys.executable, str(REPO / "apps" / "adaptive-annotate" / "main.py")]),
    "cast": [str(REPO / "scripts" / "adaptive-cast-launch.sh"), "--toggle"],
    "calculator": ["gnome-calculator"],
    "monitor": ["gnome-system-monitor"],
    "updates": ["update-manager"],
}


class Hub:
    def __init__(self, cfg, schedule=None):
        self.cfg = cfg
        self.schedule = schedule if schedule is not None else collectors.SCHEDULE
        self.cards = {}
        self.clients = set()
        self.presence = {"state": "ready", "detail": ""}
        self.handoffs = {}
        self.loom_session = None
        self.tasks = []
        self.notes_file = config_mod.DATA_DIR / "notes.md"

    # ------------------------------------------------------------ state
    def public_config(self):
        return {"backup_at": self.cfg.get("backup_at", ""), "cards_off": self.cfg.get("cards_off", []),
                "host": os.uname().nodename,
                "launch": {k: bool(shutil.which(v[0]) or Path(v[0]).exists() or (len(v) > 1 and Path(v[1]).exists()))
                           for k, v in LAUNCH.items()}}

    def snapshot(self):
        cards = dict(self.cards)
        cards["notes"] = {"data": {"items": collectors.read_notes(self.notes_file)}, "at": 0}
        state = {"cards": cards, "config": self.public_config()}
        state["next"] = brain.next_steps(state, limit=4)
        state["presence"] = self.presence
        return state

    async def broadcast(self, message):
        text = json.dumps(message, default=str)
        for ws in list(self.clients):
            try:
                await ws.send_str(text)
            except (ConnectionError, RuntimeError):
                self.clients.discard(ws)

    async def set_presence(self, state, detail=""):
        if state not in PRESENCE:
            return
        self.presence = {"state": state, "detail": str(detail)[:80]}
        await self.broadcast({"type": "presence", **self.presence})

    async def collect_once(self, name):
        entry = self.schedule.get(name) or collectors.SCHEDULE.get(name)
        if not entry:
            return
        fn, _ = entry
        try:
            data = await asyncio.to_thread(fn, self.cfg)
        except Exception as exc:  # a collector must not take the hub down
            data = {"error": f"{type(exc).__name__}: {exc}"[:200]}
        if self.cards.get(name, {}).get("data") != data:
            self.cards[name] = {"data": data, "at": time.time()}
            await self.broadcast({"type": "card", "name": name, **self.cards[name]})
            await self.broadcast({"type": "next", "items": self.snapshot()["next"]})

    async def run_collector(self, name):
        _, every = self.schedule[name]
        while True:
            await self.collect_once(name)
            await asyncio.sleep(every)

    async def start(self, _app=None):
        for name in self.schedule:
            self.tasks.append(asyncio.create_task(self.run_collector(name)))

    async def stop(self, _app=None):
        for t in self.tasks:
            t.cancel()
        for ws in list(self.clients):
            await ws.close()

    # -------------------------------------------------------------- ask
    def _post_json(self, url, payload, timeout):
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())

    def ask_local(self, text):
        """LOOM first (memory, router, skills); Ollama directly when LOOM's backend is down."""
        started = time.time()
        try:
            out = self._post_json(self.cfg["loom_url"].rstrip("/") + "/api/chat",
                                  {"content": text, "session_id": self.loom_session}, timeout=180)
            self.loom_session = out.get("session_id", self.loom_session)
            msg = out.get("message") or {}
            meta = msg.get("metadata") or {}
            return {"answer": msg.get("content", ""), "via": "LOOM",
                    "model": meta.get("model") or meta.get("resolved_model") or "",
                    "ms": int((time.time() - started) * 1000)}
        except Exception as loom_err:  # noqa: BLE001
            try:
                out = self._post_json(self.cfg["ollama_url"].rstrip("/") + "/api/chat",
                                      {"model": self.cfg["fallback_model"], "stream": False,
                                       "messages": [{"role": "user", "content": text}]}, timeout=180)
                return {"answer": (out.get("message") or {}).get("content", ""), "via": "Ollama",
                        "model": self.cfg["fallback_model"], "ms": int((time.time() - started) * 1000),
                        "note": "LOOM is not running, so this came straight from Ollama, without your memory."}
            except Exception as ollama_err:  # noqa: BLE001
                return {"answer": "", "via": "", "error":
                        f"Neither LOOM ({str(loom_err)[:60]}) nor Ollama ({str(ollama_err)[:60]}) answered. "
                        "Start LOOM's backend or Ollama and ask again."}

    async def ask(self, text):
        text = str(text or "").strip()[:4000]
        if not text:
            return {"error": "Ask something."}
        quick = brain.quick_answer(text, self.snapshot())
        if quick:
            return {"route": "instant", "answer": quick, "via": "Mario", "model": "", "ms": 0}
        decision = brain.classify(text, self.cfg["repos"])
        if decision["route"] == "claude":
            repo = decision["repo"] or str(config_mod.ADAPTIVE_REPO)
            plan = brain.plan_handoff(text, repo, self.cfg["claude_cmd"])
            plan["outward"] = decision["outward"]
            plan["status"] = "waiting"
            self.handoffs[plan["id"]] = plan
            await self.set_presence("needs_you", f"Claude Code in {plan['repo']}?")
            return {"route": "claude", "handoff": {k: v for k, v in plan.items() if k != "argv"}}
        await self.set_presence("thinking", "local")
        try:
            result = await asyncio.to_thread(self.ask_local, text)
        finally:
            await self.set_presence("ready")
        return {"route": "local", **result}

    async def run_handoff(self, plan):
        plan["status"] = "running"
        await self.set_presence("doing", f"Claude Code · {plan['repo']}")
        argv = list(plan["argv"])
        if not shutil.which(argv[0]):
            plan["status"] = "failed"
            await self.broadcast({"type": "handoff", "id": plan["id"], "status": "failed",
                                  "line": f"{argv[0]} is not installed; scripts/install-agent-office.sh installs it."})
            await self.set_presence("ready")
            return
        try:
            proc = await asyncio.create_subprocess_exec(*argv, cwd=plan["cwd"], stdout=asyncio.subprocess.PIPE,
                                                        stderr=asyncio.subprocess.STDOUT)
        except OSError as exc:
            plan["status"] = "failed"
            await self.broadcast({"type": "handoff", "id": plan["id"], "status": "failed", "line": str(exc)})
            await self.set_presence("ready")
            return
        try:
            async def pump():
                async for raw in proc.stdout:
                    await self.broadcast({"type": "handoff", "id": plan["id"], "status": "running",
                                          "line": raw.decode(errors="replace").rstrip()})
                return await proc.wait()

            code = await asyncio.wait_for(pump(), timeout=self.cfg["claude_timeout_s"])
            plan["status"] = "done" if code == 0 else "failed"
        except asyncio.TimeoutError:
            proc.kill()
            plan["status"] = "failed"
        changed, _ = await asyncio.to_thread(collectors._run, ["git", "-C", plan["cwd"], "status", "--short"])
        await self.broadcast({"type": "handoff", "id": plan["id"], "status": plan["status"],
                              "changed": (changed or "").splitlines()[:40]})
        await self.set_presence("ready")
        await self.collect_once("builds")

    # ------------------------------------------------------- tasks, notes
    async def add_task(self, text, project=""):
        """A task into a Quick Note inbox, in the format Super+Alt+N and the palette use."""
        text = " ".join(str(text or "").split())[:300]
        if not text:
            return {"ok": False, "error": "empty task"}
        import re as _re
        safe = _re.sub(r"[^\w.-]", "_", project or "General")
        inbox = collectors.NOTES_DIR / safe / "Inbox.md"
        inbox.parent.mkdir(parents=True, exist_ok=True)
        header = "" if inbox.exists() else f"# {safe} inbox\n\n"
        with open(inbox, "a", encoding="utf-8") as f:
            f.write(header + f"- {time.strftime('%Y-%m-%d %H:%M')}  {text}\n")
        await self.collect_once("tasks")
        return {"ok": True}

    async def finish_task(self, path, line):
        """Tick a task, only in a Quick Note inbox and only if that line still holds it."""
        sys.path.insert(0, str(config_mod.ADAPTIVE_REPO / "services" / "project-context"))
        import extras
        try:
            target = Path(path).resolve()
            line = int(line)
        except (TypeError, ValueError, OSError):
            return {"ok": False, "error": "bad task"}
        root = collectors.NOTES_DIR.resolve()
        if target.name != "Inbox.md" or root not in target.parents:
            return {"ok": False, "error": "not a Quick Note inbox"}
        try:
            text = target.read_text(encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        updated = extras.set_task_done(text, line)
        if updated == text:
            return {"ok": False, "error": "that task changed; refresh"}
        target.write_text(updated, encoding="utf-8")
        await self.collect_once("tasks")
        return {"ok": True}

    async def add_note(self, text):
        text = " ".join(str(text or "").split())[:300]
        if not text:
            return {"ok": False, "error": "empty note"}
        self.notes_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.notes_file, "a") as f:
            f.write(f"- {time.strftime('%d %b %H:%M')} · {text}\n")
        await self.broadcast({"type": "card", "name": "notes",
                              "data": {"items": collectors.read_notes(self.notes_file)}, "at": time.time()})
        return {"ok": True}

    # ----------------------------------------------------------- actions
    def action(self, aid, arg):
        repos = {str(p) for p in self.cfg["repos"]} | {str(self.cfg["thinking_space"])}
        if aid in ("terminal", "folder", "claude_session", "code") and str(arg) not in repos:
            return {"ok": False, "error": "not one of Mario's folders"}
        if aid == "terminal":
            cmd = ["gnome-terminal", f"--working-directory={arg}"]
        elif aid == "claude_session":
            cmd = [shutil.which("adaptive-agent") or "adaptive-agent", "claude", str(arg)]
        elif aid == "code":
            cmd = [*editor(), str(arg)]
        elif aid == "folder":
            cmd = ["xdg-open", str(arg)]
        elif aid == "url":
            if not str(arg).startswith(OPEN_URL_PREFIXES):
                return {"ok": False, "error": "Mario only opens its own kinds of links"}
            cmd = ["xdg-open", str(arg)]
        elif aid == "start_office":
            cmd = ["systemctl", "--user", "start", "adaptive-agent-office.service"]
        elif aid == "launch":
            if arg not in LAUNCH:
                return {"ok": False, "error": "not one of Mario's launchers"}
            cmd = LAUNCH[arg]
        elif aid == "open_news":
            items = (self.cards.get("news", {}).get("data") or {}).get("items", [])
            link = next((i["link"] for i in items if i["link"] == arg), None)
            if not link or not link.startswith("https://"):
                return {"ok": False, "error": "only headlines shown on Home open from here"}
            cmd = ["xdg-open", link]
        elif aid == "open_file":
            listed = {f["path"] for name in ("recent", "downloads")
                      for f in (self.cards.get(name, {}).get("data") or {}).get("files", [])}
            if str(arg) not in listed:
                return {"ok": False, "error": "only files shown on Home open from here"}
            cmd = ["xdg-open", str(arg)]
        else:
            return {"ok": False, "error": f"unknown action {aid}"}
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}


# ---------------------------------------------------------------- web

@web.middleware
async def loopback_only(request, handler):
    """Refuse other hosts (DNS rebinding) and cross-site writes from pages in a browser."""
    port = request.app["port"]
    if request.host not in (f"127.0.0.1:{port}", f"localhost:{port}"):
        return web.json_response({"error": "wrong host"}, status=403)
    origin = request.headers.get("Origin")
    if request.method != "GET" and origin and origin not in (f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
        return web.json_response({"error": "cross-site request"}, status=403)
    return await handler(request)


def make_app(hub, port):
    app = web.Application(middlewares=[loopback_only])
    app["port"] = port
    app["hub"] = hub

    async def page(_request):
        return web.FileResponse(STATIC / "index.html")

    async def state(_request):
        return web.json_response(hub.snapshot(), dumps=lambda o: json.dumps(o, default=str))

    async def ws(request):
        sock = web.WebSocketResponse(heartbeat=30)
        await sock.prepare(request)
        hub.clients.add(sock)
        await sock.send_str(json.dumps({"type": "state", **hub.snapshot()}, default=str))
        try:
            async for msg in sock:
                if msg.type == WSMsgType.ERROR:
                    break
        finally:
            hub.clients.discard(sock)
        return sock

    async def read(request):
        try:
            data = await request.json()
        except ValueError:
            data = {}
        return data if isinstance(data, dict) else {}

    async def ask(request):
        return web.json_response(await hub.ask((await read(request)).get("text")))

    async def handoff(request):
        plan = hub.handoffs.get(request.match_info["id"])
        if not plan:
            return web.json_response({"error": "no such plan"}, status=404)
        decision = (await read(request)).get("decision")
        if plan["status"] != "waiting":
            return web.json_response({"error": f"already {plan['status']}"}, status=409)
        if decision == "run":
            asyncio.create_task(hub.run_handoff(plan))
            return web.json_response({"ok": True, "status": "running"})
        plan["status"] = "cancelled"
        await hub.set_presence("ready")
        return web.json_response({"ok": True, "status": "cancelled"})

    async def action(request):
        data = await read(request)
        return web.json_response(hub.action(data.get("id"), data.get("arg")))

    async def presence(request):
        data = await read(request)
        if data.get("state") not in PRESENCE:
            return web.json_response({"error": "unknown state"}, status=400)
        await hub.set_presence(data["state"], data.get("detail", ""))
        return web.json_response({"ok": True})

    async def task(request):
        data = await read(request)
        return web.json_response(await hub.add_task(data.get("text"), data.get("project", "")))

    async def task_done(request):
        data = await read(request)
        return web.json_response(await hub.finish_task(data.get("path"), data.get("line")))

    async def note(request):
        return web.json_response(await hub.add_note((await read(request)).get("text")))

    app.router.add_post("/api/task", task)
    app.router.add_post("/api/task/done", task_done)
    app.router.add_post("/api/note", note)
    app.router.add_get("/", page)
    app.router.add_get("/panel", page)
    app.router.add_get("/api/state", state)
    app.router.add_get("/ws", ws)
    app.router.add_post("/api/ask", ask)
    app.router.add_post("/api/handoff/{id}", handoff)
    app.router.add_post("/api/action", action)
    app.router.add_post("/api/presence", presence)
    app.router.add_static("/static/", STATIC)
    app.on_startup.append(hub.start)
    # on_shutdown runs before aiohttp waits for open connections; Home's WebSocket never closes on
    # its own, so closing it only at cleanup left every stop hanging until systemd's SIGKILL
    app.on_shutdown.append(hub.stop)
    return app


def main():
    ap = argparse.ArgumentParser(description="Mario Hub")
    ap.add_argument("--port", type=int)
    ap.add_argument("--config")
    ap.add_argument("--once", action="store_true", help="print one full state and exit")
    args = ap.parse_args()
    cfg = config_mod.load(args.config)
    port = args.port or int(cfg["port"])
    hub = Hub(cfg)
    if args.once:
        async def once():
            await asyncio.gather(*(hub.collect_once(n) for n in hub.schedule))
            print(json.dumps(hub.snapshot(), indent=1, default=str))
        asyncio.run(once())
        return
    web.run_app(make_app(hub, port), host="127.0.0.1", port=port, print=None, shutdown_timeout=3)
    # A collector thread may still sit in an IMAP login or a subprocess (up to 20 s); nothing is
    # left to save, so leave now instead of waiting for it. systemd ends any child (KillMode=mixed).
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
