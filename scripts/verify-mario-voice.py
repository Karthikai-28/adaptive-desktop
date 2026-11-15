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


class Frames:
    """The worker's stdin: reads the frames it is sent and answers the way voice_worker.py would."""
    def __init__(self, proc):
        self.proc, self.buffer, self.seen = proc, b'', []

    def write(self, data):
        self.buffer += data
        while len(self.buffer) >= 5 and len(self.buffer) >= 5 + struct.unpack('>I', self.buffer[1:5])[0]:
            kind, size = self.buffer[:1], struct.unpack('>I', self.buffer[1:5])[0]
            body, self.buffer = self.buffer[5:5 + size], self.buffer[5 + size:]
            self.seen.append((kind, len(body)))
            reply = self.proc.replies.get(kind)
            if reply:
                self.proc.stdout.feed_data((json.dumps(reply) + '\n').encode())


class Mic:
    """A microphone someone else holds (the "Hey Mario" listener lends its own)."""
    def __init__(self):
        self.frames, self.released = asyncio.Queue(), False

    async def get(self):
        return await self.frames.get()

    def release(self):
        self.released = True


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
    # a room with a fan: the hum is not speech, your voice over it is, and a pause still ends it
    hum, over = struct.pack('<1600h', *([700] * 1600)), struct.pack('<1600h', *([4000] * 1600))
    gate = voice.Silence()
    assert not any(gate.feed(hum) for _ in range(30)) and gate.spoken == 0 and gate.room.bar() > 1400
    assert not any(gate.feed(over) for _ in range(8)) and gate.spoken == 8
    assert not any(gate.feed(hum) for _ in range(17)) and gate.feed(hum)
    assert gate.room.level() == 0
    # a microphone that thumps as it opens has not said anything
    gate = voice.Silence(voice.Silence.SETTLE)
    assert not any(gate.feed(over) for _ in range(5)) and gate.spoken == 0
    assert not any(gate.feed(hum) for _ in range(74)) and gate.feed(hum) and gate.spoken == 0
    events, processes = [], []
    words = {b'P': {'partial': 'Add a task'}, b'F': {'final': 'Add a task review the build'}}
    async def presence(state, detail=''): events.append(state)
    class Proc:
        def __init__(self, recording):
            self.stdout = asyncio.StreamReader()
            self.recording, self.replies = recording, dict(words)
            if recording:
                self.stdout.feed_data(silence * 6 + speech * 5 + silence * 18)
            self.stdin = Frames(self)
            self.returncode = None
            self.killed = False
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
        status = await v.command('status', start['id'])
        assert status['text'] == 'Add a task review the build' and status['state'] == 'done'
        # the words so far were recognised while it listened, then the whole request once, carefully
        worker = next(p for p in processes if not p.recording)
        assert status['partial'] == 'Add a task' and worker.stdin.seen[0] == (b'P', 7 * 3200)
        assert worker.stdin.seen[-1] == (b'F', 29 * 3200)
        assert all(p.killed for p in processes) and v.proc is None and v.worker is None
        assert events == ['listening', 'thinking', 'ready']
        # A disappeared page cancels before it can transcribe or act.
        await v.start(); v.touched = time.monotonic() - 10
        await v.task
        assert v.state == 'error' and 'disconnected' in v.error
        # Cancellation kills the recorder and the recogniser and clears dictated content.
        await v.start()
        await v.command('cancel', v.id)
        assert v.state == 'cancelled' and v.text == '' and v.partial == '' and v.proc is None and v.worker is None

        # "Hey Mario, what is the weather today?" in one breath: the session starts on the listener's
        # microphone with what was already said, the page that opens takes it over, the phrase is
        # left out of the request, and the microphone goes back.
        words.update({b'P': {'partial': 'Hey Mario, what is the weather'}, b'F': {'final': 'Hey Mario, what is the weather today?'}})
        mic = Mic()
        started = await v.start(mic=mic, prefill=speech * 12, wake=True)
        assert started.get('id') and v.unclaimed
        taken = await v.start()
        assert taken == {'id': started['id'], 'state': 'listening', 'wake': True} and not v.unclaimed
        assert (await v.start()).get('error')                  # only once
        for _ in range(30):
            mic.frames.put_nowait(silence)
        await v.task
        assert v.state == 'done' and v.text == 'What is the weather today?' and mic.released
        # "Hey Mario" and then nothing: no error, Mario steps back.
        words.update({b'P': {'partial': 'Hey Mario'}, b'F': {'final': 'Hey Mario.'}})
        mic = Mic()
        await v.start(mic=mic, prefill=speech * 8, wake=True)
        for _ in range(80):
            mic.frames.put_nowait(silence)
        await v.task
        assert v.state == 'silent' and v.text == '' and v.error == '' and mic.released
        # a lent microphone is handed back when the session cannot start
        v.available = lambda: False
        mic = Mic()
        assert (await v.start(mic=mic)).get('error') and mic.released
        v.available = lambda: True
    with tempfile.TemporaryDirectory() as tmp:
        h = hub.Hub(dict(config.DEFAULTS, repos=[], thinking_space=Path(tmp), notes_dir=str(Path(tmp) / 'Mario Notes')), schedule={})
        h.notes_file = Path(tmp) / 'notes.md'
        assert not h.wake.status()['enabled'] and h.wake.file is None      # a check never opens a microphone
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
    print('PASS: silence/no-speech boundaries, a noisy room and an opening thump, busy/ownership guards, words while listening, disconnect, cancellation, process cleanup, '
          'a session begun by "Hey Mario" (hand-over, the phrase left out, nothing said), task/note writes and bounded launch commands')


if __name__ == '__main__':
    asyncio.run(main())
