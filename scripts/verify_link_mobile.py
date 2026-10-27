"""Independent-session checks using two real private displays and HTTP routes.

Only disposable fixture apps run; no application or input on the physical
laptop is touched. Called by the existing Link verification entry point.
"""
import asyncio
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch


def checks(check):
    from mobile_launch import arguments, confined, holders, independent, snap
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
        tmp = str(Path(tmp) / 'shared')
        shared = {'ADAPTIVE_PHONE_PROFILE': 'laptop', 'ADAPTIVE_PHONE_SCALE': '2', 'ADAPTIVE_PHONE_SHORT': '824'}
        with patch('phone_form.browser_version', lambda argv, fallback: 141):
            chrome = independent(['google-chrome'], 'google-chrome.desktop', tmp, dict(shared))
        editor = independent(['antigravity-ide'], 'antigravity.desktop', tmp, dict(shared))
        firefox_env = dict(shared)
        fox = independent(['firefox'], 'firefox.desktop', tmp, firefox_env)
        office = independent(['libreoffice'], 'libreoffice-writer.desktop', tmp, dict(shared))
        check(not any(a.startswith(('--user-data-dir', '--profile', '-env:UserInstallation')) for a in chrome + editor + fox + office)
              and '--password-store=gnome-libsecret' in chrome and '--password-store=gnome-libsecret' in editor
              and not Path(tmp).exists() and firefox_env['GDK_SCALE'] == '1',
              'one device: browsers, editors and office open with the laptop\'s own profile, which is never written to')
        own = dict(shared, ADAPTIVE_PHONE_PROFILE='phone')
        independent(['code'], 'code.desktop', tmp, own)
        check(own['XDG_CONFIG_HOME'] == str(Path(tmp) / 'config'), 'one device: a profile of the phone\'s own has settings of its own')
    with tempfile.TemporaryDirectory() as tmp:
        proc, folder = Path(tmp) / 'proc', Path(tmp) / 'opt/editor'
        folder.mkdir(parents=True)
        def process(pid, exe, *env):
            (proc / str(pid)).mkdir(parents=True)
            os.symlink(exe, proc / str(pid) / 'exe')
            (proc / str(pid) / 'environ').write_bytes(b'\0'.join(item.encode() for item in env) + b'\0')
        process(10, folder / 'editor', 'HOME=/h')
        process(11, folder / 'editor', 'ADAPTIVE_MOBILE_ROOT=/phone/one')
        process(12, folder / 'editor', 'ADAPTIVE_MOBILE_ROOT=/phone/two')
        process(13, folder / 'chrome_crashpad_handler', 'HOME=/h')
        process(14, Path(tmp) / 'elsewhere/editor', 'HOME=/h')
        found = holders([str(folder / 'editor')], 'editor.desktop', '/phone/one', proc=str(proc))
        check(found == {'laptop': [10], 'phone': [12]},
              f'one device: the copies holding an app\'s profile are found on the laptop and other phones ({found})')
    check(snap(['/snap/bin/firefox']) == ('firefox', 'firefox') and snap(['/snap/bin/foo.bar']) == ('foo', 'bar')
          and snap([sys.executable]) is None, 'mobile: snap commands are recognised for their own adapter')
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / 'auth').write_bytes(b'cookie')
        env = {'ADAPTIVE_PHONE_PROFILE': 'laptop', 'XAUTHORITY': str(Path(tmp) / 'auth')}
        with patch.object(Path, 'home', lambda: Path(tmp)), patch('shutil.which', lambda name: None):
            argv = confined(['/snap/bin/firefox'], 'firefox_firefox.desktop', '/phone/one', env)
        check(argv[0] == '/snap/bin/firefox' and Path(env['XAUTHORITY']).read_bytes() == b'cookie'
              and 'XDG_CONFIG_HOME' not in env, 'one device: a snap opens with the laptop\'s profile and the session\'s X authority')
    from mobile_session import MobileSession
    session = MobileSession('/home/someone/.config/adaptive-desktop/link/mobile', 'a' * 64)
    # The longest socket an app has asked for there: Antigravity's single-instance one.
    check(len(str(session.runtime / 'vscode-aa78601b-1.10-main.sock').encode()) <= 107,
          f'mobile: sockets fit in the session\'s runtime folder ({session.runtime})')
    check(viewport([100, 9999]) == (320, 3840), 'mobile: viewport bounded inside framebuffer')
    try:
        ExecutionTarget('phone')
        check(False, 'mobile: phone target needs a session')
    except ValueError:
        check(True, 'mobile: phone target needs a session')
    form_checks(check)
    asyncio.run(real_checks(check))


def form_checks(check):
    import phone_form as form
    pixel = form.plan({'dp': [412, 915], 'density': 2.625})
    check(pixel['scale'] == 2 and pixel['size'] == [824, 1830], 'form: a phone is drawn at its dp size, twice over by default')
    check(form.plan({'dp': [412, 915], 'density': 1.5, 'sharpness': 3})['scale'] == 2
          and form.plan({'dp': [1600, 1000], 'density': 3, 'sharpness': 3})['scale'] == 2,
          'form: sharpness is capped by the phone\'s density and the framebuffer')
    phone, compact = form.environment(2, 'phone'), form.environment(2, 'compact')
    check(phone['GDK_SCALE'] == '2' and phone['QT_SCALE_FACTOR'] == '2' and phone['QT_QUICK_CONTROLS_MOBILE'] == '1'
          and compact['GDK_SCALE'] == '1' and compact['GDK_DPI_SCALE'] == '1.5', 'form: toolkits are told the layout\'s scale')
    check(form.factor(2, 'phone', 824, 520) == 1.58 and form.factor(2, 'phone', 1800, 520) == 2 and form.factor(2, 'desktop', 824, 520) == 1.2,
          'form: a browser is drawn as large as its narrowest window allows')
    check(form.kind([], 'firefox_firefox.desktop') == 'firefox' and form.kind([], 'google-chrome.desktop') == 'browser'
          and form.kind(['code'], 'code.desktop') == 'electron' and form.kind([sys.executable], 'x.desktop') == '',
          'form: browsers and Electron apps are recognised')
    env = {'ADAPTIVE_PHONE_SCALE': '2', 'ADAPTIVE_PHONE_MODE': 'phone', 'ADAPTIVE_PHONE_SHORT': '824'}
    with patch.object(form, 'browser_version', lambda argv, fallback: 141):
        chrome = form.adapt(['google-chrome'], 'google-chrome.desktop', '/nonexistent', dict(env))
        desk = form.adapt(['google-chrome'], 'google-chrome.desktop', '/nonexistent', dict(env, ADAPTIVE_PHONE_MODE='desktop'))
    check('--force-device-scale-factor=1.58' in chrome and any('Android' in a and 'Chrome/141' in a for a in chrome)
          and not any(a.startswith('--user-agent') for a in desk), 'form: Chrome gets a phone\'s user agent only in the phone layouts')
    with tempfile.TemporaryDirectory() as tmp:
        firefox_env = dict(env)
        form.adapt(['firefox'], 'firefox_firefox.desktop', tmp, firefox_env)
        prefs = (Path(tmp) / 'user.js').read_text()
        check('"dom.meta-viewport.enabled", true' in prefs and 'Android' in prefs and firefox_env['GDK_SCALE'] == '1'
              and 'min-width: 0' in (Path(tmp) / 'chrome/userChrome.css').read_text(), 'form: Firefox lays pages out as on Android')
        (Path(tmp) / 'user.js').write_text('user_pref("mine", 1);')
        form.adapt(['firefox'], 'firefox_firefox.desktop', tmp, dict(env))
        check((Path(tmp) / 'user.js').read_text() == 'user_pref("mine", 1);', 'form: an owner\'s own user.js is left alone')
        choices = form.Choices(Path(tmp) / 'form.json')
        choices.learn('a.desktop', 'compact')
        check(choices.mode('a.desktop') == 'compact' and not choices.chosen('a.desktop'), 'form: a learned layout applies')
        choices.set('a.desktop', 'phone')
        check(choices.mode('a.desktop') == 'phone' and choices.chosen('a.desktop'), 'form: the owner\'s choice beats a learned layout')
        check(choices.profile('a.desktop') == 'laptop', 'one device: apps share the laptop\'s profile by default')
        choices.set_profile('a.desktop', 'phone')
        check(choices.profile('a.desktop') == 'phone' and choices.mode('a.desktop') == 'phone', 'one device: a profile of the phone\'s own is chosen per app')
        try:
            choices.set_profile('a.desktop', 'elsewhere')
            check(False, 'one device: only the two profiles exist')
        except ValueError:
            check(True, 'one device: only the two profiles exist')
        laptop = Path(tmp) / 'adaptive'
        laptop.write_text('# the laptop session\nuser-db:adaptive\nsystem-db:local\n')
        check(form.dconf_profile('adaptive_phone_x', str(laptop)) == 'user-db:adaptive_phone_x\nuser-db:adaptive\nsystem-db:local\n',
              'one device: the phone writes settings of its own over the laptop\'s, which it reads')
        form.prepare(tmp, 2)
        check('gtk-decoration-layout=menu:' in (Path(tmp) / 'gtk-4.0/settings.ini').read_text(), 'form: GTK apps have no window buttons')


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
        phones = [{'fingerprint': 'one'}, {'fingerprint': 'two'}, {'fingerprint': 'three'}]
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
            # The laptop's settings folder, for this check: its dconf databases are files there.
            laptop_config = root / 'laptop-config'
            with patch.dict(os.environ, {'XDG_DATA_DIRS': str(data) + ':/usr/share', 'PULSE_SERVER': 'unix:/nonexistent/link-test-audio',
                                         'VSCODE_IPC_HOOK': '/nonexistent/vscode.sock', 'ELECTRON_RUN_AS_NODE': '1',
                                         'XDG_CONFIG_HOME': str(laptop_config), 'DCONF_PROFILE': ''}):
                a = await (await client.post('/v1/mobile/sessions', json={})).json()
                b = await (await client.post('/v1/mobile/sessions', json={}, headers={'X-Test-Phone': 'two'})).json()
            check(a.get('ok') and b.get('ok'), 'mobile: two paired phones create private sessions')
            first, second = mobile.sessions[a['session']['id']], mobile.sessions[b['session']['id']]
            check(first.env['DISPLAY'] != second.env['DISPLAY'] and first.env['DBUS_SESSION_BUS_ADDRESS'] != second.env['DBUS_SESSION_BUS_ADDRESS'],
                  'mobile: each phone has a distinct X display and D-Bus')
            check(dict(os.environ) == before and first.env['HOME'] == before.get('HOME'), 'mobile: daemon environment unchanged and files share HOME')
            check(first.env.get('XDG_CONFIG_HOME') == str(laptop_config) and first.env['DCONF_PROFILE'] != second.env['DCONF_PROFILE']
                  and Path(first.env['DCONF_PROFILE']).read_text().startswith('user-db:adaptive_phone_')
                  and first.env['XDG_CONFIG_DIRS'].startswith(str(first.root / 'xdg') + ':'),
                  'one device: phones use the laptop\'s folders, with settings changes of their own')
            written = sorted(p.name for p in (laptop_config / 'dconf').glob('*'))
            check(len([n for n in written if n.startswith('adaptive_phone_')]) == 2 and not any(n in written for n in ('user', 'adaptive')),
                  f'one device: the phone\'s settings go to its own database, never the laptop\'s ({written})')
            if before.get('DBUS_SESSION_BUS_ADDRESS'):
                _, owner = await first.run('dbus-send', '--session', '--print-reply', '--dest=org.freedesktop.DBus', '/org/freedesktop/DBus',
                                           'org.freedesktop.DBus.NameHasOwner', 'string:org.freedesktop.secrets')
                check(first.public()['keyring'] and 'boolean true' in owner, 'one device: the laptop\'s keyring answers on the phone\'s bus')
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
            with patch.dict(os.environ, {'XDG_DATA_DIRS': str(data) + ':/usr/share', 'PULSE_SERVER': 'unix:/nonexistent/link-test-audio',
                                         'XDG_CONFIG_HOME': str(laptop_config), 'DCONF_PROFILE': ''}):
                await form_session(check, client, mobile, catalog)
            reconnected = await (await client.post('/v1/mobile/sessions', json={})).json()
            check(reconnected['session']['id'] == first.id and first.alive(), 'mobile: reconnect resumes the same apps and display')
            reply = await (await client.post('/v1/mobile/sessions', json={'operation': 'force-end', 'session': first.id})).json()
            check(reply.get('confirm') and first.alive(), 'mobile: forced termination requires explicit confirmation')
            await client.post('/v1/mobile/sessions', json={'operation': 'force-end', 'session': first.id, 'confirm': True})
            check(first.id not in mobile.sessions and second.alive(), 'mobile: ending one phone leaves the other session running')
        finally:
            await mobile.close()
            await client.close()


async def form_session(check, client, mobile, catalog):
    """A phone that says what its screen is gets the phone form factor."""
    three = {'X-Test-Phone': 'three'}
    opened = await (await client.post('/v1/mobile/sessions', headers=three,
        json={'phone': {'dp': [300, 500], 'density': 2.5}})).json()
    s = mobile.sessions[opened['session']['id']]
    check(opened.get('ok') and opened['session']['scale'] == 2 and opened['session']['viewport'] == [600, 1000],
          'form: the session display is the phone\'s dp size times its scale')
    async def launched():
        await client.post('/v1/mobile/apps', headers=three, json={'session': s.id, 'app_id': 'mobile-fixture.desktop'})
        for _ in range(50):
            await s.refresh(await catalog())
            if s.selected:
                break
            await asyncio.sleep(.2)
        pid = s.apps['mobile-fixture.desktop']['pids'][-1]
        return dict(item.split('=', 1) for item in Path(f'/proc/{pid}/environ').read_text().split('\0') if '=' in item)
    import mobile_session
    sleeper = await asyncio.create_subprocess_exec('sleep', '1')
    def holding(app_id, root, profile='laptop'):
        alive = profile == 'laptop' and Path(f'/proc/{sleeper.pid}').exists()
        return {'laptop': [sleeper.pid] if alive else [], 'phone': []}
    with patch.object(mobile_session.mobile_launch, 'holding', holding), patch.object(mobile_session.machine, 'windows', lambda env=None: []):
        held = await (await client.post('/v1/mobile/apps', headers=three, json={'session': s.id, 'app_id': 'mobile-fixture.desktop'})).json()
        check(held.get('held', {}).get('where') == 'laptop' and 'mobile-fixture.desktop' not in s.apps,
              'one device: an app open on the laptop is not opened a second time')
        taken = await (await client.post('/v1/mobile/apps', headers=three, json={'session': s.id, 'app_id': 'mobile-fixture.desktop', 'take': True})).json()
        check(taken.get('ok') and not Path(f'/proc/{sleeper.pid}').exists() and 'mobile-fixture.desktop' in s.apps,
              'one device: moving it here waits for the laptop\'s copy to close, then opens it on the phone')
    env = await launched()
    check(env.get('ADAPTIVE_PHONE_PROFILE') == 'laptop', 'one device: the app is started with the laptop\'s profile')
    check(env.get('GDK_SCALE') == '2' and env.get('QT_SCALE_FACTOR') == '2' and env.get('ADAPTIVE_PHONE_MODE') == 'phone',
          'form: an app in the phone session is started at the phone\'s scale')
    await asyncio.sleep(.4)
    await s.refresh(await catalog())
    ok, geometry = await s.run('xdotool', 'getwindowgeometry', '--shell', str(s.selected))
    values = dict(line.split('=') for line in geometry.splitlines())
    _, hints = await s.run('xprop', '-id', str(s.selected), '_MOTIF_WM_HINTS')
    check(ok and values.get('X') == '0' and values.get('Y') == '0' and values.get('WIDTH') == '600' and '0x2, 0x0, 0x0' in hints,
          f'form: the app fills the phone screen with no window frame ({values.get("X")},{values.get("Y")} {values.get("WIDTH")})')
    reply = await (await client.post('/v1/mobile/apps', headers=three, json={'session': s.id, 'operation': 'layout',
        'app_id': 'mobile-fixture.desktop', 'layout': 'desktop'})).json()
    check(reply.get('ok') and reply.get('running') and reply['session']['layouts'].get('mobile-fixture.desktop') == 'desktop',
          'form: a layout is chosen per app and applies at its next start')
    for w in list(s.windows):
        await s.run('xdotool', 'windowkill', str(w['id']))
    await asyncio.sleep(.5)
    env = await launched()
    check(env.get('GDK_SCALE') == '1' and env.get('ADAPTIVE_PHONE_MODE') == 'desktop', 'form: the desktop layout starts the app at desktop scale')
    reply = await (await client.post('/v1/mobile/apps', headers=three, json={'session': s.id, 'operation': 'profile',
        'app_id': 'mobile-fixture.desktop', 'profile': 'phone'})).json()
    check(reply.get('ok') and reply['session']['profiles'].get('mobile-fixture.desktop') == 'phone', 'one device: a profile of the phone\'s own is kept per app')
    opened_on_laptop = []
    with patch.object(mobile_session.desktop, 'launch', lambda app_id: opened_on_laptop.append(app_id) or True), \
            patch.object(mobile_session.mobile_launch, 'mine', lambda app_id, root: []):
        moved = await (await client.post('/v1/mobile/apps', headers=three, json={'session': s.id, 'operation': 'to-laptop',
            'app_id': 'mobile-fixture.desktop'})).json()
    check(moved.get('moved') == 'laptop' and opened_on_laptop == ['mobile-fixture.desktop']
          and not any(w['app_id'] == 'mobile-fixture.desktop' for w in s.windows),
          'one device: moving an app to the laptop closes it on the phone, then opens it there')
    reply = await (await client.post('/v1/mobile/sessions', headers=three, json={'operation': 'resize', 'session': s.id,
        'phone': {'dp': [500, 300], 'density': 2.5}})).json()
    check(reply.get('ok') and reply['session']['viewport'] == [1000, 600], 'form: turning the phone turns the display')
    await client.post('/v1/mobile/sessions', headers=three, json={'operation': 'force-end', 'session': s.id, 'confirm': True})


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'services/adaptive-link'))
    def check(ok, message):
        print(('PASS ' if ok else 'FAIL ') + message, flush=True)
        if not ok:
            raise AssertionError(message)
    checks(check)
