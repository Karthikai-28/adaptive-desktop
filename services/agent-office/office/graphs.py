"""Knowledge graphs for agents: navigate with the graph, then read only what matters.

Agents get graphify's MCP tools (query_graph, get_node, get_neighbors, shortest_path, god_nodes,
get_community) over a graph scoped to their own work, never the owner's whole global brain (which
also holds personal notes and unrelated projects):

  graphs/<agent>.json   merged from the hub graphs (~/Obsidian/graphify-out/<repo>/graph.json) of the
                        repos the agent studies, or lists under "graphs" in config.json
  graphs/workspace.json the company workspace itself (code only, rebuilt when it changes)

The hub stays the source of truth; these are derived copies kept in the office state folder and
refreshed when a hub graph changes. Each agy profile gets one stdio MCP server, "graph", that serves
the file named by $OFFICE_AGENT_GRAPH, so every agent sees only its own graph.
"""
import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .config import AGY_HOME, AGY_HOME_LOCAL, COMPANY, HOME, STATE

HUB = HOME / "Obsidian" / "graphify-out"
GRAPHS = STATE / "graphs"
USER_SITE = HOME / ".local" / "lib" / f"python{os.sys.version_info.major}.{os.sys.version_info.minor}" / "site-packages"
WORKSPACE_EVERY_S = 20 * 60


def available():
    return shutil.which("graphify") is not None


def _hub_graph(repo):
    p = HUB / repo / "graph.json"
    return p if p.is_file() else None


class Graphs:
    def __init__(self, office):
        self.o = office
        GRAPHS.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ which graph an agent gets
    def repos_for(self, aid):
        names = [Path(p).name for p in self.o.study.repo_paths(aid)]
        names += self.o.agents.get(aid, {}).get("graphs", [])
        return list(dict.fromkeys(names))

    def path_for(self, aid):
        """The graph file an agent's MCP server serves (its own, else the workspace graph)."""
        own = GRAPHS / f"{aid}.json"
        if self.repos_for(aid) and own.is_file():
            return own
        ws = GRAPHS / "workspace.json"
        return ws if ws.is_file() else None

    # ------------------------------------------------------------------ building
    def _merge(self, repos, out):
        sources = [(r, _hub_graph(r)) for r in repos]
        sources = [(r, g) for r, g in sources if g]
        if not sources:
            return False
        newest = max(g.stat().st_mtime for _, g in sources)
        if out.is_file() and out.stat().st_mtime >= newest and out.with_suffix(".repos").is_file() and \
                out.with_suffix(".repos").read_text() == "\n".join(r for r, _ in sources):
            return True                                     # already current
        with tempfile.TemporaryDirectory() as tmp:
            # graphify names a merged repo after the folder above graphify-out/, so lay them out that way
            args = []
            for r, g in sources:
                d = Path(tmp) / r / "graphify-out"
                d.mkdir(parents=True)
                (d / "graph.json").symlink_to(g)
                args.append(str(d / "graph.json"))
            part = out.with_suffix(".part.json")
            if len(args) == 1:
                shutil.copyfile(sources[0][1], part)
            else:
                r = subprocess.run(["graphify", "merge-graphs", *args, "--out", str(part)],
                                   capture_output=True, text=True, timeout=600, cwd=tmp)
                if r.returncode != 0 or not part.is_file():
                    print(f"graphs: merge failed for {out.name}: {r.stderr[-300:]}", flush=True)
                    return False
            part.replace(out)
        out.with_suffix(".repos").write_text("\n".join(r for r, _ in sources))
        return True

    def _build_workspace(self):
        out_dir = GRAPHS / "workspace-build"
        stamp = GRAPHS / "workspace.stamp"
        latest = max((p.stat().st_mtime for p in COMPANY.rglob("*") if p.is_file() and "/." not in str(p)),
                     default=0)
        if stamp.is_file() and float(stamp.read_text() or 0) >= latest and (GRAPHS / "workspace.json").is_file():
            return True
        env = dict(os.environ, GRAPHIFY_OUT=str(out_dir), GRAPHIFY_VIZ_NODE_LIMIT="1")
        r = subprocess.run(["graphify", "update", str(COMPANY), "--force"], capture_output=True, text=True,
                           timeout=900, env=env, cwd=str(GRAPHS))
        g = out_dir / "graph.json"
        if r.returncode != 0 or not g.is_file():
            return False
        shutil.copyfile(g, GRAPHS / "workspace.json")
        stamp.write_text(str(latest))
        return True

    async def refresh(self):
        """Bring every agent graph up to date with the hub (cheap when nothing changed)."""
        if not available():
            return
        async with self._lock:
            loop = asyncio.get_running_loop()
            for aid in self.o.agents:
                repos = self.repos_for(aid)
                if repos:
                    await loop.run_in_executor(None, self._merge, repos, GRAPHS / f"{aid}.json")
            try:
                await loop.run_in_executor(None, self._build_workspace)
            except Exception as e:  # the workspace graph is a nicety
                print(f"graphs: workspace graph failed: {e}", flush=True)

    def start(self):
        if os.environ.get("OFFICE_NO_STUDY"):       # test servers: no background builds
            return
        self.o._spawn(self._loop())

    async def _loop(self):
        await asyncio.sleep(3)
        while True:
            try:
                await self.refresh()
            except Exception as e:
                print(f"graphs: {e}", flush=True)
            await asyncio.sleep(WORKSPACE_EVERY_S)

    # ------------------------------------------------------------------ agy wiring
    @staticmethod
    def configure_agy():
        """Register the stdio MCP server "graph" in both agy profiles (idempotent)."""
        if not available() or not shutil.which("agy"):
            return
        cmd = (f'[ -n "$OFFICE_AGENT_GRAPH" ] && [ -f "$OFFICE_AGENT_GRAPH" ] || exit 1; '
               f'PYTHONPATH="{USER_SITE}" exec python3 -m graphify.serve "$OFFICE_AGENT_GRAPH"')
        for home in (AGY_HOME, AGY_HOME_LOCAL):
            env = {k: v for k, v in os.environ.items() if k in ("PATH", "USER", "LANG", "XDG_RUNTIME_DIR",
                                                                 "DBUS_SESSION_BUS_ADDRESS")}
            env["HOME"] = str(home)
            subprocess.run(["agy", "mcp", "add", "graph", "--", "sh", "-c", cmd], env=env,
                           capture_output=True, text=True, timeout=60)
