# Agent Office

A pixel-art office where an AI company works for you. **Claude plans** each work request and
dispatches the staff, as the manager and your single point of contact. The staff are **Gemini 3.8 Flash (High)** agents running through the Antigravity
CLI (`agy`) on your Google AI Pro subscription, so there is no API billing. When the Gemini quota runs
out they carry on with a **local model** through Ollama ([Model providers](#model-providers-gemini-and-local-models-officelocalpy)).

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
| FastAPI, uvicorn, websockets, pydantic, edge-tts, PyYAML | `pip --target .local/office-pydeps` (git-ignored) |
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
| **Watch the team** | Each agent sits at a desk. The name-tag dot shows their state: green free, amber working, violet replying, blue in a meeting, red out of quota, grey paused. The bubble shows what they are doing now (typing, running a command, browsing, generating an image). Hover over someone for details, or click them for their card. Free agents wander to the kitchen and lounge. |
| **Talk to anyone** | Click an agent, or walk up to them (WASD / arrows / click) and press **E**. They reply right away, even mid-task. Click the mic to speak; it sends when you pause. Replies are read aloud in each agent's own voice (🔊). |
| **Ask Claude** | Tell Claude what you want. Claude plans it, then assigns useful work across the whole available team (chaining dependencies), reviews what comes back on *autopilot*, sends work back when it falls short, and reports to you. |
| **Meetings and calls** | **Call meeting** → pick people → everyone walks to the meeting room. Type or talk; agents answer out loud. Say a name ("Arjun, …") to ask one person. **Hands-free** keeps listening and pauses while agents speak. With Claude in the room, it chairs the meeting, writes minutes at the end and assigns the agreed action items. **Call** on an agent's card starts a 1:1 call. |
| **Pause and resume** | **Pause** in the top bar stops every agent at once: running tasks, replies, meeting turns, study sessions and Claude. Nothing starts again until you press **Resume**; then each task continues its own conversation where it stopped. The pause survives a restart or reboot. Same as `office pause` / `office resume`. |
| **Tasks** | Kanban board of every task with live activity, full reports, cancel and retry. |
| **Missions** | Outcome-based work with an objective, measurable acceptance criteria (C1, C2, ...), a writable-repository boundary, linked tasks, cancellation, and one evidence report. A mission **succeeds** only when the report has a `C<n>: PASS - <evidence>` line for every criterion; a `FAIL` line makes it **failed**, and a report without a verdict for each criterion leaves it **unverified**. Open **Missions** in the top bar or use `office mission`. |
| **Work capsules** | Save the exact repository revision, dirty files, dependency-lock fingerprints, runtime, command, launch arguments, parameters, datasets and results for a mission. A capsule is readable JSON under `data/mission-control/capsules/`, where agents can't reach it; create one from a mission or with `office capsule`. |
| **Evidence search** | Search a mission's objective, criteria, task reports, capsules, project artifacts and explicitly scoped repository. Results cite the mission, task, capsule or exact file and line; search stays local and skips secret-shaped files. |
| **Reusable workflows** | Save a mission as a parameterized team workflow. A workflow keeps its acceptance criteria, assigned roles, risk class and repository boundary; a ROS investigation keeps its problem and recordings and captures a fresh ROS snapshot on every run. Hardware and external workflows need the operator's approval on every run, and only the operator can change a saved workflow. |
| **Audit and retention** | Export a mission, task events, verdicts, policy (risk, workflow, who approved it) and capsules as one JSON audit bundle with a SHA-256 checksum. `office retention DAYS` previews old export removal; add `--apply` (operator only) to perform exactly the listed deletion. A capsule that belongs to a mission is never deleted. |
| **ROS investigations** | Capture the live ROS setup, baseline and candidate recording metadata, missing/type-changed topics and message-count regressions, plus an exact simulation or replay command in the evidence capsule. |
| **Mission Control on the phone** | Adaptive Link's native Office has a Missions tab for launching scoped work, reading criteria and reports, searching evidence and cancelling work. It uses the paired phone's mutually authenticated Office gateway and requires that device's Commands switch. |
| **Files** | Browse everything the team produces. HTML pages preview in a sandbox. |
| **Action Inbox and alerts** | Failed or blocked work, approvals waiting and quota stops land in one inbox that stays until the problem is really fixed, and reach the phone through Adaptive Link at once; finished work arrives quietly grouped ([Notifications and the Action Inbox](#notifications-and-the-action-inbox-officeeventspy-officejournalpy)). |
| **Tokens** | Live token usage: who spends what, on which work, and how. The **Tokens** button shows the team (per person by kind of work, over time, by step, by project, by how tasks ended, the most expensive tasks); click a person for their own breakdown (context per call, tasks, every run). Each person's card also has a **Tokens** tab. Windows: last hour to all time. It updates by itself as agents work. |

## Study programs

No autonomous study program is configured. Max can analyze a codebase only when the operator assigns
a scoped task. The assigned repository is mounted according to the normal Office sandbox rules, and
private code must remain local.

## Where things live

| | |
|---|---|
| Code | `services/agent-office/` (`server.py`, `office/`, `static/`, `bin/office`) |
| Team roster | `services/agent-office/config.json` (names, roles, desks, voices, model, port) |
| Unit | `services/adaptive-agent-office.service` |
| Work the team produces | `~/.local/share/adaptive-desktop/agent-office/company/` (`projects/<name>/`, `meetings/`) |
| Office database, agy home, voice cache, logs | `~/.local/share/adaptive-desktop/agent-office/data/` |
| Workflows, work capsules, audit exports | `data/mission-control/` (no agent sandbox mounts `data/`) |
| Operator key | `data/operator.key` (mode 0600; `office operator-key` prints it for the owner) |

Set `OFFICE_STATE` to put the state somewhere else. To hire someone, add an entry to
`config.json` with a free desk (`p4`-`p6`, `e4`-`e6`, `r2`-`r6`), a look, an edge-tts voice
(`edge-tts --list-voices`) and a brief, then `systemctl --user restart adaptive-agent-office`.

## Terminal: `office`

```
office status                                 who is doing what
office assign maya "Write a spec" --body "..." --project launch [--after 12]
office tasks / office show 12 --events / office cancel 12 / office retry 12
office mission create "Reproduce the failure" --objective "Find and verify the cause" \
  --criterion "The failure is reproduced" --criterion "The fix passes its regression check" --repo my-robot
office mission list / office mission show 3 / office mission cancel 3 / office mission export 3
office mission ros "localization jumps after map reload" --baseline-bag ~/bags/good \
  --bag ~/bags/failure --simulation-command "ros2 launch robot replay.launch.py" --repo my-robot
office capsule create --mission 3 --command "pytest -q" --parameter seed=42 --result reports/run.md
office capsule list / office capsule show 20261021-120000-ab12cd34
office evidence "navigation timeout" --mission 3
office workflow create inspect-component "Inspect {{component}}" \
  --objective "Explain {{component}} with cited evidence" --criterion "The report cites its sources" --risk read
office workflow run inspect-component --input component=planner
office workflow create replay-stall "Replay stall" --from-mission 7 --risk read
office workflow run move-arm --approve      hardware/external: approves this one run (owner only)
office retention 90                         preview old exports and capsules without a mission
office retention 90 --kind exports --apply delete exactly the previewed old exports (owner only)
office operator-key                         the key the office app asks for before it approves a run
office ask claude "what's the status of the launch?"     (waits for the reply)
office meeting start "Weekly sync" --with maya,arjun,claude / office meeting end
office provider [gemini|local] [--fallback local|none]   what agents run on (meetings: config "meeting_provider")
office tokens [--since 24h|7d|all] [--provider local]    token usage, split by provider
office autopilot on|off · office pause · office resume · office open
```

## How it works

- **Agents.** Every turn is `agy -p <prompt> --model gemini-3.8-flash-high --sandbox
  --output-format stream-json`. The tool-call events are the live activity you see. Each agent
  keeps separate agy conversations for its tasks, its direct messages and each meeting, so it can
  chat while it works.
- **Planning.** Claude decides whether owner work requests, autopilot follow-ups and meeting action
  items need staff at all, plans what does and dispatches it. After any turn that assigned work, the
  manager checks that every agent without an active study has running or queued work and asks Claude
  for an immediate correction pass if somebody was missed.
- **Manager.** One long-lived Claude Code session (`claude -p --resume`) with a brief describing
  the team. It works only through the `office` command. Existing running/queued work and active study
  programs count as occupied; the scheduler's parallel-work setting still controls how many run at once.
- **Manager models** (`config.json` → `manager`). Every turn runs on **Sonnet 5.5** (`model`). A turn
  goes to **Opus 5** (`complex_model`, never higher) only when it is complex: you ask for it (start a
  message with `opus:` or say "think hard" / "deep dive"), or Sonnet replies `ESCALATE_TO_OPUS` for a
  multi-project plan, a design decision with real trade-offs or a problem it cannot settle. Opus then
  takes over that turn on the same session. Meetings and minutes always stay on Sonnet. At most
  `opus_max_per_hour` (6) Opus turns an hour; past that Sonnet handles it. `verify-agent-office.sh`
  rejects any other model.
- **Manager session size.** Every call re-reads the whole session, so once one call carries more than
  `rotate_context_tokens` (120k) the next turn starts a fresh session. It opens with a hand-over: the
  last 12 messages between you and Claude, and an instruction to check `office status` first. Every
  session id is kept in `mgr:sessions` for the token ledger.
- **Scheduler.** One task at a time per agent, up to three agents at once (Settings). `--after`
  chains work. Interrupted tasks resume after a restart, and transient failures retry once.

## Safety

- **Private by construction.** The desktop server binds to `127.0.0.1`, rejects foreign Host and
  Origin headers, and requires its same-origin write header. Remote phone access goes only through
  Adaptive Link's paired, mutually authenticated gateway and the phone's Commands permission; the
  Office port is never exposed on the LAN. `GET /api/health` reports the service's local-only mode.
- **The operator key.** Approving a hardware/external workflow run, deleting records with retention,
  changing a saved workflow, and adding or re-running work in a hardware/external mission need the
  random key in `data/operator.key`. Your own `office` command attaches it. The app asks for it once
  (paste the output of `office operator-key`) and keeps it in that browser's local storage. No agent
  sandbox mounts `data/`. The manager's Claude is denied reading the key, and the server recognises
  the manager's `office` calls by their process tree, never by the identity they claim, so the manager
  can neither use the key nor pass as the owner. Its missions and workflow runs count against its
  40-tasks-an-hour limit and are recorded as `manager`. The phone has no key, so it can't approve.
- **Workflow authority.** Workflows, capsules and exports live in `data/mission-control/`, which
  agents can't reach, so they can't rewrite a workflow's risk class or edit evidence. Read workflows
  can't name a writable repository. A workflow's repository is resolved when it's saved and is its
  boundary: a run may repeat it but never name another, and a workflow saved without one never gets
  one. Role allowlists are enforced, and the mission records its risk, workflow, allowed agents and
  who approved it. Tasks added to a mission stay inside its repository and roles, and a finished
  mission takes no new tasks. The named repository remains the mission's enforced task/evidence boundary;
  general home-folder access does not authorize work outside that mission.
- **Retention is inspectable.** Retention covers audit exports, capsules saved without a mission, and
  leftover temporary files. It previews paths and byte counts by default, accepts 1–3650 days, and
  never deletes a mission's capsules, mission/task history or project source.

- Every worker agent runs inside **bubblewrap** or its provider's equivalent sandbox: the operating system
  is read-only and the operator's home folder is readable and writable. Credential stores, shell history,
  cloud/SSH/Git credentials, secret-looking project files (`.env`, private keys, keystores and service-account
  files), and private Office records are denied in both the outer sandbox and each provider's file-tool policy.
  `/tmp` is the Office's own. The environment is rebuilt from scratch, so no API key or SSH agent leaks in.
- **Repository assignment is task scope, not the filesystem permission boundary.** `office assign ... --repo
  <path|name>` (or the Repo field in the app) tells the agent, mission checks and evidence system where the
  requested change belongs. Agents can technically write other non-secret home files, but their brief requires
  them to change only what the task needs. The task brief says not to commit or branch unless the task asks.
  Agent commits are authored `Karthi Labs <office@karthi-labs.local>` (never the owner's identities).
- **No remotes, ever.** Agents' `git` is a wrapper (`$OFFICE_STATE/bin/git`, first on PATH) that
  refuses push/pull/fetch/clone/ls-remote/remote/submodule; every git they run also has
  `protocol.allow=never`, so `/usr/bin/git push` fails too; agy and Claude have matching deny rules;
  and no credential, token or SSH agent socket is in their sandbox to push with.
- **Claude manager** can run `office` and read/write non-secret home files (`--permission-mode dontAsk`);
  credential/private paths are explicitly denied. Its brief says
  never to publish, push, buy or send anything off the machine unless you ask.
- The **server** listens on 127.0.0.1 only and rejects cross-site requests and foreign Host
  headers. Agent-written pages are served in a sandboxed origin, so they can't call the office API.
  Agent *commands* share the host network, so they can reach the API over loopback. Everything
  that needs the owner checks the operator key, which they can't read (`scripts/verify-agent-office.sh`
  probes this from inside the sandbox).
- **Quota.** Autopilot reviews are capped at 20 per hour and Claude may queue at most 40 tasks per
  hour. A typical task uses 50-100k tokens. The top bar shows the remaining 5-hour and weekly limits
  for Gemini and Claude; a limit that the subscription disables is shown as off, not as 0%.

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
`GRAPHIFY_OUT=~/Obsidian/graphify-out/<repo> graphify update ~/projects/<repo>`. Never run that over a hub
graph that was built with semantic extraction: it replaces the document and rationale nodes.

## Pause and resume (`Office.pause` / `Office.resume` in `office/core.py`)

The owner's pause is separate from the quota pause and only the owner ends it. The office's own `office`
calls are refused: the manager can't pause or resume. While paused:

- a running task is interrupted and goes back to the queue with its attempt not counted. Its conversation,
  steps and tokens are kept in kv `resume:<task id>`. On resume it continues that conversation with a short
  "carry on where you stopped" prompt. On another provider, or if the conversation can't be resumed, it
  starts over with a note to continue from the partial work in the workspace;
- direct messages are held in kv `held_chats` and answered on resume. Manager jobs (your messages,
  autopilot reviews) are held in kv `mgr_held`. Meeting turns are skipped, and on resume every attendee
  answers what was said in the meantime;
- the scheduler, study programs and the quota watchdog start nothing.

Everything lives in the database, so a restart while paused comes back paused with the same held work.
A server shutdown that isn't a pause keeps running tasks the same way, so they continue their
conversation after the restart instead of being cancelled. A manager meeting turn or minutes request
that someone is waiting for is the one thing held only in memory.

## When the quota runs out (`office/quota.py`)

Work never needs restarting by hand. When an agent hits the Gemini limit, its task goes back to the
queue untouched and the office works out when the quota comes back: the exhausted window's reset in
agy's `/usage` when one shows 0%, otherwise the time in Gemini's error ("Resets in 2h44m48s"). All
agent work (tasks and study sessions) then pauses until that time, which the top bar shows ("Quota out
· resumes 22:12"). A watchdog runs every 30 seconds:

- at the reset time it resumes everything and tells you. With a known reset time it does not probe
  earlier: every retry re-sends the agent's whole conversation (on 12 Oct a 5-minute retry loop
  re-sent Omar's 120k-token thread 53 times in three hours);
- direct messages that hit the limit are answered automatically once it is back;
- queued work with free slots is always started, so nothing can stay stuck after a missed wake-up.

Only when neither gives a time (a short rate limit) is the pause 5 minutes, with an early check. Claude has the same
behaviour for its own usage limit: the manager keeps the message or review and retries every 10 minutes
(up to six hours). Settings → "Resume now" ends a pause by hand.

## Model providers: Gemini and local models (`office/local.py`)

`config.json` lists the **providers** agents can run on. Each has an `engine` (`agy` for Gemini through
the Antigravity CLI, `ollama` for a local model) and a `model`; Ollama ones also take `url`, `num_ctx`
(context window), `think`, `max_steps` (tool calls per turn) and `max_parallel` (tasks at once).
`provider` is what agents run on and `fallback` is what they switch to while it is out of quota. Both
can be changed in Settings or with `office provider`; an agent can be pinned to one with its own
`"provider"`. Adding another local model is one more entry, for example
`"coder": {"engine": "ollama", "label": "Coder", "model": "qwen3:4b"}`, and its usage is counted on
its own straight away.

- **Switching.** While Gemini is out of quota (see below) and `fallback` is set, queued tasks, study
  sessions, direct messages and meetings run on the fallback; a chat that hits the limit is answered by the
  fallback at once. At the reset, new turns go back to Gemini. Each provider keeps its own conversations
  (the key gets `@<provider>`), so a thread never jumps between models.
  A local provider takes work only while Ollama is up and its model is pulled. Study programs do not
  move to the fallback (a session every 10 minutes would keep the CPU busy all day) unless
  `"study_on_fallback": true` is set in `config.json`.
- **The local loop.** agy has its own agent loop; Ollama is only a model, so `LocalRun` is the loop: it
  sends the conversation with a small tool set (`run_command`, `read_file`, `write_file`, `edit_file`,
  `list_dir`, `search_files`, `fetch_url`), runs what the model asks for, and repeats until it answers.
  Commands run in the same bubblewrap sandbox as agy; agents that learn code only from local copies get
  `--unshare-net` and no `fetch_url`. File tools resolve paths and refuse anything outside the workspace
  (write) or the workspace, assigned repositories and graphs (read). Meetings run without tools to stay
  short. Old tool output is trimmed when a conversation nears `num_ctx`. There is no image tool and no
  graph MCP on the local path.
- **Status.** The top bar shows each local provider (green: Ollama up and the model pulled; red: not
  running, or `ollama pull <model>` needed). `office status` shows it too, and which provider each
  agent is on.
- **What to expect.** A 3-4B model on this laptop's CPU is far weaker and slower than Gemini: fine for
  chat, meetings, summaries and small well-specified tasks, poor at long multi-step engineering. The
  manager's brief says so.

### Local models

Measured on this laptop (i7-1360P, 16 GB RAM, CPU only) on 12 Oct 2026, on battery in power-saver
mode, with an 8k context window. Plugged in on Balanced or Performance, expect it to be 2-4 times faster. "Tools" is three
single-step tool-call checks (list a folder, write a file, run a command).

| Model | RAM loaded | Prompt tok/s | Output tok/s | Tools | Verdict |
|---|---|---|---|---|---|
| `granite4:tiny-h` (7B MoE, ~1B active) | 4.4 GB | 37 | 16 | 3/3 | **default**: fastest and reliable with tools |
| `granite4:3b` | 2.8 GB | 12-15 | 6-8 | 3/3 | when RAM is tight |
| `qwen3:4b` | 4.1 GB | 10 | 5 | 0/3 | not for agents (no tool calls with thinking off) |
| `qwen3.5:4b` | 3.3 GB download | - | - | - | needs Ollama newer than 0.23.4 |

Too big for this machine: `gpt-oss:20b` (14 GB), `qwen3:30b-a3b` (19 GB). Change the model with the local
provider's `model` in `config.json` after `ollama pull <model>`, and restart the office.

### Backup chain: Gemini -> Claude Haiku -> local

`"fallback": "haiku"`, and haiku names `"fallback": "local"`.
Each turn runs on the first provider in the chain that can take work. When one reports its usage limit it
is paused until the reset named in the message (an hour if none) and turns move down the chain.
`office provider` shows the chain; a fallback set with `office provider --fallback` overrides config.json.

#### Claude Haiku (`office/claude_agent.py`)

Haiku runs through Claude Code (`claude -p`) on the operator's own Claude login (the same one the manager
uses). The operator's Claude settings, hooks, plugins, MCP servers and memory are left out. Agents get only
Bash, Read, Edit, Write and the web tools, in dontAsk mode: Read/Edit/Write cover the non-secret home folder;
Bash runs in Claude Code's bubblewrap sandbox with the same credential/private-path exclusions
(`failIfUnavailable`, no unsandboxed escape). Haiku shares the operator's
Claude limits with the manager, and Claude Code's own prompt is large (a study session was ~8.6M tokens,
mostly cached).

## Token ledger (`office/ledger.py`)

Nothing is estimated. agy records every model call in the conversation's SQLite file
(`agy-home*/.gemini/antigravity-cli/conversations/<id>.db`, one `steps` row per call with its usage in
protobuf: fresh input, cached input, output, thinking). Claude's calls are in its session transcripts
(`~/.claude/projects/*/<session>.jsonl`). Local-model calls are appended by the office to
`data/usage/<provider>.jsonl` with Ollama's own counts (`prompt_eval_count` as fresh input, `eval_count`
as output; Ollama does not report cached input separately). Every 10 seconds the ledger re-reads only the files that
changed (a full read of ~70 conversations takes about a second, in a worker thread) and attributes each
call: the **person** from the persona the conversation opens with (or the study program), the **kind**
and **task** from the prompt that started that turn (`=== TASK #38`, `STUDY SESSION 4`, a direct
message, a meeting), and the **step** the call chose (run a command, read a file, edit, answer).
When anything changed it sends a `tokens` message on the socket and open views redraw.

Every call carries its **provider** (`gemini`, `local`, any other configured one, or `claude` for the
manager), and providers are never added into one another's numbers.

- `GET /api/tokens?since=<unix>[&provider=<id>]`: the team: one summary per provider, then totals, per
  person (by kind and by provider, last 10 minutes), timeline, steps, projects, task outcomes, the most
  expensive tasks. With `provider` every number but the per-provider summaries is that provider's only.
- `GET /api/tokens/agent/<id>?since=<unix>[&provider=<id>]`: one person: the same plus context per
  call, tasks and every run.

The Tokens window has the same switch (All · Gemini · Local · Claude) next to the time range.

Three numbers per call: **fresh input** (new to the model), **re-read context** (served from cache:
the conversation sent again with every step, about 95% of all tokens), **output** (thinking
included). The task board's own count is fresh input + output of a task's last attempt only.

## Notifications and the Action Inbox (`office/events.py`, `office/journal.py`)

The office keeps a record of everything that happens to work, decides from it what needs you, and tells
you, on the phone too, without you watching the page.

**Events.** Every task and mission status change becomes an event in `event_log`, written in the same
SQLite transaction as the change itself (`Store` calls the journal from `update_task`/`update_mission`).
Each event has a UUID, a sequence number `seq` (only rises, without gaps), a UTC timestamp, the agent,
task and mission, a type and severity, the text, evidence references (`task:12`, `mission:3`) and a
dedup key: the same fact recorded twice is one event. The log is append-only: SQLite triggers refuse
any UPDATE or DELETE. Types: `task.created|started|resumed|retry|interrupted|completed|failed|blocked|
cancelled|requeued`, `mission.created|started|completed|failed|unverified|cancelled|reopened`,
`approval.requested|granted|declined`, `quota.exceeded|restored`, `limit.reached|cleared`,
`office.error`, and `inbox.acknowledged|resolved|dismissed|reopened` for what people do. The rules are
pure functions in `office/events.py`. Text is redacted of anything credential-shaped and of the
operator key before it is stored.

**The Action Inbox.** One item per problem (`inbox`), the only mutable state: `NEEDS_ATTENTION` →
`IN_PROGRESS` → `RESOLVED`, and a resolved item can be reopened.

| Event | Inbox | Notification |
|---|---|---|
| task failed / blocked (a dependency failed) | opens `task:<id>` | high, at once |
| approval requested | opens an approval item holding the request | critical, at once |
| quota used up (Gemini, Haiku, Claude manager) / an hourly limit hit | opens `quota:<provider>` / `limit:<name>` | high, at once |
| office error running a task | opens `error:task-run` | high, at once |
| mission failed on its verdicts / unverified | opens `mission:<id>` | high / normal |
| task run again, or resumed | the task's item → in progress | none (the existing item is updated) |
| task finished / cancelled | the task's item resolved (`recovered` / `cancelled`) | finished work: normal, grouped |
| mission succeeded | its item resolved | normal, grouped |
| quota back, limit reset | resolved by the 30-second sweep | none |

A mission that fails *because* its task failed is recorded, but quietly: the task already has the one
item and the one alert. The same problem raised again while it is open adds nothing; a new failure of
the same task (after a retry) updates the same item and sends a new alert.

- **ack** marks an item in progress. **resolve** is refused while the problem is still there (the task
  is still failed): run the work again or cancel it and the item closes by itself. **dismiss** closes it
  anyway and needs the operator key while the problem is live. The manager can't resolve, dismiss or
  decline.
- **Approvals.** A hardware/external workflow run, or adding or re-running work in a hardware/external
  mission, asked without the operator key, is still refused exactly as before, and the request is kept
  in an approval item. **Approve** (`POST /api/inbox/<id>/approve`) needs the operator key and replays the
  stored request through the same checks as a fresh one, marked approved by the operator; it runs once.
  Acknowledging, resolving or anything from the phone never approves: the phone has no key and can only
  acknowledge or **decline**.

**Notifications** (`notifications`) are numbered in order and kept. Each channel confirms how far it has
got (`deliveries`, per paired phone as `link:<device>`), so what was not delivered is known and sent
again. Normal ones (finished work) carry a group so the phone bundles them quietly.

**On the phone.** Adaptive Link long-polls the office's notifications and hands each new one to the
phone's background listener as kind `office` (`services/adaptive-link/office_gateway.py`, the commands
switch). The phone treats that as a nudge only: it always fetches from the office's list after the
last one it showed, in order, then confirms them, so after being away or out of reach it gets
everything it missed, once. Problems and approvals arrive on their own channel with an
**Acknowledge** button; tapping opens the Office page at the inbox item, task or mission. The Office
page has an **Inbox** button with the open count. The last 100 alerts are kept on the phone for when
the computer can't be reached. Switch: Settings → the computer's alerts → *Agent Office*.

**Other channels** (`office/channels.py`). Channels the office pushes to are outbound only (they tell,
never ask: nothing they receive can approve or start work), carry one concise line, and keep their own
position, so a failing channel is retried in order with a backoff. **WhatsApp** is listed in
`config.json` → `notifications` with `"enabled": false` and has no sender yet; nothing needs it.

**API** (GETs are open on 127.0.0.1; POSTs need the office's usual `X-Office` header):

| | |
|---|---|
| `GET /api/journal?after=<seq>&limit=&type=task.*&agent=&task_id=&mission_id=&since=&until=` | events after a seq, oldest first, with `head` |
| `GET /api/inbox?state=NEEDS_ATTENTION,IN_PROGRESS&kind=&agent=&task_id=&mission_id=&priority=&limit=&offset=` | items (open first, critical first), `total`, `counts` |
| `GET /api/inbox/<id>` | one item with its history and whether the problem is still `live` |
| `POST /api/inbox/<id>/ack\|resolve\|dismiss\|reopen\|decline` `{"note": ""}` | a person's action |
| `POST /api/inbox/<id>/approve` | carry out an approval request (operator key) |
| `GET /api/notifications?after=<id>&limit=&wait=<s>&channel=link` | notifications after an id; `wait` long-polls up to 30 s |
| `POST /api/notifications/delivered` `{"channel": "link", "through": <id>}` | a channel confirms delivery |
| `POST /api/notifications/read` `{"ids": [..]}` or `{"through": <id>}` | read status |
| `GET /api/notifications/deliveries` | each channel's position, pending count and last error |

The live socket also sends `journal`, `inbox` (with counts) and `notification` messages, and the
`state` snapshot carries `journal_head`, `inbox` counts and the notification head, so a page that
reconnects asks `/api/journal?after=<the last seq it saw>`.

**Database.** These tables are migration 1 in `office/store.py` (`MIGRATIONS`, recorded in
`PRAGMA user_version`), applied once at start inside one transaction. The moment it ran is
`journal_since` in kv: on start the journal re-records only work that finished after it (whatever a
crash lost between a status write and its event), so an upgraded office does not turn its history
into alerts. To roll back, stop the office, put back the earlier code, and optionally drop the tables
(older code ignores them):

```sh
systemctl --user stop adaptive-agent-office
sqlite3 ~/.local/share/adaptive-desktop/agent-office/data/office.db \
  "DROP TABLE IF EXISTS deliveries; DROP TABLE IF EXISTS notifications; DROP TABLE IF EXISTS inbox;
   DROP TABLE IF EXISTS event_log; DELETE FROM kv WHERE key='journal_since'; PRAGMA user_version=0;"
```

Every journal action is also one JSON line on the service's output (`journalctl --user -u
adaptive-agent-office | grep '"log": "journal"'`).

## Checks

```sh
scripts/verify-agent-office.sh          # syntax, roster, a throwaway server's API and guards (no quota),
                                        # then the page in headless Chrome (scripts/verify-agent-office-ui.py)
scripts/install-agent-office.sh --status
```

## Gotchas

- agy's `--sandbox` writes `/proc/<pid>/uid_map`. Inside a read-only bubblewrap root, `/proc`
  must be bound writable, or every shell command fails once with `fork/exec agy: read-only file system`.
- `unsandboxed(...)` is not a valid agy permission rule and is silently ignored; use `command(...)`.
- agy keeps its Google sign-in in the OS keyring, reached over the session bus, so the service
  needs `DBUS_SESSION_BUS_ADDRESS` (the unit sets it) and a logged-in desktop session.
- Voice input uses the Web Speech API: Chrome or Edge, on `http://127.0.0.1` (a secure context).
