# Agent Office

A pixel-art office where an AI company works for you. **Claude** is the manager and your single
point of contact. The staff are **Gemini 3.8 Flash (High)** agents running through the Antigravity
CLI (`agy`) on your Google AI Pro subscription, so there is no API billing.

Open **http://127.0.0.1:8790** (Chrome is recommended because voice input uses Chrome's speech recognition).
On the phone, the **Adaptive Link** app has all of it under **Office**, at home and away
([ADAPTIVE_LINK.md](ADAPTIVE_LINK.md#the-agent-office)).

## Set it up

On this or any other Ubuntu machine, one command:

```sh
git clone git@github.com:Karthikai-28/adaptive-desktop.git ~/adaptive-desktop   # if it is not there yet
~/adaptive-desktop/scripts/install-agent-office.sh --open
```

Or, to Claude Code on the new machine, one prompt:

> Clone github.com/Karthikai-28/adaptive-desktop to ~/adaptive-desktop if it isn't there, run
> `scripts/install-agent-office.sh --open`, and do whatever its last lines say is still needed.

The installer is idempotent. It installs whatever is missing:

| What | How |
|---|---|
| bubblewrap (the agents' sandbox) | `apt`, asks for sudo only if missing |
| FastAPI, uvicorn, websockets, pydantic, edge-tts | `pip --target .local/office-pydeps` (git-ignored) |
| `agy` | `curl -fsSL https://antigravity.google/cli/install.sh \| bash` |
| `claude` | `curl -fsSL https://claude.ai/install.sh \| bash` |
| `office` command | link in `~/.local/bin` |
| `adaptive-agent-office.service` | systemd user unit, started now; `--autostart` also starts it at login |

Two things only you can do, which the installer checks and spells out: sign in to **agy** with
the Google account that has AI Pro (run `agy` once), and log in to **claude** (run `claude` once).
Then run `scripts/install-agent-office.sh --status`. `./install.sh` also runs it as the
`agent-office` part, and `./uninstall.sh` takes it off again (your office data stays).

## What you can do

| | |
|---|---|
| **Watch the team** | Each agent sits at a desk. The name-tag dot shows their state: green free, amber working, violet replying, blue in a meeting, red out of quota. The bubble shows what they are doing now (typing, running a command, browsing, generating an image). Hover over someone for details, or click them for their card. Free agents wander to the kitchen and lounge. |
| **Talk to anyone** | Click an agent, or walk up to them (WASD / arrows / click) and press **E**. They reply right away, even mid-task. Click the mic to speak; it sends when you pause. Replies are read aloud in each agent's own voice (🔊). |
| **Ask Claude** | Tell Claude what you want. It plans the work, assigns the right people (chaining dependent work), reviews what comes back on *autopilot*, sends work back when it falls short, and reports to you. |
| **Meetings and calls** | **Call meeting** → pick people → everyone walks to the meeting room. Type or talk; agents answer out loud. Say a name ("Arjun, …") to ask one person. **Hands-free** keeps listening and pauses while agents speak. With Claude in the room, it chairs the meeting, writes minutes at the end and assigns the agreed action items. **Call** on an agent's card starts a 1:1 call. |
| **Tasks** | Kanban board of every task with live activity, full reports, cancel and retry. |
| **Files** | Browse everything the team produces. HTML pages preview in a sandbox. |

## Study programs: an agent that masters codebases

**Max** (Codebase Scholar) studies the MagikEye codebases on his own, session after session (config.json
`"studies"`: phase 1 `mkert`; phase 2 `mkecc`, `mkeICC`, `pymkerc`, `mkestudio`, `mkesensorinit`; phase 3
the rest of the `~/mke` product repos). Each session he starts a fresh conversation, reads his knowledge base,
picks the weakest foundational topic, asks himself questions, answers them from the code with evidence
(file:line, commits), writes notes and lessons, raises deeper questions, and sends you a learning report.
Session 1 surveys every repo and builds the curriculum; every fifth session is a self-examination
(answer old questions from memory, check against the code, score honestly).

| | |
|---|---|
| Knowledge base | `company/study/mke/`: `CURRICULUM.md`, `QUESTIONS.md`, `notes/`, `lessons/`, `glossary.md`, `JOURNAL.md`, `reports/`, `progress.json` |
| Learning tab | on Max's card: mastery per topic, questions, self-test scores, **Teach me** / **Ask** per topic, his questions for you, pause / resume / study now |
| Pace | a session every `gap_min` (10) minutes, at most `max_sessions_per_day` (30); pauses with work and with Gemini quota |
| Terminal | `office study`, `office study pause`, `office study resume`, `office study now` |

**Local code only.** The repos are mounted read-only and only those he is assigned; Bitbucket and the
internal git server (192.168.1.10) are denied in his agy profile, git network commands fail inside the
sandbox, and SSH keys do not exist for him. He may use the web for research (concepts, libraries, hardware)
but is told never to put company code or names into a search. Repos not present on a machine are skipped.

## Where things live

| | |
|---|---|
| Code | `services/agent-office/` (`server.py`, `office/`, `static/`, `bin/office`) |
| Team roster | `services/agent-office/config.json` (names, roles, desks, voices, model, port) |
| Unit | `services/adaptive-agent-office.service` |
| Work the team produces | `~/.local/share/adaptive-desktop/agent-office/company/` (`projects/<name>/`, `meetings/`) |
| Office database, agy home, voice cache, logs | `~/.local/share/adaptive-desktop/agent-office/data/` |

Set `OFFICE_STATE` to put the state somewhere else. To hire someone, add an entry to
`config.json` with a free desk (`p4`-`p6`, `e4`-`e6`, `r2`-`r6`), a look, an edge-tts voice
(`edge-tts --list-voices`) and a brief, then `systemctl --user restart adaptive-agent-office`.

## Terminal: `office`

```
office status                                 who is doing what
office assign maya "Write a spec" --body "..." --project launch [--after 12]
office tasks / office show 12 --events / office cancel 12 / office retry 12
office ask claude "what's the status of the launch?"     (waits for the reply)
office meeting start "Weekly sync" --with maya,arjun,claude / office meeting end
office autopilot on|off · office pause · office resume · office open
```

## How it works

- **Agents.** Every turn is `agy -p <prompt> --model gemini-3.8-flash-high --sandbox
  --output-format stream-json`. The tool-call events are the live activity you see. Each agent
  keeps separate agy conversations for its tasks, its direct messages and each meeting, so it can
  chat while it works.
- **Manager.** One long-lived Claude Code session (`claude -p --resume`) with a brief describing
  the team. It works only through the `office` command.
- **Manager models** (`config.json` → `manager`). Every turn runs on **Sonnet 5.5** (`model`). A turn
  goes to **Opus 5** (`complex_model`, never higher) only when it is complex: you ask for it (start a
  message with `opus:` or say "think hard" / "deep dive"), or Sonnet replies `ESCALATE_TO_OPUS` for a
  multi-project plan, a design decision with real trade-offs or a problem it cannot settle. Opus then
  takes over that turn on the same session. Meetings and minutes always stay on Sonnet. At most
  `opus_max_per_hour` (6) Opus turns an hour; past that Sonnet handles it. `verify-agent-office.sh`
  rejects any other model.
- **Scheduler.** One task at a time per agent, up to three agents at once (Settings). `--after`
  chains work. Interrupted tasks resume after a restart, and transient failures retry once.

## Safety

- Every agent runs inside **bubblewrap**: the system is read-only and the home folder is replaced
  by an empty one holding only developer tools (read-only), agy's own home, the company workspace
  (the only writable place) and the repos it studies (read-only). Documents, personal folders,
  credentials and every other project simply don't exist for agents; `/tmp` is the office's own.
  agy's own sandbox additionally confines shell commands. The environment is rebuilt from scratch, so no API key leaks in (an
  inherited `GEMINI_API_KEY` would also switch agy to paid API billing).
- **Claude** can only run `office` and read files (`--permission-mode dontAsk`). Its brief says
  never to publish, push, buy or send anything off the machine unless you ask.
- The **server** listens on 127.0.0.1 only and rejects cross-site requests and foreign Host
  headers. Agent-written pages are served in a sandboxed origin, so they can't call the office API.
- **Quota.** Autopilot reviews are capped at 20 per hour and Claude may queue at most 40 tasks per
  hour. A typical task uses 50-100k tokens. The top bar shows the remaining 5-hour and weekly Gemini limits.

## Knowledge graphs and token economy (`office/graphs.py`)

Agents get graphify's MCP tools over a graph scoped to their own work, never the global brain
(which also holds personal notes and unrelated projects). `graphs/<agent>.json` is merged from the
hub graphs (`~/Obsidian/graphify-out/<repo>/graph.json`) of the repos the agent studies or lists
under `"graphs"` in config.json; `graphs/workspace.json` maps the company workspace and is rebuilt
when it changes. Both live in the office state folder and refresh from the hub every 20 minutes. Each
agy profile has one stdio MCP server, `graph`, serving the file in `$OFFICE_AGENT_GRAPH`.

Measured on mkert (2026-10-11, same question with and without the graph):

| Question | With graph | Grep only |
|---|---|---|
| Architecture: components, dependencies, frame flow | 70k tokens | 96k |
| A named function: where, what it does | 102k | 60k |

So agents use the graph for orientation and grep when they know the name. The larger savings come
from how they work. Earlier tasks cost 350-790k tokens each; the same kind of question answered with
the rules below took 60-100k:

- **Economical reading** (every agent's brief): grep -n with narrow patterns, files in line ranges, no
  full-file dumps or long command output, no re-reading. agy re-sends the whole context every step,
  so context size multiplies by the number of steps.
- **Scoped conversations:** tasks of the same project continue one thread; tasks without a project
  start fresh, and a thread that cost more than 400k tokens is not resumed (chats: 250k). Memory
  lives in the workspace files, task reports and `--after` chains, not in ever-growing threads.
- **Study sessions** start fresh and read `STATE.md` (600 words) instead of the whole knowledge base.

Graphs for repos with no hub graph are built code-only (no model calls) with
`GRAPHIFY_OUT=~/Obsidian/graphify-out/<repo> graphify update ~/mke/<repo>`. Never run that over a hub
graph that was built with semantic extraction: it replaces the document and rationale nodes.

## When the quota runs out (`office/quota.py`)

Work never needs restarting by hand. When an agent hits the Gemini limit, its task goes back to the
queue untouched and the office asks agy (`/usage`) when the exhausted window resets. All agent work
(tasks and study sessions) then pauses until that time, which the top bar shows ("Quota out ·
resumes 22:12"). A watchdog runs every 30 seconds:

- at the reset time, or earlier if `/usage` shows quota again (checked every 5 minutes), it resumes
  everything and tells you;
- direct messages that hit the limit are answered automatically once it is back;
- queued work with free slots is always started, so nothing can stay stuck after a missed wake-up.

When `/usage` shows no window at 0% (a short rate limit), the pause is 5 minutes. Claude has the same
behaviour for its own usage limit: the manager keeps the message or review and retries every 10 minutes
(up to six hours). Settings → "Resume now" ends a pause by hand.

## Checks

```sh
scripts/verify-agent-office.sh          # syntax, roster, a throwaway server's API and guards (no quota)
scripts/install-agent-office.sh --status
```

## Gotchas

- agy's `--sandbox` writes `/proc/<pid>/uid_map`. Inside a read-only bubblewrap root, `/proc`
  must be bound writable, or every shell command fails once with `fork/exec agy: read-only file system`.
- `unsandboxed(...)` is not a valid agy permission rule and is silently ignored; use `command(...)`.
- agy keeps its Google sign-in in the OS keyring, reached over the session bus, so the service
  needs `DBUS_SESSION_BUS_ADDRESS` (the unit sets it) and a logged-in desktop session.
- Voice input uses the Web Speech API: Chrome or Edge, on `http://127.0.0.1` (a secure context).
