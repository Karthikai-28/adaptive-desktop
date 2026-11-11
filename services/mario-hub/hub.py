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
  POST /api/focus        {"minutes"}: start (25/50/90...) or stop (0) a focus block
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
                     "https://www.instagram.com/", "http://127.0.0.1:", "http://localhost:")
REPO = config_mod.ADAPTIVE_REPO
# 1x1 launcher tiles: id -> command. Only these run; a missing program shows the tile dimmed.
LAUNCH = {
    "terminal": ["gnome-terminal"],
    "files": ["xdg-open", str(Path.home())],
    "code": ["code"],
    "settings": ["gnome-control-center"],
    "phone": [sys.executable, str(REPO / "apps" / "adaptive-phone" / "phone.py")],
    "mario": [sys.executable, str(REPO / "apps" / "mario-home" / "host.py"), "--panel"],
    "downloads": ["xdg-open", str(Path.home() / "Downloads")],
    "screenshot": ["gnome-screenshot", "--interactive"],
    "cast": [str(REPO / "scripts" / "adaptive-cast-launch.sh"), "--toggle"],
    "calculator": ["gnome-calculator"],
    "lock": ["loginctl", "lock-session"],
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
        self.focus = {"until": 0, "minutes": 0}
        self.notes_file = config_mod.DATA_DIR / "notes.md"

    # ------------------------------------------------------------ state
    def public_config(self):
        return {"backup_at": self.cfg.get("backup_at", ""), "cards_off": self.cfg.get("cards_off", []),
                "host": os.uname().nodename,
                "launch": {k: bool(shutil.which(v[0]) or Path(v[0]).exists() or (len(v) > 1 and Path(v[1]).exists()))
                           for k, v in LAUNCH.items()}}

    def snapshot(self):
        cards = dict(self.cards)
        cards["focus"] = {"data": self.focus, "at": 0}
        cards["notes"] = {"data": {"items": collectors.read_notes(self.notes_file)}, "at": 0}
        state = {"cards": cards, "config": self.public_config()}
        state["next"] = brain.next_steps(state)
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
        fn, _ = self.schedule[name]
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

    # ------------------------------------------------------- focus, notes
    async def set_focus(self, minutes):
        minutes = max(0, min(int(minutes or 0), 180))
        self.focus = {"until": time.time() + minutes * 60 if minutes else 0, "minutes": minutes}
        await self.broadcast({"type": "card", "name": "focus", "data": self.focus, "at": time.time()})
        if minutes:
            until = self.focus["until"]

            async def ring():
                await asyncio.sleep(minutes * 60)
                if self.focus.get("until") == until:
                    self.focus = {"until": 0, "minutes": 0}
                    await self.broadcast({"type": "card", "name": "focus", "data": self.focus, "at": time.time()})
                    if shutil.which("notify-send"):
                        subprocess.Popen(["notify-send", "-a", "Mario", "Focus done", f"{minutes} minutes. Take a break."])
            asyncio.create_task(ring())

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
        if aid in ("terminal", "folder", "claude_session") and str(arg) not in repos:
            return {"ok": False, "error": "not one of Mario's folders"}
        if aid == "terminal":
            cmd = ["gnome-terminal", f"--working-directory={arg}"]
        elif aid == "claude_session":
            cmd = [shutil.which("adaptive-agent") or "adaptive-agent", "claude", str(arg)]
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

    async def focus(request):
        await hub.set_focus((await read(request)).get("minutes"))
        return web.json_response({"ok": True, **hub.focus})

    async def note(request):
        return web.json_response(await hub.add_note((await read(request)).get("text")))

    app.router.add_post("/api/focus", focus)
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
    app.on_cleanup.append(hub.stop)
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
    web.run_app(make_app(hub, port), host="127.0.0.1", port=port, print=None)


if __name__ == "__main__":
    main()
