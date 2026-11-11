"""Mario's decisions, kept pure so they can be checked without a model, a network or a desktop.

  quick_answer   questions the hub answers from its own state, instantly, with no model
  classify       everything else: LOOM locally, or Claude Code for multi-step work in a repo
  plan_handoff   what Claude Code would be asked, where, and with which limits: shown before it runs
  next_steps     up to three one-line suggestions for the Next step card
"""
import datetime as dt
import hashlib
import re
from pathlib import Path

# Work that edits code across files is Claude Code's; questions and chat stay local.
DEV_VERBS = r"(fix|implement|refactor|add|write|build|create|scaffold|port|migrate|rename|debug|test|review|update|upgrade|clean up|remove)"
CODE_WORDS = r"(code|bug|feature|function|class|module|script|tests?|repo|branch|commit|pr\b|pull request|endpoint|api|build|lint|ci\b|extension|service|backlog)"
OUTWARD = r"\b(push|deploy|publish|release|merge|send|email|mail|post|tweet|upload|share|delete|rm|drop)\b"
LIMITS = ("Work only inside this folder. Do not push, publish, deploy, send or delete anything; "
          "when one of those is the next step, stop and list it for me instead.")


def _norm(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def mentioned_repo(text, repos):
    """The configured repo a request names, by folder name ('loom', 'adaptive desktop', ...)."""
    low = _norm(text).lower()
    for path in repos:
        name = Path(path).name.lower()
        variants = {name, name.replace("-", " "), name.replace("_", " ")}
        if any(re.search(rf"\b{re.escape(v)}\b", low) for v in variants):
            return Path(path)
    return None


def classify(text, repos=()):
    low = _norm(text).lower()
    repo = mentioned_repo(low, repos)
    dev = re.search(rf"\b{DEV_VERBS}\b", low) and (repo is not None or re.search(rf"\b{CODE_WORDS}", low))
    asks = re.match(r"^(what|why|how|when|where|who|which|is|are|does|do|can|should|explain|tell me|summari[sz]e)\b", low)
    route = "claude" if dev and not asks else "local"
    return {"route": route, "repo": str(repo) if repo else None, "outward": bool(re.search(OUTWARD, low))}


def plan_handoff(text, repo, claude_cmd="claude"):
    prompt = f"{_norm(text)}\n\n{LIMITS}"
    pid = hashlib.sha1(f"{repo}\0{prompt}".encode()).hexdigest()[:12]
    return {"id": pid, "cwd": str(repo), "prompt": prompt, "repo": Path(repo).name,
            # headless; file edits inside cwd are allowed, every other tool keeps Claude Code's own
            # permission rules, which in -p mode means anything not already allowed is refused
            "argv": [claude_cmd, "-p", prompt, "--permission-mode", "acceptEdits", "--output-format", "text"],
            "steps": [f"Open Claude Code in {Path(repo).name}",
                      "Let it edit files in that folder only",
                      "Show you what changed; nothing is pushed or sent"]}


def _cards(state):
    """The hub keeps each card as {"data": ..., "at": ...}; plain dicts work too."""
    return {k: (v["data"] if isinstance(v, dict) and "data" in v else v) or {}
            for k, v in (state.get("cards") or {}).items()}


def _ago(ts, now):
    days = int((now - ts) // 86400)
    return "today" if days < 1 else "yesterday" if days < 2 else f"{days} days ago"


def quick_answer(text, state, now=None):
    """Instant answers from the hub's own cards; None when a model should answer instead."""
    now = now or dt.datetime.now().timestamp()
    low = _norm(text).lower().rstrip("?.! ")
    cards = _cards(state)
    if re.fullmatch(r"(what('s| has)? changed( today)?|what changed in my (reel )?trackers( today)?)", low):
        lines = []
        for r in (cards.get("builds") or {}).get("repos", []):
            if r.get("when") and now - r["when"] < 86400:
                lines.append(f"{r['name']}: {r['subject']} ({r['sha']})")
        last = (cards.get("reels") or {}).get("last_change")
        if last and last.get("Date") == dt.datetime.fromtimestamp(now).strftime("%Y-%m-%d"):
            lines.append(f"Reels: {last.get('Item')} {str(last.get('Change', '')).lower()}")
        return "Today: " + "; ".join(lines) + "." if lines else "Nothing new in your repos or trackers today."
    if re.fullmatch(r"(pick a movie( for tonight)?|what should i watch( tonight)?)", low):
        t = (cards.get("reels") or {}).get("tonight") or {}
        if t.get("titles"):
            return f"On {t['service']}: {' or '.join(t['titles'])}. Both are in your Movies tracker as yet to watch."
        return "Nothing from your Movies tracker is on a subscription you have right now."
    if re.fullmatch(r"(brief me|morning brief|evening brief|status)", low):
        parts = []
        steps = next_steps(state, now)
        if steps:
            parts.append(" ".join(s["text"] + "." for s in steps))
        reels = cards.get("reels") or {}
        open_items = sum(t["total"] - t["done"] for t in reels.get("trackers", []))
        if open_items:
            parts.append(f"{open_items} saved reels are still to watch or try.")
        office = cards.get("agent_office") or {}
        if office.get("missions"):
            parts.append(f"Agent Office is working on {office['missions'][0]['title']}.")
        return " ".join(parts) or "All quiet: nothing needs you."
    return None


def next_steps(state, now=None, limit=3):
    """One line each, most useful first. Each may carry an action the hub knows how to run."""
    now = now or dt.datetime.now().timestamp()
    cards = _cards(state)
    cfg = state.get("config", {})
    out = []
    for r in (cards.get("builds") or {}).get("repos", []):
        if r.get("ahead"):
            out.append((1, {"text": f"{r['name']}: {r['ahead']} commit{'s' * (r['ahead'] > 1)} not pushed",
                            "action": {"id": "terminal", "arg": r["path"], "label": "Open"}}))
        if r.get("behind"):
            out.append((2, {"text": f"{r['name']} is {r['behind']} behind its remote",
                            "action": {"id": "terminal", "arg": r["path"], "label": "Open"}}))
        if r.get("dirty"):
            out.append((3, {"text": f"{r['name']}: {r['dirty']} changed file{'s' * (r['dirty'] > 1)} not committed",
                            "action": {"id": "terminal", "arg": r["path"], "label": "Open"}}))
        elif r.get("when") and now - r["when"] > 60 * 86400:
            out.append((6, {"text": f"{r['name']} last changed {_ago(r['when'], now)}",
                            "action": {"id": "folder", "arg": r["path"], "label": "Open"}}))
    office = cards.get("agent_office") or {}
    if office and not office.get("running"):
        out.append((4, {"text": "Agent Office is stopped", "action": {"id": "start_office", "label": "Start"}}))
    ollama = (cards.get("system") or {}).get("ollama") or {}
    if ollama and not ollama.get("running"):
        out.append((4, {"text": "Ollama is off: start it (sudo systemctl start ollama) for local answers"}))
    ts = cards.get("thinking_space") or {}
    if ts.get("pull_error"):
        out.append((5, {"text": "Thinking Space did not update: " + ts["pull_error"][:60]}))
    at = cfg.get("backup_at")
    if at and re.fullmatch(r"\d{1,2}:\d{2}", at):
        h, m = map(int, at.split(":"))
        today = dt.datetime.fromtimestamp(now)
        when = today.replace(hour=h, minute=m, second=0, microsecond=0)
        if 0 <= (when - today).total_seconds() <= 3 * 3600:
            out.append((5, {"text": f"Nightly backup runs at {at}: boards, reel trackers, version history"}))
    out.sort(key=lambda p: p[0])
    seen, steps = set(), []
    for _, s in out:
        if s["text"] not in seen:
            seen.add(s["text"])
            steps.append(s)
    return steps[:limit]
