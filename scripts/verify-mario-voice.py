#!/usr/bin/env python3
"""Voice lifecycle and command routing with fake audio/processes, no real microphone or models."""
import asyncio
import json
import struct
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'services/mario-hub'))
import voice
import hub
import config
import collectors


async def main():
    silence = bytes(3200)
    speech = struct.pack('<1600h', *([1600] * 1600))
    gate = voice.Silence()
    assert not any(gate.feed(silence) for _ in range(79))
    assert gate.feed(silence)
    gate = voice.Silence()
    assert not any(gate.feed(speech) for _ in range(5))
    assert not any(gate.feed(silence) for _ in range(17))
    assert gate.feed(silence)
    events, processes = [], []
    async def presence(state, detail=''): events.append(state)
    class Proc:
        def __init__(self, recording):
            self.stdout = asyncio.StreamReader()
            if recording:
                self.stdout.feed_data(speech * 5 + silence * 18)
            self.returncode = None
            self.killed = False
        async def communicate(self, data):
            assert len(data) == 23 * 3200
            self.returncode = 0
            return json.dumps({'text': 'Add a task review the build'}).encode(), b''
        def kill(self): self.killed = True; self.returncode = -9
        async def wait(self): return self.returncode
    async def spawn(*args, **kwargs):
        p = Proc(args[0] == 'parec'); processes.append(p); return p
    v = voice.Voice(presence, lambda: {})
    v.available = lambda: True
    with patch.object(voice.asyncio, 'create_subprocess_exec', spawn):
        start = await v.start()
        assert (await v.start()).get('error')
        assert (await v.command('cancel', 'wrong-id')).get('error')
        await v.task
        assert (await v.command('status', start['id']))['text'] == 'Add a task review the build'
        assert processes[0].killed and v.proc is None
        assert events == ['listening', 'thinking', 'ready']
        # A disappeared page cancels before it can transcribe or act.
        await v.start(); v.touched = time.monotonic() - 10
        await v.task
        assert v.state == 'error' and 'disconnected' in v.error
        # Cancellation kills the recorder and clears dictated content.
        await v.start()
        await v.command('cancel', v.id)
        assert v.state == 'cancelled' and v.text == '' and v.proc is None
    with tempfile.TemporaryDirectory() as tmp:
        h = hub.Hub(dict(config.DEFAULTS, repos=[], thinking_space=Path(tmp)), schedule={})
        h.notes_file = Path(tmp) / 'notes.md'
        with patch.object(collectors, 'NOTES_DIR', Path(tmp) / 'tasks'):
            assert (await h.ask('Mario, add a task review the build'))['ok']
            assert 'review the build' in (Path(tmp) / 'tasks/General/Inbox.md').read_text()
            assert (await h.ask('Take a note: Try the new timer'))['ok']
            assert 'Try the new timer' in h.notes_file.read_text()
            calls = []
            h.action = lambda *args: calls.append(args) or {'ok': True}
            assert (await h.ask('Open terminal.'))['ok']
            assert calls == [('launch', 'terminal')]
            assert await h.direct_command('Open terminal; delete files') is None
            assert await h.direct_command('Can you add a task?') is None
    print('PASS: silence/no-speech boundaries, busy/ownership guards, disconnect, cancellation, process cleanup, task/note writes and bounded launch commands')


if __name__ == '__main__':
    asyncio.run(main())
