// Agent Office — token usage: who spends tokens on what, live from the office's token ledger.
// The page asks /api/tokens (the team) and /api/tokens/agent/<id> (one person) and redraws whenever the
// ledger says something changed (a `tokens` message on the socket). Every provider (Gemini, a local model,
// whatever config.json adds later) is counted on its own: the provider filter narrows every number on the
// page to one of them, and the team view opens with one summary per provider.

const NS = 'http://www.w3.org/2000/svg';
const compact = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 });
export const fmt = (n) => compact.format(Math.round(n || 0));
const num = (n) => Math.round(n || 0).toLocaleString('en');
const pct = (x) => `${(100 * (x || 0)).toFixed(x >= 0.995 || x < 0.1 ? 1 : 0)}%`;

export const WINDOWS = [['1h', 'Last hour', 3600], ['6h', '6 hours', 6 * 3600], ['24h', '24 hours', 86400], ['7d', '7 days', 7 * 86400], ['all', 'All time', 0]];
const KIND = {
  task: ['Tasks', '#5865f2'], study: ['Study sessions', '#a46cf0'], meeting: ['Meetings', '#38bdf8'],
  chat: ['Direct messages', '#2fb67c'], review: ['Reviewing work', '#f5a524'], minutes: ['Meeting notes', '#8b9cff'],
  other: ['Other', '#b9bdd0'],
};
const STEP = {
  run_command: 'Run commands', view_file: 'Read files', replace_file_content: 'Edit files', multi_replace_file_content: 'Edit files',
  write_to_file: 'Write files', answer: 'Answer / report', manage_task: 'Update its to-do list', call_mcp_tool: 'Code-graph lookups',
  search_web: 'Search the web', read_url_content: 'Read web pages', schedule: 'Wait', generate_image: 'Generate images',
  invoke_subagent: 'Start helpers', manage_subagents: 'Manage helpers', define_subagent: 'Set up helpers', send_message: 'Send messages', list_dir: 'List folders', grep_search: 'Search files',
  find_by_name: 'Find files', Read: 'Read files', Grep: 'Search files', Glob: 'Find files', Edit: 'Edit files', Write: 'Write files',
  shell: 'Run commands', 'office assign': 'Assign tasks', 'office status': 'Check team status', 'office tasks': 'List tasks',
  'office show': 'Open a task', 'office cancel': 'Cancel tasks', 'office ask': 'Ask an agent', 'office log': 'Read activity',
  'office meeting': 'Run meetings', 'office retry': 'Retry tasks', 'office help': 'Read office help',
};
export const stepName = (s) => STEP[s] || String(s).replace(/_/g, ' ');
const kindName = (k) => (KIND[k] || [k])[0];
const kindColor = (k) => (KIND[k] || [0, '#b9bdd0'])[1];
const MODEL = (m) => { const x = /^claude-(opus|sonnet|haiku|fable)-(\d+)(?:-(\d+))?/i.exec(m || ''); return x ? `${x[1][0].toUpperCase()}${x[1].slice(1)} ${x[2]}${x[3] ? '.' + x[3] : ''}` : /gemini/i.test(m) ? 'Gemini' : m; };

const ENGINE_COLOR = { agy: '#4285f4', ollama: '#2fb67c', claude: '#d97757' };
const SPARE = ['#a46cf0', '#f5a524', '#38bdf8', '#e2557a'];

export function createTokens(ctx) {
  const { h, api, face, iconEl, S, MGR, openModal, modalKind, openTask } = ctx;
  const T = { win: 'all', prov: '', view: 'team', agent: null, data: null, busy: false, pending: false, version: -1, box: null };
  try { T.win = localStorage.getItem('office.tokens.win') || 'all'; T.prov = localStorage.getItem('office.tokens.prov') || ''; } catch { /* private mode */ }
  const provs = () => [...(S.providers || []), { id: 'claude', label: 'Claude', engine: 'claude', model: '' }];
  const provOf = (id) => provs().find(p => p.id === id);
  const provName = (id) => provOf(id)?.label || id;
  const provColor = (id) => { const p = provOf(id); if (p && ENGINE_COLOR[p.engine] && provs().filter(q => q.engine === p.engine).length === 1) return ENGINE_COLOR[p.engine]; const i = provs().findIndex(q => q.id === id); return SPARE[(i < 0 ? 0 : i) % SPARE.length]; };
  const provQuery = () => T.prov ? `&provider=${encodeURIComponent(T.prov)}` : '';
  const provSplit = (m) => { const e = Object.entries(m || {}).filter(([, v]) => v).sort((a, b) => b[1] - a[1]); return e.length > 1 || (e.length === 1 && !T.prov) ? e.map(([k, v]) => `${provName(k)} ${fmt(v)}`).join(' · ') : ''; };
  const since = () => { const w = WINDOWS.find(x => x[0] === T.win); return w && w[2] ? Date.now() / 1000 - w[2] : 0; };
  const nameOf = (id) => id === 'other' ? 'Setup & tests' : (S.roster[id]?.name || id);
  const colorOf = (id) => id === 'other' ? '#b9bdd0' : (S.roster[id]?.look?.shirt || '#8b90a8');
  const roleOf = (id) => id === MGR ? 'Manager · Claude' : id === 'other' ? 'Office test runs, not tied to an agent' : (S.roster[id]?.role || '');
  const windowLabel = () => (WINDOWS.find(x => x[0] === T.win) || WINDOWS[4])[1];

  // ---------------------------------------------------------------- small pieces
  const kpi = (label, value, note, cls) => h('div', { class: `tk-kpi ${cls || ''}` }, h('span', { class: 'l' }, label), h('span', { class: 'v' }, value), note ? h('span', { class: 'n' }, note) : null);
  const card = (title, note, ...kids) => h('div', { class: 'tk-card' }, h('h3', null, title), note ? h('p', { class: 'tk-note' }, note) : null, ...kids);
  const legend = (items) => h('div', { class: 'tk-legend' }, ...items.map(([n, c]) => h('span', null, h('i', { style: `background:${c}` }), n)));
  const stack = (parts, max, total) => {
    const bar = h('div', { class: 'tk-stack', style: `width:${Math.max(1, 100 * total / (max || 1))}%` });
    for (const [k, v, c, label] of parts) if (v > 0) bar.append(h('i', { style: `flex:${v};background:${c}`, title: `${label}: ${num(v)} tokens` }));
    return h('div', { class: 'tk-stackwrap' }, bar);
  };
  const bars = (rows, { label, value, note, color, onClick }) => {
    const max = Math.max(1, ...rows.map(value));
    return h('div', { class: 'tk-bars' }, ...rows.map(r => h('div', { class: `tk-bar ${onClick ? 'click' : ''}`, onclick: onClick ? () => onClick(r) : null },
      h('span', { class: 'lab', title: label(r) }, label(r)),
      h('span', { class: 'trk' }, h('i', { style: `width:${Math.max(0.5, 100 * value(r) / max)}%;background:${color ? color(r) : 'var(--accent)'}` })),
      h('span', { class: 'val' }, fmt(value(r)), note ? h('small', null, note(r)) : null))));
  };
  const empty = (text) => h('div', { class: 'empty' }, text);
  const svg = (tag, attrs = {}) => { const e = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); return e; };
  const ticks = (max, n = 4) => {
    if (max <= 0) return [0];
    const step = Math.pow(10, Math.floor(Math.log10(max / n)));
    const nice = [1, 2, 2.5, 5, 10].map(m => m * step).find(s => max / s <= n) || step * 10;
    const out = []; for (let v = 0; v <= max + 1e-9; v += nice) out.push(v); return out;
  };
  const tipEl = (box) => { let t = box.querySelector('.tk-tip'); if (!t) { t = h('div', { class: 'tk-tip hidden' }); box.append(t); } return t; };
  const showTip = (box, ev, title, lines) => {
    const t = tipEl(box);
    t.replaceChildren(h('b', null, title), ...lines.map(([c, n, v]) => h('div', null, c ? h('i', { style: `background:${c}` }) : null, n ? `${n}: ` : '', v)));
    t.classList.remove('hidden');
    const b = box.getBoundingClientRect();
    let x = ev.clientX - b.left + 12; const y = Math.max(0, ev.clientY - b.top - 10);
    if (x + t.offsetWidth > b.width) x = Math.max(0, ev.clientX - b.left - t.offsetWidth - 12);
    t.style.left = `${x}px`; t.style.top = `${y}px`;
  };

  // stacked columns over time, one colour per agent
  function timeline(tl, ids) {
    const box = h('div', { class: 'tk-chart' });
    const draw = () => {
      box.querySelectorAll('svg').forEach(s => s.remove());
      const W = Math.max(280, box.clientWidth || 600), H = 190, bottom = 20;
      const totals = tl.buckets.map(b => Object.values(b.by).reduce((a, v) => a + v, 0));
      const max = Math.max(1, ...totals);
      const tk = ticks(max), top = tk[tk.length - 1] || 1;
      const s = svg('svg', { width: '100%', height: H, viewBox: `0 0 ${W} ${H}` });
      box.prepend(s);
      const lab = svg('text', { 'font-size': 11 }); s.append(lab);
      const left = Math.max(...tk.map(v => { lab.textContent = fmt(v); return lab.getComputedTextLength(); })) + 8; lab.remove();
      const y = (v) => (H - bottom) - (H - bottom - 6) * v / top;
      for (const v of tk) {
        s.append(svg('line', { x1: left, x2: W, y1: y(v), y2: y(v), stroke: '#eceef5' }));
        const t = svg('text', { x: left - 6, y: y(v) + 4, 'text-anchor': 'end', 'font-size': 11, fill: '#6b7088' }); t.textContent = fmt(v); s.append(t);
      }
      const n = tl.buckets.length, bw = (W - left) / n, gap = Math.min(3, bw * 0.2);
      const fmtT = (t) => { const d = new Date(t * 1000); return tl.size >= 86400 / 4 && d.getHours() === 0 ? d.toLocaleDateString([], { month: 'short', day: 'numeric' }) : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); };
      const every = Math.max(1, Math.ceil(n / Math.floor((W - left) / 64)));
      tl.buckets.forEach((b, i) => {
        let acc = 0;
        const x = left + i * bw + gap / 2;
        for (const id of ids) {
          const v = b.by[id] || 0; if (!v) continue;
          const r = svg('rect', { x, width: Math.max(1, bw - gap), y: y(acc + v), height: Math.max(0.5, y(acc) - y(acc + v)), fill: colorOf(id) });
          r.addEventListener('mousemove', (ev) => showTip(box, ev, fmtT(b.t), ids.filter(q => b.by[q]).map(q => [colorOf(q), nameOf(q), fmt(b.by[q])])));
          r.addEventListener('mouseleave', () => tipEl(box).classList.add('hidden'));
          s.append(r); acc += v;
        }
        if (i % every === 0) { const t = svg('text', { x: x + bw / 2, y: H - 5, 'text-anchor': 'middle', 'font-size': 11, fill: '#6b7088' }); t.textContent = fmtT(b.t); s.append(t); }
      });
    };
    requestAnimationFrame(draw);
    return box;
  }

  // context sent per model call, in order: it climbs as a conversation grows and drops when one starts over
  function contextChart(points) {
    const box = h('div', { class: 'tk-chart' });
    const draw = () => {
      box.querySelectorAll('svg').forEach(s => s.remove());
      if (!points.length) return;
      const W = Math.max(280, box.clientWidth || 600), H = 170, bottom = 18;
      const max = Math.max(1, ...points.map(p => p.ctx));
      const tk = ticks(max), top = tk[tk.length - 1] || 1;
      const s = svg('svg', { width: '100%', height: H, viewBox: `0 0 ${W} ${H}` }); box.prepend(s);
      const lab = svg('text', { 'font-size': 11 }); s.append(lab);
      const left = Math.max(...tk.map(v => { lab.textContent = fmt(v); return lab.getComputedTextLength(); })) + 8; lab.remove();
      const y = (v) => (H - bottom) - (H - bottom - 6) * v / top;
      const x = (i) => left + 4 + (W - left - 8) * (points.length === 1 ? 0.5 : i / (points.length - 1));
      for (const v of tk) {
        s.append(svg('line', { x1: left, x2: W, y1: y(v), y2: y(v), stroke: '#eceef5' }));
        const t = svg('text', { x: left - 6, y: y(v) + 4, 'text-anchor': 'end', 'font-size': 11, fill: '#6b7088' }); t.textContent = fmt(v); s.append(t);
      }
      const a = svg('text', { x: left + 4, y: H - 4, 'font-size': 11, fill: '#6b7088' }); a.textContent = new Date(points[0].ts * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }); s.append(a);
      const z = svg('text', { x: W - 4, y: H - 4, 'font-size': 11, fill: '#6b7088', 'text-anchor': 'end' }); z.textContent = 'latest call'; s.append(z);
      const w = Math.max(1, (W - left - 8) / points.length - 0.5);
      points.forEach((p, i) => {
        const r = svg('rect', { x: x(i) - w / 2, width: w, y: y(p.ctx), height: Math.max(0.5, y(0) - y(p.ctx)), fill: kindColor(p.kind), opacity: 0.85 });
        r.addEventListener('mousemove', (ev) => showTip(box, ev, new Date(p.ts * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' }),
          [[kindColor(p.kind), null, kindName(p.kind)], [null, 'Context sent', num(p.ctx)], [null, 'Output', num(p.out)]]));
        r.addEventListener('mouseleave', () => tipEl(box).classList.add('hidden'));
        s.append(r);
      });
    };
    requestAnimationFrame(draw);
    return box;
  }

  // ---------------------------------------------------------------- the team
  function teamView(d) {
    const t = d.totals, c = d.claude;
    const scope = T.prov ? provName(T.prov) : 'Agent';
    const agents = d.agents;
    const max = Math.max(1, ...agents.map(a => a.total));
    const now = agents.reduce((a, x) => a + x.last10m, 0);
    const ids = agents.map(a => a.id);
    const kindsUsed = Object.keys(KIND).filter(k => agents.some(a => a.kinds[k]));
    const outcomes = Object.entries(d.outcomes || {}).map(([k, v]) => ({ k, ...v })).sort((a, b) => b.total - a.total);
    const statusName = { done: 'Finished', failed: 'Failed', cancelled: 'Cancelled', queued: 'Waiting (retries)', running: 'Running now' };
    return h('div', { class: 'tk' },
      card('By provider', 'Each model provider is counted on its own. Click one to see only its usage.',
        h('div', { class: 'tk-kpis tk-provs' }, ...(d.providers || []).filter(p => p.calls || p.engine !== 'claude').map(p => {
          const el = kpi(p.label, fmt(p.total), `${p.model ? p.model + ' · ' : ''}${num(p.calls)} calls · ${fmt(p.new)} new`, `${p.last10m ? 'live' : ''} ${T.prov === p.id ? 'on' : ''} click`);
          el.style.borderTop = `3px solid ${provColor(p.id)}`;
          el.onclick = () => setProv(T.prov === p.id ? '' : p.id);
          return el;
        }))),
      h('div', { class: 'tk-kpis' },
        kpi(`${scope} tokens processed`, fmt(t.total), `${windowLabel().toLowerCase()} · all agents`),
        kpi('New tokens', fmt(t.new), 'fresh input + output'),
        kpi('Re-read context', pct(t.total ? t.cached / t.total : 0), 'of every token: the conversation sent again each step'),
        kpi('Model calls', num(t.calls), `avg ${fmt(t.avg_ctx)} tokens of context each`),
        kpi('Using now', fmt(now), 'tokens in the last 10 minutes', now ? 'live' : ''),
        T.prov && T.prov !== 'claude' ? null : kpi('Claude (manager)', fmt(c.total), `${num(c.calls)} calls · avg ${fmt(c.avg_ctx)} context`)),
      card('Who uses the most', 'All tokens, split by the kind of work. Click a person for the full breakdown.',
        legend(kindsUsed.map(k => [kindName(k), kindColor(k)])),
        h('div', { class: 'tk-team' }, ...agents.map(a => h('button', { class: 'tk-row', onclick: () => openAgent(a.id) },
          a.id === 'other' ? h('span', { class: 'tk-face blank' }) : face(a.id, 32),
          h('span', { class: 'tk-name' }, h('b', null, nameOf(a.id)), h('small', null, roleOf(a.id))),
          stack(Object.keys(KIND).map(k => [k, a.kinds[k] || 0, kindColor(k), kindName(k)]), max, a.total),
          h('span', { class: 'nums' }, h('b', null, fmt(a.total)), h('small', null, `${fmt(a.new)} new · ${num(a.calls)} calls`), provSplit(a.providers) ? h('small', null, provSplit(a.providers)) : null),
          h('span', { class: `now ${a.last10m ? 'on' : ''}`, title: 'Tokens in the last 10 minutes' }, a.last10m ? fmt(a.last10m) : '—'))))),
      card('When', `Tokens per ${d.timeline.size >= 3600 ? (d.timeline.size === 3600 ? 'hour' : `${d.timeline.size / 3600} hours`) : `${d.timeline.size / 60} minutes`}, by person.`,
        legend(ids.map(id => [nameOf(id), colorOf(id)])), timeline(d.timeline, ids)),
      h('div', { class: 'tk-grid' },
        card('Where the tokens go', 'The step each model call chose. Every step re-sends the whole conversation, so many small steps cost the most.',
          bars(d.steps.slice(0, 10), { label: r => stepName(r.step), value: r => r.total, note: r => ` ${num(r.calls)} calls` })),
        card('By kind of work', T.prov ? `${provName(T.prov)} only.` : 'All agents, every provider.',
          bars(Object.entries(d.kinds).map(([k, v]) => ({ k, v })).sort((a, b) => b.v - a.v), { label: r => kindName(r.k), value: r => r.v, color: r => kindColor(r.k) })),
        card('By project', 'Assigned tasks only.',
          d.projects.length ? bars(d.projects.slice(0, 8), { label: r => r.project, value: r => r.total, note: r => ` ${fmt(r.new)} new` }) : empty('No project work in this window.')),
        card('By how tasks ended', 'Tokens spent on tasks that finished, failed or are still waiting.',
          outcomes.length ? bars(outcomes, { label: r => statusName[r.k] || r.k, value: r => r.total, color: r => ['failed', 'cancelled', 'queued'].includes(r.k) ? 'var(--err)' : 'var(--ok)' }) : empty('No task work in this window.'))),
      card('Most expensive tasks', 'All attempts of each task. "Board" is what the task board counts: new tokens of the last attempt only.',
        taskTable(d.tasks, true)));
  }

  function taskTable(tasks, showAgent) {
    if (!tasks.length) return empty('No task work in this window.');
    const max = Math.max(1, ...tasks.map(t => t.total));
    return h('div', { class: 'tk-tablebox' }, h('table', { class: 'tk-table' },
      h('thead', null, h('tr', null, h('th', null, 'Task'), showAgent ? h('th', null, 'Who') : null, h('th', null, 'Status'),
        h('th', { class: 'n' }, 'Total'), h('th', { class: 'n' }, 'New'), h('th', { class: 'n' }, 'Calls'), h('th', { class: 'n' }, 'Tries'), h('th', { class: 'n' }, 'Board'), h('th', null, 'Main steps'))),
      h('tbody', null, ...tasks.map(t => h('tr', { class: 'click', onclick: () => openTask(t.id) },
        h('td', { class: 'title' }, h('b', null, `#${t.id} `), t.title),
        showAgent ? h('td', null, h('span', { class: 'tk-who' }, face(t.agent, 18), nameOf(t.agent))) : null,
        h('td', null, h('span', { class: `pill ${t.status}` }, t.status)),
        h('td', { class: 'n' }, h('span', { class: 'tk-cell' }, fmt(t.total), h('i', { style: `width:${44 * t.total / max}px` }))),
        h('td', { class: 'n' }, fmt(t.new)), h('td', { class: 'n' }, num(t.calls)), h('td', { class: 'n' }, t.attempts || ''),
        h('td', { class: 'n' }, t.office_counted ? fmt(t.office_counted) : '—'),
        h('td', { class: 'steps' }, Object.entries(t.steps).slice(0, 3).map(([s, n]) => `${stepName(s)} ×${n}`).join(' · ')))))));
  }

  // ---------------------------------------------------------------- one person
  function runWhat(r) {
    if (r.task) return h('span', null, h('b', null, `#${r.task} `), r.title || kindName(r.kind));
    return kindName(r.kind);
  }
  function agentView(d, compactView = false) {
    const id = d.id, s = d.summary;
    const isMgr = id === MGR;
    const models = Object.entries(d.models || {}).sort((a, b) => b[1] - a[1]);
    const byProv = Object.entries(d.providers || {}).map(([p, v]) => ({ p, v })).sort((a, b) => b.v - a.v);
    const runs = d.runs.slice(0, compactView ? 12 : 60);
    const kinds = Object.entries(d.kinds).map(([k, v]) => ({ k, v })).sort((a, b) => b.v - a.v);
    const runList = h('div', { class: 'tk-runs' }, ...(runs.length ? runs.map(r => h('div', { class: `tk-run ${r.task ? 'click' : ''}`, onclick: r.task ? () => openTask(r.task) : null },
      h('span', { class: 'when' }, new Date(r.ts * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })),
      h('span', { class: 'what' }, h('i', { style: `background:${kindColor(r.kind)}` }), runWhat(r),
        h('small', null, `${num(r.calls)} call${r.calls === 1 ? '' : 's'}` + (isMgr ? ` · ${Object.keys(r.models).map(MODEL).join(', ')}` : ` · ${provName(r.provider)}`) + ' · ' +
          Object.entries(r.steps).slice(0, 3).map(([k, n]) => `${stepName(k)} ×${n}`).join(' · '))),
      h('span', { class: 'tok' }, h('b', null, fmt(r.total)), h('small', null, `${fmt(r.new)} new · max ${fmt(r.max_ctx)} ctx`)))) : [empty('Nothing in this window.')]));
    const head = h('div', { class: 'tk-kpis' },
      kpi('Tokens processed', fmt(s.total), windowLabel().toLowerCase()),
      kpi('New tokens', fmt(s.new), `${fmt(s.fresh)} input · ${fmt(s.out)} output`),
      kpi('Re-read context', pct(s.total ? s.cached / s.total : 0), 'of its tokens'),
      kpi('Model calls', num(s.calls), `avg ${fmt(s.avg_ctx)} · max ${fmt(s.max_ctx)} context`),
      compactView ? null : kpi('Thinking', fmt(s.think), 'part of output'),
      kpi('Using now', fmt(s.last10m), 'last 10 minutes', s.last10m ? 'live' : ''));
    if (compactView) {
      return h('div', { class: 'tk tk-compact' }, head,
        card('On what', null, kinds.length ? bars(kinds, { label: r => kindName(r.k), value: r => r.v, color: r => kindColor(r.k) }) : empty('Nothing in this window.')),
        !isMgr && byProv.length > 1 ? card('Which provider', null, bars(byProv, { label: r => provName(r.p), value: r => r.v, color: r => provColor(r.p) })) : null,
        card('Recent work', 'Each run and what it cost. Click a task to open it.', runList));
    }
    return h('div', { class: 'tk' }, head,
      h('div', { class: 'tk-grid' },
        card('On what', 'Tokens by kind of work.', kinds.length ? bars(kinds, { label: r => kindName(r.k), value: r => r.v, color: r => kindColor(r.k) }) : empty('Nothing in this window.')),
        card('Doing what', 'The step each model call chose.', d.steps.length ? bars(d.steps.slice(0, 10), { label: r => stepName(r.step), value: r => r.total, note: r => ` ${num(r.calls)} calls` }) : empty('Nothing in this window.')),
        isMgr ? card('Which model', 'Sonnet by default; Opus only for complex turns.', bars(models.map(([m, v]) => ({ m, v })), { label: r => MODEL(r.m), value: r => r.v, color: r => /opus/i.test(r.m) ? '#d97757' : 'var(--accent)' }))
          : card('Which provider', 'Gemini, the local model, or anything added later: each counted on its own.', byProv.length ? bars(byProv, { label: r => provName(r.p), value: r => r.v, color: r => provColor(r.p) }) : empty('Nothing in this window.'))),
      card('Context sent per call', 'Every bar is one model call, in order, coloured by the kind of work. It climbs as a conversation grows and drops when one starts fresh.',
        legend(Object.keys(KIND).filter(k => d.context.some(p => p.kind === k)).map(k => [kindName(k), kindColor(k)])), contextChart(d.context)),
      card('When', null, timeline(d.timeline, [id])),
      isMgr ? null : card('Tasks', 'All attempts of each task.', taskTable(d.tasks, false)),
      card('Every run', 'Each time the office started this person on something, newest first.', runList));
  }

  // ---------------------------------------------------------------- the window
  function shell(body) {
    const seg = h('div', { class: 'tk-seg' }, ...WINDOWS.map(([k, label]) => h('button', { class: T.win === k ? 'on' : '', onclick: () => { T.win = k; try { localStorage.setItem('office.tokens.win', k); } catch { /* ignore */ } refresh(true); } }, label)));
    const pseg = h('div', { class: 'tk-seg' }, h('button', { class: T.prov ? '' : 'on', onclick: () => setProv('') }, 'All'),
      ...provs().map(p => h('button', { class: T.prov === p.id ? 'on' : '', title: p.model || '', onclick: () => setProv(p.id) }, p.label)));
    const back = T.view === 'agent' ? h('button', { class: 'act', style: 'flex:none;padding:0 10px', onclick: () => { T.view = 'team'; refresh(true); } }, iconEl('back'), 'Team') : null;
    const live = h('span', { class: 'tk-live', title: 'Updates by itself as agents work' }, h('i'), 'Live');
    const title = T.view === 'agent' ? h('div', { class: 'tk-title' }, face(T.agent, 28), h('span', null, `${nameOf(T.agent)} · token usage`)) : 'Token usage';
    return { title, tools: h('div', { class: 'toolbar tk-tools' }, back, pseg, seg, live), body };
  }
  function render() {
    if (!T.box || !T.data) return;
    const top = T.box.scrollTop;
    const view = T.view === 'agent' ? agentView(T.data) : teamView(T.data);
    T.box.replaceChildren(view);
    T.box.scrollTop = top;
  }
  async function refresh(reset) {
    if (!isOpen()) return;
    if (T.busy) { T.pending = true; return; }
    T.busy = true;
    try {
      const url = (T.view === 'agent' ? `/api/tokens/agent/${T.agent}?since=${since()}` : `/api/tokens?since=${since()}`) + provQuery();
      const d = await api('GET', url);
      if (!isOpen()) return;
      T.data = d;
      if (reset) mount(); else render();
    } catch (e) { if (T.box) T.box.replaceChildren(empty(`Couldn't load token usage: ${e.message}`)); }
    finally { T.busy = false; if (T.pending) { T.pending = false; refresh(); } }
  }
  function mount() {
    T.box = h('div', { class: 'tk-scroll' });
    const { title, tools } = shell(T.box);
    openModal('tokens', '', T.box, [], true);
    const mh = document.querySelector('#modal .mh h2');
    mh.replaceChildren(title); mh.after(tools);
    document.querySelector('#modal .mb').classList.add('tk-mb');
    if (T.data) render(); else T.box.replaceChildren(empty('Reading the ledger…'));
  }
  const isOpen = () => modalKind() === 'tokens';
  function setProv(id) { T.prov = id; try { localStorage.setItem('office.tokens.prov', id); } catch { /* ignore */ } refresh(true); }

  function open() { T.view = 'team'; T.data = null; mount(); refresh(true); }
  function openAgent(id) { T.view = 'agent'; T.agent = id; T.data = null; mount(); refresh(true); }

  // the agent panel's Tokens tab: the compact view, same data
  const P = { el: null, id: null, busy: false };
  async function panelTab(el, id) {
    P.el = el; P.id = id;
    if (!el.firstChild) el.replaceChildren(empty('Reading the ledger…'));
    if (P.busy) return; P.busy = true;
    try {
      const d = await api('GET', `/api/tokens/agent/${id}?since=${since()}${provQuery()}`);
      if (P.el !== el || P.id !== id) return;
      const top = el.parentElement?.scrollTop;
      el.replaceChildren(h('div', { class: 'tk-seg small' }, ...WINDOWS.map(([k, label]) => h('button', { class: T.win === k ? 'on' : '', onclick: () => { T.win = k; try { localStorage.setItem('office.tokens.win', k); } catch { /* ignore */ } panelTab(el, id); } }, label))),
        agentView(d, true),
        h('button', { class: 'act', style: 'width:100%;margin-top:10px', onclick: () => openAgent(id) }, 'Open the full breakdown'));
      if (top != null && el.parentElement) el.parentElement.scrollTop = top;
    } catch (e) { el.replaceChildren(empty(`Couldn't load token usage: ${e.message}`)); }
    finally { P.busy = false; }
  }
  const panelGone = () => { P.el = null; P.id = null; };

  // live: the ledger announces changes; redraw what is on screen, at most every couple of seconds
  let timer = null;
  function changed(m) {
    S.tokensRecent = m.recent || {};
    if (timer) return;
    timer = setTimeout(() => {
      timer = null;
      if (isOpen()) refresh();
      if (P.el && P.el.isConnected) panelTab(P.el, P.id);
    }, 1500);
  }
  return { open, openAgent, changed, panelTab, panelGone };
}
