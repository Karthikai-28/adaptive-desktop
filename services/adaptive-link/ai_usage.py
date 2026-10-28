"""Read the desktop's existing AI-plan usage snapshot for a paired phone.

The shell already has one source of truth for Codex, Claude and Gemini usage.
Only its display data is returned here: never its watched file paths or other
machine-local implementation details.
"""

import importlib.util
import math
from pathlib import Path


PROVIDERS = ("codex", "claude", "gemini")
SNAPSHOT = Path(__file__).resolve().parents[2] / "shell" / "adaptive-shell@local" / "quotaSnapshot.py"
_reader = None


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def clean_snapshot(raw):
    """Bound and project the shell snapshot onto fields safe for the phone."""
    result = {"ok": True}
    raw = raw if isinstance(raw, dict) else {}
    for name in PROVIDERS:
        source = raw.get(name) if isinstance(raw.get(name), dict) else {}
        windows = []
        for entry in source.get("windows", []) if isinstance(source.get("windows"), list) else []:
            if not isinstance(entry, dict) or not _number(entry.get("used")):
                continue
            reset = entry.get("resetsAt")
            windows.append({
                "label": str(entry.get("label", ""))[:24],
                "used": max(0, min(100, round(float(entry["used"]), 1))),
                "resetsAt": reset if _number(reset) else 0,
                "expired": bool(entry.get("expired")),
            })
        result[name] = {
            "ts": source.get("ts") if _number(source.get("ts")) else 0,
            "stale": bool(source.get("stale", True)),
            "error": str(source.get("error", ""))[:160],
            "windows": windows[:6],
        }
    return result


def snapshot():
    global _reader
    try:
        if _reader is None:
            spec = importlib.util.spec_from_file_location("adaptive_quota_snapshot", SNAPSHOT)
            if spec is None or spec.loader is None:
                raise RuntimeError("AI usage reader is unavailable")
            _reader = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(_reader)
        return clean_snapshot(_reader.snapshot())
    except Exception as error:  # usage is advisory; it must never break Link
        unavailable = {"stale": True, "error": str(error)[:160], "windows": [], "ts": 0}
        return {"ok": False, **{name: dict(unavailable) for name in PROVIDERS}}
