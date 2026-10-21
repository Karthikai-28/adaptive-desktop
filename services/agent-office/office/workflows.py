"""Reusable, inspectable mission contracts stored in the shared Office workspace."""
import json
import os
import re
import time
from pathlib import Path

from .config import COMPANY

WORKFLOWS = COMPANY / "workflows"
RISKS = {"read", "write", "hardware", "external"}


def _id(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def _render(text, inputs):
    def sub(m):
        key = m.group(1)
        if key not in inputs:
            raise ValueError(f"workflow input '{key}' is required")
        return str(inputs[key])[:10_000]
    return re.sub(r"\{\{\s*([a-zA-Z][\w-]*)\s*\}\}", sub, text)


class Workflows:
    def __init__(self, office):
        self.office = office
        WORKFLOWS.mkdir(parents=True, exist_ok=True)

    def save(self, title, objective, criteria, description="", workflow_id="", agent="", project="", repo="",
             risk="write", allowed_agents=None):
        wid = _id(workflow_id or title)
        if not wid or not title.strip() or not objective.strip():
            raise ValueError("a workflow needs an id, title and objective")
        checks = [str(x).strip() for x in criteria if str(x).strip()]
        if not checks:
            raise ValueError("a workflow needs acceptance criteria")
        if risk not in RISKS:
            raise ValueError(f"risk must be one of: {', '.join(sorted(RISKS))}")
        if agent and agent not in self.office.agents:
            raise ValueError("no such agent")
        if risk == "read" and repo.strip():
            raise ValueError("read-only workflows cannot name a writable repository")
        requested = list(dict.fromkeys(allowed_agents or []))
        unknown = [x for x in requested if x not in self.office.agents]
        if unknown:
            raise ValueError(f"unknown allowed agent: {', '.join(unknown)}")
        allowed = requested
        data = {"schema": 1, "id": wid, "title": title.strip()[:200], "description": description.strip()[:2000],
                "objective": objective.strip()[:20_000], "criteria": checks[:20], "agent": agent,
                "project": project.strip()[:80], "repo": repo.strip(), "risk": risk,
                "allowed_agents": allowed, "updated_at": time.time()}
        p, tmp = WORKFLOWS / f"{wid}.json", WORKFLOWS / f"{wid}.tmp"
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        os.replace(tmp, p)
        return data

    def get(self, wid):
        if _id(wid or "") != wid:
            return None
        try:
            return json.loads((WORKFLOWS / f"{wid}.json").read_text())
        except (OSError, ValueError):
            return None

    def list(self):
        out = []
        for p in sorted(WORKFLOWS.glob("*.json")):
            try:
                out.append(json.loads(p.read_text()))
            except (OSError, ValueError):
                pass
        return out

    async def run(self, wid, inputs=None, agent="", project="", repo="", approved=False):
        w = self.get(wid)
        if not w:
            raise ValueError("no such workflow")
        inputs = inputs or {}
        if not isinstance(inputs, dict) or len(json.dumps(inputs)) > 100_000:
            raise ValueError("workflow inputs must be a small JSON object")
        aid = agent or w.get("agent") or next(iter(self.office.agents))
        allowed = w.get("allowed_agents") or []
        if allowed and aid not in allowed:
            raise ValueError(f"workflow '{wid}' is limited to: {', '.join(allowed)}")
        if w.get("risk") in ("hardware", "external") and not approved:
            raise ValueError(f"workflow '{wid}' requires explicit approval for each run")
        stored_repo = w.get("repo", "")
        if stored_repo and repo and repo != stored_repo:
            raise ValueError("a workflow run cannot widen its repository boundary")
        run_repo = repo or stored_repo
        if w.get("risk") == "read" and run_repo:
            raise ValueError("read-only workflows cannot use a writable repository")
        objective = _render(w["objective"], inputs)
        criteria = [_render(x, inputs) for x in w["criteria"]]
        return await self.office.add_mission(aid, _render(w["title"], inputs), objective, criteria,
                                             project or w.get("project", ""), run_repo)
