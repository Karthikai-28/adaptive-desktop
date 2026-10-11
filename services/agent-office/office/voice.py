"""Speech for agents: edge-tts (neural voices, one per agent), cached on disk."""
import asyncio
import hashlib
import re
import shutil
import sys

from .config import TTS_CACHE

_locks = {}


def speakable(text, limit=1200):
    text = re.sub(r"```.*?```", " (code omitted) ", text, flags=re.S)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)          # markdown links -> their label
    text = re.sub(r"https?://\S+", "a link", text)
    text = re.sub(r"[*_#`>|]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        cut = text[:limit]
        text = cut[: cut.rfind(". ") + 1] or cut
    return text


async def tts(voice, text):
    """Return the path of an mp3 of `text` in `voice`, or None if synthesis failed."""
    text = speakable(text)
    if not text:
        return None
    key = hashlib.sha1(f"{voice}\n{text}".encode()).hexdigest()
    out = TTS_CACHE / f"{key}.mp3"
    if out.exists() and out.stat().st_size > 0:
        return out
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        if out.exists() and out.stat().st_size > 0:
            return out
        tmp = out.with_suffix(".part.mp3")
        # the edge-tts command if installed, else the module from the office's own dependencies
        exe = [shutil.which("edge-tts")] if shutil.which("edge-tts") else [sys.executable, "-m", "edge_tts"]
        proc = await asyncio.create_subprocess_exec(
            *exe, "--voice", voice, "--text", text, "--write-media", str(tmp),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        try:
            _, err = await asyncio.wait_for(proc.communicate(), timeout=60)
        except asyncio.TimeoutError:
            proc.kill()
            return None
        if proc.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
            tmp.unlink(missing_ok=True)
            return None
        tmp.rename(out)
    _locks.pop(key, None)
    return out
