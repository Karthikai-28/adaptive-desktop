# Agent Office

A pixel-art office where an AI company works for you. **Claude** is the manager and your single
point of contact. The staff are **Gemini 3.8 Flash (High)** agents running through the Antigravity
CLI (`agy`) on your Google AI Pro subscription, so there is no API billing.

Open **http://127.0.0.1:8790** (Chrome is recommended because voice input uses Chrome's speech recognition).

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
- **Scheduler.** One task at a time per agent, up to three agents at once (Settings). `--after`
  chains work. Interrupted tasks resume after a restart, and transient failures retry once.

## Safety

- Every agent runs inside **bubblewrap**: the whole filesystem is read-only except the company
  workspace. SSH, GPG, cloud and Claude/Codex credentials, `~/.zshenv`, browser profiles and the
  office database are masked and simply don't exist for agents. agy's own sandbox additionally
  confines shell commands. The environment is rebuilt from scratch, so no API key leaks in (an
  inherited `GEMINI_API_KEY` would also switch agy to paid API billing).
- **Claude** can only run `office` and read files (`--permission-mode dontAsk`). Its brief says
  never to publish, push, buy or send anything off the machine unless you ask.
- The **server** listens on 127.0.0.1 only and rejects cross-site requests and foreign Host
  headers. Agent-written pages are served in a sandboxed origin, so they can't call the office API.
- **Quota.** Autopilot reviews are capped at 20 per hour and Claude may queue at most 40 tasks per
  hour. When Gemini returns a quota error, work pauses for 15 minutes and resumes by itself. The
  top bar shows the remaining 5-hour and weekly Gemini limits. A typical task uses 50-100k tokens.

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
