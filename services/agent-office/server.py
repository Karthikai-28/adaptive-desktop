"""Agent Office — web server. Run: python3 server.py  (then open http://127.0.0.1:8790). See docs/AGENT_OFFICE.md."""
import asyncio
import contextlib
import mimetypes
import os
import time

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from office import config, voice
from office.agy import _env as agy_env
from office.config import AGY_HOME, COMPANY, DATA, STATIC
from office.core import Office
from office.store import Store

CFG = config.load()
PORT = int(os.environ.get("OFFICE_PORT", CFG["port"]))
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
ALLOWED_ORIGINS = {f"http://{h}" for h in ALLOWED_HOSTS}

store = Store(DATA / "office.db")
office = Office(CFG, store)
usage_cache = {"ts": 0, "rows": [], "error": ""}


@contextlib.asynccontextmanager
async def lifespan(app):
    await office.start()
    task = asyncio.create_task(_usage_loop())
    yield
    task.cancel()
    await office.shutdown()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)


@app.middleware("http")
async def guard(request: Request, call_next):
    """Only this machine's browser may drive the office: blocks DNS rebinding and cross-site requests."""
    if request.headers.get("host") not in ALLOWED_HOSTS:
        return JSONResponse({"error": "forbidden host"}, 403)
    if request.method not in ("GET", "HEAD"):
        origin = request.headers.get("origin")
        if request.headers.get("x-office") != "1" or (origin and origin not in ALLOWED_ORIGINS):
            return JSONResponse({"error": "forbidden"}, 403)
    return await call_next(request)


def bad(e):
    raise HTTPException(400, str(e))


# ---------------------------------------------------------------- live updates
@app.websocket("/ws")
async def ws(sock: WebSocket):
    if sock.headers.get("origin") not in ALLOWED_ORIGINS or sock.headers.get("host") not in ALLOWED_HOSTS:
        await sock.close(code=1008)
        return
    await sock.accept()
    office.clients.add(sock)
    try:
        await sock.send_json(office.snapshot())
        await sock.send_json({"type": "usage", **usage_cache})
        while True:
            await sock.receive_text()       # keep-alive pings from the page
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        office.clients.discard(sock)


@app.get("/api/state")
async def state():
    return office.snapshot()


# ---------------------------------------------------------------- chat
class ChatIn(BaseModel):
    to: str
    text: str
    sender: str | None = None


@app.post("/api/chat")
async def chat(m: ChatIn):
    if not m.text.strip():
        bad("empty message")
    sender = m.sender if m.sender in (None, "operator", office.mgr["id"]) else "operator"
    try:
        return await office.dm(m.to, m.text.strip(), sender)
    except ValueError as e:
        bad(e)


@app.get("/api/messages")
async def messages(thread: str, after: int = 0, limit: int = 100):
    return store.messages(thread, limit=min(limit, 500), after_id=after)


# ---------------------------------------------------------------- tasks
class TaskIn(BaseModel):
    agent: str
    title: str
    body: str = ""
    project: str = ""
    after: int | None = None
    created_by: str | None = None


@app.post("/api/tasks")
async def add_task(t: TaskIn, request: Request):
    by = t.created_by if t.created_by in ("operator", "manager", "meeting") else "operator"
    if by == "manager":   # rate-limit what Claude can queue on autopilot
        recent = store.tasks(created_since=time.time() - 3600, limit=1000)
        if sum(1 for x in recent if x["created_by"] in ("manager", "meeting")) >= 40:
            bad("manager task limit reached (40 per hour) — ask the owner before assigning more")
    try:
        return await office.add_task(t.agent, t.title, t.body, t.project, by, t.after)
    except ValueError as e:
        bad(e)


@app.get("/api/tasks")
async def tasks(agent: str | None = None, status: str | None = None, limit: int = 100):
    return store.tasks(agent=agent, status=status, limit=min(limit, 1000))


@app.get("/api/tasks/{tid}")
async def task(tid: int):
    t = store.task(tid)
    if not t:
        raise HTTPException(404, "no such task")
    return {**t, "events": store.events(task_id=tid, limit=400)}


@app.post("/api/tasks/{tid}/cancel")
async def cancel(tid: int):
    try:
        return await office.cancel_task(tid)
    except ValueError as e:
        bad(e)


@app.post("/api/tasks/{tid}/retry")
async def retry(tid: int):
    try:
        return await office.retry_task(tid)
    except ValueError as e:
        bad(e)


@app.get("/api/events")
async def events(agent: str | None = None, limit: int = 100):
    return store.events(agent=agent, limit=min(limit, 1000))


# ---------------------------------------------------------------- agents
@app.post("/api/agents/{aid}/reset")
async def reset(aid: str):
    if aid not in office.rt:
        raise HTTPException(404, "no such agent")
    await office.reset_memory(aid)
    return {"ok": True}


@app.post("/api/agents/{aid}/stop")
async def stop(aid: str):
    if aid not in office.rt:
        raise HTTPException(404, "no such agent")
    await office.stop_agent(aid)
    return {"ok": True}


# ---------------------------------------------------------------- meetings
class MeetingIn(BaseModel):
    topic: str = ""
    attendees: list[str]


class SayIn(BaseModel):
    text: str


class InviteIn(BaseModel):
    attendees: list[str]


@app.post("/api/meeting/start")
async def meeting_start(m: MeetingIn):
    try:
        return await office.start_meeting(m.topic, m.attendees)
    except ValueError as e:
        bad(e)


@app.post("/api/meeting/say")
async def meeting_say(s: SayIn):
    if not s.text.strip():
        bad("empty message")
    try:
        return await office.meeting_say(s.text.strip())
    except ValueError as e:
        bad(e)


@app.post("/api/meeting/invite")
async def meeting_invite(i: InviteIn):
    try:
        return await office.invite(i.attendees)
    except ValueError as e:
        bad(e)


@app.post("/api/meeting/end")
async def meeting_end():
    try:
        return await office.end_meeting()
    except ValueError as e:
        bad(e)


@app.get("/api/meeting")
async def meeting_current():
    m = store.active_meeting()
    return {"meeting": m, "messages": store.messages(f"meeting:{m['id']}", limit=500) if m else []}


# ---------------------------------------------------------------- study programs
@app.get("/api/study")
async def study():
    return office.study.all_status()


@app.post("/api/study/{pid}/{action}")
async def study_control(pid: str, action: str):
    try:
        return await office.study.control(pid, action)
    except ValueError as e:
        bad(e)


# ---------------------------------------------------------------- settings / usage
class SettingsIn(BaseModel):
    autopilot: bool | None = None
    max_parallel: int | None = None
    paused: bool | None = None
    clear_quota: bool = False


@app.post("/api/settings")
async def settings(s: SettingsIn):
    return await office.update_settings(**s.model_dump())


@app.get("/api/usage")
async def usage():
    return usage_cache


async def _usage_loop():
    while True:
        await _refresh_usage()
        await asyncio.sleep(180)


async def _refresh_usage():
    try:
        proc = await asyncio.create_subprocess_exec(
            "agy", "-p", "/usage", cwd=str(COMPANY), env=agy_env("usage"),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
        rows = []
        for line in out.decode(errors="replace").splitlines():
            parts = line.split("\t")
            if len(parts) >= 3 and parts[0].startswith("Gemini"):
                rows.append({"window": "week" if "Weekly" in parts[1] else "5h",
                             "remaining": parts[2], "resets": parts[3] if len(parts) > 3 else ""})
        usage_cache.update(ts=time.time(), rows=rows, error="" if rows else "no usage data")
    except Exception as e:  # usage is informational only
        usage_cache.update(ts=time.time(), error=str(e)[:200])
    await office.broadcast({"type": "usage", **usage_cache})


# ---------------------------------------------------------------- voice
@app.get("/api/tts")
async def tts(who: str, text: str):
    person = next((p for p in office.roster() if p["id"] == who), None)
    v = person["voice"] if person else "en-US-AvaNeural"
    path = await voice.tts(v, text)
    if not path:
        raise HTTPException(503, "speech synthesis unavailable")
    return FileResponse(path, media_type="audio/mpeg", headers={"Cache-Control": "max-age=86400"})


# ---------------------------------------------------------------- company files
def _safe(rel):
    p = (COMPANY / (rel or "").lstrip("/")).resolve()
    try:
        p.relative_to(COMPANY.resolve())
    except ValueError:
        raise HTTPException(403, "outside the workspace")
    if not p.exists():
        raise HTTPException(404, "not found")
    return p


@app.get("/api/files")
async def files(path: str = ""):
    p = _safe(path)
    root = COMPANY.resolve()
    if p.is_dir():
        entries = []
        for c in sorted(p.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower())):
            if c.name.startswith(".") or c.name in ("node_modules", "__pycache__", ".venv", "venv"):
                continue
            st = c.stat()
            entries.append({"name": c.name, "path": str(c.relative_to(root)), "dir": c.is_dir(),
                            "size": st.st_size, "mtime": st.st_mtime})
        return {"type": "dir", "path": str(p.relative_to(root)) if p != root else "", "entries": entries}
    mime = mimetypes.guess_type(p.name)[0] or ""
    size = p.stat().st_size
    if mime.startswith(("image/", "video/", "audio/")) or p.suffix.lower() == ".pdf":
        return {"type": "media", "path": str(p.relative_to(root)), "mime": mime, "size": size}
    raw = p.read_bytes()[:400_000]
    if b"\0" in raw[:4096]:
        return {"type": "binary", "path": str(p.relative_to(root)), "size": size}
    return {"type": "text", "path": str(p.relative_to(root)), "size": size, "mime": mime,
            "text": raw.decode(errors="replace"), "truncated": size > len(raw)}


@app.get("/api/raw")
async def raw(path: str):
    p = _safe(path)
    if p.is_dir():
        raise HTTPException(400, "is a directory")
    # agent-made pages run in a sandboxed opaque origin: they can never call this API
    return FileResponse(p, headers={"Content-Security-Policy": "sandbox allow-scripts allow-popups allow-forms",
                                    "X-Content-Type-Options": "nosniff"})


# ---------------------------------------------------------------- page
@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


app.mount("/static", StaticFiles(directory=STATIC), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning", ws_ping_interval=20)
