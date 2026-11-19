// Agent Office — the Action Inbox on the desktop: everything that needs the owner (a failed or blocked task, an
// approval waiting, a quota or limit stop), one item per problem, from NEEDS_ATTENTION through IN_PROGRESS to
// RESOLVED. The same items, words and rules as the phone (OfficeScreens.kt) and the API (office/journal.py).
//
// Acknowledging says "I'm on it" and nothing more: it never approves or runs anything. Approving a request
// runs it, so it needs the operator key, exactly like approving a hardware workflow run.

const STATE_LABEL = { NEEDS_ATTENTION: 'Needs attention', IN_PROGRESS: 'In progress', RESOLVED: 'Resolved' };
const STATE_CLASS = { NEEDS_ATTENTION: 'failed', IN_PROGRESS: 'running', RESOLVED: 'done' };
const KIND_LABEL = {
  failed: 'Task failed', blocked: 'Task blocked', approval: 'Approval', quota: 'Quota', limit: 'Limit',
  error: 'Office error', 'mission-failed': 'Mission failed', 'mission-unverified': 'Mission unverified',
};
const FILTERS = [['open', 'Open', 'NEEDS_ATTENTION,IN_PROGRESS'], ['resolved', 'Resolved', 'RESOLVED'], ['all', 'All', '']];

export function createInbox(ctx) {
  const { h, api, nameOf, toast, openModal, closeModal, modalKind, openTask, openMission, askOperatorKey, operatorKey, ago, clock } = ctx;
  const I = { filter: 'open', itemId: null, lists: new Set() };

  const kindOf = (it) => KIND_LABEL[it.kind] || it.kind;
  const row = (it, compact) => h('button', { class: `ib-row ${it.priority}`, onclick: () => openItem(it.id) },
    h('span', { class: `ib-pri ${it.priority}`, title: `${it.priority} priority` }),
    h('span', { class: 'ib-main' },
      h('b', null, it.title || kindOf(it)),
      h('small', null, [kindOf(it), it.agent ? nameOf(it.agent) : '', it.task_id ? `task #${it.task_id}` : '', it.mission_id ? `mission #${it.mission_id}` : '',
        ago(it.updated_at || it.created_at)].filter(Boolean).join(' · '))),
    compact && it.state === 'NEEDS_ATTENTION' ? null : h('span', { class: `pill ${STATE_CLASS[it.state]}` }, STATE_LABEL[it.state] || it.state));

  // a list inside any element (the Command Center's card, the inbox window); it redraws itself on changes
  async function list(el, { state = 'NEEDS_ATTENTION,IN_PROGRESS', limit = 30, compact = false, empty = 'Nothing needs you. Problems and approvals appear here.' } = {}) {
    el._inbox = { state, limit, compact, empty };
    I.lists.add(el);
    try {
      const d = await api('GET', `/api/inbox?limit=${limit}${state ? `&state=${state}` : ''}`);
      el.replaceChildren(...(d.items.length ? d.items.map(it => row(it, compact)) : [h('div', { class: 'empty' }, empty)]),
        d.total > d.items.length ? h('button', { class: 'act', style: 'margin-top:8px;width:100%', onclick: open }, `All ${d.total}`) : null);
      return d;
    } catch (e) { el.replaceChildren(h('div', { class: 'empty' }, `Couldn't read the inbox: ${e.message}`)); }
  }

  function open(filter) {
    if (filter) I.filter = filter;
    const box = h('div', { class: 'ib-list' });
    const seg = h('div', { class: 'tk-seg' }, ...FILTERS.map(([k, label]) =>
      h('button', { class: I.filter === k ? 'on' : '', onclick: () => open(k) }, label)));
    openModal('inbox', 'Action Inbox', h('div', null,
      h('p', { class: 'tk-note', style: 'margin:0 0 12px' }, 'One item per problem. Acknowledge says you are on it; it never approves or runs anything.'),
      box), [seg], false);
    list(box, { state: FILTERS.find(f => f[0] === I.filter)[2], limit: 200 });
  }

  async function act(id, action, note = '') {
    try {
      await api('POST', `/api/inbox/${id}/${action}`, { note });
      toast({ ack: 'Acknowledged', resolve: 'Resolved', dismiss: 'Dismissed', reopen: 'Reopened', decline: 'Declined' }[action] || 'Done', 'ok');
      openItem(id);
    } catch (e) { toast(e.message, 'error'); }
  }
  async function approve(id) {
    if (!operatorKey() && !askOperatorKey('Approving a request')) return;
    try {
      const d = await api('POST', `/api/inbox/${id}/approve`);
      toast(`Approved: ${d.item.resolution || 'done'}`, 'ok');
      openItem(id);
    } catch (e) { toast(e.message, 'error'); }
  }

  async function openItem(id) {
    I.itemId = id;
    let it;
    try { it = await api('GET', `/api/inbox/${id}`); } catch (e) { return toast(e.message, 'error'); }
    if (I.itemId !== id) return;
    const kv = (k, v) => v || v === 0 ? [h('div', null, k), h('div', null, v)] : [];
    const when = (ts) => ts ? new Date(ts * 1000).toLocaleString() : '';
    const approval = it.kind === 'approval';
    const body = h('div', null,
      h('div', { class: 'kv' },
        ...kv('State', h('span', { class: `pill ${STATE_CLASS[it.state]}` }, STATE_LABEL[it.state])),
        ...kv('Kind', kindOf(it)), ...kv('Priority', it.priority),
        ...kv('Agent', it.agent ? nameOf(it.agent) : ''),
        ...kv('Task', it.task_id ? h('a', { class: 'lnk', onclick: () => openTask(it.task_id) }, `#${it.task_id}`) : ''),
        ...kv('Mission', it.mission_id ? h('a', { class: 'lnk', onclick: () => openMission(it.mission_id) }, `#${it.mission_id}`) : ''),
        ...kv('Opened', when(it.created_at)), ...kv('Acknowledged', it.acknowledged_at ? `${when(it.acknowledged_at)} by ${nameOf(it.acknowledged_by)}` : ''),
        ...kv('Resolved', it.resolved_at ? `${when(it.resolved_at)} · ${it.resolution}` : ''),
        ...kv('Reopened', it.generation > 1 ? `${it.generation - 1} time(s)` : '')),
      it.text ? h('div', { class: 'box' }, it.text) : null,
      approval && it.state !== 'RESOLVED' ? h('p', { class: 'tk-note', style: 'margin-top:10px' },
        'Approve runs the request now and needs the operator key (office operator-key). Acknowledge only marks it in progress.') : null,
      it.live && it.state !== 'RESOLVED' ? h('p', { class: 'tk-note', style: 'margin-top:10px' }, 'The problem is still there, so it resolves by itself once it is fixed (a retry that succeeds, the quota back).') : null,
      it.history?.length ? [h('div', { class: 'section' }, 'History'), h('div', { class: 'feed' }, ...it.history.slice(-60).map(e =>
        h('div', { class: `ev ${e.severity === 'error' ? 'error' : ''}` }, h('span', { class: 't' }, clock(e.ts)),
          h('span', { class: 'w' }, e.type), h('span', { class: 'x' }, [e.text, e.actor ? `(${nameOf(e.actor)})` : ''].filter(Boolean).join(' ')))))] : null);
    const b = (label, fn, cls = '') => h('button', { class: `act ${cls}`, style: 'flex:none;padding:0 14px', onclick: fn }, label);
    const foot = [];
    if (it.state === 'NEEDS_ATTENTION') foot.push(b('Acknowledge', () => act(id, 'ack')));
    if (it.state !== 'RESOLVED') {
      if (approval) { foot.push(b('Decline', () => act(id, 'decline'), 'danger')); if (it.has_request) foot.push(b('Approve and run', () => approve(id), 'primary')); }
      else {
        if (!it.live) foot.push(b('Resolve', () => act(id, 'resolve')));
        foot.push(b('Dismiss', () => { if (!it.live || confirm('The problem is still there. Dismiss it anyway?')) act(id, 'dismiss'); }));
      }
    } else if (!approval) foot.push(b('Reopen', () => act(id, 'reopen')));
    foot.push(b('All items', () => open()));
    openModal('inbox-item', it.title || kindOf(it), body, foot);
    I.itemId = id;
  }

  // live: an inbox message changes an item; redraw what is on screen
  let timer = null;
  function changed(m) {
    if (timer) return;
    timer = setTimeout(() => {
      timer = null;
      for (const el of [...I.lists]) { if (!el.isConnected) { I.lists.delete(el); continue; } list(el, el._inbox); }
      if (modalKind() === 'inbox-item' && m?.item?.id === I.itemId) openItem(I.itemId);
    }, 400);
  }
  return { list, open, openItem, changed, closeModal };
}
