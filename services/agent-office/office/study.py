"""Study programs: an agent learns a set of codebases from scratch, session after session.

A program (config.json "studies") names an agent, the repositories (read-only, local copies only)
and a pace. The agent keeps its long-term memory in a knowledge base it writes itself, in the
company workspace at study/<program id>/. Every session starts a fresh agy conversation, reads
that knowledge base, asks itself questions, answers them from the code with evidence, writes
notes and lessons, and reports to the owner. Every fifth session it examines itself.
"""
import asyncio
import datetime as dt
import json
import os
import time
from pathlib import Path

from .config import COMPANY

TICK_S = 30

KB_LAYOUT = """\
  STATE.md             START HERE. At most 600 words: where you are in the curriculum, the current focus, the
                       10 most important open questions, what you will do next. Rewrite it at the end of every session.
  progress.json        machine-readable state (schema below) - keep it valid JSON, update it every session
  CURRICULUM.md        the map: every repo -> its topics, why each matters, learning order, mastery 0-5
  QUESTIONS.md         numbered questions (Q1, Q2, ...). Open: the question and why you ask it.
                       Answered: the answer, evidence (repo/path:line, commit, function), confidence, source.
  notes/<topic-id>.md  deep, accurate notes per topic: purpose, architecture, data flow, key files and
                       functions, build/config, history (git log), gotchas, open doubts
  lessons/<topic-id>.md  teaching material: plain explanation from zero, a diagram (mermaid or ASCII),
                       a worked example from the real code, common misconceptions, 5 quiz questions with answers
  glossary.md          every term, acronym and name you meet, with a one-line meaning and where it lives
  JOURNAL.md           one entry per session: focus, what you learned, what changed your mind, new questions
  reports/session-NNN.md  your report to the owner for that session (also your final reply)"""

PROGRESS_SCHEMA = """{"session": 12, "updated": "2026-10-11", "phase": 1,
 "repos": {"mkert": {"surveyed": true, "mastery": 2}},
 "topics": [{"id": "mkert-build-system", "title": "How mkert is built", "repo": "mkert",
             "mastery": 3, "notes": "notes/mkert-build-system.md", "lesson": "lessons/mkert-build-system.md"}],
 "questions": {"open": 41, "answered": 63},
 "selftest": [{"session": 10, "score": "7/8"}],
 "questions_for_owner": ["Only things the code cannot answer: intent, product context, history"]}"""

MASTERY = ("0 never looked · 1 know it exists and where · 2 can say what it does · 3 can explain how it works "
           "with file references · 4 can explain why it is built this way, edge cases and history · "
           "5 could teach it, answer new questions about it, and spot bugs in it")


class Study:
    def __init__(self, office):
        self.o = office
        self.programs = {p["id"]: p for p in office.cfg.get("studies", [])}
        for p in self.programs.values():
            (COMPANY / "study" / p["id"]).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ lookups
    def state(self, pid):
        p = self.programs[pid]
        st = self.o.store.get(f"study:{pid}") or {"active": p.get("start_active", True), "sessions": 0,
                                                  "last_end": 0, "day": "", "today": 0}
        today = dt.date.today().isoformat()
        if st.get("day") != today:
            st["day"], st["today"] = today, 0
        return st

    def save(self, pid, st):
        self.o.store.set(f"study:{pid}", st)

    def for_agent(self, aid):
        return [p for p in self.programs.values() if p["agent"] == aid]

    def repo_paths(self, aid):
        return [str(Path(r["path"]).expanduser()) for p in self.for_agent(aid) for r in p["repos"]]

    def persona_line(self, aid):
        progs = self.for_agent(aid)
        if not progs:
            return ""
        return "".join(
            f"Your study program \"{p['title']}\": the codebases are read-only local copies at "
            f"{', '.join(str(Path(r['path']).expanduser()) for r in p['repos'])}. Your knowledge base - your long-term "
            f"memory of them - is study/{p['id']}/ in the workspace (CURRICULUM.md, QUESTIONS.md, notes/, lessons/, "
            f"glossary.md). Use it, and the code, whenever you answer or teach. When the owner answers one of your "
            f"questions, record the answer in QUESTIONS.md with source: owner.\n" for p in progs)

    @staticmethod
    def program_of(task):
        proj = task.get("project") or ""
        return proj[len("study-"):] if task.get("created_by") == "study" and proj.startswith("study-") else None

    # ------------------------------------------------------------------ pacing
    def start(self):
        if os.environ.get("OFFICE_NO_STUDY"):      # test servers must never start real sessions
            return
        self.o._spawn(self._loop())

    async def _loop(self):
        await asyncio.sleep(5)
        while True:
            for pid in list(self.programs):
                try:
                    await self._maybe_enqueue(pid)
                except Exception as e:  # a pacing hiccup must not stop the loop
                    print(f"study {pid}: {e}", flush=True)
            await asyncio.sleep(TICK_S)

    def _busy(self, pid):
        return any(self.program_of(t) == pid for t in self.o.store.tasks(status="queued,running", limit=500))

    def next_at(self, pid):
        p, st = self.programs[pid], self.state(pid)
        return st["last_end"] + p.get("gap_min", 10) * 60

    async def _maybe_enqueue(self, pid, force=False):
        p, st = self.programs[pid], self.state(pid)
        if not st["active"] or self._busy(pid):
            return None
        s = self.o.settings()
        if not force:
            if s["paused"] or self.o.provider_paused(self.o.provider_for(p["agent"])) or \
                    not self.o.study_allowed(p["agent"]):
                return None
            if time.time() < self.next_at(pid) or st["today"] >= p.get("max_sessions_per_day", 30):
                return None
        n = st["sessions"] + 1
        title = f"Study session {n}: " + ("survey every codebase and build the curriculum" if n == 1 else
                                         "self-examination and review" if n % 5 == 0 else "learn, question, answer")
        t = await self.o.add_task(p["agent"], title, "", f"study-{pid}", created_by="study")
        await self.push()
        return t

    # ------------------------------------------------------------------ the session prompt
    def prompt(self, task):
        pid = self.program_of(task)
        p, st = self.programs[pid], self.state(pid)
        n = st["sessions"] + 1
        kb = f"study/{pid}"
        phases = {}
        for r in p["repos"]:
            path = Path(r["path"]).expanduser()
            if path.is_dir():
                phases.setdefault(r.get("phase", 1), []).append(f"{path}" + (f" ({r['about']})" if r.get("about") else ""))
        repo_lines = "\n".join(f"  Phase {ph}: " + "; ".join(v) for ph, v in sorted(phases.items()))
        missing = [r["path"] for r in p["repos"] if not Path(r["path"]).expanduser().is_dir()]
        if n == 1:
            method = """THIS IS SESSION 1 - THE SURVEY. Do not go deep yet. For every repository: what it is for, language(s) and
build system, top-level layout, entry points, main components, how it depends on or talks to the other repos,
size, how active it is (git log), and anything surprising. Use your graph tools (god_nodes, graph_stats, query_graph)
to find each repo's core quickly. Then write STATE.md, the first CURRICULUM.md (topics per repo,
ordered from foundations upward, with why each matters), a seed glossary.md, progress.json, and the first 25-40
sharp questions in QUESTIONS.md - the questions an expert would want answered to truly understand this system."""
        elif n % 5 == 0:
            method = """THIS SESSION IS A SELF-EXAMINATION. 1) Pick 8 questions you answered in earlier sessions, spread over
different topics. 2) Answer each from memory first, written down, before looking. 3) Check each against the code.
4) Score yourself honestly (record it in progress.json "selftest"), correct any wrong notes, and lower mastery where
you were wrong. 5) Turn the weakest area into new questions. 6) Write or refresh lessons for topics at mastery 3+.
Then spend the rest of the session learning, as in a normal session."""
        else:
            method = """1) Read STATE.md and progress.json. Open other knowledge-base files only where you need them (grep
   QUESTIONS.md for the questions you will work on; read just the notes for your focus topic) - not whole files.
2) Choose a focus: the most foundational topic with the lowest mastery (finish phase 1 before going deep into
   phase 2, and phase 2 before phase 3), plus 4-8 open questions about it.
3) Investigate in the code: get oriented with your graph tools (query_graph, god_nodes, get_neighbors,
   shortest_path) when an area is new; grep when you know the name; then read the exact files and line ranges, follow the call paths end to end, read the build and config, and
   look at git log / git blame to learn why things are the way they are. Primary evidence, never guesses.
4) Answer the questions in QUESTIONS.md with evidence (repo/path:line, function, commit) and a confidence.
   Each answer should raise better questions: add 4-8 new, specific ones (what / how / why / what if / where).
5) Write or deepen notes/<topic>.md. When a topic reaches mastery 3 or more, write or refresh its lesson.
6) Update glossary.md, progress.json (honest mastery), CURRICULUM.md and JOURNAL.md, and rewrite STATE.md."""
        return f"""{self.o._persona(self.o.agents[p['agent']])}
=== STUDY SESSION {n} - {p['title']} ===
Your goal: become the master of these codebases - able to explain any part from first principles, answer hard
questions with evidence, find where anything lives, and teach any topic to anyone, beginner or expert.
You start each session with no memory: everything you learn must be written into your knowledge base, and you
begin by reading it. Learn like a great student: ask yourself sharp questions, find the answers in the code,
then ask the next, deeper question.

The codebases (read-only local copies; learning order by phase):
{repo_lines}
{"(Not on this machine, skip: " + ", ".join(missing) + ")" if missing else ""}
CODE FROM LOCAL COPIES ONLY - strict: learn the code only from these files on this machine. Never go near
Bitbucket or any code host or git server (bitbucket.org, 192.168.1.10), and never fetch, pull, clone or contact
a remote (git fetch/pull/clone/ls-remote/submodule update, curl, wget, ssh). Never modify the repositories;
they are read-only. Run only read-only commands there (ls, cat, grep, find, git log/show/blame/diff, wc); to
experiment, copy files into /tmp or your knowledge base.
THE WEB IS FOR RESEARCH: use web search to understand concepts, algorithms, standards, libraries, hardware and
datasheets the code relies on, and cite the sources in your notes. Never put the company's code, internal names,
file contents or anything confidential into a search or a website.

Your knowledge base (yours alone to write; it is your long-term memory): {kb}/
{KB_LAYOUT}
progress.json example: {PROGRESS_SCHEMA}
Mastery scale: {MASTERY}

Method:
{method}

Save as you go: if the session ends early, what you learned must already be on disk. Keep notes accurate -
when unsure, say so and add a question rather than guessing.

Finish by writing {kb}/reports/session-{n:03}.md and replying with the same report, in plain language for
{self.o.operator}:
  - What I studied this session (focus and why)
  - What I learned: 5-10 crisp insights, each with its file reference
  - Questions I answered, and the most interesting ones still open
  - Mastery now: topics that changed (old -> new) and the overall picture
  - What I will study next
  - Questions for {self.o.operator}: only what the code cannot tell you (intent, product context, history) - or none"""

    # ------------------------------------------------------------------ after a session
    async def finished(self, task, ok):
        pid = self.program_of(task)
        if not pid:
            return
        st = self.state(pid)
        st["last_end"] = time.time()
        if ok:
            st["sessions"] += 1
            st["today"] += 1
        self.save(pid, st)
        await self.push()

    # ------------------------------------------------------------------ control and status
    async def control(self, pid, action):
        if pid not in self.programs:
            raise ValueError(f"no study program '{pid}'")
        st = self.state(pid)
        if action == "pause":
            st["active"] = False
        elif action == "resume":
            st["active"] = True
        elif action != "now":
            raise ValueError("action must be pause, resume or now")
        self.save(pid, st)
        if action == "now":
            st["active"] = True
            self.save(pid, st)
            if self._busy(pid):
                raise ValueError("a session is already queued or running")
            await self._maybe_enqueue(pid, force=True)
        else:
            await self._maybe_enqueue(pid)
        await self.push()
        return self.status(pid)

    def status(self, pid):
        p, st = self.programs[pid], self.state(pid)
        base = COMPANY / "study" / pid
        progress, err = None, ""
        try:
            progress = json.loads((base / "progress.json").read_text())
        except FileNotFoundError:
            pass
        except (json.JSONDecodeError, OSError) as e:
            err = f"progress.json is not valid JSON yet ({e})"
        reports = sorted((base / "reports").glob("session-*.md")) if (base / "reports").is_dir() else []
        lessons = sorted(x.stem for x in (base / "lessons").glob("*.md")) if (base / "lessons").is_dir() else []
        current = next((t for t in self.o.store.tasks(status="queued,running", limit=500) if self.program_of(t) == pid), None)
        return {
            "id": pid, "title": p["title"], "agent": p["agent"], "active": st["active"],
            "sessions": st["sessions"], "today": st["today"], "max_per_day": p.get("max_sessions_per_day", 30),
            "gap_min": p.get("gap_min", 10), "next_at": self.next_at(pid) if st["active"] else None,
            "current": current and {"id": current["id"], "status": current["status"], "title": current["title"]},
            "repos": [{**r, "present": Path(r["path"]).expanduser().is_dir()} for r in p["repos"]],
            "kb": f"study/{pid}", "progress": progress, "progress_error": err,
            "latest_report": f"study/{pid}/reports/{reports[-1].name}" if reports else None,
            "lessons": lessons,
        }

    def all_status(self):
        return [self.status(pid) for pid in self.programs]

    async def push(self):
        await self.o.broadcast({"type": "study", "studies": self.all_status()})
