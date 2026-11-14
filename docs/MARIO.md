# Mario

Mario is the assistant layer of Adaptive Desktop: a live **Home** you summon with Super+H, a **panel** on
Super+J, and **Mario Hub**, the loopback service both read from. Claude answers first (the Claude
subscription, through Claude Code's headless mode); when Claude is at its usage limit, Gemini answers
(the AI Pro subscription, through the Antigravity CLI); LOOM and Ollama on this laptop answer only
when neither cloud does. Multi-step work in a repo goes to Claude Code (Gemini while Claude is out),
and only after you say yes. Design: <https://claude.ai/artifact/3JCCG6J8ZT3XTXFGEAFGPy>.

It is built the "data layer first" way: everything Mario says or shows comes from one hub that
reads what is already on the machine. Actions are added on top, one confirmed step at a time.

## Parts

| Part | Source | Job |
| --- | --- | --- |
| Mario Hub | `services/mario-hub/hub.py` (aiohttp, 127.0.0.1:8791) | Runs the collectors, pushes changed cards over `/ws`, answers `/api/ask`, holds Claude Code plans until you decide |
| Collectors | `services/mario-hub/collectors.py` | Mail (IMAP, read-only), calendar (private iCal), tasks (Quick Note inboxes), builds (git), agents (terminal tmux sessions, Agent Office), Thinking Space boards, recent files, notes, weather (Open-Meteo), AI usage (`quotaSnapshot.py`, Claude and Gemini), phone (Adaptive Link socket), health (updates, disk, battery, failed services), LOOM and system for Mario's own status; Saved Reels, downloads, processes and ports stay available to Mario's answers |
| Decisions | `services/mario-hub/brain.py` (pure) | Instant answers from state, answer vs hand-off, the hand-off's limits, the Next step list |
| Who answers | `services/mario-hub/engines.py` | Claude, then Gemini, then the laptop: the command lines, reading each CLI's reply, recognising a usage limit, the live context sent with a question |
| Settings | `services/mario-hub/config.py`, `~/.config/adaptive-desktop/mario.json` | Repos, Thinking Space checkout, mail accounts, `brain` order and models, LOOM/Ollama/Office URLs, backup time |
| Home and panel | `apps/mario-home/static/` (`index.html`, `home.css`, `home.js`) | One page: `/` is Home, `/panel` the panel. DOM only, no framework, no `innerHTML` |
| Host | `apps/mario-home/host.py` (GTK 3 + WebKitGTK), `scripts/adaptive-home.sh` | Home as a layer over the work area: loaded hidden at login (`--background`), shown and hidden by Super+H (a D-Bus message, about 20 ms), with one view per tab; `--panel` toggles the panel window |
| Unit and login entry | `services/adaptive-mario-hub.service`, `apps/mario-home/adaptive-mario-home.desktop` | Templates filled with the checkout's path |

The shell's top bar, rail and island stay the shell's; Home fills only the work area.

## Your day (Home)

Home is laid out for work, in the order a day is used: what came in, what is scheduled, what to
do, then the work itself, then capture. A side column holds the always-there tools. Cards get the
room their content needs; nothing is there to fill a gap, and nothing appears twice. Everything
updates live over the hub's WebSocket, and the tiles marked *live* also turn between faces on their
own clock, like live tiles: each at its own pace and offset so they never all move at once, paused
while the pointer is over the tile or the screen is hidden; previous/next buttons and a slide counter show which face is up. Arrow keys on a focused tile and horizontal swipes also move between faces. A manual turn pauses that tile until Play; keyboard focus and reduced-motion preferences stop automatic turns too.
New data redraws the current face in place without turning it. The top bar keeps the clock.

The top row is Mail, Tasks and Next step. Home is one screen and never scrolls as a page: a list that is longer than its tile (mail, tasks, today's events, the boards, notes) scrolls inside that tile. Below them (Today remains under the weather) is a four-column block: Projects and Thinking Space side by side
(one column each; the boards are compact rows), Recent files and This week under them, Quick note down the
third column and News down the last, both through two rows.

| Card | Shows | Opens / does |
| --- | --- | --- |
| Mail | Unread count over every account, then one tab per account (the main one first and shown by default, each with its unread count) and up to five newest unread (sender, subject, time), read-only over IMAP. A refused login says why; for a Google account password (Gmail wants an app password) a button opens the app-password page | A message opens that conversation in Gmail, in its own account (Gmail's thread id); the header and "Open" open that account's inbox |
| Today | Small tile under the weather: date, and today's events still to come on a timeline, the current one highlighted (private iCal address) | Google Calendar |
| Tasks | Open tasks from every Quick Note inbox (Super+Alt+N, the palette's `todo`), newest first, coloured by project; scroll through all tasks, tick to finish, or add a task. Draft text and selection survive live refreshes | `/api/task`, `/api/task/done` |
| Projects (live) | One repo per face, newest first (last commit, branch, changes / to push / to pull / up to date), then an Agents face: terminal agent sessions and Agent Office | Code, Terminal |
| Recent files (live) | The newest files take turns on top (type, size, when), the next two listed below | The file |
| Quick note | Capture a thought; the three latest notes (`~/.local/share/adaptive-desktop/mario/notes.md`). Does not turn, so typing is never interrupted | `/api/note` |
| This week (live) | Commits per day for the last seven days across the watched repos; then this week against last, busiest day, today | |
| News (live) | One headline at a time with the article's picture across the top of the tile, cropped to fit (outlets that block it get their name on a colour instead), rolling to the next every 30 s (a bar along the bottom fills to the next; paused under the pointer), source and age, two "Up next" with thumbnails; RSS from `news` in `mario.json` (Google News Tech and India, Hacker News by default), refreshed every 15 min. `"cards_off": ["news"]` stops the fetching | The article itself, picture or headline (only headlines on Home open) |
| Thinking Space | The four boards with their sections, or what is waiting in their Inbox | The board, the hub |
| Weather (live) | Now, feels-like, rain chance; the next six hours; today's high, low and rain (Open-Meteo) | |
| Next step | One actionable suggestion at a time: uncommitted work, stopped services, system issues | Open its action or add it as a task |
| AI assistants | Claude and Gemini: usage of the fullest window and when each resets | claude.ai, Gemini |
| Phone | Adaptive Link state | The phone's screen |

There is no "all systems up to date" line. System trouble (pending or security updates, disk over
90 %, low battery, a failed user service) shows only when it happens, as a Mario suggestion in Tasks
with an Update (Software Updater) or Check (System Monitor) button.

### Home is a layer, the wallpaper is the desktop

Home is not the desktop any more. It is one window over the work area (the top bar stays), above
every other window while it is up and gone when it is not, so whatever you were doing is untouched
underneath.

| You do | What happens |
| --- | --- |
| Super+H, or the Home button in the dock | Home fades in over your work with the keyboard on it; the cards settle in. Again: it fades out and you are back where you were |
| Escape | Closes what is open, innermost first: an answer, a voice session, then Home |
| Open something from Home (a mail, a file, a terminal) | Home steps aside as soon as the new window takes the keyboard |
| Double Ctrl | Everything is minimised and Home is sent away: the bare wallpaper. Again brings the windows back |
| Ctrl+1 … Ctrl+9 | Today, then each tab |

GNOME's own Super+H (minimise the focused window) moves to Super+Alt+H, because a binding of
Mutter's wins over a custom one on the same key.

**Tabs.** Today is the hub's page. Every other tab is a site from `"tabs"` in `mario.json`, kept
open inside Home in a view and a profile of its own (`~/.local/share/adaptive-desktop/mario/web`):
sign in there once and it stays signed in, apart from your browser. The defaults are Mail (Gmail)
and Calendar (Google Calendar); another site is one more line:

```json
"tabs": [{"id": "mail", "name": "Mail", "url": "https://mail.google.com/mail/u/0/"},
         {"id": "calendar", "name": "Calendar", "url": "https://calendar.google.com/calendar/u/0/r"},
         {"id": "sheets", "name": "Sheets", "url": "https://docs.google.com/spreadsheets/u/0/"}]
```

A link that leaves a tab's own site (a link inside a mail) opens in the browser.
`scripts/adaptive-home.sh show mail` opens Home on a tab directly.

**Ground.** Home sits on glass: the wallpaper blurred once into
`~/.cache/adaptive-desktop/glass.png` under a graphite tint, the same picture the shell puts behind
Files. The hub serves it at `/glass.png` and makes it itself when it is missing or older than the
wallpaper, so Home does not wait for the shell.

The ask bar leads with **Talk to Mario**, with **Type instead** as a fallback. It shows who answers next (Claude / Gemini · Claude at its limit / On this laptop; the
reason is in its tooltip and under the panel's title), and
"Your day" sums it up: events, open tasks, unread mail. Brief me now includes the calendar, mail and
tasks.

### Connecting mail and calendar

```sh
scripts/install-mario.sh --mail       # a Gmail address + its Google app password -> GNOME keyring;
                                      # run again for each account; it asks whether this is the main one
scripts/install-mario.sh --mail --main  # ... and make it the main one without asking
scripts/install-mario.sh --calendar   # the calendar's "Secret address in iCal format" -> keyring
```

Accounts are kept as `"mail": {"accounts": [...], "main": "..."}` in `mario.json` (the older
`"mail": {"user": ...}` still reads as one account); the main one is the tab Home shows first.
Each step tries the login or the feed once before it finishes and says what is wrong if Gmail or
Google refuses (the password itself is never printed). The secrets stay in the keyring (`secret-tool`, attributes `service mario-mail`
`account <address>`, one per account, and `service mario-calendar`); the hub reads them when it collects and never writes them to a file,
a log or its state. Mail is read-only: headers of unread messages, fetched with `BODY.PEEK` so
nothing is marked read. Recurring events need `icalendar` and `recurring_ical_events`, which
the installer puts in `.local/mario-pydeps`; without them only one-off events show.

## Install

```sh
./install.sh --only mario          # or scripts/install-mario.sh; --status changes nothing
./scripts/install-keybindings.sh   # Super+H is Home, Super+J opens Mario; Super+Space stays the keyboard-layout switch
scripts/adaptive-home.sh           # show Home now (Super+H after install-keybindings.sh)
```

For the boards and reel cards, clone the Thinking Space backup where `thinking_space` points
(default `~/thinking-space`): `gh repo clone Karthikai-28/thinking-space ~/thinking-space`. The hub
pulls it (fast-forward only) every 15 minutes; the nightly backup at 22:40 copies the boards and the
Google Sheet trackers into it, so the Home is at most a day behind the Sheet. Reading the Sheet
directly is phase 2.

Answers need `claude` (Claude Code, logged in to the Claude subscription) and, for when Claude is at its
limit, `agy` (the Antigravity CLI, logged in to the Google account with AI Pro); `--status` reports
both. For answers with neither cloud, run LOOM's backend (`local-ai/app/backend`, port 8765); without
it the hub asks Ollama directly (`fallback_model`, LOOM's `default_chat`) and says so under the answer.

## Voice commands

Press **Talk to Mario** on Home or in the **Super+J** panel, then speak. The panel fades and slides in
each time Super+J shows it, with the keyboard already on Talk to Mario. While Mario listens, three
strands in its colours move with your voice (the hub reports the microphone's level ten times a second),
so you can see that it hears you; while it recognises and answers they lie low and a line runs along them. About two seconds of
silence sends the request automatically; **Finish speaking** sends sooner. **Cancel**, Escape,
hiding the page, or losing its connection stops capture/recognition. No wake word is needed.

- “Add a task review the build” writes a task immediately.
- “Take a note: try the new layout” saves a Quick note immediately.
- “Open terminal”, “open files”, “open mail”, or “open calendar” use the existing launch whitelist.
- “Brief me” and other questions use the existing Mario answer routing.
- Code changes still show their plan and require **Run**.

`services/mario-hub/voice.py` captures the default PulseAudio microphone in memory using `parec`:
30-second maximum, eight seconds to begin speaking, and a five-second page heartbeat. Recognition
runs in a killable subprocess (`voice_transcribe.py`), using faster-whisper base.en on CPU with int8
and speech filtering. Audio never goes to a cloud service or a recording file. Only the resulting
request enters Mario's normal answer path. Replies are spoken locally through Speech Dispatcher
(`spd-say`) when installed, and remain visible in the page.

```sh
scripts/install-mario-voice.sh    # dedicated .local/mario-voice environment and public English model
```

The desktop host is WebKitGTK, so this does not depend on Chrome-only browser speech recognition.
If Mario hears nothing, check the default input and mute state in Ubuntu Sound settings. Recognition
currently expects English. The microphone is activated only by pressing the button, never at login.

## After a restart

The hub is a user service that starts at boot (lingering is on), before anyone logs in, so:

- it leaves the keyring alone until a desktop session is up (asking earlier would start a keyring
  outside the session); Mail and Today say "Waiting for the keyring" and look again every 15 s, so
  they fill in within seconds of logging in. A network that is not up yet (boot, resume) is retried
  the same way;
- everything Home opens goes to the display of the current login, read from the user manager at
  that moment (`systemctl --user show-environment`), not the one the hub started with;
- Home starts at every Adaptive login (autostart entry), reconnects to the hub on its own, and
  reloads if its web view dies;
- stopping the hub takes well under a second (it used to hang until systemd killed it).

## How a request goes

1. **Instant**: "brief me", "what changed today", "pick a movie for tonight" are answered from the
   cards with no model.
2. **Answer**: everything else that is a question or chat goes, with a few lines of live context
   (time, weather, today's events, unread mail per account, open tasks, repo state), to the first of
   `brain` (default `["claude", "gemini", "local"]`) that can answer:
   - **Claude**: `claude -p` (`claude_model`, `claude-sonnet-5-5` by default; the ask bar names it) with Mario's own system prompt and
     no tools but web search and web fetch, so it can look things up but never run or change
     anything; one conversation per hub run (`--resume`). It runs in `~/.local/share/adaptive-desktop/mario/brain`.
   - **Gemini**: when Claude is at its usage limit (the AI usage tile at 100 % in a window that has
     not reset, or Claude itself says so), or does not answer: `agy -p` in plan mode, sandboxed,
     `gemini_model` (Gemini 3.8 Flash low by default; answers in a few seconds). A limit Claude reports
     is remembered until the time it names (else 15 minutes), so later questions go straight to Gemini.
   - **The laptop**: LOOM (`POST /api/chat`, one session per hub run), else Ollama, only when neither
     cloud answers.
   The answer says who answered and, under it, why the ones before were skipped. No API key reaches
   either CLI, so both stay on the subscriptions.
3. **Hand-off**: a request to change code (a dev verb plus a repo name or code word, not phrased
   as a question) becomes a plan: which repo, what will happen, what will not. Mario's mark turns
   amber. **Run** starts `claude -p … --permission-mode acceptEdits` in that repo (while Claude is at
   its limit: `agy -p … --mode accept-edits --sandbox` with `gemini_work_model`, and the plan says so)
   and streams its output; **Open in terminal instead** opens an `adaptive-agent claude` (or `agy`)
   session there; **Not now** drops it. The prompt always ends with: work only in this folder; do not
   push, publish, deploy, send or delete; list those for me instead.

## Safety

- The hub listens on 127.0.0.1 only and refuses any other `Host` (DNS rebinding) and any write
  whose `Origin` is not itself.
- `/api/action` is a short whitelist: a terminal, Claude session or file manager in one of Mario's
  configured folders; links to claude.ai, Google Docs/Sheets, GitHub, Instagram and loopback;
  starting Agent Office. Nothing else runs.
- Collectors read local files, loopback ports and the Link's Unix socket; Mail and Today read their
  secrets from the keyring. What reaches the internet: Gmail (IMAP), the calendar feed, the weather
  (Open-Meteo, no key, the coordinates in `weather`) and News: the feeds, then for each headline once
  its page (Google News' redirect page, then the article) and its picture. Pictures are kept in
  `~/.local/share/adaptive-desktop/mario/news/` (cleared after three days) and served by the hub at
  `/news-img/`, so Home itself loads nothing from the internet. `"cards_off": ["weather"]` or
  `["news"]` turns those off.
- A question to Claude or Gemini carries the live context above (event titles, mail senders and
  subjects, task text, repo names): that is the point of asking them, and it goes to your own
  subscriptions. Instant answers ("brief me", "any mail") never leave the laptop.
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
| 3 | Optional “Mario” wake word | Explicit microphone commands are implemented; always-listening wake-word detection remains future work |
| 4 | "Mario, note that…" writes a sticky into the right board's Inbox | Through the Thinking Space boards' database, confirmed |
| 4 | Island and phone | The shell island shows presence and the current plan; the Link app gets the ask box |
| 5 | Council mode, nightly review, routines | Three local models on big questions; a nightly look back that proposes one fix; "remember this as…" |

Ideas behind several of these came from saved reels (LLM Council, a Claude brain kit, TurboQuant,
Pixel Agents, notes as a network, hand gestures, the desk as buttons, Mimik, GitNexus); the design
canvas lists all 19 with what each contributes.

## Check

```sh
python3 scripts/verify-mario-voice.py  # fake microphone lifecycle, cancellation and commands
python3 scripts/verify-mario-ui.py     # isolated Chrome: slides, focus, tasks and voice routing
python3 scripts/verify-mario.py   # collectors, decisions, hub over HTTP/WebSocket, page; part of verify-all --quick
python3 services/mario-hub/hub.py --once   # one full state as JSON, from this machine
```

Not covered by the check: the desktop hint and panel toggle under GNOME 42, the real `claude` and
`agy` CLIs (the check feeds recorded replies), Gmail opening a thread link, the news sites, LOOM and
Ollama. Record those with `scripts/record-live-verification.py` once tried live.
