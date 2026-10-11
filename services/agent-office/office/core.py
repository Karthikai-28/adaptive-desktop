"""The office: agents, the task scheduler, direct messages and meetings.

Each agent keeps three agy conversations so they never collide:
  conv:<id>              its work thread (tasks, run one at a time, in order)
  chatconv:<id>          its direct-message thread (can run while it works)
  meetconv:<mid>:<id>    one per meeting it attends
"""
import asyncio
import datetime as dt
import json
import re
import time

from . import agy
from .config import COMPANY
from .manager import Manager
from .quota import QuotaGuard
from .graphs import Graphs
from .study import Study

NAME_RE_CACHE = {}


CONV_ROTATE_TOKENS = 400_000     # a work thread that cost more than this is not resumed again
CHAT_ROTATE_TOKENS = 250_000


def _clean_speech(text):
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"[*_#`>]+", "", text)
    return text.strip()


def _slug(s, n=40):
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:n].strip("-") or "meeting"


class Office:
    def __init__(self, cfg, store):
        self.cfg = cfg
        self.store = store
        self.company = cfg["company"]
        self.operator = cfg["operator"]
        self.model = cfg["gemini_model"]
        self.mgr = cfg["manager"]
        self.agents = {a["id"]: a for a in cfg["agents"]}
        self.rt = {aid: self._fresh_rt() for aid in [*self.agents, self.mgr["id"]]}
        self.clients = set()
        self.task_runs = {}                 # task id -> AgyRun
        self.chat_runs = {}                 # agent id -> AgyRun
        self.chat_q = {aid: asyncio.Queue() for aid in self.agents}
        self.meet_locks = {aid: asyncio.Lock() for aid in self.agents}
        self.meet_runs = {}                 # agent id -> AgyRun
        self.quota_until = store.get("quota_until", 0)
        self.manager = Manager(self)
        self.study = Study(self)
        self.quota = QuotaGuard(self)
        self.graphs = Graphs(self)
        self._bg = set()
        self._sched_lock = asyncio.Lock()

    @staticmethod
    def _fresh_rt():
        return {"status": "idle", "task": None, "activity": "", "activity_ts": 0, "chatting": False,
                "meeting_busy": False}

    # ------------------------------------------------------------------ lifecycle
    async def start(self):
        agy.write_agy_settings()
        await asyncio.get_running_loop().run_in_executor(None, Graphs.configure_agy)
        for t in self.store.tasks(status="running"):     # the server stopped mid-task: pick it up again
            self.store.update_task(t["id"], status="queued")
            self.store.add_event(t["agent"], "info", "Resuming after an office restart", t["id"])
        for aid in self.agents:
            self._spawn(self._chat_worker(aid))
        self.manager.start()
        self.study.start()
        self.quota.start()
        self.graphs.start()
        self.kick()

    def _spawn(self, coro):
        t = asyncio.create_task(coro)
        self._bg.add(t)
        t.add_done_callback(self._bg.discard)
        return t

    # ------------------------------------------------------------------ settings
    def settings(self):
        return {
            "autopilot": self.store.get("autopilot", self.mgr.get("autopilot", True)),
            "max_parallel": self.store.get("max_parallel", self.cfg.get("max_parallel_tasks", 3)),
            "paused": self.store.get("paused", False),
        }

    async def update_settings(self, **kw):
        for k in ("autopilot", "max_parallel", "paused"):
            if k in kw and kw[k] is not None:
                v = kw[k]
                if k == "max_parallel":
                    v = max(1, min(8, int(v)))
                self.store.set(k, v)
        if kw.get("clear_quota") and self.quota_until:
            await self.quota.resume()
        await self.broadcast({"type": "settings", "settings": self.settings(), "quota_until": self.quota_until})
        self.kick()
        return self.settings()

    # ------------------------------------------------------------------ broadcast
    async def broadcast(self, msg):
        dead = []
        data = json.dumps(msg)
        for ws in list(self.clients):
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    def roster(self):
        people = [{**{k: a[k] for k in ("id", "name", "role", "team", "desk", "voice", "look")},
                   "kind": "gemini"} for a in self.agents.values()]
        m = self.mgr
        people.append({"id": m["id"], "name": m["name"], "role": m["role"], "team": "Management",
                       "desk": "boss", "voice": m["voice"], "look": m["look"], "kind": "claude"})
        return people

    def agent_state(self, aid):
        rt = self.rt[aid]
        meeting = self.store.active_meeting()
        in_meeting = bool(meeting and aid in meeting["attendees"])
        if aid == self.mgr["id"]:
            status = "working" if self.manager.busy else "idle"
            queued = self.manager.pending
        else:
            queued = len(self.store.next_queued(aid))
            if self.quota_until > time.time() and not rt["task"]:
                status = "quota"
            elif rt["task"]:
                status = "working"
            elif rt["chatting"] or rt["meeting_busy"]:
                status = "thinking"
            else:
                status = "idle"
        return {"id": aid, "status": status, "in_meeting": in_meeting, "task": rt["task"],
                "activity": rt["activity"], "activity_ts": rt["activity_ts"], "queued": queued,
                "chatting": rt["chatting"], "meeting_busy": rt["meeting_busy"]}

    async def push_agent(self, aid):
        await self.broadcast({"type": "agent", "agent": self.agent_state(aid)})

    async def activity(self, aid, kind, text, task_id=None):
        ev = self.store.add_event(aid, kind, text, task_id)
        rt = self.rt[aid]
        rt["activity"], rt["activity_ts"] = text, ev["ts"]
        await self.broadcast({"type": "event", "event": ev})
        await self.push_agent(aid)

    async def post(self, thread, sender, text, meta=None):
        m = self.store.add_message(thread, sender, text, meta)
        await self.broadcast({"type": "message", "message": m})
        return m

    async def toast(self, text, level="info", agent=None):
        await self.broadcast({"type": "toast", "text": text, "level": level, "agent": agent})

    def snapshot(self):
        return {
            "type": "state",
            "company": self.company, "operator": self.operator, "model": self.model,
            "roster": self.roster(),
            "agents": [self.agent_state(a) for a in self.rt],
            "tasks": self.store.tasks(limit=150),
            "meeting": self.store.active_meeting(),
            "settings": self.settings(),
            "quota_until": self.quota_until,
            "studies": self.study.all_status(),
        }

    # ------------------------------------------------------------------ prompts
    def _team_line(self):
        return "; ".join(f"{a['name']} ({a['role']})" for a in self.agents.values())

    def _persona(self, a):
        return (
            f"You are {a['name']}, {a['role']} at {self.company}, an AI company owned by {self.operator}. "
            f"Claude is the manager who coordinates the team; {self.operator} is the owner.\n"
            f"{a['brief']}\n"
            f"Team: {self._team_line()}; manager: Claude.\n"
            f"Workspace: your current directory {COMPANY} is the company's shared workspace; teammates' files "
            f"are here too. Work only inside it. Projects live in projects/<project-name>/, meeting notes in meetings/.\n"
            + self.study.persona_line(a["id"])
            + self._efficiency(a["id"])
        )

    def _conv_key(self, t):
        """Tasks of the same project continue one agy conversation; anything else starts fresh.
        Study sessions always start fresh (their memory is the knowledge base)."""
        if self.study.program_of(t) or not t.get("project"):
            return None
        return f"conv:{t['agent']}:{t['project']}"

    def _efficiency(self, aid):
        graph = self.graphs.path_for(aid)
        # measured 2026-10-11 on mkert: the graph saved 27% on an architecture question but cost 70% more on a
        # named-symbol lookup, where grep is the shortest path - so agents get both, each for its job
        nav = ("For orientation - an unfamiliar area, the architecture, how two parts connect, what the core pieces "
               "are - ask your `graph` tools (query_graph, god_nodes, get_community, get_neighbors, shortest_path). "
               "When you already know a name, grep for it instead. " if graph else "")
        return ("Work economically - every step re-sends your whole context, so keep it small without cutting "
                "corners on quality. " + nav +
                "Search with grep -n (narrow patterns, -m limits) instead of opening whole files; view large files in "
                "line ranges; never cat big files, dump directory trees or print long command output (pipe through "
                "head, tail or wc). Don't re-read what you already read in this session; write short notes instead.\n")

    def _run_opts(self, aid):
        """Sandbox options for every agy run of this agent: the repos it studies (read-only), and the
        guarded profile for agents that must learn code only from local copies."""
        return {"ro_dirs": self.study.repo_paths(aid), "offline": bool(self.agents[aid].get("code_local_only")),
                "graph": self.graphs.path_for(aid)}

    def _task_prompt(self, t):
        a = self.agents[t["agent"]]
        by = {"operator": self.operator, "manager": "Claude (manager)", "meeting": "a team meeting"}.get(
            t["created_by"], t["created_by"])
        p = [self._persona(a),
             "You work autonomously: you cannot ask questions while working, so make sensible assumptions and "
             "state them in your report. Verify your work (run the code, open the files) before you report.\n",
             f"=== TASK #{t['id']} (assigned by {by}) ===",
             f"Title: {t['title']}"]
        if t["project"]:
            p.append(f"Project: {t['project']} — keep its files in projects/{t['project']}/")
        if t["body"]:
            p.append(f"Details:\n{t['body']}")
        if t["depends_on"]:
            d = self.store.task(t["depends_on"])
            if d:
                who = self.agents.get(d["agent"], {}).get("name", d["agent"])
                p.append(f"This builds on task #{d['id']} \"{d['title']}\" by {who}. Their report:\n"
                         f"{(d['result'] or '')[:4000]}")
        if t["attempts"] > 1:
            p.append("Note: an earlier attempt at this task was interrupted or failed. Check the workspace for "
                     "partial work and continue from there rather than starting over.")
        p.append("\nWhen finished, reply with a short report: what you did, the files you created or changed "
                 "(paths relative to the workspace), how you verified it, and anything still open.")
        return "\n".join(p)

    def _status_line(self, aid):
        rt = self.rt[aid]
        if rt["task"]:
            s = f"you are working on task #{rt['task']['id']} \"{rt['task']['title']}\""
            if rt["activity"]:
                s += f" (latest step: {rt['activity']})"
        else:
            s = "you are free right now"
        recent = [t for t in self.store.tasks(agent=aid, limit=5) if t["status"] in ("done", "failed")][:3]
        if recent:
            s += ". Recently: " + "; ".join(f"#{t['id']} {t['title']} ({t['status']})" for t in recent)
        q = self.store.next_queued(aid)
        if q:
            s += f". Queued next: " + "; ".join(f"#{t['id']} {t['title']}" for t in q[:3])
        return s

    # ------------------------------------------------------------------ tasks
    async def add_task(self, agent, title, body="", project="", created_by="operator", depends_on=None):
        if agent not in self.agents:
            raise ValueError(f"unknown agent '{agent}'. Agents: {', '.join(self.agents)}")
        if not title.strip():
            raise ValueError("a task needs a title")
        if depends_on and not self.store.task(int(depends_on)):
            raise ValueError(f"task #{depends_on} does not exist")
        project = _slug(project, 40) if project else ""
        t = self.store.add_task(agent, title.strip(), body.strip(), project, created_by,
                                int(depends_on) if depends_on else None)
        await self.broadcast({"type": "task", "task": t})
        await self.activity(agent, "assign", f"New task #{t['id']}: {t['title']}", t["id"])
        self.kick()
        return t

    async def cancel_task(self, tid):
        t = self.store.task(tid)
        if not t:
            raise ValueError("no such task")
        if t["status"] == "running" and tid in self.task_runs:
            self.task_runs[tid].cancel()
        elif t["status"] in ("queued", "blocked"):
            t = self.store.update_task(tid, status="cancelled", finished_at=time.time())
            await self.broadcast({"type": "task", "task": t})
            await self.push_agent(t["agent"])
        return self.store.task(tid)

    async def retry_task(self, tid):
        t = self.store.task(tid)
        if not t or t["status"] not in ("failed", "cancelled"):
            raise ValueError("only failed or cancelled tasks can be retried")
        t = self.store.update_task(tid, status="queued", error="", finished_at=None)
        await self.broadcast({"type": "task", "task": t})
        self.kick()
        return t

    def kick(self):
        self._spawn(self._schedule())

    async def _schedule(self):
        async with self._sched_lock:
            await self._schedule_locked()

    async def _schedule_locked(self):
        s = self.settings()
        if s["paused"] or self.quota_until > time.time():
            return
        # oldest waiting task first, one running task per agent
        waiting = sorted((t for aid in self.agents for t in self.store.next_queued(aid)), key=lambda t: t["id"])
        busy = {a for a in self.agents if self.rt[a]["task"]}
        for t in waiting:
            if len(self.task_runs) >= s["max_parallel"]:
                break
            if t["agent"] in busy:
                continue
            if t["depends_on"]:
                d = self.store.task(t["depends_on"])
                if d and d["status"] in ("failed", "cancelled"):
                    t = self.store.update_task(t["id"], status="failed", finished_at=time.time(),
                                               error=f"blocked: task #{d['id']} {d['status']}")
                    await self.broadcast({"type": "task", "task": t})
                    continue
                if d and d["status"] != "done":
                    continue
            fresh = self.store.task(t["id"])
            if fresh["status"] != "queued":
                continue
            busy.add(t["agent"])
            self._run_task_start(fresh)

    def _run_task_start(self, t):
        aid = t["agent"]
        t = self.store.update_task(t["id"], status="running", started_at=time.time(), attempts=t["attempts"] + 1)
        self.rt[aid]["task"] = {"id": t["id"], "title": t["title"]}

        async def on_event(kind, text):
            await self.activity(aid, kind, text, t["id"])

        study = self.study.program_of(t)
        run = agy.AgyRun(self.study.prompt(t) if study else self._task_prompt(t),
                         agent_name=self.agents[aid]["name"], model=self.model,
                         conv_id=self.store.get(self._conv_key(t)) if self._conv_key(t) else None,
                         timeout_min=self.cfg.get("task_timeout_min", 45), on_event=on_event, **self._run_opts(aid))
        self.task_runs[t["id"]] = run
        self._spawn(self._run_task(t, run))

    async def _run_task(self, t, run):
        aid, tid = t["agent"], t["id"]
        name = self.agents[aid]["name"]
        await self.broadcast({"type": "task", "task": t})
        await self.push_agent(aid)
        try:
            r = await run.wait()
        except Exception as e:  # never leave an agent stuck at "working"
            r = agy.AgyResult()
            r.error = f"office error: {e}"
        finally:
            self.task_runs.pop(tid, None)
            self.rt[aid]["task"] = None
        study = self.study.program_of(t)
        key = self._conv_key(t)
        if key:
            # keep a project's thread for its next task, but start over once it has grown expensive
            if r.conv_id and r.tokens < CONV_ROTATE_TOKENS:
                self.store.set(key, r.conv_id)
            else:
                self.store.delete(key)
        now = time.time()
        if r.ok and study:
            t = self.store.update_task(tid, status="done", result=r.text.strip(), finished_at=now,
                                       steps=r.steps, tokens=r.tokens, error="")
            await self.activity(aid, "done", f"Finished {t['title']}", tid)
            await self.post(f"dm:{aid}", aid, r.text.strip(), {"task": tid, "kind": "learning", "program": study})
            await self.toast(f"{name} has a learning report ({t['title'].split(':')[0]})", "ok", aid)
        elif r.ok:
            t = self.store.update_task(tid, status="done", result=r.text.strip(), finished_at=now,
                                       steps=r.steps, tokens=r.tokens, error="")
            await self.activity(aid, "done", f"Finished task #{tid}: {t['title']}", tid)
            await self.post(f"dm:{aid}", aid, f"Finished task #{tid} \"{t['title']}\".\n\n{r.text.strip()}",
                            {"task": tid, "kind": "report"})
            await self.toast(f"{name} finished #{tid}: {t['title']}", "ok", aid)
        elif r.cancelled:
            t = self.store.update_task(tid, status="cancelled", finished_at=now, steps=r.steps, tokens=r.tokens)
            await self.activity(aid, "info", f"Task #{tid} cancelled", tid)
        elif r.quota:
            # back in the queue untouched; the quota guard resumes it when Gemini resets
            t = self.store.update_task(tid, status="queued", attempts=max(0, t["attempts"] - 1), error=r.error)
            await self.activity(aid, "error", "Gemini quota reached — waiting for it to reset", tid)
            self._spawn(self.quota.hit(aid))
        elif "conversation" in r.error.lower() and key and self.store.get(key) and t["attempts"] < 3:
            self.store.delete(key)   # a stale work thread: start a fresh one
            t = self.store.update_task(tid, status="queued", error=r.error)
        elif t["attempts"] < 2 and "time" not in r.error.lower():
            t = self.store.update_task(tid, status="queued", error=r.error)
            await self.activity(aid, "error", f"Task #{tid} hit a problem, retrying: {r.error[:120]}", tid)
        else:
            t = self.store.update_task(tid, status="failed", finished_at=now, error=r.error,
                                       result=r.text.strip(), steps=r.steps, tokens=r.tokens)
            await self.activity(aid, "error", f"Task #{tid} failed: {r.error[:140]}", tid)
            await self.post(f"dm:{aid}", aid, f"I couldn't finish task #{tid} \"{t['title']}\": {r.error}",
                            {"task": tid, "kind": "failure"})
            await self.toast(f"{name}: task #{tid} failed", "error", aid)
        await self.broadcast({"type": "task", "task": t})
        await self.push_agent(aid)
        if study and t["status"] in ("done", "failed", "cancelled"):
            await self.study.finished(t, t["status"] == "done")
        if t["status"] in ("done", "failed") and t["created_by"] in ("manager", "meeting"):
            self.manager.task_finished(t)
        self.kick()

    # ------------------------------------------------------------------ direct messages
    async def dm(self, aid, text, sender=None):
        sender = sender or "operator"
        if aid == self.mgr["id"]:
            m = await self.post("manager", sender, text)
            self.manager.chat(text)
            return m
        if aid not in self.agents:
            raise ValueError(f"unknown agent '{aid}'")
        m = await self.post(f"dm:{aid}", sender, text)
        await self.chat_q[aid].put((m, sender))
        return m

    async def _chat_worker(self, aid):
        a = self.agents[aid]
        while True:
            m, sender = await self.chat_q[aid].get()
            batch = [(m, sender)]
            while not self.chat_q[aid].empty():           # answer several quick messages at once
                batch.append(self.chat_q[aid].get_nowait())
            who = lambda s: self.operator if s == "operator" else ("Claude (manager)" if s == self.mgr["id"] else s)
            lines = "\n".join(f"{who(s)}: {mm['text']}" for mm, s in batch)
            conv = self.store.get(f"chatconv:{aid}")
            prompt = ((self._persona(a) if not conv else "") +
                      "=== DIRECT MESSAGE ===\n" + lines +
                      f"\n\n(Context, not from them: {self._status_line(aid)}.)\n"
                      "Reply to them directly and conversationally, in your own voice. Keep it short unless they ask "
                      "for detail — it may be read aloud, so avoid big tables and heavy markdown. If they ask you "
                      "to do something, you can do it now with your tools and then tell them what you did.")
            self.rt[aid]["chatting"] = True
            await self.push_agent(aid)

            async def on_event(kind, text):
                if kind not in ("think", "start"):
                    await self.activity(aid, kind, text)

            run = agy.AgyRun(prompt, agent_name=a["name"], model=self.model, conv_id=conv,
                             timeout_min=self.cfg.get("chat_timeout_min", 15), on_event=on_event, **self._run_opts(aid))
            self.chat_runs[aid] = run
            try:
                r = await run.wait()
                if not r.ok and conv and not r.quota and not r.cancelled:   # stale thread: retry fresh once
                    self.store.delete(f"chatconv:{aid}")
                    run = agy.AgyRun(self._persona(a) + prompt, agent_name=a["name"], model=self.model,
                                     timeout_min=self.cfg.get("chat_timeout_min", 15), on_event=on_event,
                                     **self._run_opts(aid))
                    self.chat_runs[aid] = run
                    r = await run.wait()
            except Exception as e:
                r = agy.AgyResult(); r.error = str(e)
            finally:
                self.chat_runs.pop(aid, None)
                self.rt[aid]["chatting"] = False
            if r.conv_id and r.tokens < CHAT_ROTATE_TOKENS:
                self.store.set(f"chatconv:{aid}", r.conv_id)
            elif r.conv_id:
                self.store.delete(f"chatconv:{aid}")     # long thread: the next message starts a fresh one
            if r.ok:
                await self.post(f"dm:{aid}", aid, r.text.strip(), {"reply_to": batch[-1][0]["id"]})
            elif r.quota:
                self.quota.defer_chat(aid, batch)       # answered automatically when the quota is back
                await self.post(f"dm:{aid}", aid, "(I've hit the Gemini usage limit. I'll answer this automatically "
                                                  "as soon as it resets.)", {"kind": "failure"})
                self._spawn(self.quota.hit(aid))
            elif not r.cancelled:
                await self.post(f"dm:{aid}", aid, f"(Sorry, I couldn't reply: {r.error[:300]})", {"kind": "failure"})
            await self.push_agent(aid)

    # ------------------------------------------------------------------ meetings
    async def start_meeting(self, topic, attendees, by="operator"):
        if self.store.active_meeting():
            raise ValueError("a meeting is already running — end it first")
        valid = [a for a in dict.fromkeys(attendees) if a in self.agents or a == self.mgr["id"]]
        if not valid:
            raise ValueError("invite at least one agent")
        topic = (topic or "").strip() or "Team sync"
        m = self.store.start_meeting(topic, valid)
        names = ", ".join(self._name(a) for a in valid)
        await self.post(f"meeting:{m['id']}", "system", f"Meeting started: {topic}. Attending: {self.operator}, {names}.")
        await self.broadcast({"type": "meeting", "meeting": m})
        for a in valid:
            await self.push_agent(a)
        return m

    def _name(self, aid):
        if aid == self.mgr["id"]:
            return self.mgr["name"]
        if aid == "operator":
            return self.operator
        return self.agents.get(aid, {}).get("name", aid)

    async def invite(self, aids):
        m = self.store.active_meeting()
        if not m:
            raise ValueError("no meeting is running")
        new = [a for a in aids if (a in self.agents or a == self.mgr["id"]) and a not in m["attendees"]]
        if new:
            self.store.set_attendees(m["id"], m["attendees"] + new)
            await self.post(f"meeting:{m['id']}", "system", f"{', '.join(self._name(a) for a in new)} joined.")
            m = self.store.active_meeting()
            await self.broadcast({"type": "meeting", "meeting": m})
            for a in new:
                await self.push_agent(a)
        return m

    def _addressed(self, text, attendees):
        hit = []
        for aid in attendees:
            name = self._name(aid)
            if re.search(rf"\b{re.escape(name)}\b", text, re.I):
                hit.append(aid)
        if re.search(r"\b(everyone|everybody|all of you|team|guys|folks)\b", text, re.I):
            return list(attendees), True
        return (hit, False) if hit else (list(attendees), True)

    async def meeting_say(self, text, sender="operator"):
        m = self.store.active_meeting()
        if not m:
            raise ValueError("no meeting is running")
        msg = await self.post(f"meeting:{m['id']}", sender, text)
        if sender != "operator":
            return msg
        targets, general = self._addressed(text, m["attendees"])
        agents = [a for a in targets if a in self.agents]
        claude_in = self.mgr["id"] in m["attendees"]
        claude_named = self.mgr["id"] in targets and not general

        async def round_():
            if agents:
                await asyncio.gather(*(self._meeting_turn(m, a) for a in agents))
            if claude_in and (general or claude_named):
                await self._manager_meeting_turn(m)

        self._spawn(round_())
        return msg

    def _transcript(self, mid, after_id=0, limit=400):
        lines = []
        for mm in self.store.messages(f"meeting:{mid}", limit=limit, after_id=after_id):
            who = "(office)" if mm["sender"] == "system" else self._name(mm["sender"])
            lines.append((mm["id"], f"{who}: {mm['text']}"))
        return lines

    async def _meeting_turn(self, m, aid):
        a = self.agents[aid]
        async with self.meet_locks[aid]:
            if not self.store.active_meeting() or self.store.active_meeting()["id"] != m["id"]:
                return
            seen_key = f"meetseen:{m['id']}:{aid}"
            seen = self.store.get(seen_key, 0)
            lines = self._transcript(m["id"], after_id=seen)
            if not lines:
                return
            conv = self.store.get(f"meetconv:{m['id']}:{aid}")
            others = ", ".join(self._name(x) for x in m["attendees"] if x != aid)
            head = ""
            if not conv:
                head = (self._persona(a) +
                        f"=== MEETING: {m['topic']} ===\nIn the room: {self.operator} (owner), {others}, and you.\n"
                        f"Your own status: {self._status_line(aid)}.\n")
            prompt = (head + "Transcript since you last spoke:\n" + "\n".join(l for _, l in lines)[-60_000:] +
                      f"\n\nSpeak now as {a['name']}, out loud to the room: 1-4 short sentences of natural speech "
                      "(it is read aloud — no markdown, no lists, no headings). Build on what others said instead "
                      "of repeating it. If you have nothing useful to add, reply with exactly: PASS")
            self.rt[aid]["meeting_busy"] = True
            await self.push_agent(aid)
            run = agy.AgyRun(prompt, agent_name=a["name"], model=self.model, conv_id=conv,
                             timeout_min=self.cfg.get("meeting_timeout_min", 4), **self._run_opts(aid))
            self.meet_runs[aid] = run
            try:
                r = await run.wait()
            except Exception as e:
                r = agy.AgyResult(); r.error = str(e)
            finally:
                self.meet_runs.pop(aid, None)
                self.rt[aid]["meeting_busy"] = False
            self.store.set(seen_key, lines[-1][0])
            if r.conv_id:
                self.store.set(f"meetconv:{m['id']}:{aid}", r.conv_id)
            if not self.store.active_meeting():
                await self.push_agent(aid)
                return
            if r.ok:
                say = _clean_speech(r.text)
                if say and say.upper().rstrip(".") != "PASS":
                    await self.post(f"meeting:{m['id']}", aid, say)
            elif r.quota:
                await self.post(f"meeting:{m['id']}", "system", f"{a['name']} is out of Gemini quota for now.")
                self._spawn(self.quota.hit(aid))
            elif not r.cancelled:
                await self.post(f"meeting:{m['id']}", "system", f"{a['name']} couldn't answer ({r.error[:120]}).")
            await self.push_agent(aid)

    async def _manager_meeting_turn(self, m):
        mid = m["id"]
        seen_key = f"meetseen:{mid}:{self.mgr['id']}"
        lines = self._transcript(mid, after_id=self.store.get(seen_key, 0))
        if not lines:
            return
        self.store.set(seen_key, lines[-1][0])
        first = self.store.get(f"meetintro:{mid}") is None
        self.store.set(f"meetintro:{mid}", True)
        attendees = ", ".join(self._name(x) for x in m["attendees"] if x != self.mgr["id"])
        prompt = (f"[Meeting #{mid} \"{m['topic']}\" — you chair it. In the room: {self.operator} (owner), "
                  f"{attendees}.]\n" if first else f"[Meeting #{mid} continues.]\n")
        prompt += ("New lines of the transcript:\n" + "\n".join(l for _, l in lines)[-40_000:] +
                   "\n\nSpeak as chair, out loud: 1-3 short sentences (read aloud — plain speech, no markdown). "
                   "Steer to decisions. If the owner clearly asked for work to be done, you may assign it now with "
                   "`office assign`. If you have nothing to add, reply exactly: PASS")
        text = await self.manager.ask(prompt, kind="meeting")
        if text and self.store.active_meeting() and text.strip().upper().rstrip(".") != "PASS":
            await self.post(f"meeting:{mid}", self.mgr["id"], _clean_speech(text))

    async def end_meeting(self):
        m = self.store.active_meeting()
        if not m:
            raise ValueError("no meeting is running")
        for aid in list(self.meet_runs):
            self.meet_runs[aid].cancel()
        transcript = [l for _, l in self._transcript(m["id"], limit=5000)]
        stamp = dt.datetime.fromtimestamp(m["started_at"]).strftime("%Y-%m-%d-%H%M")
        rel = f"meetings/{stamp}-{_slug(m['topic'])}.md"
        path = COMPANY / rel
        people = ", ".join([self.operator] + [self._name(a) for a in m["attendees"]])
        path.write_text(f"# {m['topic']}\n\n{dt.datetime.fromtimestamp(m['started_at']):%A %d %B %Y, %H:%M}  \n"
                        f"Attendees: {people}\n\n## Transcript\n\n" + "\n\n".join(transcript) + "\n")
        m = self.store.end_meeting(m["id"], rel)
        await self.post(f"meeting:{m['id']}", "system", f"Meeting ended. Notes saved to {rel}.")
        await self.broadcast({"type": "meeting", "meeting": None, "ended": m})
        for a in m["attendees"]:
            await self.push_agent(a)
        self.store.delete_prefix(f"meetconv:{m['id']}:")
        if self.mgr["id"] in m["attendees"] and len(transcript) > 2:
            self._spawn(self._minutes(m, rel))
        return m

    async def _minutes(self, m, rel):
        prompt = (f"[Meeting #{m['id']} \"{m['topic']}\" has ended. The full transcript is in {rel}.] "
                  "Read it, then: 1) assign the action items that were clearly agreed, with `office assign` "
                  "(use --project when there is one, --after to chain dependent work); 2) reply with the minutes for "
                  f"{self.operator}: decisions, action items (owner + task number), open questions. Plain text, brief.")
        text = await self.manager.ask(prompt, kind="minutes")
        if text:
            path = COMPANY / rel
            path.write_text(path.read_text() + f"\n## Minutes (Claude)\n\n{text.strip()}\n")
            await self.post("manager", self.mgr["id"], f"Minutes for \"{m['topic']}\" ({rel}):\n\n{text.strip()}",
                            {"kind": "minutes"})

    # ------------------------------------------------------------------ admin
    async def reset_memory(self, aid):
        if aid == self.mgr["id"]:
            self.store.delete("mgr:session")
        else:
            self.store.delete_prefix(f"conv:{aid}:")
            self.store.delete(f"conv:{aid}")
            self.store.delete(f"chatconv:{aid}")
        await self.activity(aid, "info", "Memory reset — starting fresh conversations")

    async def stop_agent(self, aid):
        """Cancel everything an agent is doing right now (its running task and any reply)."""
        for tid, run in list(self.task_runs.items()):
            if self.store.task(tid)["agent"] == aid:
                run.cancel()
        if aid in self.chat_runs:
            self.chat_runs[aid].cancel()
        if aid in self.meet_runs:
            self.meet_runs[aid].cancel()
        if aid == self.mgr["id"]:
            self.manager.cancel()

    async def shutdown(self):
        for run in [*self.task_runs.values(), *self.chat_runs.values(), *self.meet_runs.values()]:
            run.cancel()
        self.manager.cancel()
