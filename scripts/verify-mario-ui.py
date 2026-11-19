#!/usr/bin/env python3
"""Exercise Home with fixtures in isolated Chrome. No models, microphone, or personal data."""
import asyncio
import base64
import importlib.util
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import aiohttp
from aiohttp import web
import websockets

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'services/mario-hub'))
import hub
import config
import tiles


async def main(tmp):
    cfg = dict(config.DEFAULTS, repos=[], thinking_space=tmp, notes_dir=str(tmp / 'Mario Notes'))
    h = hub.Hub(cfg, schedule={}, cfg_file=tmp / 'mario.json')
    h.notes_file = tmp / 'notes.md'
    h.sticky_file = tmp / 'sticky.md'
    h.sticky_file.write_text('first scribble')
    tiles.MOVIE_MARKS = tmp / 'movies.json'
    tiles.PHOTOS_DIR = tmp / 'photos'
    tiles.PHOTOS_DIR.mkdir()
    # two tiny pictures (1x1 PNG bytes under a .jpg name: the page only needs something to show)
    png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==')
    photo_names = ['a' * 16 + '.jpg', 'b' * 16 + '.jpg']
    for name in photo_names:
        (tiles.PHOTOS_DIR / name).write_bytes(png)
    now = time.time()
    h.cards = {k: {'data': v, 'at': now} for k, v in {
        'mail': {'unread': 8, 'items': [{'from': 'Project team', 'subject': 'Review the build before Friday', 'when': now} for _ in range(5)]},
        # the Agent Office's board (GET /api/board through the agent_office collector): more cards than a column shows
        'agent_office': {'running': True, 'paused': False, 'agents': [], 'missions': [], 'board': {
            'agents': [{'id': f'a{i}', 'name': f'Agent {i}', 'role': 'Researcher', 'state': ('working', 'idle', 'blocked')[i % 3],
                        'state_label': ('Working', 'Idle', 'Blocked')[i % 3], 'task': {'id': 100 + i, 'title': f'Run {i}'} if i % 3 == 0 else None,
                        'running_since': now - 90 if i % 3 == 0 else None, 'needs_you': 1 if i % 3 == 2 else 0, 'queued_count': 2,
                        'active_24h_s': 600} for i in range(6)],
            'columns': {
                'todo': [{'id': 200 + i, 'title': f'Queued work item {i} with a long enough title to wrap', 'agent': f'a{i % 6}',
                          'mission': 'India AV', 'depends_on': 199 + i if i else None, 'attempts': 1} for i in range(12)],
                'doing': [{'id': 100 + i, 'title': f'Run {i}', 'agent': f'a{i}', 'running_since': now - 90, 'actions': 3, 'last': 'Reading the paper'} for i in (0, 3)],
                'needs_you': [{'inbox_id': 7, 'priority': 'high', 'reason': 'Approve the plan', 'kind': 'approval', 'state': 'NEEDS_ATTENTION', 'since': now - 600,
                               'task': {'id': 150, 'title': 'Plan the survey', 'agent': 'a2', 'status': 'blocked'}}],
                'done': [{'id': 300 + i, 'title': f'Finished {i}', 'agent': f'a{i}', 'status': 'done' if i else 'failed', 'run_s': 400} for i in range(5)]},
            'counts': {'active': 2, 'agents': 6, 'done_today': 4, 'failed_today': 1, 'cancelled_today': 0},
            'inbox': {'NEEDS_ATTENTION': 1}, 'todo_total': 12}},
        'builds': {'repos': [{'name': f'Project {i}', 'path': str(tmp), 'branch': 'master', 'subject': 'Latest useful change', 'when': now, 'dirty': 2} for i in range(3)]},
        'downloads': {'files': [{'name': f'Notes {i}.pdf', 'path': f'/fixture/{i}.pdf', 'size': 12345} for i in range(3)]},
        'calendar': {'events': []},
        'weather': {'temp': 25, 'feels': 26, 'place': 'Bengaluru', 'sky': 'Rain', 'scene': 'rain', 'hours': [], 'high': 29, 'low': 20},
        'usage': {'providers': {'claude': {'used': 40, 'window': '5h', 'windows': []}}},
        'movies': {'today': 'Film 0', 'tomorrow': 'Film 1', 'left': 9, 'watched': 0, 'total': 9, 'sheet': '',
                   'items': [{'title': f'Film {i}', 'year': '2020', 'type': 'Movie', 'where': 'Netflix', 'included': True, 'watched': False, 'marked': False} for i in range(9)]},
        'storage': {'total': 500e9, 'used': 120e9, 'free': 380e9, 'pct': 24, 'reclaim': 2e9,
                    'places': [{'id': f'p{i}', 'label': f'Cache {i}', 'bytes': (9 - i) * 1e8, 'hint': 'Rebuilt when needed', 'path': '/fixture', 'clear': i % 2 == 0, 'admin': ''} for i in range(8)],
                    'folders': [{'name': f'Folder {i}', 'bytes': 1e9, 'path': '/fixture'} for i in range(4)]},
        'spotify': {'running': True, 'installed': True, 'player': 'spotify', 'is_spotify': True, 'status': 'Playing', 'title': 'Song',
                    'artist': 'Artist', 'album': 'LP', 'art': '', 'length': 200, 'position': 50},
        'photos': {'album': 'https://photos.google.com/share/x', 'title': 'Album', 'items': [{'name': n} for n in photo_names], 'count': 2},
        'accounts': {'accounts': [{'user': 'first@example.com', 'main': True, 'mail': True, 'calendar': True, 'has_password': True, 'has_calendar': True},
                                  {'user': 'second@example.com', 'main': False, 'mail': True, 'calendar': False, 'has_password': False, 'has_calendar': False}]},
        'news': {'items': [{'title': f'Research update {i}', 'source': 'Science', 'link': f'https://example.org/{i}', 'when': now} for i in range(3)]},
    }.items()}
    calls = []
    h.action = lambda aid, arg: calls.append((aid, arg)) or {'ok': True}
    async def fake_ask(text, **_):
        calls.append(('ask', text))
        return {'answer': 'Done from voice.', 'via': 'Mario'}
    h.ask = fake_ask
    async def quiet(*args): pass
    h.speak = quiet
    # a voice session that stays in "listening", with words so far, for as long as the check holds it
    hold = {'on': False, 'state': 'done'}
    async def start(**_): return {'id': 'fixture', 'state': 'listening'}
    async def command(action, sid):
        if action != 'status': return {'state': 'cancelled'}
        if hold['on']: return {'state': 'listening', 'level': 0.6, 'partial': 'Open term'}
        return {'state': 'done', 'text': 'Open terminal'} if hold['state'] == 'done' else {'state': hold['state'], 'text': ''}
    h.voice.start, h.voice.command = start, command
    # "Hey Mario": no microphone, no models; training that mishears the first try, then hears the phrase four times
    wake = {'available': True, 'trained': False, 'enabled': False, 'hearing': False, 'training': False, 'trained_at': 0, 'error': ''}
    looks = {'n': 0}
    h.wake.status = lambda: dict(wake)
    async def train_start(): looks['n'] = time.monotonic(); return {'id': 'train', 'state': 'starting', 'step': 0, 'of': 4, 'level': 0, 'message': '', 'heard': ''}
    async def train_status(sid):
        step = min(4, int((time.monotonic() - looks['n']) / 0.7))
        if step == 4: wake.update(trained=True, enabled=True, hearing=True, trained_at=now)
        return {'id': 'train', 'state': 'done' if step == 4 else 'say', 'step': step, 'of': 4, 'level': 0.5, 'heard': 'Hey Mario',
                'message': 'I heard “Hey Maria”. Say just “Hey Mario”.' if step == 0 else ''}
    async def train_cancel(sid=None): return {'state': 'cancelled'}
    async def enable(on): wake.update(enabled=on, hearing=on); await h.push_wake(); return dict(wake)
    h.wake.train_start, h.wake.train_status, h.wake.train_cancel, h.wake.enable = train_start, train_status, train_cancel, enable
    port = 18991
    runner = web.AppRunner(hub.make_app(h, port))
    await runner.setup()
    await web.TCPSite(runner, '127.0.0.1', port).start()
    chrome = subprocess.Popen(['google-chrome', '--headless=new', '--no-first-run', '--disable-gpu',
                               '--remote-debugging-port=0', f'--user-data-dir={tmp}/chrome',
                               '--window-size=1920,1120', f'http://127.0.0.1:{port}/'],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        active = tmp / 'chrome/DevToolsActivePort'
        for _ in range(100):
            if active.exists(): break
            await asyncio.sleep(.1)
        debug = active.read_text().splitlines()[0]
        async with aiohttp.ClientSession() as session:
            async with session.get(f'http://127.0.0.1:{debug}/json') as res:
                pages = await res.json()
        target = next(p for p in pages if p['type'] == 'page')
        async with websockets.connect(target['webSocketDebuggerUrl'], max_size=None) as ws:
            seq = 0
            async def call(method, params=None):
                nonlocal seq
                seq += 1
                await ws.send(json.dumps({'id': seq, 'method': method, 'params': params or {}}))
                while True:
                    msg = json.loads(await ws.recv())
                    if msg.get('id') == seq:
                        assert 'error' not in msg, msg
                        return msg['result']
            async def ev(expr):
                r = await call('Runtime.evaluate', {'expression': expr, 'awaitPromise': True, 'returnByValue': True})
                assert 'exceptionDetails' not in r, r
                return r['result'].get('value')
            for _ in range(60):
                if await ev('!!document.querySelector("#c-projects .tile-nav")'): break
                await asyncio.sleep(.1)
            # tabs: Today, then the sites from the hub's config; a site tab swaps the cards for its slot. The Agent
            # Office's board is a tile on Today, not a tab (the operator's decision of 2026-11-20)
            tabs = await ev('[...document.querySelectorAll("#tabs .tab")].map(t => t.firstChild.textContent)')
            assert tabs[0] == 'Today' and 'Agents' not in tabs, tabs
            assert await ev('document.querySelector("#accts").hidden')      # account chips belong to a Google tab, not Today
            if len(tabs) > 1:
                await ev('homeSpace.select(2); true')
                assert await ev('document.querySelector(".main").hidden && !document.querySelector("#web").hidden && document.querySelector("#tabs .tab.on").firstChild.textContent !== "Today"')
                # one chip per account, the main one chosen; a chip chooses its account
                assert await ev('[...document.querySelectorAll("#accts .acct")].map(a => a.querySelector(".nm").textContent).join() === "first,second" && document.querySelector("#accts .acct.on .nm").textContent === "first"')
                await ev('document.querySelectorAll("#accts .acct")[1].click(); true')
                assert await ev('document.querySelector("#accts .acct.on .nm").textContent === "second"')
                assert 'AccountChooser?Email=second%40example.com' in await ev('accountUrl(siteTabs()[0], "second@example.com")')
                await ev('homeSpace.select(1); true')
            assert await ev('!document.querySelector(".main").hidden && document.querySelector("#web").hidden')
            assert await ev('document.body.classList.contains("opening")')
            assert await ev('document.querySelectorAll(".card").length') == 14
            assert await ev('!document.querySelector("#c-mail, #c-next, #c-note, #c-recent")')
            assert await ev('!document.querySelector("#c-apps, #c-focus, #c-downloads")')
            # one screen: the page never scrolls, and whatever is long scrolls inside its own tile
            assert await ev('document.documentElement.scrollHeight <= innerHeight && getComputedStyle(document.body).overflowY === "hidden"')
            assert await ev('[...document.querySelectorAll("#c-board .bd-list")].every(l => getComputedStyle(l).overflowY === "auto")')
            cut = await ev('[...document.querySelectorAll(".card")].filter(c => c.scrollHeight > c.clientHeight + 2).map(c => c.id)')
            assert not cut, cut
            thinking, projects = await ev('[document.querySelector("#c-thinking").offsetWidth, document.querySelector("#c-projects").offsetWidth]')
            assert abs(thinking - projects) <= 2, (thinking, projects)   # Thinking Space is one column, like Projects
            await ev('Object.values(LIVE).forEach(t => t.paused=true); true')
            assert await ev('LIVE.projects.faces.length') == 4
            await ev('LIVE.projects.i=0; document.querySelector("#c-projects [aria-label=\\"Next slide\\"]").click(); true')
            assert await ev('LIVE.projects.i === 1 && LIVE.projects.paused')
            await ev('for(let i=0;i<9;i++) turn("projects",1,true); true')
            assert await ev('LIVE.projects.i === 2 && document.querySelector("#c-projects .face").textContent.includes("Project 2")')
            await ev('document.querySelector("#c-projects").dispatchEvent(new KeyboardEvent("keydown",{key:"ArrowLeft",bubbles:true})); true')
            assert await ev('LIVE.projects.i') == 1
            # Agents: the Agent Office's board in the first tile of the top row, twice as wide as its neighbours: a chip
            # per agent, four columns that scroll in themselves, a card opens its task in the office
            assert await ev('!document.querySelector("#c-tasks") && document.querySelector(".r2 > .card").id === "c-board"')
            board_w, movies_w = await ev('[document.querySelector("#c-board").offsetWidth, document.querySelector("#c-movies").offsetWidth]')
            assert board_w > 1.8 * movies_w, (board_w, movies_w)
            assert await ev('[...document.querySelectorAll("#c-board .bd-col h3")].map(h => h.textContent).join()') == 'To do,In progress,Needs you,Done today'
            assert await ev('document.querySelectorAll("#c-board .bd-agent").length') == 6
            assert await ev('document.querySelectorAll("#c-board .bd-col.todo .bd-card").length') == 12
            assert await ev('document.querySelector("#board-sum").textContent') == '2 of 6 working · 1 need you'
            assert await ev('(l => l.scrollHeight > l.clientHeight)(document.querySelector("#c-board .bd-col.todo .bd-list"))')
            await ev('document.querySelector("#c-board .bd-col.todo .bd-list").scrollTop = 30; render.board(); true')
            assert await ev('document.querySelector("#c-board .bd-col.todo .bd-list").scrollTop') == 30
            assert await ev('document.querySelectorAll("#c-board .bd-col.doing .bd-run").length') == 2
            await ev('document.querySelector("#c-board .bd-agent").click(); true')          # Agent 0: only its work
            assert await ev('document.querySelectorAll("#c-board .bd-col.todo .bd-card").length') == 2
            await ev('document.querySelector("#c-board .bd-agent.on").click(); true')       # again: everyone
            assert await ev('document.querySelectorAll("#c-board .bd-col.todo .bd-card").length') == 12
            await ev('document.querySelector("#c-board .bd-col.doing .bd-card").click(); document.querySelector("#board-open").click(); true')
            for _ in range(30):
                if ('office', '') in calls: break
                await asyncio.sleep(.1)
            assert ('office', 'task:100') in calls and ('office', '') in calls, calls
            # Watch next: today's and tomorrow's picks, a list that scrolls in the tile, a mark that sticks
            assert await ev('[...document.querySelectorAll("#c-movies .pick .ttl")].map(n => n.textContent).join() === "Film 0,Film 1"')
            assert await ev('getComputedStyle(document.querySelector("#c-movies .movie-list")).overflowY === "auto"')
            await ev('document.querySelector("#c-movies .movie-list").scrollTop = 40; render.movies(); true')
            assert await ev('document.querySelector("#c-movies .movie-list").scrollTop') == 40
            await ev('document.querySelector("#c-movies .pick .seen").click(); true')
            for _ in range(30):
                if tiles.movie_marks(tmp / 'movies.json').get('Film 0'): break
                await asyncio.sleep(.1)
            assert tiles.movie_marks(tmp / 'movies.json')['Film 0']['watched'] is True
            # the sticky note: what the hub holds, kept while you type, saved by itself
            assert await ev('document.querySelector("#sticky-text").value') == 'first scribble'
            await ev('(() => { const a = document.querySelector("#sticky-text"); a.focus(); a.value = "typing now"; a.dispatchEvent(new Event("input")); state.cards.sticky = {data: {text: "from the hub", filed: 0}}; render.sticky(); return true; })()')
            assert await ev('document.querySelector("#sticky-text").value') == 'typing now'
            for _ in range(30):
                if h.sticky_file.read_text() == 'typing now': break
                await asyncio.sleep(.1)
            assert h.sticky_file.read_text() == 'typing now'
            # Storage: scrolls in the tile; clearing asks first
            assert await ev('getComputedStyle(document.querySelector("#c-storage .scroll")).overflowY === "auto" && document.querySelectorAll("#c-storage .place").length === 12')
            await ev('document.querySelector("#c-storage .place .mini").click(); true')
            assert await ev('document.querySelector("#c-storage .mini.danger").textContent.startsWith("Clear ")')
            # the weather's sky is raining; Spotify plays; the photos turn
            assert await ev('document.querySelector("#c-weather").dataset.scene === "rain" && document.querySelectorAll("#c-weather .sky .drop").length > 20 && getComputedStyle(document.querySelector(".drop")).animationName === "fall"')
            assert await ev('document.querySelector("#c-spotify").classList.contains("playing") && document.querySelector("#sp-title").textContent === "Song" && getComputedStyle(document.querySelector("#c-spotify .eq i")).animationName === "eq"')
            assert await ev('document.querySelector("#photos-meta").textContent === "1 / 2" && document.querySelectorAll("#ph-stage img.ph").length >= 1')
            await ev('showPhoto(photoI + 1); true')
            assert await ev('document.querySelector("#photos-meta").textContent === "2 / 2"')
            await ev('document.querySelector("#ph-stage").click(); true')
            assert await ev('!document.querySelector("#lightbox").hidden && document.querySelector("#lb-img").src.includes("/photo/")')
            # the strip under the picture holds every photo, small; the one that is up is marked, a click picks another
            assert await ev('document.querySelectorAll("#lb-strip button").length === 2 && document.querySelector("#lb-strip button.on") === document.querySelectorAll("#lb-strip button")[1] && document.querySelector("#lb-strip img").src.endsWith("?thumb=1")')
            await ev('document.dispatchEvent(new KeyboardEvent("keydown", {key: "ArrowRight", bubbles: true})); true')
            assert await ev('document.querySelector("#lb-count").textContent === "1 / 2"')
            await ev('document.querySelectorAll("#lb-strip button")[1].click(); true')
            assert await ev('document.querySelector("#lb-count").textContent === "2 / 2" && document.querySelectorAll("#lb-strip button")[1].classList.contains("on") && document.querySelector("#lb-img").src.includes("bbbbbbbbbbbbbbbb")')
            await ev('document.body.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true})); true')
            assert await ev('document.querySelector("#lightbox").hidden')
            # the accounts sheet: each account with its two switches; what you type survives a redraw
            await ev('document.querySelector("#accounts-btn").click(); true')
            assert await ev('!document.querySelector("#sheet").hidden && document.querySelectorAll("#sheet .acct-row").length === 2 && document.querySelectorAll("#sheet .switch").length === 4')
            assert await ev('[...document.querySelectorAll("#sheet .switch")].map(x => x.getAttribute("aria-checked")).join() === "true,true,true,false"')
            await ev('(() => { const i = document.querySelector(\'#sheet input[data-key="new"]\'); i.value = "third@exa"; render.sheet(); return true; })()')
            assert await ev('document.querySelector(\'#sheet input[data-key="new"]\').value') == 'third@exa'
            await ev('document.querySelector("#sheet-close").click(); true')
            assert await ev('document.querySelector("#sheet").hidden')
            # a tile says when its data changed; nothing moves while Home is away
            await ev('cardChanged("usage"); true')
            assert await ev('document.querySelector("#c-ai").classList.contains("fresh")')
            await ev('homeSpace.closed(); true')
            assert await ev('document.body.classList.contains("away") && getComputedStyle(document.querySelector(".drop")).animationPlayState === "paused"')
            await ev('document.body.classList.remove("away"); true')
            # the listening picture: strands at the microphone's level, drifting only while it listens
            await ev('voiceStatus("Listening", true, "listening", 0.5); true')
            assert await ev('(() => { const b = document.querySelector("#voice-status"); return !b.hidden && b.dataset.phase === "listening" && b.style.getPropertyValue("--level") === "0.5" && getComputedStyle(b.querySelector(".w1")).animationName === "drift" && b.querySelector(".w1").getAttribute("d").length > 50; })()')
            await ev('voiceStatus("Working", false, "working"); true')
            assert await ev('getComputedStyle(document.querySelector(".wave .w1")).animationName === "none" && getComputedStyle(document.querySelector(".wave .working")).animationName === "working"')
            await ev('voiceStatus(""); true')
            assert await ev('document.querySelector("#voice-status").hidden && document.querySelector("#voice-status").dataset.phase === "idle"')
            # the words so far take the hint's place while you speak
            hold['on'] = True
            await ev('toggleVoice(); true')
            await asyncio.sleep(.5)
            assert await ev('document.querySelector("#voice-status span").textContent') == '“Open term”'
            hold['on'] = False
            for _ in range(40):
                if ('ask', 'Open terminal') in calls: break
                await asyncio.sleep(.1)
            assert ('ask', 'Open terminal') in calls
            await asyncio.sleep(.3)
            assert await ev('document.querySelector("#answer").textContent.includes("Done from voice")')
            await ev('cancelVoice(); document.querySelector("#answer").hidden=true; true')
            # Controls must be visible inside their cards at the target laptop size.
            clipped = await ev('''[...document.querySelectorAll('.tile-nav button, #board-open, #c-board .bd-col')].filter(n=>!n.closest('[hidden]')).filter(n=>{let a=n.getBoundingClientRect(),b=n.closest('.card').getBoundingClientRect();return a.bottom>b.bottom || a.right>b.right}).map(n=>n.closest('.card').id)''')
            assert not clipped, clipped
            shot = await call('Page.captureScreenshot', {'format': 'png'})
            Path('/tmp/mario-home.png').write_bytes(base64.b64decode(shot['data']))
            # Mario over your work (/panel), in a stand-in for its host: what the page tells it is kept
            await call('Page.enable')
            await call('Page.addScriptToEvaluateOnNewDocument', {'source':
                'window.__told = []; window.webkit = {messageHandlers: {home: {postMessage: (m) => window.__told.push(JSON.parse(m))}}};'})
            await call('Page.navigate', {'url': f'http://127.0.0.1:{port}/panel'})
            for _ in range(60):
                if await ev('document.body && document.body.classList.contains("is-panel") && (window.__told || []).some(m => m.type === "ready")'): break
                await asyncio.sleep(.1)
            # only the orb until there is something to say
            await ev('marioShown("quiet"); true')
            await asyncio.sleep(.5)
            assert await ev('document.querySelector("#panel").classList.contains("shown") && document.querySelector("#heard").hidden && document.querySelector("#log").hidden && document.querySelector("#panel-form").hidden')
            drawn = await ev('(() => { const c = document.querySelector("#orb"); const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data; let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i] > 8) n++; return n; })()')
            assert drawn > 2000, drawn
            # the orb is at the centre of the layer, and only what is drawn takes the pointer
            box = await ev('(() => { const r = document.querySelector("#orb-stage").getBoundingClientRect(); return [r.left + r.width / 2 - innerWidth / 2, r.top + r.height / 2 - innerHeight / 2, r.width]; })()')
            assert abs(box[0]) < 2 and abs(box[1]) < 2 and box[2] == 280, box
            # what the host shows of the page: the orb, a circle, and the three small buttons under it
            shapes = await ev('window.__told.filter(m => m.type === "shape").pop().shapes')
            assert len(shapes) == 4 and shapes[0][2:] == [280, 280, 140] and all(s[4] == 15 for s in shapes[1:]), shapes
            # the key: it listens at once, your words appear as you say them, then the answer under the orb
            calls.clear()
            hold['on'] = True
            await ev('marioShown("talk"); true')
            await asyncio.sleep(.6)
            assert await ev('document.querySelector("#orb").dataset.state === "listening" && document.querySelector("#heard-text").textContent === "Open term" && !document.querySelector("#heard").hidden')
            assert await ev('getComputedStyle(document.querySelector("#layer-tools")).opacity === "0"')     # only the animation and the words
            hold['on'] = False
            for _ in range(40):
                if await ev('document.querySelector("#log").textContent.includes("Done from voice")'): break
                await asyncio.sleep(.1)
            assert ('ask', 'Open terminal') in calls
            assert await ev('document.querySelector("#heard-text").textContent === "Open terminal" && !document.querySelector("#log").hidden && document.querySelector("#panel").classList.contains("has-more")')
            await asyncio.sleep(2)                      # past the moment kept for the reply to start being read
            assert await ev('document.querySelector("#orb-stage").getBoundingClientRect().width') == 164     # the orb makes room
            shapes = await ev('window.__told.filter(m => m.type === "shape").pop().shapes')
            assert len(shapes) == 6 and shapes[0][2:] == [164, 164, 82], shapes       # orb, words, answer, three buttons
            box = await ev('(() => { const r = document.querySelector("#log").getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; })()')
            assert [round(v) for v in shapes[2][:4]] == [round(v) for v in box], (shapes[2], box)
            shot = await call('Page.captureScreenshot', {'format': 'png'})
            Path('/tmp/mario-layer-answer.png').write_bytes(base64.b64decode(shot['data']))
            # it follows the speaking state
            await ev('marioVoice("idle", 0); state.presence = {state: "speaking"}; true')
            await asyncio.sleep(.4)
            assert await ev('document.querySelector("#orb").dataset.state === "speaking"')
            await ev('state.presence = {state: "ready"}; true')
            # "Hey Mario" heard: the hub's session is taken over; said and then nothing, Mario steps back
            hold['state'] = 'silent'
            await ev('window.__told.length = 0; marioShown("wake"); true')
            for _ in range(40):
                if await ev('window.__told.some(m => m.type === "close")'): break
                await asyncio.sleep(.1)
            assert await ev('window.__told.some(m => m.type === "close") && document.querySelector("#log").hidden')
            hold['state'] = 'done'
            # typing instead: any letter opens the box and asks the host for the keyboard
            await ev('marioShown("quiet"); marioAttended(true); document.body.dispatchEvent(new KeyboardEvent("keydown", {key: "w", bubbles: true})); true')
            assert await ev('!document.querySelector("#panel-form").hidden && document.activeElement === document.querySelector("#panel-input") && window.__told.some(m => m.type === "keyboard")')
            await ev('document.querySelector("#panel-input").value = "what changed"; document.querySelector("#panel-form").requestSubmit(); true')
            for _ in range(40):
                if ('ask', 'what changed') in calls: break
                await asyncio.sleep(.1)
            assert ('ask', 'what changed') in calls
            await asyncio.sleep(.3)
            assert await ev('document.querySelector("#heard-text").textContent === "what changed" && document.querySelector("#panel-form").hidden')
            # teaching Mario your voice: four times the phrase, a miss says what was heard, then it is on
            assert await ev('document.querySelector("#tool-wake span").textContent') == 'Set up Hey Mario'
            await ev('document.querySelector("#tool-wake").click(); true')
            assert await ev('!document.querySelector("#train").hidden && document.querySelector("#train h3").textContent === "Teach Mario your voice"')
            await ev('document.querySelector("#train .btn.primary").click(); true')
            await asyncio.sleep(.35)
            seen = await ev('[document.querySelector("#train h3").textContent, document.querySelector(".train-note").textContent, document.querySelector("#orb").dataset.state, document.querySelector("#train").hidden]')
            assert seen[0] == 'Say “Hey Mario”' and 'Hey Maria' in seen[1] and seen[2] == 'listening', seen
            for _ in range(60):
                if await ev('document.querySelector("#train h3").textContent === "Mario knows your voice"'): break
                await asyncio.sleep(.1)
            assert await ev('document.querySelectorAll(".train-dots .got").length') == 4
            await ev('[...document.querySelectorAll("#train .btn")].find(b => b.textContent === "Done").click(); true')
            await h.push_wake()
            await asyncio.sleep(.3)
            assert await ev('document.querySelector("#train").hidden && document.querySelector("#tool-wake span").textContent === "Hey Mario" && document.querySelector("#tool-wake").dataset.state === "on"')
            # the switch turns the listener off
            await ev('document.querySelector("#tool-wake").click(); true')
            await ev('document.querySelector("#train input[role=switch]").click(); true')
            await asyncio.sleep(.4)
            assert not wake['enabled'] and await ev('document.querySelector("#tool-wake").dataset.state === "off" && !document.querySelector("#train input[role=switch]").checked')
            shot = await call('Page.captureScreenshot', {'format': 'png'})
            Path('/tmp/mario-layer.png').write_bytes(base64.b64decode(shot['data']))
            print('PASS: one screen with in-tile scrolling, rapid/wrapping/keyboard slides, the Agents board tile, account chips and sheet, '
                  'movies, sticky note, storage, the weather sky, Spotify, photos full screen, the listening picture with the words so far, '
                  'spoken request in Home; Mario over your work: the orb at the centre, the outlines its host shows, live words, answer, '
                  '"Hey Mario" hand-over and stepping back, typing instead, voice training and its switch')
            print('Screenshots: /tmp/mario-home.png /tmp/mario-layer-answer.png /tmp/mario-layer.png')
    finally:
        chrome.terminate()
        await asyncio.to_thread(chrome.wait, 10)
        await runner.cleanup()


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='mario-ui-') as tmp:
        asyncio.run(main(Path(tmp)))
