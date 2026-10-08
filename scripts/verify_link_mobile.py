"""Independent-session checks using two real private displays and HTTP routes.

Only disposable fixture apps run; no application or input on the physical
laptop is touched. Called by the existing Link verification entry point.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch


def checks(check):
    from mobile_launch import arguments, independent, snap
    from mobile_session import ExecutionTarget, viewport
    check(arguments('app --label "two words" %U %%', 'Test', '/app.desktop', files=['/tmp/a b']) ==
          ['app', '--label', 'two words', '/tmp/a b', '%'], 'mobile: desktop Exec expands argv without a shell')
    for command in ('app --uri=%u', 'app %unknown'):
        try:
            arguments(command, '', '')
            check(False, 'mobile: malformed Exec rejected')
        except ValueError:
            check(True, 'mobile: malformed Exec rejected')
    with tempfile.TemporaryDirectory() as tmp:
        for ident, executable, expected in (('firefox.desktop', 'firefox', '--no-remote'),
                ('google-chrome.desktop', 'google-chrome', '--user-data-dir='), ('code.desktop', 'code', '--user-data-dir'),
                ('libreoffice-writer.desktop', 'libreoffice', '-env:UserInstallation=')):
            argv = independent([executable], ident, tmp)
            check(any(v.startswith(expected) for v in argv), 'mobile: independent profile adapter ' + ident)
        check('--password-store=basic' in independent(['google-chrome'], 'google-chrome.desktop', tmp)
              and '--password-store=basic' in independent(['antigravity-ide'], 'antigravity.desktop', tmp),
              'mobile: browsers and editors skip the fresh keyring prompt')
    check(snap(['/snap/bin/firefox']) == ('firefox', 'firefox') and snap(['/snap/bin/foo.bar']) == ('foo', 'bar')
          and snap([sys.executable]) is None, 'mobile: snap commands are recognised for their own adapter')
    check(viewport([100, 9999]) == (320, 3840), 'mobile: viewport bounded inside framebuffer')
    try:
        ExecutionTarget('phone')
        check(False, 'mobile: phone target needs a session')
    except ValueError:
        check(True, 'mobile: phone target needs a session')
    asyncio.run(real_checks(check))


async def real_checks(check):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    import app_workspace
    import mobile_session
    import machine
    import screen
    with tempfile.TemporaryDirectory(prefix='link-mobile-check-') as tmp:
        root = Path(tmp)
        data = root / 'installed'
        (data / 'applications').mkdir(parents=True)
        fixture = root / 'fixture.py'
        fixture.write_text('''import os, tkinter as tk
from pathlib import Path
root=tk.Tk(className="MobileFixture")
root.title("Mobile fixture")
root.geometry("600x500")
value=tk.StringVar()
entry=tk.Entry(root,textvariable=value)
entry.pack(fill="x")
output=Path(os.environ["ADAPTIVE_MOBILE_ROOT"])/"typed.txt"
value.trace_add("write",lambda *args:output.write_text(value.get()))
entry.focus_force()
def dialog():
 win=tk.Toplevel(root); win.title("Save fixture"); win.transient(root)
 tk.Button(win,text="Save",command=win.destroy).pack()
root.bind("<Control-d>",lambda event:dialog())
root.mainloop()
''')
        (data / 'applications/mobile-fixture.desktop').write_text(
            '[Desktop Entry]\nType=Application\nName=Mobile fixture\nExec=' + sys.executable + ' ' + str(fixture) + '\nStartupWMClass=MobileFixture\n')
        (data / 'applications/mobile-broken.desktop').write_text(
            '[Desktop Entry]\nType=Application\nName=Mobile broken\nExec=false\n')
        phones = [{'fingerprint': 'one'}, {'fingerprint': 'two'}]
        permission = {'allow_input': True, 'allow_exec': True, 'allow_files': True}
        link = SimpleNamespace(link_dir=root / 'link', phones=phones, relay=None,
            _allowed=lambda key: permission.get(key, False), audit=SimpleNamespace(write=lambda *args: None),
            _risk=lambda *args: '', _track=lambda ws: None)
        link.workspace = app_workspace.Workspace(link)
        mobile = mobile_session.MobileDesktop(link)
        async def catalog():
            return [{'id': 'mobile-fixture.desktop', 'name': 'Mobile fixture', 'wm_class': 'MobileFixture', 'executable': sys.executable},
                    {'id': 'mobile-broken.desktop', 'name': 'Mobile broken', 'wm_class': '', 'executable': 'false'}]
        mobile.catalog = catalog
        @web.middleware
        async def paired(request, handler):
            request['phone'] = {'fingerprint': request.headers.get('X-Test-Phone', 'one')}
            request['peer'] = 'test'
            return await handler(request)
        app = web.Application(middlewares=[paired])
        mobile.routes(app.router)
        client = TestClient(TestServer(app))
        await client.start_server()
        before = dict(os.environ)
        try:
            with patch.dict(os.environ, {'XDG_DATA_DIRS': str(data) + ':/usr/share', 'PULSE_SERVER': 'unix:/nonexistent/link-test-audio',
                                         'VSCODE_IPC_HOOK': '/nonexistent/vscode.sock', 'ELECTRON_RUN_AS_NODE': '1'}):
                a = await (await client.post('/v1/mobile/sessions', json={})).json()
                b = await (await client.post('/v1/mobile/sessions', json={}, headers={'X-Test-Phone': 'two'})).json()
            check(a.get('ok') and b.get('ok'), 'mobile: two paired phones create private sessions')
            first, second = mobile.sessions[a['session']['id']], mobile.sessions[b['session']['id']]
            check(first.env['DISPLAY'] != second.env['DISPLAY'] and first.env['DBUS_SESSION_BUS_ADDRESS'] != second.env['DBUS_SESSION_BUS_ADDRESS'],
                  'mobile: each phone has a distinct X display and D-Bus')
            check(dict(os.environ) == before and first.env['HOME'] == before.get('HOME'), 'mobile: daemon environment unchanged and files share HOME')
            check(first.env['XDG_CONFIG_HOME'] != second.env['XDG_CONFIG_HOME'], 'mobile: persistent profiles separated by phone')
            check('VSCODE_IPC_HOOK' not in first.env and 'ELECTRON_RUN_AS_NODE' not in first.env,
                  'mobile: the launcher\'s editor hand-off is not inherited by phone apps')
            response = await client.get('/v1/mobile/apps?session=' + first.id, headers={'X-Test-Phone': 'two'})
            check(response.status == 403, 'mobile: foreign session inventory denied')
            response = await client.get('/v1/mobile/screen?session=' + first.id, headers={'X-Test-Phone': 'two'})
            check(response.status == 403, 'mobile: foreign session capture denied before websocket upgrade')
            for s, phone in ((first, 'one'), (second, 'two')):
                opened = await (await client.post('/v1/mobile/apps', json={'session': s.id, 'app_id': 'mobile-fixture.desktop'}, headers={'X-Test-Phone': phone})).json()
                for _ in range(50):
                    if s.selected: break
                    await asyncio.sleep(.2)
                    await s.refresh(await catalog())
                if not s.selected:
                    print('fixture root', await s.run('xprop', '-root', '_NET_CLIENT_LIST_STACKING', '_NET_ACTIVE_WINDOW'), 'parsed', await asyncio.to_thread(machine.windows, s.env), flush=True)
                check(opened.get('ok') and s.selected != 0, 'mobile: launch and identify actual private application for ' + phone)
            listed = await (await client.get('/v1/mobile/apps')).json()
            check(mobile.compatibility().get('mobile-fixture.desktop', {}).get('result') == 'works'
                  and any(a.get('compatibility') == 'works' for a in listed['apps'] if a['id'] == 'mobile-fixture.desktop'),
                  'mobile: an app that opened is recorded as working, and the drawer is told')
            await client.post('/v1/mobile/apps', json={'session': second.id, 'app_id': 'mobile-broken.desktop'}, headers={'X-Test-Phone': 'two'})
            for _ in range(20):
                await second.refresh(await catalog())
                if second.apps['mobile-broken.desktop']['state'] != 'starting':
                    break
                await asyncio.sleep(.2)
            check(second.apps['mobile-broken.desktop']['state'] == 'failed'
                  and mobile.compatibility().get('mobile-broken.desktop', {}).get('result') == 'failed',
                  'mobile: an app that exits with an error is reported at once, not after the window wait')
            await second.focus(second.windows[0]['id'])
            active_before = await second.run('xdotool', 'getactivewindow')
            socket = await client.ws_connect('/v1/mobile/input?session=' + first.id)
            await socket.send_json({'t': 'text', 's': 'phone-one-only'})
            await asyncio.sleep(.35)
            check((first.root / 'typed.txt').read_text() == 'phone-one-only' and not (second.root / 'typed.txt').exists(),
                  'mobile: live input reaches only the selected private display')
            check(await second.run('xdotool', 'getactivewindow') == active_before, 'mobile: another session keeps keyboard focus')
            permission['allow_input'] = False
            await asyncio.sleep(.6)
            await socket.send_json({'t': 'text', 's': 'forbidden'})
            await asyncio.sleep(.2)
            check((first.root / 'typed.txt').read_text() == 'phone-one-only', 'mobile: permission revocation stops live input')
            permission['allow_input'] = True
            await socket.close()
            capture = screen.Capture(mobile_session.FRAMEBUFFER, region=(0, 0, *first.canvas), display=first.env['DISPLAY'], env=first.env)
            try:
                await asyncio.to_thread(capture.start)
                frame = await asyncio.to_thread(capture.next_frame, 5)
                check(bool(frame and frame.startswith(b'\xff\xd8')), 'mobile: private display yields an actual JPEG frame')
            finally:
                await asyncio.to_thread(capture.stop)
            old_pid = first.apps['mobile-fixture.desktop']['pids'][0]
            for size in ([1100, 700], [500, 800]):
                reply = await (await client.post('/v1/mobile/sessions', json={'operation': 'resize', 'session': first.id, 'viewport': size})).json()
                check(reply.get('ok') and first.apps['mobile-fixture.desktop']['pids'][0] == old_pid, 'mobile: viewport resize keeps application process')
            await asyncio.sleep(.3)
            ok, geometry = await first.run('xdotool', 'getwindowgeometry', '--shell', str(first.selected))
            width = int(dict(line.split('=') for line in geometry.splitlines()).get('WIDTH', 0))
            check(ok and 0 < width <= 500, f'mobile: the app window is fitted to the phone viewport ({width} px wide)')
            await first.input.send({'t': 'key', 'k': 'd', 'm': ['ctrl']})
            await asyncio.sleep(.2)
            await first.refresh(await catalog())
            check(any(w['parent'] == first.selected for w in first.windows), 'mobile: application dialog stays inside private session')
            ident = 'macro-order'
            reply = await (await client.post('/v1/mobile/runs', json={'session': first.id, 'request_id': ident,
                'steps': [{'kind': 'command', 'value': 'printf one > order.txt', 'cwd': str(root)},
                          {'kind': 'delay', 'value': '3'}, {'kind': 'command', 'value': 'printf two >> order.txt', 'cwd': str(root)}]})).json()
            check(reply.get('ok'), 'mobile: macro accepted with explicit session')
            await asyncio.sleep(.3)
            await client.post('/v1/mobile/runs', json={'operation': 'cancel'})
            check((root / 'order.txt').read_text() == 'one' and mobile.runs[ident]['state'] == 'cancelled', 'mobile: cancelling skips remaining macro steps')
            await client.post('/v1/mobile/runs', json={'session': first.id, 'request_id': ident, 'steps': [{'kind': 'command', 'value': 'false'}]})
            check(mobile.runs[ident]['state'] == 'cancelled', 'mobile: request ID replay never reexecutes cancelled command')
            reconnected = await (await client.post('/v1/mobile/sessions', json={})).json()
            check(reconnected['session']['id'] == first.id and first.alive(), 'mobile: reconnect resumes the same apps and display')
            reply = await (await client.post('/v1/mobile/sessions', json={'operation': 'force-end', 'session': first.id})).json()
            check(reply.get('confirm') and first.alive(), 'mobile: forced termination requires explicit confirmation')
            await client.post('/v1/mobile/sessions', json={'operation': 'force-end', 'session': first.id, 'confirm': True})
            check(first.id not in mobile.sessions and second.alive(), 'mobile: ending one phone leaves the other session running')
        finally:
            await mobile.close()
            await client.close()


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'services/adaptive-link'))
    def check(ok, message):
        print(('PASS ' if ok else 'FAIL ') + message, flush=True)
        if not ok:
            raise AssertionError(message)
    checks(check)
