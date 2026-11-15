#!/usr/bin/env python3
""""Hey Mario": the phrase and voiceprint rules, the listener and the training, with a fake
microphone and a fake recogniser. No real microphone, no models, nothing of yours.

    verify-mario-wake.py                 rules, listener, training (part of verify-all --quick)
    verify-mario-wake.py --real VOICE    also the real worker and models against made-up voices:
                                         VOICE is a folder with a many-speaker Piper voice from
                                         sherpa-onnx's tts-models (vits-piper-en_US-libritts_r-medium);
                                         each voice is trained, then everyone says the phrase
"""
import asyncio
import json
import stat
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'services/mario-hub'))
import voice
import voice_rules as rules
import wake as wake_mod

FRAME = voice.FRAME


def test_rules():
    yes = ['Hey Mario', 'Hey, Mario!', 'hey mario what is the weather', 'Hi Mario, add a task', 'Himario.', 'Okay Mario. Brief me', 'Hey Mari-o']
    no = ['Hey Maria, how are you', 'Super Mario is fun', 'Mario, open files', 'I was playing Mario', 'Hey, are you there', '']
    assert all(rules.is_wake(t) for t in yes) and not any(rules.is_wake(t) for t in no)
    assert rules.strip_wake('Hey Mario, what is the weather today?') == 'What is the weather today?'
    assert rules.strip_wake('Hey Mario.') == '' and rules.strip_wake('Open files') == 'Open files'
    assert rules.only_wake('Hey, Mario!') and not rules.only_wake('Hey Mario, open files')
    assert rules.BEGINS.match('Hey') and rules.BEGINS.match('Hey Ma') and not rules.BEGINS.match('Open files')
    you = [[1, 0, 0, .1], [.9, .15, 0, .1], [.95, 0, .12, .1], [1, .05, .05, .15]]
    profile = rules.make_profile(you)
    assert rules.LOW <= profile['bar'] <= rules.HIGH and len(profile['prints']) == 4
    assert abs(sum(x * x for x in profile['centre']) - 1) < 1e-6
    assert rules.cosine(you[0], profile['centre']) > profile['bar'] > rules.cosine([0, 1, 0, 0], profile['centre'])
    # the bar follows how much your own samples differ, and never leaves its range
    assert rules.bar([[1, 0], [0, 1]]) == rules.LOW and rules.bar([[1, 0], [1, 0], [1, 0]]) == rules.HIGH
    assert rules.belongs(you[:2], you[2]) and not rules.belongs(you[:2], [0, 1, 0, 0]) and rules.belongs([], [0, 1])


class WorkerProc:
    """voice_worker.py wake, played by the check: it "hears" the phrase after `wake_after` frames."""
    def __init__(self, script):
        self.stdout = asyncio.StreamReader()
        self.stdout.feed_data(b'{"ready": "wake"}\n')
        self.script, self.buffer, self.seen, self.heard = script, b'', [], 0
        self.stdin = self
        self.transport = self
        self.returncode, self.killed = None, False

    def get_write_buffer_size(self):
        return 0

    def write(self, data):
        self.buffer += data
        while len(self.buffer) >= 5 and len(self.buffer) >= 5 + struct.unpack('>I', self.buffer[1:5])[0]:
            kind, size = self.buffer[:1], struct.unpack('>I', self.buffer[1:5])[0]
            body, self.buffer = self.buffer[5:5 + size], self.buffer[5 + size:]
            self.seen.append((kind, body))
            if kind == b'R':
                self.heard = 0
            elif kind == b'A':
                self.heard += 1
                if self.heard == self.script.get('wake_after'):
                    self.say({'wake': {'start': self.script['start'], 'score': 0.7}})
            elif kind == b'E':
                self.say({'sample': self.script['samples'].pop(0)})

    def say(self, message):
        self.stdout.feed_data((json.dumps(message) + '\n').encode())

    def kill(self): self.killed = True; self.returncode = -9
    async def wait(self): return self.returncode


class MicProc:
    def __init__(self):
        self.stdout = asyncio.StreamReader()
        self.returncode, self.killed = None, False

    def kill(self): self.killed = True; self.returncode = -9
    async def wait(self): return self.returncode


def frame(n):
    return struct.pack('<1600h', *([1000 + n] * 1600))


async def until(what, seconds=3):
    end = time.monotonic() + seconds
    while not what():
        assert time.monotonic() < end, 'timed out'
        await asyncio.sleep(0.01)


async def test_listener(tmp):
    file = tmp / 'voice.json'
    script = {'wake_after': 12, 'start': 8 * 1600}       # the utterance began at the ninth frame
    made, fired, changes, speaking = [], [], [], [False]

    async def spawn(*args, **kwargs):
        made.append(MicProc() if args[0] == 'parec' else WorkerProc(script))
        return made[-1]

    async def on_wake(mic, said, score): fired.append((mic, said, score))
    async def changed(): changes.append(1)
    w = wake_mod.Wake(lambda: {}, file, on_wake, changed, lambda: speaking[0])
    w.available = lambda: True
    assert w.status() == {'available': True, 'trained': False, 'enabled': False, 'hearing': False, 'training': False, 'trained_at': 0, 'error': ''}
    assert (await w.enable(True)).get('error')            # not before it knows your voice
    await w.start()
    assert w.task is None and w.lend() is None            # off: no microphone, and nothing to lend
    w.data = {'enabled': True, 'trained_at': 1, 'profile': rules.make_profile([[1, 0, 0], [.9, .1, 0]])}
    w.save()
    assert stat.S_IMODE(file.stat().st_mode) == 0o600      # the voiceprint is yours alone
    with patch.object(wake_mod.asyncio, 'create_subprocess_exec', spawn), patch.object(voice.asyncio, 'create_subprocess_exec', spawn):
        await w.start()
        await until(lambda: len(made) == 2)
        worker, mic = made
        sent = [frame(i) for i in range(12)]
        for f in sent:
            mic.stdout.feed_data(f)
        await until(lambda: fired)
        # it was told whose voice to listen for, then given the sound
        kinds = [k for k, _ in worker.seen]
        assert kinds[0] == b'V' and json.loads(worker.seen[0][1])['bar'] == w.data['profile']['bar'] and kinds.count(b'A') == 12
        lent, said, score = fired[0]
        assert said == b''.join(sent[8:]) and score == 0.7        # the session starts with the breath that held the phrase
        assert w.status()['hearing'] and w.lend() is None           # one borrower at a time
        # while a session has the microphone, the sound goes to it and not to the listener
        mic.stdout.feed_data(frame(50) + frame(51))
        assert await lent.get() == frame(50) and await lent.get() == frame(51)
        assert kinds.count(b'A') == [k for k, _ in worker.seen].count(b'A')
        lent.release()
        assert worker.seen[-1][0] == b'R' and w.lent is None        # given back: the stream starts afresh
        # Mario's own voice is not for the listener, nor the moment after a session
        w.quiet_until = 0
        speaking[0] = True
        before = len(worker.seen)
        mic.stdout.feed_data(frame(60) * 3)
        await asyncio.sleep(0.05)
        assert len(worker.seen) == before
        speaking[0] = False
        mic.stdout.feed_data(frame(61))
        await until(lambda: worker.seen[-1][0] == b'A')
        assert [k for k, _ in worker.seen[before:]] == [b'R', b'A']
        # turned off: the microphone and the worker are gone
        status = await w.enable(False)
        assert not status['enabled'] and not status['hearing'] and mic.killed and worker.killed and w.task is None
        assert json.loads(file.read_text())['enabled'] is False and changes
    return file


async def test_training(tmp):
    file = tmp / 'train.json'
    you = [[1, 0, 0, .1], [.9, .15, 0, .1], [.95, 0, .12, .1], [1, .05, .05, .15]]
    script = {'samples': [
        {'text': 'Hey Maria', 'phrase': False, 'print': [], 'seconds': 0.8},                 # not the phrase
        {'text': 'Hey Mario', 'phrase': True, 'print': you[0], 'seconds': 0.8},
        {'text': 'Hey Mario', 'phrase': True, 'print': [0, 1, 0, 0], 'seconds': 0.8},        # another voice
        *({'text': 'Hey Mario', 'phrase': True, 'print': p, 'seconds': 0.8} for p in you[1:]),
    ]}
    made = []

    async def spawn(*args, **kwargs):
        made.append(MicProc() if args[0] == 'parec' else WorkerProc(script))
        return made[-1]

    async def nothing(*_): pass
    w = wake_mod.Wake(lambda: {}, file, nothing, nothing)
    w.available = lambda: True
    quiet, speech = bytes(FRAME), struct.pack('<1600h', *([2000] * 1600))
    messages = []
    with patch.object(wake_mod.asyncio, 'create_subprocess_exec', spawn), patch.object(voice.asyncio, 'create_subprocess_exec', spawn):
        started = await w.train_start()
        assert started['of'] == rules.SAMPLES and w.status()['training']
        assert (await w.train_status('someone-else')).get('error')
        await until(lambda: len(made) == 2)
        worker, mic = made
        for _ in range(6):                               # six times said: one misheard, one in another voice
            seen = len([k for k, _ in worker.seen if k == b'E'])
            mic.stdout.feed_data(quiet * 3 + speech * 8 + quiet * 8)
            await until(lambda: len([k for k, _ in worker.seen if k == b'E']) > seen)
            await asyncio.sleep(0.02)
            status = await w.train_status(started['id'])
            messages.append((status['step'], status['message']))
        await until(lambda: w.train['state'] == 'done')
        # each sample is one utterance: a little before the first sound to the quiet after it
        sample = next(body for k, body in worker.seen if k == b'E')
        assert 8 * FRAME <= len(sample) <= 19 * FRAME
        assert messages[0] == (0, 'I heard “Hey Maria”. Say just “Hey Mario”.')
        assert messages[1] == (1, '') and messages[2][0] == 1 and 'different' in messages[2][1]
        assert [m[0] for m in messages[3:]] == [2, 3, 4]
        await until(lambda: w.task is not None)          # trained: Hey Mario is on and listening
        saved = json.loads(file.read_text())
        assert saved['enabled'] is True and len(saved['profile']['prints']) == 4 and rules.LOW <= saved['profile']['bar'] <= rules.HIGH
        assert stat.S_IMODE(file.stat().st_mode) == 0o600 and mic.killed and worker.killed
        assert 'audio' not in saved and all(len(p) == 4 for p in saved['profile']['prints'])     # numbers, not recordings
        # forgetting removes the voiceprint and turns it off
        status = await w.forget()
        assert not file.exists() and not status['trained'] and not status['enabled'] and w.task is None
        # a page that goes away closes the microphone
        script['samples'] = []
        del made[:]
        started = await w.train_start()
        await until(lambda: len(made) == 2)
        w.train['touched'] = time.monotonic() - 10
        made[1].stdout.feed_data(quiet)
        await until(lambda: w.train['state'] == 'error')
        assert 'closed' in w.train['message'] and made[1].killed
        await w.close()


def real(voice_dir):
    """The real worker and models: every made-up voice is trained, then all of them say the phrase."""
    import audioop
    import collections
    import numpy as np
    import sherpa_onnx
    name = next(Path(voice_dir).glob('*.onnx')).stem
    tts = sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
        vits=sherpa_onnx.OfflineTtsVitsModelConfig(model=f'{voice_dir}/{name}.onnx', tokens=f'{voice_dir}/tokens.txt',
                                                   data_dir=f'{voice_dir}/espeak-ng-data'), num_threads=4)))

    def speak(text, who, speed=1.0):
        audio = tts.generate(text, sid=who, speed=speed)
        pcm = (np.clip(np.array(audio.samples, dtype=np.float32), -1, 1) * 32767).astype('<i2').tobytes()
        return audioop.ratecv(pcm, 2, 1, audio.sample_rate, 16000, None)[0]

    people = [int(x) for x in np.random.default_rng(7).choice(tts.num_speakers, 6, replace=False)]
    said = {who: {'train': [speak('Hey Mario.', who, s) for s in (1.0, 0.92, 1.08, 0.86)],
                  'phrase': [speak('Hey Mario.', who, s) for s in (1.15, 0.97)],
                  'ask': [speak('Hey Mario, what is the weather today?', who)],
                  'other': [speak('Okay, let us review the build and add a task for tomorrow.', who),
                            speak('Hey Maria, how are you doing today?', who)]} for who in people}
    worker = subprocess.Popen([str(voice.VOICE_DIR / 'venv/bin/python'), str(voice.WORKER), 'wake'],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def send(kind, body=b''):
        worker.stdin.write(kind + len(body).to_bytes(4, 'big') + body)
        worker.stdin.flush()

    def read():
        return json.loads(worker.stdout.readline())

    def stream(pcm):
        """Quiet, the clip, quiet, as the microphone would bring it. True if the worker woke."""
        send(b'R')
        pcm = bytes(32000) + pcm + bytes(70400)
        for i in range(0, len(pcm), FRAME):
            send(b'A', pcm[i:i + FRAME])
        send(b'P')                                   # a marker: what came before it belongs to this stream
        woke = False
        while True:
            reply = read()
            if 'partial' in reply:
                return woke
            woke = woke or 'wake' in reply

    assert 'ready' in read()
    total, woke = collections.Counter(), collections.Counter()
    for who in people:
        prints = []
        for pcm in said[who]['train']:
            send(b'E', bytes(9600) + pcm + bytes(25600))
            sample = read()['sample']
            if sample['phrase']:
                prints.append(sample['print'])
        if len(prints) < 3:
            print(f'  voice {who}: the recogniser did not hear the phrase from this made-up voice; skipped')
            continue
        profile = rules.make_profile(prints)
        send(b'V', json.dumps({'centre': profile['centre'], 'bar': profile['bar']}).encode())
        for other in people:
            for kind in ('phrase', 'ask', 'other'):
                for pcm in said[other][kind]:
                    label = ('your ' if other == who else "someone else's ") + {'phrase': '“Hey Mario”', 'ask': '“Hey Mario, …” in one breath', 'other': 'other words'}[kind]
                    total[label] += 1
                    woke[label] += stream(pcm)
    worker.kill()
    for label in sorted(total):
        print(f'  {label:44s} woke {woke[label]}/{total[label]}')
    yours = sum(woke[k] for k in total if k.startswith('your') and 'other' not in k) / max(1, sum(total[k] for k in total if k.startswith('your') and 'other' not in k))
    others = sum(woke[k] for k in total if k.startswith('someone')) / max(1, sum(total[k] for k in total if k.startswith('someone')))
    assert not any(woke[k] for k in total if 'other words' in k), 'woke on words that are not the phrase'
    # the voices of one synthesiser are nearer to each other than people are: a loose bound
    assert yours >= 0.8 and others <= 0.2, (yours, others)
    print(f'PASS (real models, made-up voices): your phrase woke it {yours:.0%} of the time, another voice {others:.0%}')


async def main():
    test_rules()
    with tempfile.TemporaryDirectory(prefix='mario-wake-') as tmp:
        await test_listener(Path(tmp))
        await test_training(Path(tmp))
    print('PASS: the phrase and what follows it, the voiceprint bar; the listener (off until trained, the breath handed to the session, '
          'lending the microphone, quiet while Mario speaks, off closes it); training (misheard, another voice, four samples, '
          'numbers only, private file, forget, a closed page)')
    if '--real' in sys.argv:
        real(sys.argv[sys.argv.index('--real') + 1])


if __name__ == '__main__':
    asyncio.run(main())
