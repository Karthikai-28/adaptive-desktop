"""Mario's settings: one JSON file, every key optional.

~/.config/adaptive-desktop/mario.json overrides the defaults below key by key. Paths may start with
~. Nothing here names a user or a home folder; the Adaptive checkout is found from this file.
"""
import json
import os
from pathlib import Path

ADAPTIVE_REPO = Path(os.environ.get("ADAPTIVE_REPO") or Path(__file__).resolve().parents[2])
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "adaptive-desktop"
CONFIG_FILE = CONFIG_DIR / "mario.json"
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "adaptive-desktop" / "mario"

DEFAULTS = {
    # where the hub listens; loopback only
    "port": 8791,
    # git checkouts shown on the Builds card, newest commit first; missing ones are skipped
    "repos": [str(ADAPTIVE_REPO), "~/LOOM", "~/thinking-space", "~/agent-brain"],
    # the Thinking Space backup checkout: boards/ and reels/ come from here
    "thinking_space": "~/thinking-space",
    # pull it (fast-forward only) this often, so the boards and trackers stay current
    "thinking_space_pull_s": 900,
    # the nightly GitHub backup, shown in the island and Next step (local time, HH:MM)
    "backup_at": "22:40",
    # LOOM's backend (local-ai/app/backend, uvicorn on 8765) answers questions locally
    "loom_url": "http://127.0.0.1:8765",
    "agent_office_url": "http://127.0.0.1:8790",
    "ollama_url": "http://127.0.0.1:11434",
    # asked directly when LOOM's backend is not running (LOOM's default_chat role)
    "fallback_model": "qwen2.5:7b-instruct",
    # Claude Code for multi-step dev work; asked only after you confirm
    "claude_cmd": "claude",
    "claude_timeout_s": 1800,
    # AI plans shown on the usage tile (quotaSnapshot.py keys): the subscriptions you have
    "usage_providers": ["claude", "gemini"],
    # the weather tile (Open-Meteo, no key); "cards_off": ["weather"] keeps the hub offline
    "weather": {"name": "Bengaluru", "lat": 12.97, "lon": 77.59},
    # cards that are off unless turned on here
    "cards_off": ["career"],
}


def load(path=None):
    cfg = dict(DEFAULTS)
    path = Path(path) if path else CONFIG_FILE
    try:
        user = json.loads(path.read_text())
    except (OSError, ValueError):
        user = {}
    if isinstance(user, dict):
        cfg.update({k: v for k, v in user.items() if k in DEFAULTS})
    cfg["repos"] = [Path(os.path.expanduser(p)) for p in cfg["repos"]]
    cfg["thinking_space"] = Path(os.path.expanduser(cfg["thinking_space"]))
    return cfg
