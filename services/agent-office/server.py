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

from office import callers, config, operator, voice
from office.config import AGY_HOME, COMPANY, DATA, STATIC
from office.core import Office
from office.store import Store
from office.mission_templates import launch_ros_investigation
from office.ros_compare import compare_bags

CFG = config.load()
PORT = int(os.environ.get("OFFICE_PORT", CFG["port"]))
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
ALLOWED_ORIGINS = {f"http://{h}" for h in ALLOWED_HOSTS}

store = Store(DATA / "office.db")
office = Office(CFG, store)
operator.key()                       # created on first start; the owner's `office` command reads it


@contextlib.asynccontextmanager
async def lifespan(app):
    await office.start()
    yield
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


async def caller(request: Request, claimed=""):
    """(actor, is_operator) for a request. The manager is recognised by its process tree, not by what it
    says; the operator by the key in X-Office-Operator. Anyone else is attributed as they claim
    ("manager"/"meeting"), else as the operator's app - which grants nothing the key would."""
    peer = request.client
    manager = bool(office.manager.pids) and peer is not None and await asyncio.to_thread(
        callers.owned_by, set(office.manager.pids), peer.host, peer.port, PORT)
    if manager:
        return "manager", False
    if operator.valid(request.headers.get("x-office-operator", "")):
        return "operator", True
    claimed = claimed or request.headers.get("x-office-actor", "")
    return (claimed if claimed in ("manager", "meeting") else "operator"), False


def manager_limit(by):
    """Claude may queue at most 40 tasks an hour on autopilot; a mission's first task counts."""
    if by in ("manager", "meeting"):
        recent = store.tasks(created_since=time.time() - 3600, limit=1000)
        if sum(1 for x in recent if x["created_by"] in ("manager", "meeting")) >= 40:
            bad("manager task limit reached (40 per hour) — ask the owner before assigning more")


def needs_operator(is_operator, what):
    if not is_operator:
        raise HTTPException(403, f"{what} needs the operator key (run `office operator-key` in your terminal "
                                 "and enter it in the office app, or use the `office` command yourself)")


def guard_mission_risk(mid, is_operator, what):
    m = store.mission(int(mid)) if mid else None
    if m and m.get("risk") in ("hardware", "external"):
        needs_operator(is_operator, f"{what} in a {m['risk']} mission")


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
        await sock.send_json({"type": "usage", **office.quota.usage})
        while True:
            await sock.receive_text()       # keep-alive pings from the page
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        office.clients.discard(sock)


@app.get("/api/state")
async def state():
    return office.snapshot()


@app.get("/api/health")
async def health():
    return {"ok": True, "service": "agent-office", "local_only": True,
            "paused": bool(store.get("paused", False)), "autopilot": bool(store.get("autopilot", False)),
            "missions": store.mission_count()}


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
    repo: str = ""
    mission_id: int | None = None


@app.post("/api/tasks")
async def add_task(t: TaskIn, request: Request):
    by, is_operator = await caller(request, t.created_by or "")
    manager_limit(by)
    guard_mission_risk(t.mission_id, is_operator, "adding work")
    try:
        return await office.add_task(t.agent, t.title, t.body, t.project, by, t.after, t.repo, t.mission_id)
    except ValueError as e:
        bad(e)


@app.get("/api/repos")
async def repos():
    """Repository index used to scope tasks; agents can access non-secret files throughout home."""
    return {"enabled": office.repos.enabled, "repos": office.repos.paths, "scanned_at": office.repos.scanned_at}


@app.get("/api/tasks")
async def tasks(agent: str | None = None, status: str | None = None, limit: int = 100):
    return store.tasks(agent=agent, status=status, limit=min(limit, 1000))


# ---------------------------------------------------------------- missions
class MissionIn(BaseModel):
    agent: str
    title: str
    objective: str
    criteria: list[str]
    project: str = ""
    repo: str = ""


@app.post("/api/missions")
async def add_mission(m: MissionIn, request: Request):
    by, _ = await caller(request)
    manager_limit(by)
    try:
        return await office.add_mission(m.agent, m.title, m.objective, m.criteria, m.project, m.repo, created_by=by)
    except ValueError as e:
        bad(e)


@app.get("/api/missions")
async def missions(limit: int = 100):
    return store.missions(limit=max(1, min(limit, 500)))


@app.get("/api/missions/{mid}")
async def mission(mid: int):
    m = store.mission(mid, with_tasks=True)
    if not m:
        raise HTTPException(404, "no such mission")
    return m


@app.post("/api/missions/{mid}/cancel")
async def cancel_mission(mid: int):
    try:
        return await office.cancel_mission(mid)
    except ValueError as e:
        bad(e)


@app.post("/api/missions/{mid}/export")
async def export_mission(mid: int):
    try:
        return await office.audit_export.mission(mid)
    except ValueError as e:
        bad(e)


class RetentionIn(BaseModel):
    days: int = 90
    kinds: list[str] = ["capsules", "exports"]
    apply: bool = False


@app.post("/api/retention")
async def retention(r: RetentionIn, request: Request):
    if r.apply:
        needs_operator((await caller(request))[1], "deleting records")
    try:
        return await asyncio.to_thread(office.retention.inspect, r.days, r.kinds, r.apply, store.mission_ids())
    except ValueError as e:
        bad(e)


class RosMissionIn(BaseModel):
    agent: str
    problem: str
    title: str = "Investigate ROS 2 failure"
    bag: str = ""
    baseline_bag: str = ""
    simulation_command: str = ""
    project: str = ""
    repo: str = ""


@app.post("/api/missions/ros-investigation")
async def ros_investigation(m: RosMissionIn, request: Request):
    by, _ = await caller(request)
    manager_limit(by)
    try:
        return await launch_ros_investigation(office, m.agent, m.title, m.problem, m.bag, m.project, m.repo,
                                              m.baseline_bag, m.simulation_command, created_by=by)
    except ValueError as e:
        bad(e)


# ---------------------------------------------------------------- reusable workflows
class WorkflowIn(BaseModel):
    id: str = ""
    title: str
    description: str = ""
    objective: str = ""
    criteria: list[str] = []
    agent: str = ""
    project: str = ""
    repo: str = ""
    risk: str = "write"
    allowed_agents: list[str] = []
    from_mission: int | None = None     # copy objective, criteria, scope, owner and template from a mission


class WorkflowRunIn(BaseModel):
    inputs: dict = {}
    agent: str = ""
    project: str = ""
    repo: str = ""
    approved: bool = False


@app.get("/api/workflows")
async def workflows():
    return office.workflows.list()


@app.post("/api/workflows")
async def save_workflow(w: WorkflowIn, request: Request):
    by, is_operator = await caller(request)
    objective, criteria, project, repo, agent, template = w.objective, w.criteria, w.project, w.repo, w.agent, None
    if w.from_mission:
        m = store.mission(w.from_mission, with_tasks=True)
        if not m:
            bad("no such mission")
        template = m.get("template") or None
        objective = (template or {}).get("problem") or m["objective"]
        criteria, project, repo = m["criteria"], m["project"], m["repo"]
        agent = agent or (m["tasks"][0]["agent"] if m["tasks"] else "")
    try:
        return office.workflows.save(w.title, objective, criteria, w.description, w.id, agent, project, repo,
                                     w.risk, w.allowed_agents, template, by, is_operator)
    except ValueError as e:
        bad(e)


@app.get("/api/workflows/{wid}")
async def workflow(wid: str):
    w = office.workflows.get(wid)
    if not w:
        raise HTTPException(404, "no such workflow")
    return w


@app.post("/api/workflows/{wid}/run")
async def run_workflow(wid: str, r: WorkflowRunIn, request: Request):
    by, is_operator = await caller(request)
    if r.approved:
        needs_operator(is_operator, "approving a workflow run")
    manager_limit(by)
    try:
        return await office.workflows.run(wid, r.inputs, r.agent, r.project, r.repo,
                                          "operator" if r.approved else "", by)
    except ValueError as e:
        bad(e)


class RosCompareIn(BaseModel):
    baseline: str
    candidate: str


@app.post("/api/ros/compare")
async def ros_compare(r: RosCompareIn):
    try:
        return await asyncio.to_thread(compare_bags, r.baseline, r.candidate)
    except ValueError as e:
        bad(e)


# ---------------------------------------------------------------- reproducible work capsules
class CapsuleIn(BaseModel):
    mission_id: int | None = None
    project: str = ""
    repo: str = ""
    command: str = ""
    launch_args: list[str] = []
    parameters: dict = {}
    datasets: list[str] = []
    results: list[str] = []
    notes: str = ""


@app.post("/api/capsules")
async def create_capsule(c: CapsuleIn):
    try:
        return await office.capsules.create(**c.model_dump())
    except ValueError as e:
        bad(e)


@app.get("/api/capsules")
async def capsules(limit: int = 100, mission_id: int | None = None):
    return await asyncio.to_thread(office.capsules.list, max(1, min(limit, 500)), mission_id)


@app.get("/api/capsules/{cid}")
async def capsule(cid: str):
    c = office.capsules.get(cid)
    if not c:
        raise HTTPException(404, "no such capsule")
    return c


@app.get("/api/evidence/search")
async def search_evidence(q: str, mission_id: int | None = None, limit: int = 40):
    try:
        return await office.evidence.search(q, mission_id, limit)
    except ValueError as e:
        bad(e)


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
async def retry(tid: int, request: Request):
    t = store.task(tid)
    guard_mission_risk(t and t.get("mission_id"), (await caller(request))[1], "running work again")
    try:
        return await office.retry_task(tid)
    except ValueError as e:
        bad(e)


@app.get("/api/events")
async def events(agent: str | None = None, task_id: int | None = None, limit: int = 100):
    return store.events(agent=agent, task_id=task_id, limit=min(limit, 1000))


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
    provider: str | None = None
    fallback: str | None = None
    clear_quota: bool = False


@app.post("/api/settings")
async def settings(s: SettingsIn, request: Request):
    if s.paused is not None and (await caller(request))[0] == "manager":
        raise HTTPException(403, "only the owner can pause or resume the office")
    try:
        return await office.update_settings(**s.model_dump())
    except ValueError as e:
        bad(e)


@app.get("/api/usage")
async def usage():
    return office.quota.usage


@app.post("/api/usage/refresh")
async def refresh_usage():
    """Refresh agy's plan limits now; used by the desktop usage card."""
    return await office.quota.refresh()


# ---------------------------------------------------------------- token ledger
@app.get("/api/tokens")
async def tokens(since: float = 0, provider: str | None = None):
    return office.ledger.overview(since, provider or None)


@app.get("/api/tokens/agent/{aid}")
async def tokens_agent(aid: str, since: float = 0, provider: str | None = None):
    if aid not in office.rt and aid not in ("planner", "other"):
        raise HTTPException(404, "no such agent")
    return office.ledger.agent(aid, since, provider or None)


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
