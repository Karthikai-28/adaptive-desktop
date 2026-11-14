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
    # Who answers (engines.py): Claude first, Gemini when Claude is at its limit or does not
    # answer, LOOM/Ollama on this laptop only when neither cloud answers
    "brain": ["claude", "gemini", "local"],
    # Claude Code, headless, on the Claude subscription: answers, and multi-step dev work in a repo
    # (that only after you confirm)
    # The model is named in full so an alias moving on never changes who answers.
    "claude_cmd": "claude",
    "claude_model": "claude-sonnet-5-5",
    "claude_timeout_s": 1800,
    # Gemini through the Antigravity CLI on the AI Pro subscription: a fast model for answers, a
    # stronger one when it takes a code hand-off because Claude is at its limit
    "gemini_cmd": "agy",
    "gemini_model": "gemini-3.8-flash-low",
    "gemini_work_model": "gemini-3.8-flash-high",
    # how long one answer may take before the next engine is asked
    "answer_timeout_s": 150,
    # AI plans shown on the usage tile (quotaSnapshot.py keys): the subscriptions you have
    "usage_providers": ["claude", "gemini"],
    # the weather tile (Open-Meteo, no key); "cards_off": ["weather"] keeps the hub offline
    "weather": {"name": "Bengaluru", "lat": 12.97, "lon": 77.59},
    # Mail card: IMAP, read-only; each account's app password is in the keyring
    # (install-mario.sh --mail). "main" is the account Home shows first; without it, the first one.
    "mail": {"accounts": [], "main": "", "imap_host": "imap.gmail.com"},
    # News tile: RSS feeds, merged newest first; the tile rolls to the next headline every 30 s.
    # "cards_off": ["news"] keeps the hub from fetching them.
    "news": [
        {"name": "Tech", "url": "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-IN&gl=IN&ceid=IN:en"},
        {"name": "India", "url": "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en"},
        {"name": "Hacker News", "url": "https://hnrss.org/frontpage"},
    ],
    # Home's tabs after Today: each is a site kept open inside Home (signed in once, there). Add a
    # line for any site you work in every day; "id" is its name in `host.py --show <id>`.
    "tabs": [
        {"id": "mail", "name": "Mail", "url": "https://mail.google.com/mail/u/0/"},
        {"id": "calendar", "name": "Calendar", "url": "https://calendar.google.com/calendar/u/0/r"},
    ],
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
