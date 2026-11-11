# Mario

Mario is the assistant layer of Adaptive Desktop: a live **Home** on the desktop, a **panel** on
Super+Space, and **Mario Hub**, the loopback service both read from. The brain is hybrid: LOOM
answers on this laptop with its memory and router; multi-step work in a repo goes to Claude Code,
and only after you say yes. Design: <https://claude.ai/artifact/3JCCG6J8ZT3XTXFGEAFGPy>.

It is built the "data layer first" way: everything Mario says or shows comes from one hub that
reads what is already on the machine. Actions are added on top, one confirmed step at a time.

## Parts

| Part | Source | Job |
| --- | --- | --- |
| Mario Hub | `services/mario-hub/hub.py` (aiohttp, 127.0.0.1:8791) | Runs the collectors, pushes changed cards over `/ws`, answers `/api/ask`, holds Claude Code plans until you decide |
| Collectors | `services/mario-hub/collectors.py` | Builds (git, 14-day commit activity), Thinking Space boards (sections, Inbox items, last backup), Saved Reels (tracker progress, what to watch / try / cook next, newest saves, version history), Agent Office and terminal agent sessions (tmux), AI usage (`quotaSnapshot.py`, only `usage_providers`: Claude and Gemini), system (CPU, RAM, GTX via `nvidia-smi`, disk, network, battery, busiest processes, Ollama), LOOM (`/api/health`), weather (Open-Meteo), recent files, downloads, listening ports (`ss`), phone (Adaptive Link control socket) |
| Decisions | `services/mario-hub/brain.py` (pure) | Instant answers from state, local vs Claude Code, the hand-off's limits, the Next step list |
| Settings | `services/mario-hub/config.py`, `~/.config/adaptive-desktop/mario.json` | Repos, Thinking Space checkout, LOOM/Ollama/Office URLs, backup time |
| Home and panel | `apps/mario-home/static/` (`index.html`, `home.css`, `home.js`) | One page: `/` is Home, `/panel` the panel. DOM only, no framework, no `innerHTML` |
| Host | `apps/mario-home/host.py` (GTK 3 + WebKitGTK) | Home as a desktop-type window over the work area (Adaptive session only); `--panel` toggles the panel window |
| Unit and login entry | `services/adaptive-mario-hub.service`, `apps/mario-home/adaptive-mario-home.desktop` | Templates filled with the checkout's path |

The shell's top bar, rail and island stay the shell's; Home fills only the work area.

## Live tiles

Home is 28 tiles packed on a 14 × 7 grid of near-square cells (the check proves every cell is used
once and that no tile appears twice): 18 live tiles and 10 one-cell launchers. Each tile shows
something no other tile does. A tile with more than one face turns by itself on its own beat: small
tiles flip, wide ones peek-slide. It pauses while the pointer is on it, keeps its face when new
data arrives, and stops animating under reduced motion. Every tile has a header in its own tint:
an icon and its name, then its count and the dots that say how many faces it has. The top bar
keeps the clock; Home does not repeat it.

| Tile | Cells | Faces |
| --- | --- | --- |
| Next step | 4 × 2 | Up to four suggestions, each with its action |
| Builds | 4 × 2 | Repos with branch, last commit, changed and unpushed counts · 14-day commit heatmap |
| Weather | 2 × 2 | Now, today's range and the next six hours |
| Tonight | 2 × 2 | One film per face that is on a subscription, with two more from the list |
| Thinking Space | 4 × 2 | Four boards with their sections and Inbox counts · Inbox items · hub summary and last GitHub backup; opens the hub |
| Saved Reels | 4 × 2 | Progress per tracker · newest saves · version history; opens the Google Sheet |
| Try next | 2 × 2 | Newest named AI tools, Claude ideas and websites still to try; opens the reel |
| AI usage | 2 × 2 | Claude and Gemini, fullest window first, and when each window resets |
| This laptop | 4 × 2 | CPU, RAM, GTX with a live CPU line · busiest processes · battery, disk, network, uptime |
| Recent files | 4 × 2 | Newest files you opened (GTK's recently-used list), with the app; opens them |
| Agents | 2 × 2 | Claude / agy / codex sessions on `adaptive-agent`'s tmux server, by folder · Agent Office; opens the office |
| Downloads | 2 × 2 | Newest downloads with size; opens the file or the folder |
| Phone | 2 × 1 | Adaptive Link state; opens the phone's screen |
| Focus | 4 × 1 | 25 / 50 / 90-minute block with a live bar; a desktop notification when it ends (`/api/focus`) |
| Jot | 4 × 1 | Quick notes kept in `~/.local/share/adaptive-desktop/mario/notes.md` (`/api/note`) |
| Cook next | 2 × 1 | Recipes still to cook; opens the reel |
| LOOM | 2 × 1 | LOOM's backend and the model Ollama holds in memory |
| Open to network | 2 × 1 | Services listening beyond this laptop (`ss`), with the process |

Launchers (1 × 1): Terminal, Files, Code, Settings, Claude, Gemini, Screenshot, Cast to TV,
Calculator, Lock. A place that already has a tile has no launcher: the tile opens it. They run only
the commands in `hub.py`'s `LAUNCH` table or open their own links; a program that is not installed
shows dimmed.

## Install

```sh
./install.sh --only mario          # or scripts/install-mario.sh; --status changes nothing
./scripts/install-keybindings.sh   # Super+Space opens Mario (layout switching keeps its own key)
apps/mario-home/host.py &          # Home now, instead of at the next Adaptive login
```

For the boards and reel cards, clone the Thinking Space backup where `thinking_space` points
(default `~/thinking-space`): `gh repo clone Karthikai-28/thinking-space ~/thinking-space`. The hub
pulls it (fast-forward only) every 15 minutes; the nightly backup at 22:40 copies the boards and the
Google Sheet trackers into it, so the Home is at most a day behind the Sheet. Reading the Sheet
directly is phase 2.

For local answers with memory, run LOOM's backend (`local-ai/app/backend`, port 8765). Without it
the hub asks Ollama directly (`fallback_model`, LOOM's `default_chat`) and says so under the answer.

## How a request goes

1. **Instant**: "brief me", "what changed today", "pick a movie for tonight" are answered from the
   cards with no model.
2. **Local**: everything else that is a question or chat goes to LOOM (`POST /api/chat`), keeping
   one LOOM session per hub run.
3. **Claude Code**: a request to change code (a dev verb plus a repo name or code word, not phrased
   as a question) becomes a plan: which repo, what will happen, what will not. Mario's mark turns
   amber. **Run** starts `claude -p … --permission-mode acceptEdits` in that repo and streams its
   output; **Open in terminal instead** opens an `adaptive-agent claude` session there; **Not now**
   drops it. The prompt always ends with: work only in this folder; do not push, publish, deploy,
   send or delete; list those for me instead.

## Safety

- The hub listens on 127.0.0.1 only and refuses any other `Host` (DNS rebinding) and any write
  whose `Origin` is not itself.
- `/api/action` is a short whitelist: a terminal, Claude session or file manager in one of Mario's
  configured folders; links to claude.ai, Google Docs/Sheets, GitHub, Instagram and loopback;
  starting Agent Office. Nothing else runs.
- Collectors read local files, loopback ports and the Link's Unix socket; they open no credentials.
  The weather tile is the only one that reaches the internet (Open-Meteo, no key, the coordinates
  in `weather`); `"cards_off": ["weather"]` turns it off.
- Anything that leaves the laptop needs your yes, every time.

## Presence

Mario's mark is three strands (your work, the world, you). `/api/presence` and the `presence`
WebSocket message carry the state: `ready` (strands nearly flat, still), `listening` (strands
swing), `thinking` (a shuttle runs along them), `doing` (one line fills), `needs_you` (one amber
strand). Reduced motion stops every animation.

## Next

| Phase | What | Notes |
| --- | --- | --- |
| 2 | Read the Google Sheet directly; Calendar card | Through the Link's Google project (`--link-cloud`), read-only scopes |
| 3 | Voice: push-to-talk and a "Mario" wake word | `services/mario-voice/`: faster-whisper on the GTX 1050 (int8, `small`), openWakeWord with a custom "Mario" model; both local. Super+Space toggles listening (GNOME gives no key-up), silence ends it; the listener sets presence through `/api/presence` and posts the text to `/api/ask`. Answers spoken with Piper. The mic light in the top bar shows whenever the wake word is listening |
| 4 | "Mario, note that…" writes a sticky into the right board's Inbox | Through the Thinking Space boards' database, confirmed |
| 4 | Island and phone | The shell island shows presence and the current plan; the Link app gets the ask box |
| 5 | Council mode, nightly review, routines | Three local models on big questions; a nightly look back that proposes one fix; "remember this as…" |

Ideas behind several of these came from saved reels (LLM Council, a Claude brain kit, TurboQuant,
Pixel Agents, notes as a network, hand gestures, the desk as buttons, Mimik, GitNexus); the design
canvas lists all 19 with what each contributes.

## Check

```sh
python3 scripts/verify-mario.py   # collectors, decisions, hub over HTTP/WebSocket, page; part of verify-all --quick
python3 services/mario-hub/hub.py --once   # one full state as JSON, from this machine
```

Not covered by the check: the desktop hint and panel toggle under GNOME 42, LOOM, Ollama and
Claude Code themselves. Record those with `scripts/record-live-verification.py` once tried live.
