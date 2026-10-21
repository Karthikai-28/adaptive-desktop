"""Reusable, inspectable mission contracts, kept where agents cannot rewrite them (records.py).

A workflow's repository is its boundary: a run may repeat it but never name another one, and a workflow
saved without a repository never gets one. Hardware and external workflows need the operator's approval
for every run, and only the operator may change a workflow that already exists.
"""
import json
import re
import time

from . import records

RISKS = {"read", "write", "hardware", "external"}
TEMPLATE_FIELDS = ("problem", "bag", "baseline_bag", "simulation_command")
VAR = re.compile(r"\{\{\s*([a-zA-Z][\w-]*)\s*\}\}")


def _id(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def _render(text, inputs):
    def sub(m):
        key = m.group(1)
        if key not in inputs:
            raise ValueError(f"workflow input '{key}' is required")
        return str(inputs[key])[:10_000]
    return VAR.sub(sub, text)


def _template(template):
    """A saved mission template: today only the ROS investigation, whose snapshot is retaken on every run."""
    if not template:
        return {}
    if not isinstance(template, dict) or template.get("kind") != "ros-investigation":
        raise ValueError("unknown workflow template")
    out = {"kind": "ros-investigation"}
    for k in TEMPLATE_FIELDS:
        v = template.get(k, "")
        if not isinstance(v, str) or len(v) > 20_000:
            raise ValueError(f"workflow template field '{k}' must be text under 20,000 characters")
        out[k] = v.strip()
    if not out["problem"]:
        raise ValueError("a ROS investigation workflow needs the problem to investigate")
    return out


class Workflows:
    def __init__(self, office):
        self.office = office
        records.folder("workflows")

    @property
    def root(self):
        return records.folder("workflows")

    def save(self, title, objective, criteria, description="", workflow_id="", agent="", project="", repo="",
             risk="write", allowed_agents=None, template=None, created_by="operator", operator=False):
        wid = _id(workflow_id or title)
        title, objective, description = title.strip(), objective.strip(), description.strip()
        if not wid or not title or not objective:
            raise ValueError("a workflow needs an id, title and objective")
        if len(title) > 200 or len(description) > 2000 or len(objective) > 100_000:
            raise ValueError("keep the title under 200, the description under 2,000 and the objective under "
                             "100,000 characters")
        checks = [str(x).strip() for x in criteria if str(x).strip()]
        if not checks:
            raise ValueError("a workflow needs acceptance criteria")
        if len(checks) > 20 or any(len(x) > 500 for x in checks):
            raise ValueError("use at most 20 acceptance criteria, each under 500 characters")
        if risk not in RISKS:
            raise ValueError(f"risk must be one of: {', '.join(sorted(RISKS))}")
        if agent and agent not in self.office.agents:
            raise ValueError("no such agent")
        if risk == "read" and repo.strip():
            raise ValueError("read-only workflows cannot name a writable repository")
        allowed = list(dict.fromkeys(allowed_agents or []))
        unknown = [x for x in allowed if x not in self.office.agents]
        if unknown:
            raise ValueError(f"unknown allowed agent: {', '.join(unknown)}")
        if agent and allowed and agent not in allowed:
            raise ValueError("the workflow's default agent must be one of its allowed agents")
        repo = self.office.repos.resolve(repo) if repo.strip() else ""
        template = _template(template)
        if self.get(wid) and not operator:
            raise ValueError(f"workflow '{wid}' already exists; only the operator can change it")
        data = {"schema": 1, "id": wid, "title": title, "description": description, "objective": objective,
                "criteria": checks, "agent": agent, "project": project.strip()[:80], "repo": repo, "risk": risk,
                "allowed_agents": allowed, "template": template, "created_by": created_by,
                "updated_at": time.time()}
        records.write_json(self.root / f"{wid}.json", data)
        return data

    def get(self, wid):
        if not wid or _id(wid) != wid:
            return None
        try:
            return json.loads((self.root / f"{wid}.json").read_text())
        except (OSError, ValueError):
            return None

    def list(self):
        out = []
        for p in sorted(self.root.glob("*.json")):
            try:
                out.append(json.loads(p.read_text()))
            except (OSError, ValueError):
                pass
        return out

    async def run(self, wid, inputs=None, agent="", project="", repo="", approved_by="", created_by="operator"):
        from .mission_templates import launch_ros_investigation
        w = self.get(wid)
        if not w:
            raise ValueError("no such workflow")
        inputs = inputs or {}
        if not isinstance(inputs, dict) or len(json.dumps(inputs)) > 100_000:
            raise ValueError("workflow inputs must be a small JSON object")
        allowed = w.get("allowed_agents") or []
        aid = agent or w.get("agent") or (allowed[0] if allowed else next(iter(self.office.agents), ""))
        if not aid:
            raise ValueError("the office has no agents")
        if allowed and aid not in allowed:
            raise ValueError(f"workflow '{wid}' is limited to: {', '.join(allowed)}")
        risk = w.get("risk") or "write"
        if risk in ("hardware", "external") and not approved_by:
            raise ValueError(f"workflow '{wid}' is {risk}: every run needs the operator's approval "
                             "(the operator key in the office app, or `office workflow run --approve` in a terminal)")
        stored_repo = w.get("repo", "")
        run_repo = self.office.repos.resolve(repo) if repo.strip() else stored_repo
        if run_repo != stored_repo:
            raise ValueError("a workflow run cannot widen its repository boundary" if not stored_repo else
                             f"workflow '{wid}' may only change {stored_repo}")
        title = _render(w["title"], inputs)
        common = dict(created_by=created_by, risk=risk, workflow_id=wid, approved_by=approved_by,
                      allowed_agents=allowed)
        project = project or w.get("project", "")
        template = w.get("template") or {}
        if template:
            t = {k: _render(template.get(k, ""), inputs) for k in TEMPLATE_FIELDS}
            return await launch_ros_investigation(self.office, aid, title, t["problem"], t["bag"], project, run_repo,
                                                  t["baseline_bag"], t["simulation_command"],
                                                  criteria=[_render(x, inputs) for x in w["criteria"]], **common)
        return await self.office.add_mission(aid, title, _render(w["objective"], inputs),
                                             [_render(x, inputs) for x in w["criteria"]], project, run_repo, **common)
