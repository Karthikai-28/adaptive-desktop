# Mario

Mario is the assistant layer of Adaptive Desktop: a live **Home** you summon with Super+H, **Mario over
your work** on Super+J or when you say “Hey Mario” (the orb at the centre of the screen), and
**Mario Hub**, the loopback service both read from. Claude answers first (the Claude
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
| Collectors | `services/mario-hub/collectors.py` | Mail (IMAP, read-only), calendar (private iCal, every account's merged), tasks (Quick Note inboxes), builds (git), agents (terminal tmux sessions, Agent Office), Thinking Space boards, recent files, notes, weather (Open-Meteo), AI usage (`quotaSnapshot.py`, Claude and Gemini), phone (Adaptive Link socket), health (updates, disk, battery, failed services), LOOM and system for Mario's own status; Saved Reels, downloads, processes and ports stay available to Mario's answers |
| Tiles | `services/mario-hub/tiles.py` | The tiles that do more than read: Watch next (the Sheet's mirror plus your watched marks), Storage (sizes, and emptying the places Home may empty), Spotify (MPRIS on the session bus), Photos (a shared Google Photos album copied here), the sticky note and Mario Notes, and the accounts (`mario.json` and the keyring) |
| Decisions | `services/mario-hub/brain.py` (pure) | Instant answers from state, answer vs hand-off, the hand-off's limits, the Next step list |
| Who answers | `services/mario-hub/engines.py` | Claude, then Gemini, then the laptop, with the model and effort a question needs (`tier()`: quick or deep): the command lines, reading each CLI's reply, recognising a usage limit, the live context sent with a question |
| Settings | `services/mario-hub/config.py`, `~/.config/adaptive-desktop/mario.json` | Repos, Thinking Space checkout, mail accounts, `brain` order and models, LOOM/Ollama/Office URLs, backup time |
| Home and Mario's layer | `apps/mario-home/static/` (`index.html`, `home.css`, `home.js`, `tiles.js`, `layer.js`) | One page: `/` is Home, `/panel` Mario over your work. `home.js` is the frame (connection, tabs, slides, the voice session), `tiles.js` the newer tiles, the accounts sheet, the photo viewer and the orb, `layer.js` the layer: words as you speak, the answer, typing instead, leaving by itself, Hey Mario's switch and training. DOM only, no framework, no `innerHTML` |
| Voice | `services/mario-hub/voice.py`, `voice_worker.py`, `wake.py`, `voice_rules.py` (pure), `speech.py`, `tts_worker.py` | The microphone session and the words while you speak; the recogniser, in the voice environment; the “Hey Mario” listener and the training; what counts as the phrase and as your voice; Mario's own voice (Kokoro, on this laptop) |
| Host | `apps/mario-home/host.py` (GTK 3 + WebKitGTK), `scripts/adaptive-home.sh` | Home as a layer over the work area: loaded hidden at login (`--background`), shown and hidden by Super+H (a D-Bus message, about 20 ms), with one view per tab; `--panel` is Mario's layer at the centre of the screen (`--wake`, `--train`, `--quiet`, `--hide`) |
| Unit and login entry | `services/adaptive-mario-hub.service`, `apps/mario-home/adaptive-mario-home.desktop` | Templates filled with the checkout's path |

The shell's top bar, rail and island stay the shell's; Home fills only the work area.

## Your day (Home)

Home is laid out for work: what to do, what to watch, what you scribbled, the disk; then the work
itself, your pictures, the news and the music. A side column holds the always-there tools. Mail and
Calendar are tabs, not tiles. Everything updates live over the hub's WebSocket, and the tiles
marked *live* also turn between faces on their own clock, like live tiles: each at its own pace and
offset so they never all move at once, paused while the pointer is over the tile or the screen is
hidden; previous/next buttons and a slide counter show which face is up. Arrow keys on a focused
tile and horizontal swipes also move between faces. A manual turn pauses that tile until Play;
keyboard focus and reduced-motion preferences stop automatic turns too. New data redraws the
current face in place without turning it. The top bar keeps the clock.

The top row is Tasks, Watch next, Sticky note and Storage. Home is one screen and never scrolls as
a page: a list that is longer than its tile (tasks, the movie list, the storage rows, today's
events, the boards) scrolls inside that tile. Below is a four-column block: Projects and Thinking
Space side by side with Spotify and This week under them, Photos down the third column and News
down the last, both through two rows. The side column is Weather, Today, AI assistants and Phone.

| Card | Shows | Opens / does |
| --- | --- | --- |
| Tasks | Open tasks from every Quick Note inbox (Super+Alt+N, the palette's `todo`), newest first, coloured by project; scroll through all tasks, tick to finish, or add a task. Draft text and selection survive live refreshes | `/api/task`, `/api/task/done` |
| Watch next | From the movie tracker Sheet (its nightly mirror, `reels/data/movies-shows.csv` in the Thinking Space checkout): one pick for **today** and one for **tomorrow** out of the titles not yet watched that a subscription of yours carries, then the whole list, scrolling, with where each one streams and a tally | The round tick marks a title watched or not (`/api/movie`); the header opens the Sheet. Marks are kept on this laptop (`~/.local/share/adaptive-desktop/mario/movies.json`) and laid over the Sheet's own Status; the Sheet is not written |
| Sticky note | A paper note to scribble on; it saves as you type (`sticky.md` beside the other Mario data) and survives restarts | **Tidy with Mario**, or saying "tidy my sticky note": Mario rewrites the scribble as clean notes, adds them to today's page of Mario Notes (`notes_dir`, `~/Documents/Mario Notes/YYYY-MM-DD.md`) and hands back an empty note; the count of notes filed today opens that page. If nobody can be asked, it is filed as a plain list and says so |
| Storage | A ring for how full the disk is, free space, how much can be had back; then rows, largest first, that scroll: Trash, thumbnails, pip / npm / Gradle caches, your week-old files in `/tmp`, Chrome and other caches, Downloads, apt's package downloads, the system journal; and the eight largest folders of your home | **Clear** on a row Home may empty (Trash, thumbnails, pip, npm, Gradle, old temporary files) asks once more, then empties it and says how much came back (`/api/storage/clear`). Rows that need your password show the command to copy; the rest open in Files. Refresh button; re-measured every 30 min |
| Projects (live) | One repo per face, newest first (last commit, branch, changes / to push / to pull / up to date), then an Agents face: terminal agent sessions and Agent Office | Code, Terminal |
| Thinking Space | The four boards with their sections, or what is waiting in their Inbox | The board, the hub |
| Photos | The pictures of one shared Google Photos album, crossfading one after another with a slow drift, a counter and a progress line | Previous / next, pause, and full screen: a viewer over the whole of Home with arrows, a strip of every picture to pick one from (small copies the hub makes once, `/photo/<name>?thumb=1`), Space to pause, Escape to leave. The first time it asks for the album's link; the gear changes it (`/api/photos`) |
| News (live) | One headline at a time with the article's picture across the top of the tile, cropped to fit (outlets that block it get their name on a colour instead), rolling to the next every 30 s (a bar along the bottom fills to the next; paused under the pointer), source and age, two "Up next" with thumbnails; RSS from `news` in `mario.json` (Google News Tech and India, Hacker News by default), refreshed every 15 min. `"cards_off": ["news"]` stops the fetching | The article itself, picture or headline (only headlines on Home open) |
| Spotify | What the Spotify app is playing: cover, title, artist, a moving position bar and an equaliser that dances only while it plays | Previous, play / pause, next (`/api/spotify`, the desktop app over MPRIS); when Spotify is not running, a button opens it |
| This week (live) | Commits per day for the last seven days across the watched repos; then this week against last, busiest day, today | |
| Weather (live) | Now, feels-like, rain chance; the next six hours; today's high, low and rain (Open-Meteo), over a moving sky that matches it: sun or stars when clear, drifting cloud, falling rain or drizzle, snow, fog, lightning in a storm, darker at night | |
| Today | Small tile under the weather: date, and today's events still to come from every account's calendar on one timeline, the current one highlighted | Google Calendar |
| AI assistants | Claude and Gemini: usage of the fullest window and when each resets, with the time it was last read | Refresh button reads it again now (`/api/refresh`); claude.ai, Gemini |
| Phone | Adaptive Link state | The phone's screen |

**Tiles are alive.** Every tile lifts under the pointer; a tile that just received new data is
swept once by a line of light; live dots pulse; bars grow into place. All of it stops while Home is
hidden (`body.away`) and under the reduced-motion preference, so a hidden Home costs nothing.

**Refresh.** Tiles with a refresh button (`data-refresh`) ask the hub to run that collector now
(`POST /api/refresh {"card": …}`); the hub pushes the result to every open page.

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

Signing in happens inside the tab, never in the browser: the browser has its own profile, so a
sign-in there leaves Home signed out. Signed out, Google sends Calendar and Gmail to an advert for
the product whose "Sign in" link asks for a new window; Home skips that page for Google's sign-in
form and loads any sign-in page a site opens (also "Add another account") in the tab's own view.
The tabs share one profile, so one sign-in serves them all: the others load again by themselves.
A link that leaves a tab's own site (a link inside a mail, a document, a pop-out window) opens in
the browser. The rules are `apps/mario-home/site_rules.py` (pure, checked by `verify-mario.py`).
`scripts/adaptive-home.sh show mail` opens Home on a tab directly.

**Accounts.** On a Google tab the bar shows one chip per account (the main one marked, each with
its unread count on Mail). A chip takes that tab to that account: Home loads Google's account
chooser for the address with the tab as the way back, so an account that is already signed in
opens at once and a new one gets its sign-in form, in the tab. The page may only send a tab to its
own site or its sign-in pages (`site_rules.belongs`). The person button beside the chips opens the
**Accounts** sheet, below.

**Ground.** Home sits on glass: the wallpaper blurred once into
`~/.cache/adaptive-desktop/glass.png` under a graphite tint, the same picture the shell puts behind
Files. The hub serves it at `/glass.png` and makes it itself when it is missing or older than the
wallpaper, so Home does not wait for the shell.

The ask bar leads with **Talk to Mario**, with **Type instead** as a fallback. It shows who answers next (Claude / Gemini · Claude at its limit / On this laptop; the
reason is in its tooltip and under the panel's title), and
"Your day" sums it up: events, open tasks, unread mail. Brief me now includes the calendar, mail and
tasks.

### Accounts: mail and calendar

The **Accounts** sheet (the person button in the tab bar) is where accounts are kept:

- **Add account**: an address. It becomes a chip on the Google tabs; sign in to it once in the tab.
- **Mail** and **Calendar** switches per account: on, the hub reads that account's unread mail (the
  chip's count, "any mail", the briefing) or its calendar (Today, the briefing); off, it stops, and
  nothing else about the account changes. That is sync and unsync.
- **Connect** under a switch asks for what the hub needs to read on your behalf, and puts it in the
  GNOME keyring: for Mail the account's Google **app password**, for Calendar that calendar's
  **"Secret address in iCal format"** (Calendar settings → the calendar → Integrate calendar).
  The Mail and Calendar tabs themselves need neither: they are Google's own pages, signed in.
- **Make main** (the account shown first) and **Remove** (asks once more; also removes its secrets).

The same from a terminal:

```sh
scripts/install-mario.sh --mail       # a Gmail address + its Google app password -> GNOME keyring;
                                      # run again for each account; it asks whether this is the main one
scripts/install-mario.sh --mail --main  # ... and make it the main one without asking
scripts/install-mario.sh --calendar   # the calendar's "Secret address in iCal format" -> keyring
```

Accounts are kept as `"mail": {"accounts": [{"user": …, "mail": true, "calendar": true}], "main": "..."}`
in `mario.json` (the older `"mail": {"user": ...}` still reads as one account); a change from the
sheet is written there and the hub reads its settings again at once (`/api/accounts`).
Each terminal step tries the login or the feed once before it finishes and says what is wrong if Gmail or
Google refuses (the password itself is never printed). The secrets stay in the keyring (`secret-tool`, attributes `service mario-mail`
`account <address>` and `service mario-calendar` `account <address>`, one per account; the older single
`account ical` feed still reads); the hub reads them when it collects and never writes them to a file,
a log or its state. Mail is read-only: headers of unread messages, fetched with `BODY.PEEK` so
nothing is marked read. Recurring events need `icalendar` and `recurring_ical_events`, which
the installer puts in `.local/mario-pydeps`; without them only one-off events show.

### Photos, Spotify and the movie list

- **Photos** shows one *shared album*: in Google Photos open an album → Share → **Create link**,
  and paste that link into the tile. Anyone who has the link can see that album, which is how the
  hub reads it without signing in; your library itself is never opened. Up to `photos.max` (60)
  pictures are copied to `~/.local/share/adaptive-desktop/mario/photos/` at screen size, a batch
  per half hour, and pictures taken out of the album are removed here; Home shows the copies
  (`/photo/<name>`), so the tile turns without a network. A short `photos.app.goo.gl` link is
  followed once to the long `photos.google.com/share/…` address and only that is kept: some
  providers answer the name `goo.gl` with an address of their own where nothing listens (this
  laptop's connection does), so when the plain way fails the name is looked up through Google's
  public DNS over HTTPS and the certificate is still checked against the name.
- **Spotify** is the desktop app (the snap, `/snap/bin/spotify`), driven over MPRIS on the session
  bus: no Spotify account access, no token. The cover is fetched once per track from Spotify's
  image server and kept with the news pictures.
- **Watch next** reads the mirror the nightly backup makes of the tracker Sheet, so a title added
  to the Sheet today appears tomorrow. Marking a title watched here does not change the Sheet;
  writing it back needs Google sign-in for the Sheet and is phase 2.

## Install

```sh
./install.sh --only mario          # or scripts/install-mario.sh; --status changes nothing
./scripts/install-keybindings.sh   # Super+H is Home, Super+J is Mario over your work; Super+Space stays the keyboard-layout switch
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

## Talking to Mario

**Super+J** brings Mario up over whatever you are doing: the orb, at the centre of the screen, and
nothing else. It is not a window: nothing is drawn around or behind it, everything on the screen
stays as it is and keeps running, and a click beside the orb goes to whatever is there. It is
listening as soon as it appears.

| You do | What happens |
| --- | --- |
| Super+J | The orb appears at the centre and listens. Again, or Escape: it goes |
| Speak | The orb's ring takes the shape of your voice, and **your words appear under it as you say them** (recognised again about every half second of new speech) |
| Pause for a second | The request is sent (after 0.6 s for a whole command such as “open Spotify”, which then needs no second recognition pass); **Space** or a click on the orb sends it sooner. The words stay under the orb, the answer comes in below them and is read aloud; the orb grows smaller and glides up to make room |
| Space, or click the orb | Talk again |
| Any letter, or **Type** under the orb | A box to type the request instead |
| Move to another window | Mario stays while it is working, then leaves by itself |

The three small buttons under the orb (Type, Hey Mario, close) show only while Mario is not busy
or the pointer is on it; while you speak there is only the orb and your words.

On Home, **Talk to Mario** does the same in Home's own bar: three strands move with your voice and
the words so far take the place of the hint.

- “Add a task review the build” writes a task immediately.
- “Take a note: try the new layout” saves the note at once: in Mario's own notes and on today's page of Mario Notes (`notes_dir`).
- “Tidy my sticky note” (also “clean up”, “regularise”, “file”) does what the tile's **Tidy with Mario** does.
- “Open terminal”, “open files”, “open mail”, or “open calendar” use the existing launch whitelist.
- “Brief me” and other questions use the existing Mario answer routing.
- Code changes still show their plan and require **Run**.

### Hey Mario

Say **“Hey Mario”** and Mario comes up the same way, without a key, and only for your voice. The
request can follow in the same breath: “Hey Mario, what is on today?”. It is off until you teach
Mario your voice:

1. Super+J, then **Set up Hey Mario** under the orb (`host.py --panel --train` opens it directly).
2. **Start**, and say “Hey Mario” four times. Each time, Mario checks that it heard the phrase and
   nothing else, and that it sounds like the times before; if not it says what it heard and asks
   again. The orb moves with your voice and four dots fill.
3. It is on. The same sheet has the switch, **Train again** and **Forget my voice**.

How it listens, cheapest step first, all on this laptop (`voice_worker.py wake`):

1. a small speech detector (Silero) notices that somebody began to speak;
2. the speaker model (NVIDIA TitaNet small) compares the first second or so with your voiceprint;
   another voice stops here;
3. only then are the first words recognised (Whisper) and compared with the phrase
   (`voice_rules.py`: “Hey Mario”, “Hi Mario”, “OK Mario”; not “Hey Maria”, not “Super Mario”).

Then the hub starts an ordinary voice session **on the same open microphone**, beginning with the
breath that held the phrase, so nothing said right after it is lost, and brings the orb up. Summoned
this way Mario does not take the keyboard from what you are typing in, and it leaves by itself a
few seconds after it has answered (longer for a long answer, not while the pointer is on it, not
while a plan waits for **Run**). “Hey Mario” and then nothing: it steps back without a word.

What to know:

- **While Hey Mario is on, the microphone is open all the time** and its sound is examined on this
  laptop only; nothing is recorded and nothing is sent anywhere. Turn it off with the switch and
  the microphone is closed. It costs about 1 % of one processor core while the room is quiet.
- The only thing kept is the **voiceprint**: four lists of numbers and their middle, in
  `~/.local/share/adaptive-desktop/mario/voice.json`, readable by you alone. No recording is kept,
  also not of the training. **Forget my voice** deletes the file.
- It is a convenience, **not a lock**. A voice like yours, or a recording of you, can pass; what
  Mario may do is limited in the same way whoever asks (Safety, below).
- The listener pauses while a voice session has the microphone, while Mario is speaking and while
  you train; it ignores the phrase while the screen is locked.
- From the phrase to the orb takes a little under a second (the words are recognised by the same
  model as your requests, about 0.6 s on this laptop).
- Tried so far with made-up voices only (`verify-mario-wake.py --real`): a trained voice woke it
  about nine times in ten, another voice saying the phrase about one time in fourteen, other words
  never. With your own voice it is still to be tried.

### How it is built

`services/mario-hub/voice.py` captures the default PulseAudio microphone in memory using `parec`:
30-second maximum, eight seconds to begin speaking, and a five-second page heartbeat. What counts
as speech is measured against the room (the quietest tenth of what was heard so far, so a fan is
not speech), and the first 0.6 s after the microphone opens is not judged (many inputs start with a
thump). Recognition runs in a separate process that is killed on cancel or timeout
(`voice_worker.py`, faster-whisper base.en on CPU with int8 and speech filtering): it is asked for
the words so far while you speak and once, carefully, for the whole request. Audio never goes to a
cloud service or a recording file. Only the resulting request enters Mario's normal answer path.
The recogniser is given the installed apps' names (faster-whisper `hotwords`, from `control.vocabulary`),
so it writes “Spotify”, not “spot if I”; tested with Indian, British and American voices, this
turned “Lunch Firefox” into “Launch Firefox” and “Switch the ground” into “Switch the Chrome”.
`wake.py` is the “Hey Mario” listener and the training.

**Mario's voice.** Replies are read in a natural neural voice, Kokoro v1.0 (`speech.py`,
`tts_worker.py`, through sherpa-onnx in the voice environment), on this laptop: the model stays
loaded for the hub's life, and a reply is made and played a sentence at a time, so the first words
come about 0.6 s after the answer (the rest is made while it plays, about 1.2x real time on this
CPU). Short replies such as “Opening Spotify.” are kept as sound in
`~/.cache/adaptive-desktop/mario-voice` and play at once the next time. What is read is cleaned
for the ear (`for_speech`: no Markdown, links, paths or code). A newer reply cuts the last one off.
Without the model, or with `"voice": {"engine": "espeak"}`, Speech Dispatcher (`spd-say`) speaks.
The voice is `"voice": {"speaker": "am_michael", "speed": 1.0}` in `mario.json`; others include
`am_fenrir`, `am_puck`, `bm_george`, `af_heart` (the most natural of all), `af_bella`, `bf_emma`, and
`hm_omega` / `hf_alpha` (Indian English); every name is in the model's `names.txt`. The full-precision
model is used: the int8 one runs at a third of real time on CPUs without VNNI.

```sh
scripts/install-mario-voice.sh    # dedicated .local/mario-voice environment; public models only:
                                  # Whisper base.en, Kokoro v1.0 (the voice), and for Hey Mario the
                                  # speech detector and the speaker model
```

The desktop host is WebKitGTK, so this does not depend on Chrome-only browser speech recognition.
If Mario hears nothing, check the default input and mute state in Ubuntu Sound settings. Recognition
currently expects English. Without Hey Mario, the microphone opens only on Super+J or a button,
never at login.

**The layer.** `host.py --panel` is a see-through, undecorated window of the dock type (above
other windows, on every workspace, not in the switcher, not animated by the shell) centred on the
screen. WebKitGTK 2.50 does not erase a see-through page when it repaints, so anything that moved
would leave a trail; instead the page is solid, `layer.js` reports the outline of every piece it
draws (each frame while something moves), and the host shows the page only inside those outlines,
with smooth edges and a shadow under each, and gives only those outlines to the pointer. The login
entry loads the layer hidden, so the first Super+J is as fast as the others.

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

0. **Command**: something to do on the computer, the TV or the Kinect ("open Spotify", "connect to
   my TV", "how tall am I", "snap left", "volume 40", "night vision on") is carried out at once:
   `commands.py` says what was meant, `control.py` does it through what is already bounded (the
   shell's `org.adaptive.Shell` bridge with fixed action names, the Kinect hub on 127.0.0.1:8792,
   the Cast command line, pactl, MPRIS, the app grid's launcher). A sentence with command-line
   symbols (`; & | $ < >`) is never a command, nothing spoken is run as a command line, and an
   "open X" that is not an app falls through to an answer. Names are matched the way they are
   heard: exactly first, then run together (“fire fox”), then by spelling and by sound
   (`control.sounds`: “spotifai”, “spotty fy”, “sportify” are Spotify; “open sesame” is nothing).
   Misheard verbs count too (“often”, “oven”, “opening” for open; “lunch” for launch; “switch
   the” for switch to), and an app's name said on its own (“Spotify”) opens it when the name is
   clear. Every sentence you can say is in
   docs/MARIO_COMMANDS.md, written from `commands.CHEATSHEET`; "what can I say?" opens it at
   http://127.0.0.1:8791/commands. Checked by `scripts/verify-mario-commands.py`.
1. **Instant**: "brief me", "what changed today", "pick a movie for tonight" are answered from the
   cards with no model.
2. **Answer**: everything else that is a question or chat goes, with a few lines of live context
   (time, weather, today's events, unread mail per account, open tasks, repo state), to the first of
   `brain` (default `["claude", "gemini", "local"]`) that can answer. **The router** (`engines.tier`,
   from the words alone, so deciding costs nothing) calls a question *quick* (a fact, a chat, a
   short how-to) or *deep* (explain, why, compare, plan, write, code, an error, more than 28 words or
   more than one question), and each engine answers with that tier's set-up (`models` and `effort`
   in `mario.json`):

   | | Claude | Gemini (at Claude's limit) |
   | --- | --- | --- |
   | quick | Sonnet 5.5, `--effort low` | Gemini 3.8 Flash Low |
   | deep | Sonnet 5.5, `--effort high` | Gemini 3.8 Flash Medium |

   Measured here on 2026-11-17, each CLI run exactly as Mario runs it, over 11 spoken questions:
   Sonnet 5.5 took a median 2.7-3.0 s from asking to the whole answer and Haiku 5.5 3.7-3.9 s (slower
   in every pair, so Haiku is not the quick model; `"models": {"quick": {"claude": "claude-haiku-5-5"}}`
   puts it back), and Gemini through `agy` 11-14 s, most of it agy's own start-up. A question asked
   by voice also asks for a short, talking reply (`engines.SPOKEN`).
   - **Claude**: `claude -p` with Mario's own system prompt and no tools but web search and web
     fetch, so it can look things up but never run or change anything. It runs lean
     (`engines.LEAN`): no MCP servers, skills or settings files, which also keeps CLAUDE.md and
     memory out (about 2,600 tokens a question instead of 7,500), still on the subscription's own
     login (`--bare` is not used: it needs an API key). A conversation carries on (`--resume`) while
     it was used in the last `conversation_s` (10 minutes); after that a question starts afresh.
     It runs in `~/.local/share/adaptive-desktop/mario/brain`.
   - **Gemini**: when Claude is at its usage limit (the AI usage tile at 100 % in a window that has
     not reset, or Claude itself says so), or does not answer: `agy -p` in plan mode, sandboxed, the
     tier's Gemini model. A limit Claude reports is remembered until the time it names (else 15
     minutes), so later questions go straight to Gemini.
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
  secrets from the keyring. What reaches the internet: Gmail (IMAP), the calendar feeds, the shared
  Photos album and its pictures, the cover of the track Spotify plays, the weather
  (Open-Meteo, no key, the coordinates in `weather`) and News: the feeds, then for each headline once
  its page (Google News' redirect page, then the article) and its picture. Pictures are kept in
  `~/.local/share/adaptive-desktop/mario/news/` (cleared after three days) and served by the hub at
  `/news-img/`, so Home itself loads nothing from the internet. `"cards_off": ["weather"]` or
  `["news"]` turns those off.
- A question to Claude or Gemini carries the live context above (event titles, mail senders and
  subjects, task text, repo names): that is the point of asking them, and it goes to your own
  subscriptions. Instant answers ("brief me", "any mail") never leave the laptop.
- **Tidy with Mario** sends the sticky note's text to whoever answers (Claude, else Gemini, else the
  laptop), like any other question to Mario.
- Storage's **Clear** empties only the six places named in `tiles.storage_places` as clearable,
  after a second click; nothing that needs your password is run, only shown. `open_place` opens
  just the folders the Storage and sticky tiles list.
- Anything that leaves the laptop needs your yes, every time.
- “Hey Mario” is off until you train it. On, the microphone stays open and is examined on this
  laptop only; the voiceprint is kept in a file only you can read, recordings are not kept at all,
  and the phrase is ignored while the screen is locked. The voice match is a convenience, not a
  lock: what a spoken request may do is the same short list whoever says it, and a code change
  still waits for **Run**.

## Presence

Mario's mark is three strands (your work, the world, you). `/api/presence` and the `presence`
WebSocket message carry the state: `ready` (strands nearly flat, still), `listening` (strands
swing), `thinking` (a shuttle runs along them), `speaking` (while a reply is read aloud), `doing`
(one line fills), `needs_you` (one amber strand). Reduced motion stops every animation.

**The orb** (Super+J, “Hey Mario”) is the same state drawn as a circle on a canvas, in the tokens'
colours: slow concentric rings and orbiting arcs at rest; while it listens the inner ring swells
and roughens with the microphone's real level and ripples run outward; while it thinks the arcs
spin up; while it speaks, waves travel round the ring and pulse outward for as long as the reply is
being read (until the voice worker says the sound has ended; the talk-back waves are drawn, not
measured). Clicking the orb is Talk to Mario. It stops drawing while the layer is hidden.

## Next

| Phase | What | Notes |
| --- | --- | --- |
| 2 | Read the Google Sheet directly and write the watched mark back to it; Photos from the library rather than one shared album | Through the Link's Google project (`--link-cloud`); the Sheet write needs a write scope and your yes |
| 3 | Hey Mario with your own voice | Built and tried with made-up voices; needs your training and a few days of use to set how strict the voice match should be (`LOW`, `HIGH` in `voice_rules.py`) |
| 4 | "Mario, note that…" writes a sticky into the right board's Inbox | Through the Thinking Space boards' database, confirmed |
| 4 | Island and phone | The shell island shows presence and the current plan; the Link app gets the ask box |
| 5 | Council mode, nightly review, routines | Three local models on big questions; a nightly look back that proposes one fix; "remember this as…" |

Ideas behind several of these came from saved reels (LLM Council, a Claude brain kit, TurboQuant,
Pixel Agents, notes as a network, hand gestures, the desk as buttons, Mimik, GitNexus); the design
canvas lists all 19 with what each contributes.

## Check

```sh
python3 scripts/verify-mario-voice.py  # fake microphone: pauses, a noisy room, words while listening, cancellation, a session Hey Mario began, commands
python3 scripts/verify-mario-wake.py   # Hey Mario with fakes: the phrase, the voiceprint, the listener, training; --real VOICE runs the real models on made-up voices
python3 scripts/verify-mario-ui.py     # isolated Chrome: slides, focus, tasks, the newer tiles, accounts sheet, photo viewer; Mario's layer: orb, outlines, live words, answer, training
python3 scripts/verify-mario.py   # collectors, decisions, hub over HTTP/WebSocket, page; part of verify-all --quick
python3 services/mario-hub/hub.py --once   # one full state as JSON, from this machine
```

Not covered by the check: the real `claude` and `agy` CLIs (the check feeds recorded replies), the
news sites, LOOM and Ollama, a second Google account signing in from its chip, a real shared album
of yours, Spotify actually playing, and everything that needs your voice: a spoken request end to
end on Super+J, and Hey Mario trained by you. Seen on the real screen on 2026-11-15: the layer over
other windows with only the orb showing, no trail when a piece comes or goes, the keyboard left
where it was when it comes up the Hey Mario way, and the real microphone feeding the session and
the listener. Record those with `scripts/record-live-verification.py` once tried live.
