"""Paths and the company roster (config.json).

Code lives in the repo (services/agent-office). What the office produces lives outside it, like the
rest of Adaptive Desktop's user data: $OFFICE_STATE, by default
~/.local/share/adaptive-desktop/agent-office, holding
  company/   the shared workspace the agents work in (projects/, meetings/)
  data/      the office database, agy's isolated home, the voice cache, logs
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = Path(os.path.expanduser("~"))
STATE = Path(os.environ.get("OFFICE_STATE") or HOME / ".local/share/adaptive-desktop/agent-office").resolve()
DATA = STATE / "data"
COMPANY = STATE / "company"
STATIC = ROOT / "static"
AGY_HOME = DATA / "agy-home"          # isolated HOME for agy (sign-in comes from the OS keyring)
TTS_CACHE = DATA / "tts"
LOGS = DATA / "logs"

for d in (DATA, COMPANY / "projects", COMPANY / "meetings", AGY_HOME, TTS_CACHE, LOGS):
    d.mkdir(parents=True, exist_ok=True)


def load() -> dict:
    cfg = json.loads((ROOT / "config.json").read_text())
    ids = [a["id"] for a in cfg["agents"]]
    if len(ids) != len(set(ids)) or cfg["manager"]["id"] in ids:
        raise SystemExit("config.json: agent ids must be unique and differ from the manager id")
    return cfg
