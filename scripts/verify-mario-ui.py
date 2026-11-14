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


async def main(tmp):
    cfg = dict(config.DEFAULTS, repos=[], thinking_space=tmp)
    h = hub.Hub(cfg, schedule={})
    h.notes_file = tmp / 'notes.md'
    now = time.time()
    h.cards = {k: {'data': v, 'at': now} for k, v in {
        'mail': {'unread': 8, 'items': [{'from': 'Project team', 'subject': 'Review the build before Friday', 'when': now} for _ in range(5)]},
        'tasks': {'count': 12, 'open': [{'text': f'Review task {i}', 'path': '/fixture/Inbox.md', 'line': i, 'project': 'Desktop'} for i in range(12)]},
        'builds': {'repos': [{'name': f'Project {i}', 'path': str(tmp), 'branch': 'master', 'subject': 'Latest useful change', 'when': now, 'dirty': 2} for i in range(3)]},
        'downloads': {'files': [{'name': f'Notes {i}.pdf', 'path': f'/fixture/{i}.pdf', 'size': 12345} for i in range(3)]},
        'recent': {'files': []}, 'calendar': {'events': []},
        'weather': {'temp': 25, 'feels': 26, 'place': 'Bengaluru', 'sky': 'Clear', 'hours': [], 'high': 29, 'low': 20},
        'news': {'items': [{'title': f'Research update {i}', 'source': 'Science', 'link': f'https://example.org/{i}', 'when': now} for i in range(3)]},
    }.items()}
    calls = []
    h.action = lambda aid, arg: calls.append((aid, arg)) or {'ok': True}
    async def fake_ask(text):
        calls.append(('ask', text))
        return {'answer': 'Done from voice.', 'via': 'Mario'}
    h.ask = fake_ask
    async def quiet(*args): pass
    h.speak = quiet
    async def start(): return {'id': 'fixture', 'state': 'listening'}
    async def command(action, sid):
        return {'state': 'done', 'text': 'Open terminal'} if action == 'status' else {'state': 'cancelled'}
    h.voice.start, h.voice.command = start, command
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
            assert await ev('document.querySelectorAll(".card").length') == 15
            assert await ev('!document.querySelector("#c-apps")')
            await ev('Object.values(LIVE).forEach(t => t.paused=true); true')
            assert await ev('LIVE.projects.faces.length') == 4
            await ev('LIVE.projects.i=0; document.querySelector("#c-projects [aria-label=\\"Next slide\\"]").click(); true')
            assert await ev('LIVE.projects.i === 1 && LIVE.projects.paused')
            await ev('for(let i=0;i<9;i++) turn("projects",1,true); true')
            assert await ev('LIVE.projects.i === 2 && document.querySelector("#c-projects .face").textContent.includes("Project 2")')
            await ev('document.querySelector("#c-projects").dispatchEvent(new KeyboardEvent("keydown",{key:"ArrowLeft",bubbles:true})); true')
            assert await ev('LIVE.projects.i') == 1
            await ev('document.querySelector("#c-downloads .face button").click(); true')
            await asyncio.sleep(.1)
            assert ('open_file', '/fixture/0.pdf') in calls
            assert await ev('document.querySelectorAll("#c-tasks .tick").length') == 12
            await ev('document.querySelector("#c-tasks input").value="keep this draft"; render.tasks(); true')
            assert await ev('document.querySelector("#c-tasks input").value') == 'keep this draft'
            await ev('focusAction("reset"); focusAction("toggle"); true')
            assert await ev('focusState.end > Date.now() && document.querySelector("#focus-start").textContent==="Pause"')
            await ev('focusState.end=Date.now()-1; updateFocus(); true')
            assert await ev('document.querySelector("#focus-message").textContent.includes("complete")')
            await ev('toggleVoice()')
            assert ('ask', 'Open terminal') in calls
            assert await ev('document.querySelector("#answer").textContent.includes("Done from voice")')
            await ev('cancelVoice(); document.querySelector("#answer").hidden=true; true')
            # Controls must be visible inside their cards at the target laptop size.
            clipped = await ev('''[...document.querySelectorAll('.tile-nav button, #focus-start, #c-tasks .add')].filter(n=>!n.closest('[hidden]')).filter(n=>{let a=n.getBoundingClientRect(),b=n.closest('.card').getBoundingClientRect();return a.bottom>b.bottom || a.right>b.right}).map(n=>n.closest('.card').id)''')
            assert not clipped, clipped
            shot = await call('Page.captureScreenshot', {'format': 'png'})
            Path('/tmp/mario-home.png').write_bytes(base64.b64decode(shot['data']))
            await call('Page.navigate', {'url': f'http://127.0.0.1:{port}/panel'})
            for _ in range(60):
                if await ev('document.body.classList.contains("is-panel")'): break
                await asyncio.sleep(.1)
            await ev('toggleVoice()')
            assert await ev('document.querySelector("#log").textContent.includes("Done from voice")')
            print('PASS: layout, rapid/wrapping/keyboard slides, downloads, all tasks, draft preservation, focus deadline, spoken request in Home and panel')
            print('Screenshot: /tmp/mario-home.png')
    finally:
        chrome.terminate()
        await asyncio.to_thread(chrome.wait, 10)
        await runner.cleanup()


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='mario-ui-') as tmp:
        asyncio.run(main(Path(tmp)))
