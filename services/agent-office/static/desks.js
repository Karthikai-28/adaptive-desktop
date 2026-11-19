// Agent Office — the desks of the Virtual Office: one card per agent along the office floor, saying who they
// are, their status word, the task and mission at their desk, how long this run has gone, what it has done so
// far, and the last thing they did. Selecting a desk opens that agent's workspace in the side panel.
// Data: /api/overview (office/tracker.py), the same the Command Center and the phone read.
import { fmtDur, missionProgress, STATE_LABEL } from './views.js';

export function createDesks(ctx) {
  const { h, face, S, openAgent, openTask, openMission, openInboxItem, ago } = ctx;
  const el = h('div', { id: 'desks', class: 'desks', role: 'list', 'aria-label': 'Agent desks' });
  let last = null;

  function desk(a, now) {
    const sel = S.view.kind === 'agent' && S.view.id === a.id;
    const m = a.mission ? missionProgress(a.mission) : null;
    const recent = (a.recent || [])[0];
    const stop = (fn) => (e) => { e.stopPropagation(); fn(); };
    return h('div', { class: `desk st-${a.state} ${sel ? 'sel' : ''}`, role: 'listitem', tabindex: '0', 'data-id': a.id,
      onclick: () => openAgent(a.id), onkeydown: (e) => { if (e.key === 'Enter') openAgent(a.id); } },
      h('div', { class: 'dk-head' }, face(a.id, 30),
        h('div', { class: 'dk-who' }, h('b', null, a.name), h('small', null, a.role)),
        // the chip has the short word; why (the blocker's title) is on the line below
        h('span', { class: `st st-${a.state}`, title: a.state_label }, h('i'), a.state === 'blocked' || a.state === 'error' ? STATE_LABEL[a.state] : a.state_label)),
      a.task
        ? h('a', { class: 'dk-task lnk', title: a.task.title, onclick: stop(() => openTask(a.task.id)) }, `#${a.task.id} ${a.task.title}`)
        : h('div', { class: 'dk-task muted' }, a.queued_count ? `${a.queued_count} task(s) waiting` : 'No task'),
      m ? h('a', { class: 'dk-mission lnk', title: `${a.mission.title}: ${m.text}`, onclick: stop(() => openMission(a.mission.id)) },
        h('span', { class: 'dk-mt' }, a.mission.title),
        m.frac == null ? null : h('span', { class: 'cc-prog' }, h('i', { style: `width:${(100 * m.frac).toFixed(1)}%` })),
        h('small', null, m.text)) : null,
      h('div', { class: 'dk-run' },
        a.running_since ? [h('span', { class: 'dk-timer', 'data-since': a.running_since }, fmtDur(now - a.running_since)), ' running'] : null,
        a.actions ? h('span', null, ` · ${a.actions} action${a.actions === 1 ? '' : 's'}`) : null,
        a.queued_count && a.task ? h('span', null, ` · ${a.queued_count} queued`) : null,
        !a.running_since && !a.task ? h('span', { class: 'muted' }, `${fmtDur(a.active_24h_s)} active in 24 h`) : null),
      h('div', { class: 'dk-recent', title: recent ? recent.text : '' },
        recent ? [h('span', { class: 'muted' }, ago(recent.ts)), ' ', recent.text] : h('span', { class: 'muted' }, 'Nothing yet')),
      a.blockers.length ? h('button', { class: 'dk-alert', onclick: stop(() => openInboxItem(a.blockers[0].id)) },
        a.blockers.length === 1 ? a.blockers[0].title || 'Needs you' : `${a.blockers.length} items need you`) : null);
  }

  function render(ov = last) {
    if (!ov) return;
    last = ov;
    const now = Date.now() / 1000;
    const keepScroll = el.scrollLeft;
    // desks stay where they are (roster order): a status change never moves a desk
    const pos = (id) => { const i = S.order.indexOf(id); return i < 0 ? 1e6 : i; };
    el.replaceChildren(...[...ov.agents].sort((a, b) => pos(a.id) - pos(b.id)).map(a => desk(a, now)));
    el.scrollLeft = keepScroll;
  }
  return { el, render, agent: (id) => last?.agents.find(a => a.id === id) || null };
}
