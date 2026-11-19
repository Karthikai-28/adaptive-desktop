// Agent Office — the Command Center: the same office as the Virtual Office, as a compact dashboard.
// Every number comes from the APIs the other views use (/api/overview, /api/activity/*, /api/inbox,
// /api/reports, /api/tokens). Selecting an agent, task or mission opens the same side panel or window as in
// the Virtual Office, so switching views never loses what you were looking at.
import { fmtDur, kpis, lanes, hourTicks, missionProgress, sortDesks, STATE_LABEL } from './views.js';
import { fmt as fmtTokens } from './tokens.js';

const WINDOWS = [['6h', '6 hours', 6 * 3600], ['12h', '12 hours', 12 * 3600], ['24h', '24 hours', 86400]];
const PERIODS = [['today', 'Today'], ['7d', '7 days']];
const OUTCOME = { done: 'Done', failed: 'Failed', running: 'Running', cancelled: 'Cancelled', blocked: 'Blocked', retry: 'Retried', interrupted: 'Interrupted' };

export function createCommand(ctx) {
  const { h, api, face, S, nameOf, openTask, openMission, openMissions, openBoard, openAgent, inbox, reports, tokens } = ctx;
  const C = { ov: null, win: '24h', period: 'today', shown: false, busy: {} };
  try { C.win = localStorage.getItem('office.cc.win') || C.win; C.period = localStorage.getItem('office.cc.period') || C.period; } catch { /* private mode */ }
  const keep = (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } };

  const card = (title, note, tools, ...kids) => h('section', { class: 'cc-card' },
    h('header', null, h('h3', null, title), tools ? h('div', { class: 'cc-tools' }, tools) : null),
    note ? h('p', { class: 'tk-note' }, note) : null, ...kids);
  const seg = (items, cur, pick) => h('div', { class: 'tk-seg small-inline' }, ...items.map(([k, label]) =>
    h('button', { class: cur === k ? 'on' : '', onclick: () => pick(k) }, label)));
  const stateChip = (a) => h('span', { class: `st st-${a.state}`, title: a.state_label }, h('i'), a.state_label || STATE_LABEL[a.state]);

  // ---------------------------------------------------------------- the frame (built once, kept)
  const V = {
    kpis: h('div', { class: 'cc-kpis' }),
    agents: h('div', { class: 'cc-agents' }),
    inbox: h('div', { class: 'ib-list compact' }),
    lanes: h('div', { class: 'cc-lanes' }),
    missions: h('div', { class: 'cc-missions' }),
    worktime: h('div', { class: 'tk-bars' }),
    reports: h('div', { class: 'rp-list' }),
    tokens: h('div'),
    winSeg: h('span'), periodSeg: h('span'),
  };
  const el = h('div', { class: 'cc' },
    V.kpis,
    h('div', { class: 'cc-grid' },
      h('div', { class: 'span2' }, card('Agents', 'Who is on what right now. Select a row for the agent\'s workspace.', null, V.agents)),
      card('Action Inbox', 'Open problems and approvals, most urgent first.',
        h('button', { class: 'act', onclick: () => inbox.open() }, 'Open inbox'), V.inbox),
      h('div', { class: 'span2' }, card('Task timelines', 'Each bar is a run of a task, from start to its end. Select one to open the task.', V.winSeg, V.lanes)),
      card('Missions', 'Progress is tasks done out of the mission\'s tasks so far; the plan can still grow.',
        h('button', { class: 'act', onclick: () => openMissions() }, 'All missions'), V.missions),
      card('Work time', 'Active time per agent (overlapping runs counted once) and how long their tasks waited.', V.periodSeg, V.worktime),
      card('Daily reports', null, h('span', { class: 'cc-tools' }, ...reports.nowButtons()), V.reports),
      card('Tokens and cost', null, h('button', { class: 'act', onclick: () => tokens.open() }, 'Full analytics'), V.tokens)));

  // ---------------------------------------------------------------- parts
  function renderKpis() {
    const goto = { active: () => V.agents.scrollIntoView({ behavior: 'smooth', block: 'center' }), missions: () => openMissions(),
      tasks: () => openBoard(), done: () => openBoard(), failed: () => openBoard(), blocked: () => inbox.open('open'), decisions: () => inbox.open('open') };
    V.kpis.replaceChildren(...kpis(C.ov).map(k => h('button', { class: `tk-kpi click ${k.alert ? 'alert' : ''}`, onclick: goto[k.key] },
      h('span', { class: 'l' }, k.label), h('span', { class: 'v' }, String(k.value)), k.note ? h('span', { class: 'n' }, k.note) : h('span', { class: 'n' }, ' '))));
  }

  function renderAgents() {
    const now = Date.now() / 1000;
    const rows = sortDesks(C.ov.agents, S.order).map(a => h('tr', { class: `click ${S.view.kind === 'agent' && S.view.id === a.id ? 'sel' : ''}`, onclick: () => openAgent(a.id) },
      h('td', null, h('span', { class: 'tk-who' }, face(a.id, 18), h('span', null, h('b', null, a.name), h('small', null, a.role)))),
      h('td', null, stateChip(a)),
      h('td', { class: 'title' }, a.task ? h('a', { class: 'lnk', onclick: (e) => { e.stopPropagation(); openTask(a.task.id); } }, `#${a.task.id} ${a.task.title}`) : h('span', { class: 'muted' }, a.queued_count ? `${a.queued_count} queued` : '—')),
      h('td', { class: 'title' }, a.mission ? h('a', { class: 'lnk', onclick: (e) => { e.stopPropagation(); openMission(a.mission.id); } }, a.mission.title) : h('span', { class: 'muted' }, '—')),
      h('td', { class: 'n' }, a.running_since ? h('span', { 'data-since': a.running_since }, fmtDur(now - a.running_since)) : '—'),
      h('td', { class: 'n' }, a.actions || '—'),
      h('td', { class: 'n' }, fmtDur(a.active_24h_s)),
      h('td', { class: 'n' }, a.blockers.length ? h('span', { class: 'pill failed' }, a.blockers.length) : '—')));
    V.agents.replaceChildren(h('div', { class: 'tk-tablebox' }, h('table', { class: 'tk-table cc-table' },
      h('thead', null, h('tr', null, ...['Agent', 'Status', 'Current task', 'Mission', 'Running for', 'Actions', 'Active 24 h', 'Needs you'].map((t, i) => h('th', { class: i >= 4 ? 'n' : '' }, t)))),
      h('tbody', null, ...rows))),
      C.ov.estimated ? h('p', { class: 'tk-note', style: 'margin:8px 0 0' }, 'Some active time is estimated: work finished before the event journal existed only has its start and finish.') : null);
  }

  function renderMissions() {
    const ms = C.ov.missions || [];
    V.missions.replaceChildren(...(ms.length ? ms.map(m => {
      const p = missionProgress(m);
      return h('button', { class: 'cc-mission', onclick: () => openMission(m.id) },
        h('span', { class: 'cc-mhead' }, h('b', null, m.title), h('span', { class: `pill ${m.status}` }, m.status)),
        p.frac == null ? null : h('span', { class: 'cc-prog' }, h('i', { style: `width:${(100 * p.frac).toFixed(1)}%` })),
        h('small', null, p.text + (m.criteria ? ` · ${m.passed}/${m.criteria} criteria passed` : '')));
    }) : [h('div', { class: 'empty' }, 'No missions this week. Missions group tasks around a checked result.')]));
  }

  async function renderLanes() {
    if (C.busy.lanes) return; C.busy.lanes = true;
    V.winSeg.replaceChildren(seg(WINDOWS.map(w => [w[0], w[1]]), C.win, (k) => { C.win = k; keep('office.cc.win', k); renderLanes(); }));
    try {
      const b = Date.now() / 1000, a = b - WINDOWS.find(w => w[0] === C.win)[2];
      const hist = await api('GET', `/api/activity/history?since=${a}&until=${b}&limit=1000`);
      const label = WINDOWS.find(w => w[0] === C.win)[1];
      const order = sortDesks(C.ov?.agents || [], S.order).map(x => x.id);
      const L = lanes(hist, a, b, order);
      const every = C.win === '24h' ? 4 * 3600 : C.win === '12h' ? 2 * 3600 : 3600;
      const ticks = hourTicks(a, b, every);
      V.lanes.replaceChildren(
        h('div', { class: 'cc-axis' }, h('span'), h('div', { class: 'cc-ticks' }, ...ticks.map(t => h('span', { style: `left:${t.left}%` }, t.label)))),
        ...order.map(id => h('div', { class: 'cc-lane' },
          h('button', { class: 'cc-lname', onclick: () => openAgent(id) }, face(id, 18), nameOf(id)),
          h('div', { class: 'cc-track' }, ...ticks.map(t => h('i', { class: 'cc-grid-line', style: `left:${t.left}%` })),
            ...(L.get(id) || []).map(s => h('button', {
              class: `cc-seg ${s.outcome} ${s.estimated ? 'est' : ''}`, style: `left:${s.left}%;width:${s.width}%`,
              title: `#${s.task.id} ${s.task.title || ''}\n${OUTCOME[s.outcome] || s.outcome} · ${fmtDur(s.seconds)}${s.estimated ? ' (estimated)' : ''}`,
              onclick: () => openTask(s.task.id) })),
            h('i', { class: 'cc-now' })))),
        hist.length ? null : h('div', { class: 'cc-quiet' }, `No task ran in the last ${label}.`),
        h('div', { class: 'tk-legend', style: 'margin-top:8px' }, ...['done', 'running', 'failed', 'cancelled'].map(o => h('span', null, h('i', { class: `cc-key ${o}` }), OUTCOME[o]))));
    } catch (e) { V.lanes.replaceChildren(h('div', { class: 'empty' }, `Couldn't read the timelines: ${e.message}`)); }
    finally { C.busy.lanes = false; }
  }

  async function renderWorktime() {
    if (C.busy.work) return; C.busy.work = true;
    V.periodSeg.replaceChildren(seg(PERIODS, C.period, (k) => { C.period = k; keep('office.cc.period', k); renderWorktime(); }));
    try {
      const b = Date.now() / 1000, a = C.period === 'today' ? (C.ov?.day_start || b - 86400) : b - 7 * 86400;
      const d = await api('GET', `/api/activity/summary?since=${a}&until=${b}`);
      const rows = [...d.agents].sort((x, y) => y.active_s - x.active_s);
      const max = Math.max(1, ...rows.map(r => r.active_s));
      V.worktime.replaceChildren(...rows.map(r => h('div', { class: 'tk-bar click', onclick: () => openAgent(r.agent) },
        h('span', { class: 'lab' }, r.name),
        h('span', { class: 'trk' }, h('i', { class: 'cc-fill', style: `width:${Math.max(0.5, 100 * r.active_s / max)}%` })),
        h('span', { class: 'val' }, fmtDur(r.active_s), h('small', null, ` · ${r.runs} run${r.runs === 1 ? '' : 's'} · waited ${fmtDur(r.queue_s)}`)))),
        d.approvals ? h('p', { class: 'tk-note', style: 'margin:6px 0 0' }, `Waiting for your approval: ${fmtDur(d.approval_wait_s)} over ${d.approvals} request(s).`) : null,
        d.estimated ? h('p', { class: 'tk-note', style: 'margin:6px 0 0' }, 'Includes estimated time for work from before the event journal.') : null);
    } catch (e) { V.worktime.replaceChildren(h('div', { class: 'empty' }, `Couldn't read work time: ${e.message}`)); }
    finally { C.busy.work = false; }
  }

  async function renderTokens() {
    if (C.busy.tok) return; C.busy.tok = true;
    try {
      const a = C.ov?.day_start || Date.now() / 1000 - 86400;
      const d = await api('GET', `/api/tokens?since=${a}`);
      const people = [...(d.agents || [])].sort((x, y) => y.total - x.total).slice(0, 8);
      const max = Math.max(1, ...people.map(p => p.total));
      V.tokens.replaceChildren(
        h('div', { class: 'tk-kpis cc-mini' },
          // the agents' models and Claude (the manager) are counted apart by the ledger: today is both
          h('div', { class: 'tk-kpi' }, h('span', { class: 'l' }, 'Tokens today'), h('span', { class: 'v' }, fmtTokens((d.totals?.total || 0) + (d.claude?.total || 0))),
            h('span', { class: 'n' }, `agents ${fmtTokens(d.totals?.total)} · Claude ${fmtTokens(d.claude?.total)} · ${fmtTokens((d.totals?.calls || 0) + (d.claude?.calls || 0))} calls`)),
          h('div', { class: 'tk-kpi' }, h('span', { class: 'l' }, 'Cost'), h('span', { class: 'v' }, '—'), h('span', { class: 'n' }, 'Not billed per token: subscription plans and local models'))),
        h('div', { class: 'tk-bars', style: 'margin-top:10px' }, ...people.map(p => h('div', { class: 'tk-bar click', onclick: () => tokens.openAgent(p.id) },
          h('span', { class: 'lab' }, nameOf(p.id)), h('span', { class: 'trk' }, h('i', { class: 'cc-fill', style: `width:${Math.max(0.5, 100 * p.total / max)}%` })),
          h('span', { class: 'val' }, fmtTokens(p.total))))),
        people.length ? null : h('div', { class: 'empty' }, 'No model calls today.'));
    } catch (e) { V.tokens.replaceChildren(h('div', { class: 'empty' }, `Couldn't read the ledger: ${e.message}`)); }
    finally { C.busy.tok = false; }
  }

  // ---------------------------------------------------------------- live
  function overview(ov) {
    C.ov = ov;
    if (!C.shown) return;
    renderKpis(); renderAgents(); renderMissions();
  }
  let slow = 0;
  function refreshSlow() {         // the parts read from the activity API and the ledger, not the overview
    if (!C.shown) return;
    renderLanes(); renderWorktime(); renderTokens();
  }
  function show() {
    C.shown = true;
    if (C.ov) { renderKpis(); renderAgents(); renderMissions(); }
    inbox.list(V.inbox, { compact: true, limit: 12 });
    reports.list(V.reports, { limit: 5 });
    refreshSlow();
    clearInterval(slow); slow = setInterval(refreshSlow, 60000);
  }
  function hide() { C.shown = false; clearInterval(slow); }
  // a task changed: its timeline and work time move; at most every few seconds
  let soon = null;
  function taskChanged() { if (!C.shown || soon) return; soon = setTimeout(() => { soon = null; renderLanes(); renderWorktime(); }, 4000); }
  function selected() { if (C.shown && C.ov) renderAgents(); }
  // the ledger announces every model call; the token card follows at most every few seconds
  let tokSoon = null;
  function tokensChanged() { if (!C.shown || tokSoon) return; tokSoon = setTimeout(() => { tokSoon = null; renderTokens(); }, 5000); }
  return { el, show, hide, overview, taskChanged, tokensChanged, selected };
}
