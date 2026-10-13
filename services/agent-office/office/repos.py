"""Every git repository on the laptop, readable by every agent; one of them writable when a task names it.

config.json "repos": {"all": true, "roots": ["~"], "skip": []}. The scan walks the roots, skips hidden
folders (tool state, credentials, the office's own state), caches and node_modules, and keeps the
outermost repo where repos nest. It runs in the background every SCAN_EVERY_S.

Inside a repo, files that usually hold secrets (.env, private keys, keystores, cloud credential files)
are hidden from agents, and so is a .git/config whose remote URL carries a password. Agents never get
a remote: the git on their PATH refuses push/pull/fetch/clone/ls-remote/remote changes, every git they
run has protocol.allow=never, and no credential or SSH agent reaches their sandbox.

REPOS.md in the workspace lists the repos for the agents.
"""
import asyncio
import fnmatch
import os
import re
import time
from pathlib import Path

from .config import COMPANY, HOME, STATE

SCAN_EVERY_S = 15 * 60
PRUNE = {"node_modules", "__pycache__", "snap", "site-packages", "venv", "build", "dist", "target"}
# file names that usually hold secrets; matched against the name only
SECRET_NAMES = (".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore", "id_rsa*",
                "id_ecdsa*", "id_ed25519*", ".netrc", ".git-credentials", ".npmrc", ".pypirc",
                "credentials", "credentials.json", "credentials.toml", "service-account*.json",
                "client_secret*.json", "*.kdbx", "secrets.yaml", "secrets.yml", "secrets.json",
                "local.properties", "keystore.properties", "google-services.json")
NOT_SECRET = (".env.example", ".env.sample", ".env.template", ".env.dist", "*.pub")
SECRET_PRUNE = PRUNE | {".git", ".venv", ".tox", ".mypy_cache", ".pytest_cache", ".gradle", ".idea"}
URL_PASSWORD = re.compile(rb"://[^/\s@:]+:[^/\s@]+@")

# git subcommands that talk to (or change) a remote; the agents' git refuses them
REMOTE_GIT = ("push", "pull", "fetch", "clone", "ls-remote", "remote", "submodule", "request-pull",
              "send-email", "send-pack", "fetch-pack", "upload-pack", "receive-pack", "svn", "p4",
              "credential", "credential-store", "credential-cache")
GIT_ENV = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "protocol.allow", "GIT_CONFIG_VALUE_0": "never",
           "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "/bin/false", "SSH_ASKPASS": "/bin/false",
           # agent commits (local branches only): a neutral identity, never the owner's work or personal one
           "GIT_AUTHOR_NAME": "Karthi Labs", "GIT_AUTHOR_EMAIL": "office@karthi-labs.local",
           "GIT_COMMITTER_NAME": "Karthi Labs", "GIT_COMMITTER_EMAIL": "office@karthi-labs.local"}
AGENT_BIN = STATE / "bin"          # the agents' git wrapper; first on their PATH
SECRET_ENV = ("SSH_AUTH_SOCK", "SSH_AGENT_PID", "GPG_AGENT_INFO", "GNOME_KEYRING_CONTROL", "GH_TOKEN",
              "GITHUB_TOKEN", "GITLAB_TOKEN", "BITBUCKET_TOKEN", "HF_TOKEN", "KAGGLE_KEY")

GIT_WRAPPER = """#!/bin/sh
# Agent Office: agents work on local copies only - no git command that reaches or changes a remote.
skip=""
for a in "$@"; do
  if [ -n "$skip" ]; then skip=""; continue; fi
  case "$a" in
    -C|-c|--git-dir|--work-tree|--namespace|--exec-path|--config-env) skip=1 ;;
    -*) ;;
    *) sub="$a"; break ;;
  esac
done
case "$sub" in
  %s)
    echo "git $sub: not allowed in Agent Office - agents never push, pull, fetch, clone or change remotes." >&2
    echo "Leave the change in the repo (or the workspace) and say in your report what the owner should push." >&2
    exit 1 ;;
esac
exec /usr/bin/git "$@"
"""


def git_env(env):
    """An agent's environment: no agent sockets or tokens, the guarded git first on PATH, no git transport."""
    env = {k: v for k, v in env.items() if k not in SECRET_ENV}
    env.update(GIT_ENV)
    env["PATH"] = f"{AGENT_BIN}:{env.get('PATH', '/usr/bin:/bin')}"
    return env


def install_git_wrapper():
    AGENT_BIN.mkdir(parents=True, exist_ok=True)
    git = AGENT_BIN / "git"
    text = GIT_WRAPPER % "|".join(REMOTE_GIT)
    if not git.is_file() or git.read_text() != text:
        git.write_text(text)
        git.chmod(0o755)


def _is_secret(name):
    return any(fnmatch.fnmatch(name, p) for p in SECRET_NAMES) and \
        not any(fnmatch.fnmatch(name, p) for p in NOT_SECRET)


def find_repos(roots, skip=()):
    """Outermost git repos under the roots (hidden folders and caches skipped)."""
    skip = {str(Path(s).expanduser()) for s in skip}
    skip.add(str(STATE))
    found = []
    for root in roots:
        root = Path(root).expanduser()
        if not root.is_dir():
            continue
        for dirpath, dirs, files in os.walk(root, followlinks=False):
            if dirpath in skip:
                dirs[:] = []
                continue
            if (".git" in dirs or ".git" in files) and dirpath != str(root):   # ~ itself may be a repo
                found.append(dirpath)
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in PRUNE]
    return sorted(set(found))


def find_secrets(repo):
    """Paths inside one repo that agents must not read."""
    hidden = []
    cfg = Path(repo, ".git", "config")
    try:
        if cfg.is_file() and URL_PASSWORD.search(cfg.read_bytes()):
            hidden.append(str(cfg))
    except OSError:
        pass
    for dirpath, dirs, files in os.walk(repo, followlinks=False):
        dirs[:] = [d for d in dirs if d not in SECRET_PRUNE]
        hidden += [os.path.join(dirpath, f) for f in files if _is_secret(f)]
    return hidden


class Repos:
    def __init__(self, office):
        self.office = office
        self.cfg = {"all": True, "roots": ["~"], "skip": [], **(office.cfg.get("repos") or {})}
        self.paths, self.hidden = [], []
        self.scanned_at = 0
        install_git_wrapper()

    @property
    def enabled(self):
        return bool(self.cfg.get("all"))

    def scan(self):
        if not self.enabled:
            self.paths, self.hidden = [], []
            return
        paths = find_repos(self.cfg["roots"], self.cfg.get("skip", ()))
        hidden = [h for r in paths for h in find_secrets(r)]
        self.paths, self.hidden, self.scanned_at = paths, hidden, time.time()
        self._write_list()

    def _write_list(self):
        home = str(HOME)
        lines = ["# Repositories on this laptop", "",
                 "Every git repository here is readable at its own path (read-only). A task that names a repo",
                 "makes that one writable for the task. Agents never push, pull, fetch or clone: work on these",
                 "local copies. Files that usually hold secrets (.env, keys) are hidden.", ""]
        lines += [f"- {p.replace(home, '~', 1)}" for p in self.paths]
        out = COMPANY / "REPOS.md"
        text = "\n".join(lines) + "\n"
        if not out.is_file() or out.read_text() != text:
            out.write_text(text)

    async def loop(self, on_scan=None):
        loop = asyncio.get_running_loop()
        while True:
            await asyncio.sleep(SCAN_EVERY_S)
            try:
                await loop.run_in_executor(None, self.scan)
                if on_scan:
                    on_scan()
            except Exception as e:      # a scan failure keeps the last list
                print(f"repo scan: {e}", flush=True)

    def resolve(self, ref):
        """A repo path from what a task names: a path (absolute or ~/...) or a repo's unique folder name."""
        ref = (ref or "").strip().rstrip("/")
        if not ref:
            return ""
        p = Path(ref).expanduser()
        if p.is_absolute() or ref.startswith("~"):
            p = p.resolve()
            if not p.is_dir():
                raise ValueError(f"repo {ref}: no such folder")
            if not (p / ".git").exists() and not any(Path(r) in p.parents for r in self.paths):
                raise ValueError(f"{ref} is not a git repository")
            hidden = HOME in p.parents and any(part.startswith(".") for part in p.relative_to(HOME).parts)
            if p == HOME or p == STATE or STATE in p.parents or hidden:
                raise ValueError(f"{ref} can't be made writable")
            return str(p)
        hits = [r for r in self.paths if os.path.basename(r) == ref or r.endswith("/" + ref)]
        if len(hits) == 1:
            return hits[0]
        if not hits:
            raise ValueError(f"no repo named {ref!r} (see REPOS.md, or give its path)")
        raise ValueError(f"{ref!r} matches several repos: {', '.join(hits[:5])} - give the path")
