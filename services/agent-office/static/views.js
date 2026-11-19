// Agent Office — what the two views (Virtual Office, Command Center) compute from /api/overview and the
// activity API. Pure: no DOM, no fetch, so scripts/verify-agent-office.sh checks it with node.
//
// Progress is only ever what the office really knows: a mission's tasks done out of its tasks so far, the
// time a run has taken and the actions it recorded. A single task has no known share done, so there is no
// percentage for it anywhere.

export const VIEWS = ['office', 'command'];
export const VIEW_LABEL = { office: 'Virtual Office', command: 'Command Center' };
export const normalizeView = (v) => VIEWS.includes(v) ? v : 'office';

// the status words, the same as the server's (office/activity.py desk_state) and the phone's
export const STATES = ['working', 'blocked', 'error', 'paused', 'idle'];
export const STATE_LABEL = { working: 'Working', idle: 'Idle', blocked: 'Blocked', error: 'Error', paused: 'Paused' };
export const stateRank = (s) => { const i = STATES.indexOf(s); return i < 0 ? STATES.length : i; };

export function fmtDur(s) {
  s = Math.max(0, Math.round(Number(s) || 0));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, '0')}s`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m`;
}

// "3 of 5 tasks done" and the share for a bar, or no bar when the mission has no tasks yet
export function missionProgress(m) {
  const total = Math.max(0, m?.total_tasks | 0), done = Math.max(0, m?.done_tasks | 0);
  if (!total) return { text: 'No tasks yet', frac: null, done, total };
  const failed = m.failed_tasks | 0;
  const text = `${done} of ${total} task${total === 1 ? '' : 's'} done` + (failed ? ` · ${failed} failed` : '');
  return { text, frac: Math.min(1, done / total), done, total };
}

// what a desk says about the work under way, without inventing a share done
export function runProgress(a, now) {
  if (!a?.task) return a?.queued_count ? `${a.queued_count} queued` : '';
  const parts = [];
  if (a.running_since) parts.push(`running ${fmtDur(now - a.running_since)}`);
  else parts.push(a.task.status === 'queued' ? 'waiting its turn' : a.task.status);
  if (a.actions) parts.push(`${a.actions} action${a.actions === 1 ? '' : 's'}`);
  if (a.queued_count) parts.push(`${a.queued_count} queued`);
  return parts.join(' · ');
}

// desks in a steady order: who needs you first (blocked, error), then who works, then the rest by roster
export function sortDesks(agents, order = []) {
  const pos = (id) => { const i = order.indexOf(id); return i < 0 ? 1e6 : i; };
  return [...agents].sort((a, b) => stateRank(a.state) - stateRank(b.state) || pos(a.id) - pos(b.id));
}

// Task timeline lanes: one per agent, each run a segment placed by its share of [a, b)
export function lanes(history, a, b, agents = []) {
  const span = Math.max(1, b - a);
  const out = new Map(agents.map(id => [id, []]));
  for (const row of history || []) {
    const segs = out.get(row.agent) || [];
    for (const [s, e, outcome] of row.runs || []) {
      const s0 = Math.max(a, s), e0 = Math.min(b, e ?? b);
      if (e0 <= s0) continue;
      segs.push({ left: 100 * (s0 - a) / span, width: Math.max(0.3, 100 * (e0 - s0) / span), outcome: outcome || 'running',
        task: row.task, seconds: e0 - s0, estimated: !!row.estimated });
    }
    out.set(row.agent, segs);
  }
  for (const segs of out.values()) segs.sort((x, y) => x.left - y.left);
  return out;
}

// hour marks for a timeline axis: [{left %, label}]
export function hourTicks(a, b, every = 3600, label = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })) {
  const span = Math.max(1, b - a), out = [];
  for (let t = Math.ceil(a / every) * every; t < b; t += every) out.push({ left: 100 * (t - a) / span, label: label(t) });
  return out;
}

// the Command Center's top line, from the overview's counts
export function kpis(ov) {
  const c = ov?.counts || {}, ib = ov?.inbox || {};
  const decisions = (ib.NEEDS_ATTENTION || 0);
  return [
    { key: 'active', label: 'Active agents', value: `${c.active || 0}/${c.agents || 0}`, note: `${c.idle || 0} idle` + (c.paused ? ` · ${c.paused} paused` : '') },
    { key: 'missions', label: 'Running missions', value: c.running_missions || 0, note: `${c.queued_missions || 0} queued` },
    { key: 'tasks', label: 'Running tasks', value: c.running_tasks || 0, note: `${c.queued_tasks || 0} queued` },
    { key: 'done', label: 'Completed today', value: c.done_today || 0, note: c.cancelled_today ? `${c.cancelled_today} cancelled` : '' },
    { key: 'failed', label: 'Failed today', value: c.failed_today || 0, note: '', alert: (c.failed_today || 0) > 0 },
    { key: 'blocked', label: 'Blocked agents', value: (c.blocked || 0) + (c.error || 0), note: c.error ? `${c.error} with a failure` : '', alert: (c.blocked || 0) + (c.error || 0) > 0 },
    { key: 'decisions', label: 'Pending decisions', value: decisions, note: ib.critical ? `${ib.critical} critical` : `${ib.IN_PROGRESS || 0} in progress`, alert: decisions > 0 },
  ];
}
