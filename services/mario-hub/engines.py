"""Who answers Mario: Claude first, Gemini when Claude is at its limit, the laptop when both are out,
and which model, by how hard the question is (tier()):

  quick    a short question, a fact, a chat: Sonnet 5.5 at low effort (little thinking); Gemini 3.8
           Flash Low at Claude's limit
  deep     reasoning, explaining, comparing, planning, writing, code: Sonnet 5.5 at high effort;
           Gemini 3.8 Flash Medium at Claude's limit

Measured on this laptop (2026-11-17, `claude -p` and `agy -p` exactly as run here, 11 spoken
questions each): Sonnet 5.5 median 2.7-3.0 s from asking to the whole answer, Haiku 5.5 3.7-3.9 s
(slower in every pair, so it is not the quick model), Gemini 3.8 Flash through agy 11-14 s (agy's own
start-up is most of that), so Gemini is the fallback, not the fast path. "models" and "effort" in
mario.json change any of these.

  claude   the Claude subscription, through Claude Code's headless mode (`claude -p`). No tools but
           web search and web fetch: an answer can look something up, never run or change anything.
  gemini   the Google AI Pro subscription, through the Antigravity CLI (`agy -p`) in plan mode,
           read-only. The Gemini CLI no longer serves personal accounts; agy is the way in.
  local    LOOM (memory, router) and then Ollama, on this laptop: only when neither cloud answers.

The order is `brain` in mario.json. Neither CLI is given an API key: both run on the subscriptions
(an inherited ANTHROPIC_API_KEY or GEMINI_API_KEY would switch them to paid API billing).
Everything here except run() is pure, so the check can feed it recorded replies.
"""
import json
import os
import re
import subprocess
import time

ENGINES = ("claude", "gemini", "local")
LABEL = {"claude": "Claude", "gemini": "Gemini", "local": "this laptop"}
# what Claude Code and agy print when a plan's window is used up
LIMIT = re.compile(r"usage limit|limit reached|hit your (usage )?limit|rate.?limit|resource.?exhausted|\b429\b|"
                   r"quota|out of (extra )?usage|too many requests", re.I)
DROP_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "OPENAI_API_KEY",
            "GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS", "CLAUDECODE",
            "CLAUDE_CODE_ENTRYPOINT")

SYSTEM = (
    "You are Mario, the assistant built into Karthi's laptop desktop (Adaptive Desktop on Ubuntu). "
    "Answer briefly and directly in plain sentences: no Markdown headings or tables, short lists only "
    "when they help. The answer appears in a small box on the desktop and may be read aloud. "
    "Each message starts with live context from the desktop (time, calendar, mail, tasks, repos); use it "
    "when the question is about Karthi's day or work, and never invent items that are not in it. "
    "You cannot run commands or change files from here. For a change to code, say: ask Mario to do it "
    "in that repo, and it will hand the work to Claude Code after Karthi confirms.")
# added to a question asked by voice: the answer is heard, not read
SPOKEN = ("[Karthi said this out loud and will hear your reply in a voice. Talk like a warm, quick "
          "friend: one to three short sentences, contractions welcome, no lists, symbols, links or "
          "Markdown. Longer only if asked.]")


TIERS = ("quick", "deep")
MODELS = {"quick": {"claude": "claude-sonnet-5-5", "gemini": "gemini-3.8-flash-low"},
          "deep": {"claude": "claude-sonnet-5-5", "gemini": "gemini-3.8-flash-medium"}}
# Claude Code's --effort: how much the model thinks before it answers (agy's Flash Low / Medium
# are the same idea for Gemini)
EFFORT = {"quick": "low", "deep": "high"}
# what makes a question worth the stronger model
_DEEP = re.compile(
    r"\b(?:explain|why|compare|comparison|versus|vs|difference between|differences|analy[sz]e|analysis|plan|"
    r"design|architect|strategy|pros and cons|trade-?offs?|step by step|in detail|detailed|thorough|"
    r"write|draft|rewrite|essay|email|letter|cover letter|story|poem|code|program|script|function|algorithm|"
    r"regex|sql|debug|error|bug|stack trace|prove|derive|calculate|solve|equation|summari[sz]e|review|"
    r"research|recommend|should i|help me (?:decide|choose|understand|think)|how does|how do .{1,40} work|"
    r"teach me|walk me through|brainstorm|ideas for|itinerary|translate)\b", re.I)


def tier(text):
    """quick or deep, from the words alone: no model is asked to decide (that would cost the time
    it saves). Long or many-part questions, code, and the verbs above are deep."""
    t = str(text or "").strip()
    words = len(t.split())
    if words > 28 or t.count("?") > 1 or "\n" in t or re.search(r"[{}`]|=>|\bdef |\breturn\b", t) or _DEEP.search(t):
        return "deep"
    return "quick"


def model_for(cfg, engine, level):
    """The model `engine` answers a `level` question with: "models" in mario.json, else the defaults."""
    chosen = ((cfg.get("models") or {}).get(level) or {}).get(engine)
    return chosen or MODELS.get(level, MODELS["quick"]).get(engine) or cfg.get(f"{engine}_model") or ""


def effort_for(cfg, level):
    chosen = (cfg.get("effort") or {}).get(level)
    return chosen if chosen in ("low", "medium", "high", "xhigh", "max") else EFFORT.get(level)


def model_name(model):
    """A model id as people say it: claude-sonnet-5-5 -> Sonnet 5.5, gemini-3.8-flash-low -> Gemini 3.8 Flash."""
    found = re.match(r"claude-(opus|sonnet|haiku|fable)-(\d+)(?:-(\d+))?", model or "", re.I)
    if found:
        return f"{found.group(1).capitalize()} {found.group(2)}" + (f".{found.group(3)}" if found.group(3) else "")
    found = re.match(r"gemini-([\d.]+)-([a-z]+)", model or "", re.I)
    if found:
        return f"Gemini {found.group(1)} {found.group(2).capitalize()}"
    return (model or "").capitalize()


def order(cfg):
    """The engines to try, in order, with unknown names left out; local is always the last resort."""
    names = [n for n in (cfg.get("brain") or ENGINES) if n in ENGINES]
    return list(dict.fromkeys(names + ["local"]))


def clean_env(base=None):
    return {k: v for k, v in (base if base is not None else os.environ).items() if k not in DROP_ENV}


# Claude Code without what an answer does not need: no MCP servers, skills, settings files (they
# bring CLAUDE.md and memory: about 5,000 tokens a question) or per-machine prompt sections. Still
# the subscription's own login; --bare is not used because it needs an API key.
LEAN = ["--strict-mcp-config", "--disable-slash-commands", "--setting-sources", "",
        "--exclude-dynamic-system-prompt-sections"]


def claude_argv(cfg, prompt, session=None, model=None, effort=None):
    argv = [cfg.get("claude_cmd") or "claude", "-p", prompt, "--output-format", "json",
            "--system-prompt", SYSTEM,
            "--tools", "WebSearch,WebFetch", "--allowedTools", "WebSearch,WebFetch", *LEAN]
    model = model or cfg.get("claude_model")
    if model:
        argv += ["--model", model]
    if effort:
        argv += ["--effort", effort]
    if session:
        argv += ["--resume", session]
    return argv


def gemini_argv(cfg, prompt, conversation=None, model=None):
    argv = [cfg.get("gemini_cmd") or "agy", "-p", f"{SYSTEM}\n\n{prompt}", "--output-format", "json",
            "--mode", "plan", "--sandbox", "--model", model or cfg.get("gemini_model") or "gemini-3.8-flash-low"]
    if conversation:
        argv += ["--conversation", conversation]
    return argv


def handoff_argv(engine, cfg, prompt):
    """The command a confirmed code hand-off runs in the repo: Claude Code, or agy when Claude is out."""
    if engine == "gemini":
        return [cfg.get("gemini_cmd") or "agy", "-p", prompt, "--mode", "accept-edits", "--sandbox",
                "--model", cfg.get("gemini_work_model") or "gemini-3.8-flash-high"]
    return [cfg.get("claude_cmd") or "claude", "-p", prompt, "--permission-mode", "acceptEdits", "--output-format", "text"]


def _json(text):
    """The last JSON object a CLI printed (a warning line may come first)."""
    text = (text or "").strip()
    for start in [0] + [m.start() for m in re.finditer(r"\n\{", text)][::-1]:
        try:
            out = json.loads(text[start:].strip())
            if isinstance(out, dict):
                return out
        except ValueError:
            continue
    return None


def limit_until(text, now=None):
    """When a limit message says the limit lifts (Claude Code prints "...limit reached|<epoch>")."""
    m = re.search(r"\|(\d{10})\b", text or "")
    return int(m.group(1)) if m and int(m.group(1)) > (now or time.time()) else None


def parse_claude(code, out, err):
    """claude -p --output-format json -> {"answer", "session", "model", "limited", "until", "error"}."""
    data = _json(out)
    if data and not data.get("is_error") and str(data.get("result", "")).strip():
        models = list((data.get("modelUsage") or {}).keys())
        main = next((m for m in models if "haiku" not in m), models[0] if models else "")
        return {"answer": str(data["result"]).strip(), "session": data.get("session_id"), "model": main}
    text = str((data or {}).get("result") or "") or f"{out}\n{err}".strip()
    return {"error": _short(text) or f"claude exited with {code}", "limited": bool(LIMIT.search(text)),
            "until": limit_until(text)}


def parse_gemini(code, out, err):
    """agy -p --output-format json -> the same shape as parse_claude."""
    data = _json(out)
    if data and str(data.get("status", "")).upper() == "SUCCESS" and str(data.get("response", "")).strip():
        return {"answer": str(data["response"]).strip(), "session": data.get("conversation_id"), "model": ""}
    text = json.dumps(data) if data else f"{out}\n{err}".strip()
    if code == 0 and data is None and not text:
        text = "agy gave an empty reply"
    return {"error": _short(text) or f"agy exited with {code}", "limited": bool(LIMIT.search(text))}


def _short(text):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text[:160]


def run(argv, cwd, timeout):
    """Run one engine; never raises. -> (exit code, stdout, stderr)."""
    try:
        out = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                             env=clean_env(), stdin=subprocess.DEVNULL)
        return out.returncode, out.stdout, out.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"no answer within {timeout} s"
    except OSError as exc:
        return 127, "", str(exc)


def usage_limit(usage_card, name, now=None):
    """From the AI usage tile: when `name`'s plan is at 100 % in a window that has not reset yet,
    the time it resets (0 when unknown); None when it is not at its limit."""
    now = now or time.time()
    p = ((usage_card or {}).get("providers") or {}).get(name) or {}
    full = [w for w in p.get("windows") or [] if (w.get("used") or 0) >= 100
            and (not w.get("resets") or w["resets"] > now)]
    if not full:
        return None
    return max((w.get("resets") or 0) for w in full)


def context(state, now=None):
    """What Mario knows right now, as a few lines for the model: the same data Home shows."""
    import datetime as dt
    now = now or time.time()
    cards = {k: (v.get("data") if isinstance(v, dict) and "data" in v else v) or {}
             for k, v in (state.get("cards") or {}).items()}
    lines = [dt.datetime.fromtimestamp(now).strftime("Now: %A %d %B %Y, %H:%M")]
    w = cards.get("weather") or {}
    if w.get("temp") is not None and not w.get("off"):
        lines.append(f"Weather in {w.get('place', '')}: {w['temp']}°C, {w.get('sky', '')}, "
                     f"high {w.get('high')}° low {w.get('low')}°")
    cal = cards.get("calendar") or {}
    if "events" in cal:
        ev = cal["events"] or []
        lines.append("Calendar today: " + ("; ".join(f"{e.get('start') or 'all day'} {e.get('title')}" for e in ev[:8]) or "nothing"))
    m = cards.get("mail") or {}
    for acct in m.get("accounts") or ([m] if m.get("unread") is not None else []):
        if acct.get("unread") is None:
            continue
        top = "; ".join(f"{i.get('from')}: {i.get('subject')}" for i in (acct.get("items") or [])[:5])
        lines.append(f"Mail {acct.get('user', '')}: {acct['unread']} unread" + (f". Newest: {top}" if top else ""))
    t = cards.get("tasks") or {}
    if t.get("open"):
        lines.append(f"Open tasks ({t.get('count', len(t['open']))}): " + "; ".join(x.get("text", "") for x in t["open"][:8]))
    for r in (cards.get("builds") or {}).get("repos", [])[:6]:
        bits = [r.get("branch") or ""]
        bits += [f"{r['dirty']} uncommitted"] if r.get("dirty") else []
        bits += [f"{r['ahead']} to push"] if r.get("ahead") else []
        lines.append(f"Repo {r.get('name')}: {', '.join(b for b in bits if b)}; last commit \"{r.get('subject', '')}\"")
    office = cards.get("agent_office") or {}
    if office.get("missions"):
        lines.append("Agent Office is working on: " + "; ".join(x.get("title", "") for x in office["missions"]))
    return "\n".join(lines)[:3500]
